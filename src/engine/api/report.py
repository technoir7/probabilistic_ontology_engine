"""
Report generation: hash-gated Fireworks AI calls with persistent cache under POE_DATA_DIR.

LLM provider: Fireworks AI via OpenAI-compatible endpoint, matching the pattern
used in probabilistic_ontology_engine_abductive/src/poea/llm.py.

Env vars:
  FIREWORKS_API_KEY   (required for generation)
  FIREWORKS_REPORT_MODEL  (optional; defaults to accounts/fireworks/models/deepseek-v4-0324)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve prompt path relative to this file — works from any cwd.
_PROMPT_PATH = Path(__file__).resolve().parents[4] / "prompts" / "snapshot_report.md"

# Fireworks constants matching POE-A defaults.
_FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
_DEFAULT_MODEL = "accounts/fireworks/models/deepseek-v4-0324"
_FIREWORKS_API_KEY_ENV = "FIREWORKS_API_KEY"
_FIREWORKS_MODEL_ENV = "FIREWORKS_REPORT_MODEL"


# ── Prompt versioning ─────────────────────────────────────────────────────────
# Bump this whenever prompts/snapshot_report.md changes.  It is baked into the
# cache filename so that any existing cached report is invalidated on the next
# POST /v1/report/{domain}/refresh even if the snapshot is otherwise unchanged.

PROMPT_VERSION = "1"


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

    JSON serialisation uses sort_keys=True so key insertion order is irrelevant.
    """
    stable = dict(snapshot)
    if "metadata" in stable and isinstance(stable["metadata"], dict):
        stable["metadata"] = {
            k: v for k, v in stable["metadata"].items() if k != "timestamp"
        }
    stable.pop("interpretation_hints", None)
    canon = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


# ── Cache paths ───────────────────────────────────────────────────────────────

def reports_dir(data_dir: Path) -> Path:
    d = data_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(data_dir: Path, domain: str, mode: str, hash_hex: str) -> Path:
    fname = f"{domain}__{mode}__pv{PROMPT_VERSION}__{hash_hex[:16]}.json"
    return reports_dir(data_dir) / fname


def stale_cache_path(data_dir: Path, domain: str, mode: str) -> Optional[Path]:
    """Return the most-recently-written cache file for this domain/mode, if any."""
    rd = reports_dir(data_dir)
    prefix = f"{domain}__{mode}__"
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
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read report cache %s: %s", path, exc)
        return None


def save_cache(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write report cache %s: %s", path, exc)


# ── Fireworks LLM client ──────────────────────────────────────────────────────

def _fireworks_model() -> str:
    return os.environ.get(_FIREWORKS_MODEL_ENV, _DEFAULT_MODEL)


def _generate_report_sync(snapshot: dict, api_key: str) -> str:
    """
    Synchronous Fireworks AI call.  Runs in a thread via asyncio.to_thread() so
    the async FastAPI event loop is not blocked.

    Mirrors the FireworksClient pattern from
    probabilistic_ontology_engine_abductive/src/poea/llm.py:
      - OpenAI SDK with Fireworks base_url
      - Same env var (FIREWORKS_API_KEY)
      - Same default model (accounts/fireworks/models/deepseek-v4-0324)
    """
    from openai import OpenAI

    prompt_text = _PROMPT_PATH.read_text(encoding="utf-8")
    snapshot_json = json.dumps(snapshot, indent=2, default=str)
    user_content = (
        f"{prompt_text}\n\n"
        f"## SNAPSHOT JSON\n\n"
        f"```json\n{snapshot_json}\n```\n\n"
        f"Write the report now."
    )

    client = OpenAI(base_url=_FIREWORKS_BASE_URL, api_key=api_key)
    response = client.chat.completions.create(
        model=_fireworks_model(),
        max_tokens=1500,
        messages=[
            {"role": "system", "content": "You are an expert at interpreting probabilistic epistemic systems and writing clear analytical reports."},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content or ""


async def generate_report(
    snapshot: dict,
    api_key: str,
    timeout: float = 90.0,
) -> str:
    """Async wrapper — runs the synchronous Fireworks call in a thread."""
    return await asyncio.wait_for(
        asyncio.to_thread(_generate_report_sync, snapshot, api_key),
        timeout=timeout,
    )
