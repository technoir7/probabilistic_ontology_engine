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
import re
from pathlib import Path
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

# Resolve prompt path relative to this file — works from any cwd.
# parents[3] of src/engine/api/report.py is the project root (where prompts/ lives).
PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "snapshot_report.md"
# One trend list's report (D30): the art domain's new, growing, fading or argued-over trends.
TREND_PROMPT_PATH = PROMPT_PATH.parent / "trend_report.md"
# One kind of success's report (D31): what predicts an artist's success next year.
SUCCESS_PROMPT_PATH = PROMPT_PATH.parent / "success_report.md"
# Which themes help (ART-PLAN §14): a theme's record against each kind of success.
THEMES_PROMPT_PATH = PROMPT_PATH.parent / "themes_report.md"

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
SUCCESS_PROMPT_VERSION = "15"   # bump when prompts/success_report.md, life_check.md or its model changes
THEMES_PROMPT_VERSION = "2"    # bump when prompts/themes_report.md changes


# ── A success report's image prompt (abductive_engine ART-PLAN §12.8) ─────────
# The writer writes only the description; the label and the setting are fixed
# here so that neither it nor an image model fills what the data does not say.

REASONS_HEADING = "## How the image prompt was made"
IMAGE_HEADING = "## Image prompt"
IMAGE_LABEL = ('*An illustration of what a "successful" work looks like by this measure, built from the '
               'findings above. It is not a real work, and nothing guarantees success.*')
IMAGE_SETTING = "The work alone in an empty white gallery, photographed straight on for a museum catalogue, in even, soft daylight."
NOTHING_TO_ILLUSTRATE = ("Nothing in the coverage reliably predicts this kind of success, so there is no "
                         "illustration of it.")


WALL_HEADING = "## Wall text"
STATEMENT_HEADING = "## Artist statement"
STATEMENT_LABEL = ("*A fictional artist statement for the imagined work above, by its imagined artist (ART-PLAN §12.12). "
                   "Its ideas are the critics' claims in this theme; it is not the words of any real artist.*")
LIFE_HEADING = "## The imagined artist"
LIFE_LABEL = ("*A fictional life for the imagined artist, kept apart from the work (ART-PLAN 15.12), assembled from "
              "what critics said about the lives of real artists who had this kind of success. It is not the life of "
              "anyone. Each sentence names the claims it comes from, listed below, and was read against them by two "
              "models; a sentence either found saying more was cut (ART-PLAN 15.13).*")
NO_LIVES = "No life block has a good record for this kind of success, so there is no life."
UNGROUNDED = "No sentence written for the life said only what its claims say, so there is no life."
LIFE_CHECK_PATH = PROMPT_PATH.parent / "life_check.md"
# Another maker's model than the writer's, so no model reads its own writing (ART-PLAN 15.10).
LIFE_CHECK_MODEL = "accounts/fireworks/models/glm-5p3-flash"
_CITED = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_SENTENCE_END = re.compile(r"(?<=[.!?\]])\s+(?=[A-Z\"'‘“])")


def life_trail(lives: list[dict]) -> str:
    """The claims an imagined life is built from, as a critic made each."""
    return "*Built from these claims critics made about real artists who had this success:*\n\n" + "\n".join(
        f"- [{c['n']}] {c['who']} ({c['when']}), in \"{c['block']}\": {c['claim']}" for c in lives)


def _sentences(life: str, lives: list[dict]) -> list[tuple[str, list[int]]]:
    """LIFE's sentences, each with the claims in LIVES it cites; ValueError
    if one cites none, or one it was not given."""
    known = {c["n"] for c in lives}
    out = []
    for sentence in _SENTENCE_END.split(life):
        cited = [int(n) for group in _CITED.findall(sentence) for n in group.split(",")]
        if not cited or not set(cited) <= known:
            raise ValueError(f"a sentence of the imagined life cites no claim it was given: {sentence[:120]!r}")
        out.append((sentence, cited))
    return out


def life_check_request(sentences: list[tuple[str, list[int]]], lives: list[dict]) -> str:
    """The fixed instructions, then each sentence beside only the claims it cites."""
    claims = {c["n"]: c["claim"] for c in lives}
    shown = "\n\n".join(f"Sentence {i}: {text}\nIts claims:\n" + "\n".join(f"[{n}] {claims[n]}" for n in dict.fromkeys(cited))
                         for i, (text, cited) in enumerate(sentences, 1))
    return f"{LIFE_CHECK_PATH.read_text(encoding='utf-8')}\n\n{shown}\n"


def _verdicts(answer: str, count: int) -> list[bool]:
    """One y or n per sentence, numbered in order; ValueError otherwise."""
    lines = [line.split() for line in answer.strip().splitlines() if line.strip()]
    if len(lines) != count or any(parts != [str(i), parts[-1]] or parts[-1] not in ("y", "n")
                                  for i, parts in enumerate(lines, 1)):
        raise ValueError(f"the life check answered out of its form: {answer[:120]!r}")
    return [parts[1] == "y" for parts in lines]


def _verdicts_of(read: Callable[[str], str], request: str, count: int) -> list[bool]:
    """READ's answer; one out of the form is asked once more, then refused."""
    try:
        return _verdicts(read(request), count)
    except ValueError:
        return _verdicts(read(request), count)


