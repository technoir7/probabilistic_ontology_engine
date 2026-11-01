"""The word rule of the imagined life (abductive_engine ART-PLAN 15.14):
a sentence may use only words of the claims it cites, and words that
assert nothing, with "they" for the artist unless a claim states other
pronouns."""
from __future__ import annotations

import re

_CITED = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

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


def lacking(sentence: str, claims: list[str]) -> list[str]:
    """The words of SENTENCE that are neither ones that assert nothing nor
    CLAIMS', and the pronouns for a person that are neither "they" nor
    ones a claim states; none: the sentence is in its claims' words."""
    theirs = set().union(*(_forms(w) for c in claims for w in _words(c) if w not in _PRONOUNS))
    stated = _PRONOUN_SETS["they"].union(*(_stated(c) for c in claims))
    return list(dict.fromkeys(w for w in _words(sentence)
                              if not (w in stated if w in _PRONOUNS else w in _JOINING or _forms(w) & theirs)))
