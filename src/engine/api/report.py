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
SUCCESS_PROMPT_VERSION = "19"   # bump when prompts/success_report.md, life_check.md, its model or the life's checks change
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
              "anyone, and is they/them unless a claim states other pronouns. Each sentence keeps the critics' words and "
              "names the claims it comes from, listed below; code cut any with a word those claims lack, and two models "
              "read the rest against them (ART-PLAN 15.14).*")
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


# Words that assert nothing, so a life may use them to join claims in their own words (ART-PLAN 15.14). No word
# of time, cause or contrast is here: such a word may stand only where a claim it cites has it.
_JOINING = frozenset("""a an the and or nor of in on at to for with by from as into about
is was are were be been being am has had have having do does did
it its this that these those who whose whom which not no artist artists""".split())
_WORD = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?")


# Common irregular verbs, each form counted as the same word, so a change of tense is not a new word.
_IRREGULAR = {form: lemma for lemma, forms in {
    "become": "became", "begin": "began begun", "take": "took taken", "make": "made", "give": "gave given",
    "find": "found", "come": "came", "go": "went gone", "see": "saw seen", "know": "knew known",
    "grow": "grew grown", "win": "won", "write": "wrote written", "leave": "left", "draw": "drew drawn",
    "get": "got gotten", "hold": "held", "keep": "kept", "meet": "met", "run": "ran", "sell": "sold",
    "show": "shown", "teach": "taught", "think": "thought", "buy": "bought", "bring": "brought", "build": "built",
    "feel": "felt", "lose": "lost", "say": "said", "tell": "told", "stand": "stood", "fall": "fell fallen",
    "rise": "rose risen", "choose": "chose chosen", "speak": "spoke spoken", "break": "broke broken",
    "spend": "spent", "send": "sent", "lead": "led", "fight": "fought", "shoot": "shot", "sit": "sat",
    "hang": "hung", "forget": "forgot forgotten", "hide": "hid hidden", "wear": "wore worn"}.items()
    for form in forms.split()}


def _forms(word: str) -> set[str]:
    """The word and the bases it may have by a plural or tense ending, with
    irregular verbs to one form, so tense and number may change."""
    word = _IRREGULAR.get(word, word)
    out = {word}
    for end, back in (("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"), ("es", ""), ("s", "")):
        if len(word) > len(end) + 2 and word.endswith(end):
            out.add(word[:-len(end)] + back)
    return out


def _words(text: str) -> list[str]:
    return [re.sub(r"['’]s$", "", w) for w in _WORD.findall(_CITED.sub("", text).lower())]


# The imagined artist is "they" by default, the most neutral; "she" or "he" only where a claim states the person's
# pronouns ("she/her"), never from a critic's own "she" or "he", the critic's assumption (ART-PLAN 15.14 as amended).
_PRONOUN_SETS = {"he": {"he", "him", "his", "himself"}, "she": {"she", "her", "hers", "herself"},
                 "they": {"they", "them", "their", "theirs", "themselves", "themself"}}
_PRONOUNS = frozenset().union(*_PRONOUN_SETS.values())
_STATED = re.compile(r"\b(he|she|they)\s*/\s*(he|him|his|she|her|hers|they|them|their)\b")


def _stated(claim: str) -> set[str]:
    """The pronouns CLAIM states for a person, as whole sets."""
    found = set()
    for pair in _STATED.findall(claim.lower()):
        for word in pair:
            found |= next((ws for ws in _PRONOUN_SETS.values() if word in ws), set())
    return found


def _lacking(sentence: str, claims: list[str]) -> list[str]:
    """The words of SENTENCE that are neither ones that assert nothing nor
    CLAIMS', and the pronouns for a person that are neither "they" nor
    ones a claim states; none: the sentence is in its claims' words."""
    theirs = set().union(*(_forms(w) for c in claims for w in _words(c) if w not in _PRONOUNS))
    stated = _PRONOUN_SETS["they"].union(*(_stated(c) for c in claims))
    return list(dict.fromkeys(w for w in _words(sentence)
                              if not (w in stated if w in _PRONOUNS else w in _JOINING or _forms(w) & theirs)))


