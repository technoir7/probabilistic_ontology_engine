"""Matching artists across the four sources (docs/art-artists-plan.md §3)."""
from evals.art_artists import Person, cma_person, match, normalise, nyt_person


def test_names_are_compared_without_accents_case_punctuation_or_order():
    assert normalise("Yayoi Kusama") == normalise("Kusama, Yayoi") == "yayoi kusama"
    assert normalise("Édouard Manet") == "edouard manet"
    assert normalise("Gogh, Vincent van") == "vincent van gogh"


def test_cma_descriptions_give_name_and_birth_year():
    assert cma_person("Yayoi Kusama (Japanese, 1929-)") == Person("yayoi kusama", 1929)
    assert cma_person("Rembrandt van Rijn (Dutch, 1606–1669)") == Person("rembrandt van rijn", 1606)
    assert cma_person("Mary Cassatt (American, 1844-1926), printer") == Person("mary cassatt", 1844)
    assert cma_person("Japan, Edo period (1615-1868)") is None          # a place and period, not a person
    assert cma_person("Unknown") is None


def test_nyt_persons_are_names_without_their_qualifiers():
    assert nyt_person("Kusama, Yayoi") == "yayoi kusama"
    assert nyt_person("Warhol, Andy (1928-87)") == "andy warhol"


def test_an_artist_is_matched_by_name_and_birth_year_where_both_give_one():
    museums = {"aic": [Person("yayoi kusama", 1929), Person("john smith", 1900)],
               "cma": [Person("yayoi kusama", 1929), Person("john smith", 1950)]}
    got = match(museums, press={"nyt": {"yayoi kusama", "john smith"}, "guardian": {"yayoi kusama"}})
    assert got.artists["yayoi kusama"] == {"aic", "cma", "nyt", "guardian"}
    # two museums' John Smiths were born 50 years apart: two people, so the name is dropped
    assert "john smith" not in got.artists and "john smith" in got.ambiguous
