"""match_name decides every kill, heal, check and vote — it must not guess."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from village.agent import match_name

ALIVE = ["Martha", "Silas", "Edith", "Jonas", "Clara", "Peter"]

CASES = [
    # the model answered cleanly
    ("exact", "Jonas", "Jonas"),
    ("wrong case", "MARTHA", "Martha"),
    ("padded", "  Jonas  ", "Jonas"),
    ("trailing stop", "Jonas.", "Jonas"),
    ("quoted", '"Clara"', "Clara"),
    # the name is buried in a sentence
    ("in a sentence", "I say we hang Jonas today", "Jonas"),
    ("possessive", "Jonas's story does not add up", "Jonas"),
    ("leading filler", "My target is Peter", "Peter"),
    # two names: the FIRST one named wins, not whoever sits earliest
    ("two names", "I vote Peter and Clara", "Peter"),
    ("two names reversed", "I vote Clara and Peter", "Clara"),
    # cut short mid-name
    ("truncated name", "Marth", "Martha"),
    ("truncated name 2", "Jona", "Jonas"),
    # nothing usable: abstaining beats hanging a random villager
    ("single letter", "a", None),          # used to return Martha
    ("single letter 2", "s", None),        # used to return Silas
    ("two letters", "ma", None),
    ("persona not name", "the miller", None),
    ("nonsense", "xyz", None),
    ("empty", "", None),
    ("none", None, None),
    ("whitespace", "   ", None),
    # a dead or absent player is not a legal target
    ("not in the list", "Agnes", None),
    ("dead in a sentence", "Agnes was right about all of this", None),
]


def main() -> None:
    for name, candidate, want in CASES:
        got = match_name(candidate, ALIVE)
        assert got == want, f"{name}: match_name({candidate!r}) -> {got!r}, wanted {want!r}"
        print(f"  {name:20} {str(candidate)[:28]!r:32} -> {got!r}")

    # the run-off pool is narrower than the living: a vote for someone
    # outside it must not be silently redirected
    assert match_name("Jonas", ["Clara", "Peter"]) is None, "voted outside the run-off pool"
    print("  run-off pool         rejects an outsider")
    print("OK")


main()
