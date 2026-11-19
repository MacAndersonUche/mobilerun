"""Local uvicorn: push_to_device must use in-memory websockets when no API GW."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List


class _FakeWs:
    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    async def send_json(self, payload: Dict[str, Any]) -> None:
        self.sent.append(payload)


def test_push_to_device_local_memory(monkeypatch):
    import backend.device_push as push
    import backend.main as main

    monkeypatch.delenv("WEBSOCKET_MANAGEMENT_ENDPOINT", raising=False)
    ws = _FakeWs()
    main.device_websockets["android_local_test"] = ws  # type: ignore[assignment]

    async def _runner() -> None:
        main._app_loop = asyncio.get_running_loop()

        def _do_push() -> bool:
            return push.push_to_device(
                "android_local_test",
                {"type": "command", "command": "ping", "request_id": "r1"},
            )

        ok = await asyncio.to_thread(_do_push)
        assert ok is True
        assert ws.sent and ws.sent[0]["command"] == "ping"

    asyncio.run(_runner())
    main.device_websockets.pop("android_local_test", None)