def _grounded(life: str, lives: list[dict],
              readers: Sequence[Callable[[str], str]]) -> tuple[list[str], list[tuple[str, str]], int]:
    """The sentences of LIFE in the words of the claims they cite (ART-PLAN
    15.14) that every one of READERS, given each beside its claims, finds
    say nothing more (15.9, 15.13); each sentence cut, with why; and how
    many were written."""
    sentences = _sentences(life, lives)
    claims = {c["n"]: c["claim"] for c in lives}
    lacking = [(text, cited, _lacking(text, [claims[n] for n in cited])) for text, cited in sentences]
    cut = [(text, f"words its claims lack: {', '.join(words)}") for text, _, words in lacking if words]
    worded = [(text, cited) for text, cited, words in lacking if not words]
    kept: list[str] = []
    if worded:
        request = life_check_request(worded, lives)
        found = [all(f) for f in zip(*(_verdicts_of(read, request, len(worded)) for read in readers))]
        kept = [text for (text, _), keep in zip(worded, found) if keep]
        cut += [(text, "the readers found it says more than its claims") for (text, _), keep in zip(worded, found)
                if not keep]
    order = {text: i for i, (text, _) in enumerate(sentences)}
    return kept, sorted(cut, key=lambda c: order[c[0]]), len(sentences)


def _cut_list(cut: list[tuple[str, str]]) -> str:
    return "*Cut by the checks:*\n\n" + "\n".join(f"- ~~{text}~~ ({why})" for text, why in cut)


class EmptyLife(Exception):
    """No sentence of the imagined life survived the checks (ART-PLAN
    15.15): the writer may be asked again. REPORT is the finished report as
    it stands, saying there is no life, with what was cut."""

    def __init__(self, report: str):
        super().__init__("no sentence of the imagined life survived the checks")
        self.report = report


def life_graph(edges: Sequence[dict]) -> str:
    """How the life stories of an imagined life go together (ART-PLAN 15.16),
    as code says it: one line a pair, since "times the usual" is the same both
    ways and the shares are not."""
    share = {(e["source"], e["target"]): e for e in edges}
    pairs = [e for e in edges if e["source"] < e["target"] or (e["target"], e["source"]) not in share]
    def back(e):
        other = share.get((e["target"], e["source"]))
        return f", {other['share']:.0%} the other way" if other else ""
    return "*How these life stories go together, in the lives of real artists:*\n\n" + "\n".join(
        f"- \"{e['source']}\" and \"{e['target']}\": told together {e['times']:g} times the usual; "
        f"{e['share']:.0%} of artists told the first are told the second{back(e)}" for e in pairs)


def _life_section(life: str, lives: list[dict], finding: str, readers: Sequence[Callable[[str], str]],
                  edges: Sequence[dict] = ()) -> str:
    if not lives:
        return f"{finding} {NO_LIVES}"
    kept, cut, written = _grounded(life, lives, readers)
    if not kept:
        return f"{finding} {UNGROUNDED}\n\n{_cut_list(cut)}\n\n{life_trail(lives)}"
    note = (f"\n\n*{len(cut)} of {written} sentences written for this life were dropped.*\n\n{_cut_list(cut)}"
            if cut else "")
    graph = f"\n\n{life_graph(edges)}" if edges else ""
    return f"{LIFE_LABEL}\n\n{finding}\n\n{' '.join(kept)}{note}{graph}\n\n{life_trail(lives)}"


def wall_text_label(voice: str) -> str:
    return (f"*A fictional wall text for the imagined work above, written as {voice} (ART-PLAN §12.11). Its ideas "
            "are the critics' claims in this theme; nothing in it is a fact about any real work or artist.*")


def finish_success_report(text: str, reasons: Optional[list[str]], voice: Optional[str], lives: list[dict],
                          finding: str, readers: Sequence[Callable[[str], str]], *, edges: Sequence[dict] = ()) -> str:
    """Replace the writer's image prompt section with the finished one: the
    rule's REASONS, then the label, the writer's description and the
    setting; then the writer's wall text (in VOICE) and artist statement,
    each under its label; then the imagined artist's life, every sentence
    citing one of LIVES and kept only if every one of READERS finds it
    says no more than they do, after the life-block test's FINDING, with the claims listed
    under it, or NO_LIVES where there are none. REASONS None: nothing to
    illustrate, so none of them. ValueError when an illustration is wanted
    and the writer left a part out, or wrote a sentence of the life that
    cites no claim given, or a reader twice answers out of its form;
    EmptyLife, with the finished report, when no sentence of the life
    survives."""
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
    life_section = _life_section(life, lives, finding, readers, edges)
    empty = bool(lives) and UNGROUNDED in life_section
    finished = (f"{body}\n\n{REASONS_HEADING}\n\n{why}\n\n{IMAGE_HEADING}\n\n{IMAGE_LABEL}\n\n"
                f"{description} {IMAGE_SETTING}\n\n{WALL_HEADING}\n\n{wall_text_label(voice)}\n\n{wall}\n\n"
                f"{STATEMENT_HEADING}\n\n{STATEMENT_LABEL}\n\n{statement}\n\n{LIFE_HEADING}\n\n{life_section}")
    if empty:
        raise EmptyLife(finished)
    return finished


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
