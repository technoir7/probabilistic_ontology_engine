"""One kind of success's report data (REFACTOR_SPEC D31): what predicts it,
the verdicts fixed by rule, and the image prompt's subject with its reasons
(abductive_engine ART-PLAN §§12.8–12.9)."""
from __future__ import annotations

import math
from typing import Optional

from ..model.trends import TrendLists
from ..runtime.success import current_success
from ..runtime.trends import current_trends
from . import context
from .dto import NarrativeCaseForecastOut
from .success_dto import (
    NarrativeImageSubjectOut,
    NarrativeOtherKindOut,
    NarrativeSuccessAddsOut,
    NarrativeSuccessEffectOut,
    NarrativeSuccessMechanismOut,
    NarrativeSuccessOut,
    NarrativeThemeKindOut,
    NarrativeThemesOut,
    RewardedOut,
)


SUCCESS_ROWS = 12
_AMOUNT = {1: "one", 2: "several"}


def success_snapshot(domain: str, kind: str) -> NarrativeSuccessOut:
    """One kind of success for its report. LookupError for a domain without
    success or an unknown kind."""
    key = domain.lower()
    s = current_success(key) if key in context.DOMAIN_MAP else None
    if s is None or kind not in s.kinds:
        raise LookupError(f"no kind of success '{kind}' for domain '{domain}'")
    k = s.kinds[kind]

    def words(features) -> str:
        return " + ".join(s.meanings.get(f, f) for f in features) or "each artist's own past alone"
    return NarrativeSuccessOut(
        domain=key, kind=kind, title=k.title, success_means=k.outcome, forecast_for=s.forecast_for,
        leader=words(k.leader), leader_since=k.leader_since, gain_nats_over_own_past=round(k.gain, 1),
        scored_years=len(k.years), verdicts=_verdicts(s, kind),
        best_rival_sets=[NarrativeSuccessMechanismOut(mechanisms=words(m.split("+")), gain_nats=round(g, 1))
                         for m, g in k.mechanisms[:SUCCESS_ROWS]],
        leader_effects=[NarrativeSuccessEffectOut(feature=f"{_AMOUNT.get(v, v)}: {s.meanings.get(f, f)}", push=round(e, 2),
                                                  times_the_odds_of_an_artist_with_the_same_past_and_none=round(math.exp(e), 1))
                        for (f, v), e in sorted(k.effects.items(), key=lambda kv: -abs(kv[1]))],
        each_leading_feature_adds=sorted(
            (NarrativeSuccessAddsOut(feature=s.meanings.get(f, f), nats=round(k.gain - sum(g) / len(g), 1))
             for f, g in k.dealt.items() if g), key=lambda a: -a.nats),
        control_placebo_features_from_the_year_after_gain_nats=round(k.placebo, 1),
        control_placebo_is_a_fair_test=k.placebo_fair,
        artists_the_leader_favours=[NarrativeCaseForecastOut(case=a, own_past_chance=round(o, 3), with_leader_chance=round(w, 3))
                                    for a, o, w in k.most_raised[:SUCCESS_ROWS]],
        other_kinds={o.title: _other_kind(o, s.meanings) for o in _others(s, kind)},
        critics_rewarded_this_year=[RewardedOut(kind=r.kind, name=r.name, approvals=r.approvals, disapprovals=r.disapprovals,
                                                approved=list(r.approved), disapproved=list(r.disapproved)) for r in s.rewarded],
        image_subject=_image_subject(s, key, kind),
        note=(f"artists are those Chicago or Cleveland ever acquired; years run {min(y for y, _ in k.years) if k.years else '?'} "
              f"to {max(y for y, _ in k.years) if k.years else '?'}; what critics rewarded is the year to September {s.year}"))


THEME_FEATURES = ("good_theme", "poor_theme")


def themes_snapshot(domain: str) -> NarrativeThemesOut:
    """Which themes help (ART-PLAN §14), for its report. LookupError for a
    domain without theme tests."""
    key = domain.lower()
    s = current_success(key) if key in context.DOMAIN_MAP else None
    if s is None or not s.themes:
        raise LookupError(f"no theme tests for domain '{domain}'")

    def words(features) -> str:
        return " + ".join(s.meanings.get(f, f) for f in features) or "each artist's own past alone"
    kinds = []
    for k, t in s.themes.items():
        kinds.append(NarrativeThemeKindOut(
            kind=k, title=s.kinds[k].title, verdicts=_theme_verdicts(t, s.kinds[k]), leader=words(t.leader),
            leader_effects=[NarrativeSuccessEffectOut(
                feature=f"{_AMOUNT.get(v, v)}: {s.meanings.get(f, f)}", push=round(e, 2),
                times_the_odds_of_an_artist_with_the_same_past_and_none=round(math.exp(e), 1))
                for (f, v), e in sorted(t.effects.items(), key=lambda kv: -abs(kv[1]))],
            best_records_this_year=[n for n, _ in t.best], worst_records_this_year=[n for n, _ in t.worst]))
    year = next(iter(s.themes.values())).year
    return NarrativeThemesOut(
        domain=key, kinds=kinds,
        how_records_are_made=(
            "For each kind of success and each year, every theme critics write in gets a track record from the years "
            "before only: among artists written about in that theme, how many had that success the next year, against "
            "how many would have among all artists with the same amount of it so far, shrunk toward nothing when the "
            "theme has few cases. Each artist-year then counts its claims in themes with a good record and in themes "
            "with a poor one, and these two are tested on top of what already predicts that kind of success."),
        note=f"records shown are those for {year}, from the years before; only named themes are shown")


