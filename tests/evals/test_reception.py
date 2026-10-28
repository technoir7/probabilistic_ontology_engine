"""Critical reception by artist: assertions read from the press, linked to
artists by the names the museums give them."""
import json

from evals.reception import linked, reception


def test_a_subject_is_linked_to_the_longest_artist_name_it_contains():
    names = {"yayoi kusama", "john smith", "smith"}
    assert linked("Yayoi Kusama's mirror rooms at Tate", names) == "yayoi kusama"
    assert linked("Kusama's dots", names) is None            # a surname alone is not enough
    assert linked("the John Smith retrospective", names) == "john smith"


def test_reception_counts_judgements_by_artist_year_and_stance(tmp_path):
    (tmp_path / "guardian").mkdir()
    rows = [{"id": "a", "published": "2004-03-01", "assertions": [
        {"who": "w", "about": "Yayoi Kusama's show", "asserts": "dazzles", "force": "judges", "stance": "approval"},
        {"who": "w", "about": "Yayoi Kusama", "asserts": "was born in 1929", "force": "reports", "stance": "neither"},
        {"who": "w", "about": "the Tate", "asserts": "is dull", "force": "judges", "stance": "disapproval"}]},
        {"id": "b", "published": "2004-07-01", "assertions": [
        {"who": "w", "about": "Kusama, Yayoi", "asserts": "repeats herself", "force": "judges", "stance": "disapproval"}]}]
    (tmp_path / "guardian" / "2004-03.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    got = reception(tmp_path, {"yayoi kusama"})
    assert got["yayoi kusama"] == {"approval": {2004: 1}, "disapproval": {2004: 1}, "judged": {2004: 2},
                                   "contested": {2004: 1}}   # approved and condemned in the same year
