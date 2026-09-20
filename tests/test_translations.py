import json
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "shelly_phase_netting"


def load(name):
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def key_paths(node, prefix=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from key_paths(value, prefix + (key,))
    else:
        yield prefix


def test_german_and_english_translations_have_the_same_keys():
    assert set(key_paths(load("translations/de.json"))) == set(key_paths(load("translations/en.json")))


def test_strings_json_matches_english_translation():
    assert load("strings.json") == load("translations/en.json")
