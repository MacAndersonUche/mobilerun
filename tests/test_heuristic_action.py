from backend.cloud_agent import _heuristic_action

def test_heuristic_taps_display():
    tree = '''<hierarchy screen="settings">
  <node text="Display" resource-id="" clickable="true" bounds="[40,320,1000,420]" center="(520,370)"/>
</hierarchy>'''
    a = _heuristic_action("go to Display and turn on dark theme", tree, [])
    assert a["action"] == "tap"
    assert a["x"] == 520

def test_heuristic_done_when_on():
    tree = '''<hierarchy>
  <node text="Dark theme" clickable="true" bounds="[40,320,1000,420]" center="(520,370)"/>
  <node text="On" resource-id="dark_toggle" clickable="true" bounds="[800,320,1000,420]" center="(900,370)"/>
</hierarchy>'''
    a = _heuristic_action("turn on dark theme", tree, ["tap Display"])
    assert a["action"] == "done"