def _theme_verdicts(t, kind) -> list[str]:
    """What the themes report must say for one kind, decided by rule."""
    title = kind.title.lower()
    out = []
    if any(f in t.leader for f in THEME_FEATURES):
        over = t.gain - t.gain_without
        strength = ("too little to claim anything" if over < SMALL_NATS else "by an overwhelming margin"
                    if over >= LARGE_NATS else "clearly but modestly")
        out.append(f"For {title}, a theme's record joins what leads, and beats that kind's own leader {strength}.")
        for f in THEME_FEATURES:
            deals = t.dealt.get(f)
            if f in t.leader and deals and t.gain - sum(deals) / len(deals) <= 1.0:
                out.append(f"For {title}, {f.replace('_', '-')} claims add nothing: dealt at random, the engine does "
                           "as well or better.")
    else:
        out.append(f"For {title}, a theme's record adds nothing: it does not join what leads, and dealt at random "
                   "it changes nothing.")
    if not kind.placebo_fair:
        out.append(f"For {title}, the year-after control is no test here: next year's features count part of next "
                   "year's success.")
    elif t.placebo >= t.gain:
        out.append(f"For {title}, next year's features predict as well or better, so the coverage comes with this "
                   "success rather than before it.")
    else:
        out.append(f"For {title}, this year's features predict better than next year's, so the coverage comes before "
                   "this success.")
    return out


def _image_subject(s, domain: str, kind: str) -> Optional[NarrativeImageSubjectOut]:
    """What the image prompt shows (abductive_engine ART-PLAN §12.8), by rule
    so the four prompts differ only where the findings do: the theme the
    leader's trend lists push up most (one claim's push, so a list that
    pushes down counts against), ties to this year's net approvals, then
    writers; the leader's medium that pushes up most, else this year's most
    approved medium. With the rule's reasons, in words. None where the gain
    is too small to claim."""
    k = s.kinds[kind]
    top = s.at_the_top.get(kind)
    if top:                     # this kind describes, by the user's choice (ART-PLAN §12 deviation 6)
        return _described_subject(s, k, _trends_now(s, domain), top)
    if k.gain < SMALL_NATS:
        return None
    t = _trends_now(s, domain)
    now = t.years.index(t.year)
    push = {s.lists[f]: k.effects.get((f, 1), 0.0) for f in k.leader if f in s.lists}

    def rank(x):
        on = sum(p for name, p in push.items() if x.key in t.lists[name])
        return (on, x.verdicts[0] - x.verdicts[1], x.writers[now])
    ranked = sorted(t.trends.values(), key=rank, reverse=True)
    theme = ranked[0]
    tied = [x for x in ranked if rank(x)[0] == rank(theme)[0]]
    media = sorted(((k.effects.get((f, 1), 0.0), f) for f in k.leader if f in s.media), reverse=True)
    feature = next((f for p, f in media if p > 0), None)
    approved = max((r for r in s.rewarded if r.kind == "medium"), key=lambda r: r.approvals - r.disapprovals)
    medium = s.media[feature] if feature else approved.name
    return NarrativeImageSubjectOut(
        theme=theme.name, theme_is_on_this_years_lists=[n for n in t.lists if theme.key in t.lists[n]],
        distinctive_words=list(theme.words), what_critics_said=list(theme.sample),
        medium=medium, medium_from_the_leading_features=feature is not None,
        reasons=[_theme_reason(k, t, push, theme, tied), _medium_reason(s, k, feature, approved),
                 _details("what critics said in it")],
        describes_instead=False)


def _trends_now(s, domain: str) -> TrendLists:
    t = current_trends(domain)
    if t is None or t.year != s.year:
        raise ValueError(f"success describes {s.year} but the trend lists {t.year if t else 'are missing'}")
    return t


