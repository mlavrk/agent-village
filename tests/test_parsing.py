"""parse_json must survive everything cheap models do to JSON."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from village.zen import parse_json

CASES = [
    ("plain", '{"thought":"t","say":"s","target":"Jonas"}', "s", "Jonas", False),
    ("fenced", '```json\n{"thought":"t","say":"s","target":"Jonas"}\n```', "s", "Jonas", False),
    ("chatty", 'Sure! Here you go:\n{"thought":"t","say":"s","target":"Jonas"}', "s", "Jonas", False),
    ("truncated say", '{"thought": "a plan", "say": "Edith speaks sense: wolves eat', 
     "Edith speaks sense: wolves eat", None, True),
    ("escaped quotes", '{"say": "he said \\"I slept\\" and went quiet", "target": null',
     'he said "I slept" and went quiet', None, True),
]


def main() -> None:
    for name, raw, want_say, want_target, want_partial in CASES:
        data = parse_json(raw)
        assert data.get("say") == want_say, f"{name}: say={data.get('say')!r}"
        assert data.get("target") == want_target, f"{name}: target={data.get('target')!r}"
        assert bool(data.get("_partial")) is want_partial, f"{name}: partial flag"
        print(f"  {name:16} ok")
    print("OK")


main()
