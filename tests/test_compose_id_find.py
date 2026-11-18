"""WhatsApp compose/send centers prefer resource-id entry/send."""

from backend.dm_heuristics import find_compose_center, find_send_center

TREE = """
<hierarchy>
<n t="Precious Achalugo" xy="200,120" c="0"/>
<n i="com.whatsapp:id/entry" h="Message" e="1" xy="540,2200" c="1"/>
<n i="com.whatsapp:id/send" d="Send" c="1" xy="1000,2200"/>
</hierarchy>
"""


def test_find_compose_by_entry_id():
    c = find_compose_center(
        TREE,
        ("Message",),
        compose_ids=("com.whatsapp:id/entry",),
        search_labels=("Search",),
    )
    assert c == (540, 2200)


def test_find_send_by_send_id():
    c = find_send_center(TREE, ("Send",), send_ids=("com.whatsapp:id/send",))
    assert c == (1000, 2200)