def _described_subject(s, k, t: TrendLists, top) -> Optional[NarrativeImageSubjectOut]:
    """The prompt shows those who have this success now (ART-PLAN §12.9): the
    theme whose claims name the most of them, ties to claims about them, then
    net approvals; the medium tag on the most of their articles, ties in the
    order of the tagged media. The first reason says why it describes, from
    the verdicts."""
    themes = sorted((k for k in top.themes if k in t.trends), reverse=True,
                    key=lambda k: (*top.themes[k], t.trends[k].verdicts[0] - t.trends[k].verdicts[1]))
    if not themes or not top.media:
        return None
    theme, order = t.trends[themes[0]], list(s.media.values())
    medium = max(top.media, key=lambda m: (top.media[m], -order.index(m) if m in order else -len(order)))
    named = top.themes[themes[0]]
    if k.gain < SMALL_NATS:
        why = "Nothing in the coverage reliably predicts this kind of success, so this prompt describes instead"
    elif k.placebo_fair and k.placebo >= k.gain:
        why = ("The coverage goes with market success rather than ahead of it: next year's coverage predicts a place "
               "as well as this year's or better. So this prompt describes instead")
    else:
        why = "This prompt describes those who have this success now rather than what predicts it"
    reasons = [
        f"{why}: what the press wrote this year about the {top.artists} artists here who were in Artprice's "
        f"{top.table_year} Top 500. It shows what goes with market success, not what leads to it.",
        f"The subject is {theme.name}: of this year's themes, its claims named the most of these artists "
        f"({named[0]}, in {named[1]} claims)."
        + (f" Next came {t.trends[themes[1]].name} ({top.themes[themes[1]][0]}, in {top.themes[themes[1]][1]} claims)."
           if len(themes) > 1 else ""),
        f"The medium is {medium}: more articles about these artists were tagged {medium} than anything else "
        f"({top.media[medium]} articles).{_untested_media(s, 'are counted')}",
        _details("what critics said about these artists in it")]
    return NarrativeImageSubjectOut(
        theme=theme.name, theme_is_on_this_years_lists=[n for n in t.lists if theme.key in t.lists[n]],
        distinctive_words=list(theme.words), what_critics_said=list(top.said.get(themes[0], ())),
        medium=medium, medium_from_the_leading_features=False, reasons=reasons, describes_instead=True)


def _details(said: str) -> str:
    return (f"The details of the work below are a reading of the theme's words and of {said}, not findings. The "
            "setting at the end is the same for every prompt, so that the image model has as little as possible left "
            "to choose.")


_LIST_WORDS = {"argued": "argued over"}


def _listing(words: list[str], last: str = "and") -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} {last} {words[-1]}"


def _for_against(approvals: int, disapprovals: int) -> str:
    return f"{approvals or 'none'} for, {disapprovals or 'none'} against"


def _theme_reason(k, t: TrendLists, push: dict, theme, tied: list) -> str:
    up = [n for n, p in push.items() if p > 0]
    down = [n for n, p in push.items() if p < 0]
    if not up:
        return (f"The subject is {theme.name}, the theme with the best balance of critics' approval this year "
                f"({_for_against(*theme.verdicts)}). No trend list that helps is among the features that predict "
                "this, so the theme describes the year; it is not a tested finding.")
    on = [_LIST_WORDS.get(n, n) for n in up if theme.key in t.lists[n]]
    both = len(on) == len(up) > 1
    out = [f"The subject is {theme.name}. The findings say that when claims about an artist sit in a theme that is "
           f"{_listing([_LIST_WORDS.get(n, n) for n in up], 'or')} this year, the artist tends to get more {k.outcome}. "
           f"This theme is {'both' if both else _listing(on) if on else 'neither'}."]
    if down:
        out.append(f"Claims in a {_listing([_LIST_WORDS.get(n, n) for n in down], 'or')} theme count against the "
                   "artist here, so themes on that list score lower.")
    if len(tied) > 1:
        out.append(f"On that, {len(tied)} themes did equally well, this one included; it had the best balance of critics' approval "
                   f"this year ({_for_against(*theme.verdicts)}), and next came {tied[1].name} "
                   f"({_for_against(*tied[1].verdicts)}).")
    else:
        out.append("No other theme scored as well on that.")
    out.append("The findings test being in such a theme, not this theme in particular: it is this year's example.")
    return " ".join(out)


