"""Unit tests for cloud agent JSON action parsing (no LLM / network)."""

from backend.cloud_agent import _parse_action_json


def test_parse_plain_json():
    a = _parse_action_json('{"action":"tap","x":10,"y":20,"reason":"ok"}')
    assert a["action"] == "tap"
    assert a["x"] == 10


def test_parse_fenced_json():
    raw = """```json
{"action":"done","reason":"finished"}
```"""
    a = _parse_action_json(raw)
    assert a["action"] == "done"


def test_parse_embedded_json():
    raw = 'Sure.\n{"action":"back","reason":"go back"}\nThanks'
    a = _parse_action_json(raw)
    assert a["action"] == "back"
