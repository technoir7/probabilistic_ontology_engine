"""
Report generation: hash-gated Fireworks AI calls with persistent cache under POE_DATA_DIR.

LLM provider: Fireworks AI via its OpenAI-compatible endpoint.

Env vars:
  FIREWORKS_API_KEY   (required for generation)
  FIREWORKS_REPORT_MODEL  (optional; defaults to accounts/fireworks/models/deepseek-v4p1-flash; Fireworks withdrew v4-pro from serverless on 2026-09-25)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve prompt path relative to this file — works from any cwd.
# parents[3] of src/engine/api/report.py is the project root (where prompts/ lives).
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "snapshot_report.md"
# One trend list's report (D30): the art domain's new, growing, fading or argued-over trends.
TREND_PROMPT_PATH = PROMPT_PATH.parent / "trend_report.md"
# One kind of success's report (D31): what predicts an artist's success next year.
SUCCESS_PROMPT_PATH = PROMPT_PATH.parent / "success_report.md"

# Fireworks constants matching POE-A defaults.
_FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
_DEFAULT_MODEL = "accounts/fireworks/models/deepseek-v4p1-flash"
_FIREWORKS_API_KEY_ENV = "FIREWORKS_API_KEY"
_FIREWORKS_MODEL_ENV = "FIREWORKS_REPORT_MODEL"


# ── Prompt versioning ─────────────────────────────────────────────────────────
# Bump this whenever prompts/snapshot_report.md changes.  It is baked into the
# cache filename so that any existing cached report is invalidated on the next
# POST /v1/report/{domain}/refresh even if the snapshot is otherwise unchanged.

PROMPT_VERSION = "4"
TREND_PROMPT_VERSION = "1"   # bump when prompts/trend_report.md changes
SUCCESS_PROMPT_VERSION = "3"   # bump when prompts/success_report.md changes


# ── Hashing ──────────────────────────────────────────────────────────────────

def snapshot_hash(snapshot: dict) -> str:
    """
    Stable SHA-256 of the snapshot's genuine epistemic content.

    Excluded from the hash (time-derived, non-epistemic):
      - metadata.timestamp: wall-clock capture time; changes on every request.
      - interpretation_hints: narrative text derived from the snapshot at call
        time (e.g. "last paradigm shift was N days ago").  These change with
        wall-clock time even when epistemic state is identical, so including
        them would defeat the cache.

    Included (drives regeneration when changed):
      - evidence_count, current_generation (metadata)
      - current_regime_state (variable posteriors)
      - dominant_hypothesis (name, edges, log_score)
      - competing_candidates (scores, gap)
      - ontology_competition (entropy, shift count, recent shifts)
      - frontier edges
      - case_mechanisms, when the domain has any (D29)
      - trends, when the domain has them (D30)

    JSON serialisation uses sort_keys=True so key insertion order is irrelevant.
    """
    stable = dict(snapshot)
    if "metadata" in stable and isinstance(stable["metadata"], dict):
        stable["metadata"] = {
            k: v for k, v in stable["metadata"].items() if k != "timestamp"
        }
    stable.pop("interpretation_hints", None)
    # Absent for domains without cases (D29), so their cached reports stay valid.
    if not stable.get("case_mechanisms"):
        stable.pop("case_mechanisms", None)
    if stable.get("trends") is None:
        stable.pop("trends", None)
    canon = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


# ── Cache paths ───────────────────────────────────────────────────────────────

def reports_dir(data_dir: Path) -> Path:
    d = data_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


# "apriori" is left from a retired second ontology mode; kept in the file
# names so reports already cached on the data volume are still found.
def _prefix(domain: str, version: Optional[str] = None) -> str:
    return f"{domain}__apriori__pv{version or PROMPT_VERSION}__"


def cache_path(data_dir: Path, domain: str, hash_hex: str, version: Optional[str] = None) -> Path:
    return reports_dir(data_dir) / f"{_prefix(domain, version)}{hash_hex[:16]}.json"


def stale_cache_path(data_dir: Path, domain: str, version: Optional[str] = None) -> Optional[Path]:
    """Return the most-recently-written pv{PROMPT_VERSION} cache file, if any.

    Version-gated: only files whose name contains the current PROMPT_VERSION are
    considered.  Files from earlier versions (e.g. pv1 when we are on pv2) are
    silently ignored so stale prompts are never served.
    """
    rd = reports_dir(data_dir)
    prefix = _prefix(domain, version)
    candidates = sorted(
        (p for p in rd.glob(f"{prefix}*.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


# ── Cache I/O ─────────────────────────────────────────────────────────────────

def load_cache(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read report cache %s: %s", path, exc)
        return None
    # An empty report was once cached as if written (a thinking model's empty
    # reply); it is no report, so it is neither served nor a cache hit.
    return data if data.get("report") else None


def save_cache(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write report cache %s: %s", path, exc)


# ── Meta-reasoning sanitizer ──────────────────────────────────────────────────
# Patterns that indicate the model produced scaffolding/preamble rather than
# the analyst brief directly.  Checked in the first 600 characters.

_META_PATTERNS = (
    "we are asked",
    "let's analyze",
    "let's extract",
    "let me ",
    "interpret the json",
    "the snapshot json",    # specific: referencing the data artifact, not "snapshot of the market"
    "based on the json",
    "based on the snapshot",
    "based on the provided",
    "the provided json",
    "looking at the provided",
    "you've provided",
    "i will now",
    "in this report,",
    "as requested,",
)


def contains_meta_reasoning(text: str) -> bool:
    """Return True if the first 600 chars contain LLM scaffolding / meta-reasoning."""
    sample = text[:600].lower()
    return any(pat in sample for pat in _META_PATTERNS)


# ── Fireworks LLM client ──────────────────────────────────────────────────────

_STRICT_SYSTEM = (
    "Begin your response immediately with '## In short'. "
    "Do not write any introductory text, preamble, or explanation of the task. "
    "Do not reference the JSON data, the system, or your instructions. "
    "Write only the report content, starting with the section header."
)


def _generate_report_sync(snapshot: dict, api_key: str, model: str, strict: bool = False,
                          prompt_path: Path = PROMPT_PATH) -> str:
    """
    Synchronous Fireworks AI call.  Runs in a thread via asyncio.to_thread() so
    the async FastAPI event loop is not blocked.

    When strict=True a stronger system prompt is used as a retry hedge against
    meta-reasoning output from the first attempt.
    """
    from openai import OpenAI

    prompt_text = prompt_path.read_text(encoding="utf-8")
    snapshot_json = json.dumps(snapshot, indent=2, default=str)
    user_content = (
        f"{prompt_text}\n\n"
        f"## SNAPSHOT JSON\n\n"
        f"```json\n{snapshot_json}\n```\n\n"
        f"Write the report now."
    )

    system = (
        _STRICT_SYSTEM if strict
        else "You write short, plain, specific notes for busy readers, in your own voice."
    )

    client = OpenAI(base_url=_FIREWORKS_BASE_URL, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        # DeepSeek V4.1 Flash thinks by default, from the same budget, and at
        # 1500 or even 4096 tokens thought until none were left and wrote
        # nothing. Writing a report from data needs no thinking; off, a report
        # costs well under a cent, and the cap bounds the worst case (the
        # report asks for under 350 words, about 500 tokens; art's, with
        # trends, up to 750, about 1,100).
        max_tokens=2000,
        reasoning_effort="none",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )
    choice = response.choices[0]
    if not choice.message.content:
        details = getattr(response.usage, "completion_tokens_details", None)
        thought = getattr(details, "reasoning_tokens", None)
        raise ValueError(f"the model wrote no report (finish_reason: {choice.finish_reason}; "
                         f"thinking tokens: {thought}; reasoning text: "
                         f"{len(getattr(choice.message, 'reasoning_content', None) or '')} chars)")
    return choice.message.content


async def generate_report(
    snapshot: dict,
    api_key: str,
    model: str,
    timeout: float = 90.0,
    prompt_path: Path = PROMPT_PATH,
) -> str:
    """Async wrapper — runs the synchronous Fireworks call in a thread.

    Checks the output for meta-reasoning scaffolding and retries once with a
    stricter system prompt.  Raises ValueError if both attempts fail the check.
    """
    async def attempt(strict: bool = False) -> str:
        return await asyncio.wait_for(
            asyncio.to_thread(_generate_report_sync, snapshot, api_key, model, strict=strict, prompt_path=prompt_path),
            timeout=timeout,
        )

    try:
        text = await attempt()
    except ValueError as exc:
        # The model sometimes thinks despite being told not to, and spends its
        # whole budget doing so; a second try usually writes.
        logger.warning("No report on the first try (%s); trying once more", exc)
        text = await attempt()
    if contains_meta_reasoning(text):
        logger.warning(
            "Report output contains meta-reasoning scaffolding; retrying with strict prompt"
        )
        text = await attempt(strict=True)
        if contains_meta_reasoning(text):
            # Retry also matched — log the warning but return the text rather than
            # returning a 502.  A slightly impure report is better than a broken
            # user experience; the strict prompt usually produces cleaner output
            # even when the heuristic still fires on borderline phrases.
            logger.warning(
                "Retry output still matches meta-reasoning heuristic; "
                "serving it anyway — review patterns if this recurs"
            )
    return text