def _medium_reason(s, k, feature: Optional[str], approved) -> str:
    if feature:
        deals = k.dealt.get(feature)
        adds = k.gain - sum(deals) / len(deals) if deals else None
        out = f"The medium is {s.media[feature]} because one of the features that predict this is {s.meanings[feature]}."
        if adds is not None and adds < SMALL_NATS:
            out += (f" But shuffled at random among the artists, that feature "
                    f"{'adds nothing' if adds <= 1.0 else 'adds almost nothing'} to the prediction, so the medium is the "
                    "least certain part of the prompt.")
    else:
        out = (f"None of the features that predict this is a medium, so the medium is {approved.name}, the one critics "
               f"approved of most this year ({_for_against(approved.approvals, approved.disapprovals)}): a description "
               "of the year, not a tested finding.")
    return out + _untested_media(s, "were tested as features")


def _untested_media(s, verb: str) -> str:
    tested = list(s.media.values())
    untested = sorted(r.name for r in s.rewarded if r.kind == "medium" and r.name not in tested)
    out = f" Only {_listing(tested)} {verb}, because they are the only media the papers tag"
    return out + (f"; {_listing(untested)}, which critics also judged this year, never had the chance to show up."
                  if untested else ".")


# Gains are totals over every artist and scored year; below SMALL the leader
# barely beats own past, above LARGE it dwarfs every control.
SMALL_NATS, LARGE_NATS = 10.0, 100.0


def _push(k, f: str) -> float:
    return sum(e for (g, _), e in k.effects.items() if g == f)


def _verdicts(s, kind: str) -> list[str]:
    """What a success report must say, decided by rule, so the writer cannot
    soften a weak result or invent agreement between kinds."""
    k, m = s.kinds[kind], s.meanings
    out = []
    if k.gain < SMALL_NATS:
        out.append("The leading features barely beat each artist's own past over all artists and years: "
                   "too small to claim anything.")
    elif k.gain >= LARGE_NATS:
        out.append("The leading features beat each artist's own past by an overwhelming margin.")
    else:
        out.append("The leading features beat each artist's own past clearly but modestly.")
    if not k.placebo_fair:
        out.append("The year-after control is no test here: next year's features count part of next year's success.")
    elif k.placebo >= k.gain:
        out.append("The year-after control is a fair test here, since this success is counted apart from the press; "
                   "next year's features predict as well or better, so the coverage comes with this success "
                   "rather than before it.")
    else:
        out.append("The year-after control is a fair test here, since this success is counted apart from the press; "
                   "this year's features predict better than next year's, so the coverage comes before this success.")
    last = max((y for y, _ in k.years), default=None)
    for f, deals in k.dealt.items():
        adds = k.gain - sum(deals) / len(deals) if deals else None
        if adds is None or adds > 1.0:
            continue
        if abs(adds) < 0.05 and k.leader_since is not None and last is not None and k.leader_since > last:
            # Dealing it changed nothing scored: the engine never used it.
            out.append(f"{m.get(f, f)} joined the leader only in {k.leader_since}, after the last scored year, "
                       "so no control has tested it yet; its push is a fit to past years, not a tested forecast.")
        else:
            out.append(f"{m.get(f, f)} adds nothing: dealt at random, the engine does as well or better.")
    others = _others(s, kind)
    for f in k.leader:
        name = m.get(f, f)
        leads = [o for o in others if f in o.leader]
        if len(leads) == len(others) and kind in s.apart:
            hurts = [o.title.lower() for o in others if _push(o, f) < 0]
            out.append(f"{name} leads for every kind of success too; "
                       + (f"it helps, except that it hurts for {', '.join(hurts)}." if hurts else "it helps in all of them."))
        elif len(leads) == len(others):
            hurts = [o.title.lower() for o in [k, *others] if _push(o, f) < 0]
            out.append(f"{name} leads for all four kinds; "
                       + (f"it helps, except that it hurts for {', '.join(hurts)}." if hurts else "it helps in all four."))
        elif leads:
            out.append(f"{name} also leads for "
                       + ", ".join(f"{o.title.lower()} ({'helps' if _push(o, f) > 0 else 'hurts'})" for o in leads)
                       + "; not for " + ", ".join(o.title.lower() for o in others if o not in leads) + ".")
        else:
            out.append(f"{name} leads for no other kind.")
    return out


def _others(s, kind: str) -> list:
    """The kinds KIND is compared with: the main kinds besides itself, never a
    kind kept apart."""
    return [o for kk, o in s.kinds.items() if kk != kind and kk not in s.apart]


def _other_kind(o, meanings) -> NarrativeOtherKindOut:
    """Another kind's leading features and which way each pushes (summed
    over its levels), so a report cannot claim agreement that is not there."""
    return NarrativeOtherKindOut(
        leading_features=[meanings.get(f, f) for f in o.leader], gain_nats_over_own_past=round(o.gain, 1),
        helps=[meanings.get(f, f) for f in o.leader if _push(o, f) > 0],
        hurts=[meanings.get(f, f) for f in o.leader if _push(o, f) < 0])