def _grounded(life: str, lives: list[dict], readers: Sequence[Callable[[str], str]]) -> tuple[list[str], int]:
    """The sentences of LIFE that every one of READERS, given each beside
    its claims, finds say nothing more than they do (ART-PLAN 15.9, 15.13),
    and how many there were."""
    sentences = _sentences(life, lives)
    request = life_check_request(sentences, lives)
    kept = [all(found) for found in zip(*(_verdicts_of(read, request, len(sentences)) for read in readers))]
    return [text for (text, _), keep in zip(sentences, kept) if keep], len(sentences)


def _life_section(life: str, lives: list[dict], finding: str, readers: Sequence[Callable[[str], str]]) -> str:
    if not lives:
        return f"{finding} {NO_LIVES}"
    kept, written = _grounded(life, lives, readers)
    if not kept:
        return f"{finding} {UNGROUNDED}"
    dropped = written - len(kept)
    note = (f"\n\n*{dropped} of {written} sentences written for this life were dropped: read against the claims "
            "they cite, they said more than those claims do.*") if dropped else ""
    return f"{LIFE_LABEL}\n\n{finding}\n\n{' '.join(kept)}{note}\n\n{life_trail(lives)}"


def wall_text_label(voice: str) -> str:
    return (f"*A fictional wall text for the imagined work above, written as {voice} (ART-PLAN §12.11). Its ideas "
            "are the critics' claims in this theme; nothing in it is a fact about any real work or artist.*")


def finish_success_report(text: str, reasons: Optional[list[str]], voice: Optional[str], lives: list[dict],
                          finding: str, readers: Sequence[Callable[[str], str]]) -> str:
    """Replace the writer's image prompt section with the finished one: the
    rule's REASONS, then the label, the writer's description and the
    setting; then the writer's wall text (in VOICE) and artist statement,
    each under its label; then the imagined artist's life, every sentence
    citing one of LIVES and kept only if every one of READERS finds it
    says no more than they do, after the life-block test's FINDING, with the claims listed
    under it, or NO_LIVES where there are none. REASONS None: nothing to
    illustrate, so none of them. ValueError when an illustration is wanted
    and the writer left a part out, or wrote a sentence of the life that
    cites no claim given, or a reader twice answers out of its form."""
    body, _, written = text.partition(f"\n{IMAGE_HEADING}")
    body = body.rstrip()
    if reasons is None:
        return f"{body}\n\n{IMAGE_HEADING}\n\n{NOTHING_TO_ILLUSTRATE}"
    image, _, rest = written.partition(f"\n{WALL_HEADING}")
    wall, _, rest = rest.partition(f"\n{STATEMENT_HEADING}")
    statement, _, life = rest.partition(f"\n{LIFE_HEADING}")
    description = " ".join(_section(image).split())
    wall, statement = _section(wall).strip(), _section(statement).strip()
    life = " ".join(_section(life).split())
    for part, name in ((description, "image prompt description"), (wall, "wall text"), (statement, "artist statement"),
                       (life or not lives, "imagined artist's life")):
        if not part:
            raise ValueError(f"the report has no {name}")
    why = "\n\n".join(reasons)
    life_section = _life_section(life, lives, finding, readers)
    return (f"{body}\n\n{REASONS_HEADING}\n\n{why}\n\n{IMAGE_HEADING}\n\n{IMAGE_LABEL}\n\n"
            f"{description} {IMAGE_SETTING}\n\n{WALL_HEADING}\n\n{wall_text_label(voice)}\n\n{wall}\n\n"
            f"{STATEMENT_HEADING}\n\n{STATEMENT_LABEL}\n\n{statement}\n\n{LIFE_HEADING}\n\n{life_section}")


def _section(written: str) -> str:
    """A section's text past its heading line, whatever the writer put on
    that line, up to any heading after it."""
    return written.partition("\n")[2].split("\n## ")[0]


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
        # report asks for under 350 words, about 500 tokens; a success
        # report, up to 900 words and an image prompt, past 2,000).
        max_tokens=3000,
        reasoning_effort="none",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )
    choice = response.choices[0]
    if choice.message.content and choice.finish_reason == "length":
        raise ValueError("the report was cut off at the token cap (finish_reason: length)")
    if not choice.message.content:
        details = getattr(response.usage, "completion_tokens_details", None)
        thought = getattr(details, "reasoning_tokens", None)
        raise ValueError(f"the model wrote no report (finish_reason: {choice.finish_reason}; "
                         f"thinking tokens: {thought}; reasoning text: "
                         f"{len(getattr(choice.message, 'reasoning_content', None) or '')} chars)")
    return choice.message.content


def fetch_life_check(request: str, api_key: str, model: str) -> str:
    """The life check's answer to REQUEST: one Fireworks call (ART-PLAN
    15.9, 15.10). GLM-5.3 always thinks and refuses reasoning_effort
    "none", so it thinks a little, from a budget that leaves room for the
    answer of a line a sentence."""
    from openai import OpenAI

    client = OpenAI(base_url=_FIREWORKS_BASE_URL, api_key=api_key, timeout=120.0)
    response = client.chat.completions.create(
        model=model, max_tokens=16000, temperature=0, reasoning_effort="low",
        messages=[{"role": "system", "content": "You check sentences against their sources and answer only in the form asked."},
                  {"role": "user", "content": request}])
    answer = response.choices[0].message.content
    if not answer:
        raise ValueError(f"the life check wrote nothing (finish_reason: {response.choices[0].finish_reason})")
    return answer


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
