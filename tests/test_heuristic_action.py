from backend.cloud_agent import LLM_UNAVAILABLE_LABEL, _heuristic_action


def test_heuristic_open_settings_only():
    a = _heuristic_action("open Settings", "", [])
    assert a is not None
    assert a["action"] == "open_app"
    assert a["app"] == "Settings"
    assert LLM_UNAVAILABLE_LABEL in a["reason"]


def test_heuristic_rejects_multistep_display():
    tree = """<hierarchy screen="settings">
  <node text="Display" resource-id="" clickable="true" bounds="[40,320,1000,420]" center="(520,370)"/>
</hierarchy>"""
    a = _heuristic_action("go to Display and turn on dark theme", tree, [])
    assert a is None


def test_heuristic_rejects_open_settings_and_display():
    a = _heuristic_action("open Settings and go to Display", "", [])
    assert a is None
