"""Authed WS rows must not be wiped after a short heartbeat gap."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend import storage


def test_cleanup_keeps_fresh_authed_connection():
    now = 1_700_000_000
    items = [
        {
            "connection_id": "alive",
            "device_id": "android_46101066-test",
            "authed": True,
            "role": "device",
            "connected_at": now - 120,  # 2 min — within 15m grace
        },
        {
            "connection_id": "pending_old",
            "device_id": "pending_xyz",
            "authed": False,
            "connected_at": now - 500,
        },
    ]
    table = MagicMock()
    table.scan.return_value = {"Items": items}
    deleted = []

    def _del(Key):
        deleted.append(Key["connection_id"])

    table.delete_item.side_effect = _del

    with (
        patch.object(storage, "_table", return_value=table),
        patch("time.time", return_value=now),
    ):
        n = storage.cleanup_stale_connections()
    assert "pending_old" in deleted
    assert "alive" not in deleted
    assert n == 1
