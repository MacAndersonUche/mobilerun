#!/usr/bin/env python3
"""Minimal APK-like device: claim short code + WS command RPC for cloud agent E2E.

Simulates Settings → About phone (Android version) and Display → Dark theme
so the prod cloud LLM agent can complete multi-step tasks without a local emu.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional

try:
    import websockets
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "websockets"])
    import websockets

API = os.environ.get(
    "API_URL", "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com"
).rstrip("/")
WS = os.environ.get(
    "WS_URL", "wss://sv7144gijj.execute-api.eu-west-2.amazonaws.com/prod"
)
USER = os.environ.get("E2E_USER", "ci-e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "admin")
DEVICE_ID = os.environ.get("DEVICE_ID", f"device_sim_{int(time.time())}")


def http(method: str, path: str, body=None, token=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


# Screen graph: Settings → About phone / Display → Dark theme
SCREENS = {
    "home": {
        "nodes": [
            {
                "text": "Settings",
                "clickable": True,
                "bounds": "100,400,900,500",
                "cx": 500,
                "cy": 450,
            },
            {
                "text": "Chrome",
                "clickable": True,
                "bounds": "100,600,900,700",
                "cx": 500,
                "cy": 650,
            },
        ]
    },
    "settings": {
        "nodes": [
            {
                "text": "Network & internet",
                "clickable": True,
                "bounds": "40,200,1000,300",
                "cx": 520,
                "cy": 250,
            },
            {
                "text": "Display",
                "clickable": True,
                "bounds": "40,320,1000,420",
                "cx": 520,
                "cy": 370,
            },
            {
                "text": "About phone",
                "clickable": True,
                "bounds": "40,440,1000,540",
                "cx": 520,
                "cy": 490,
            },
            {
                "text": "Sound",
                "clickable": True,
                "bounds": "40,560,1000,660",
                "cx": 520,
                "cy": 610,
            },
        ]
    },
    "about": {
        "nodes": [
            {
                "text": "Device name",
                "clickable": False,
                "bounds": "40,200,1000,280",
                "cx": 520,
                "cy": 240,
            },
            {
                "text": "Android version",
                "clickable": True,
                "bounds": "40,300,1000,400",
                "cx": 520,
                "cy": 350,
            },
            {
                "text": "14",
                "resourceId": "android_version",
                "clickable": False,
                "bounds": "40,400,1000,460",
                "cx": 520,
                "cy": 430,
            },
            {
                "text": "Android 14",
                "clickable": False,
                "bounds": "40,460,1000,520",
                "cx": 520,
                "cy": 490,
            },
        ]
    },
    "display": {
        "nodes": [
            {
                "text": "Brightness",
                "clickable": True,
                "bounds": "40,200,1000,300",
                "cx": 520,
                "cy": 250,
            },
            {
                "text": "Dark theme",
                "clickable": True,
                "bounds": "40,320,1000,420",
                "cx": 520,
                "cy": 370,
            },
            {
                "text": "Off",
                "resourceId": "dark_toggle",
                "clickable": True,
                "bounds": "800,320,1000,420",
                "cx": 900,
                "cy": 370,
            },
        ]
    },
    "display_dark": {
        "nodes": [
            {
                "text": "Brightness",
                "clickable": True,
                "bounds": "40,200,1000,300",
                "cx": 520,
                "cy": 250,
            },
            {
                "text": "Dark theme",
                "clickable": True,
                "bounds": "40,320,1000,420",
                "cx": 520,
                "cy": 370,
            },
            {
                "text": "On",
                "resourceId": "dark_toggle",
                "clickable": True,
                "bounds": "800,320,1000,420",
                "cx": 900,
                "cy": 370,
            },
        ]
    },
}

state = {"screen": "home", "dark": False, "about_seen": False}


def tree_xml() -> str:
    screen = SCREENS[state["screen"]]
    lines = [f'<hierarchy screen="{state["screen"]}">']
    for n in screen["nodes"]:
        rid = n.get("resourceId", "")
        lines.append(
            f'  <node text="{n.get("text","")}" resource-id="{rid}" '
            f'clickable="{str(n.get("clickable", False)).lower()}" '
            f'bounds="[{n["bounds"]}]" center="({n["cx"]},{n["cy"]})"/>'
        )
    lines.append("</hierarchy>")
    return "\n".join(lines)


def nearest_node(x: int, y: int) -> Optional[Dict[str, Any]]:
    nodes = SCREENS[state["screen"]]["nodes"]
    best = None
    best_d = 1e18
    for n in nodes:
        d = (n["cx"] - x) ** 2 + (n["cy"] - y) ** 2
        if d < best_d:
            best_d = d
            best = n
    return best


def handle_command(cmd: str, params: Dict[str, Any]) -> Any:
    cmd = (cmd or "").lower()
    if cmd == "get_ui_tree":
        return tree_xml()
    if cmd == "tap":
        x = int(params.get("x") or 0)
        y = int(params.get("y") or 0)
        n = nearest_node(x, y)
        text = (n or {}).get("text", "")
        print(f"  tap({x},{y}) -> {text!r} screen={state['screen']}", flush=True)
        if state["screen"] == "home" and "Settings" in text:
            state["screen"] = "settings"
        elif state["screen"] == "settings" and "About" in text:
            state["screen"] = "about"
            state["about_seen"] = True
        elif state["screen"] == "settings" and "Display" in text:
            state["screen"] = "display"
        elif state["screen"] == "about" and (
            "Android" in text or "version" in text.lower()
        ):
            state["about_seen"] = True
        elif state["screen"] in ("display", "display_dark") and (
            "Dark" in text or "On" in text or "Off" in text
        ):
            state["dark"] = not state["dark"]
            state["screen"] = "display_dark" if state["dark"] else "display"
        return "OK"
    if cmd == "open_app":
        app = str(params.get("app") or params.get("package") or "").lower()
        print(f"  open_app({app})", flush=True)
        if "setting" in app:
            state["screen"] = "settings"
        return "OK"
    if cmd == "press_button":
        btn = str(params.get("button") or "")
        if btn == "back":
            if state["screen"] in ("display", "display_dark", "about"):
                state["screen"] = "settings"
            elif state["screen"] == "settings":
                state["screen"] = "home"
        return "OK"
    if cmd in ("swipe", "input_text", "type_text"):
        return "OK"
    raise RuntimeError(f"unknown command {cmd}")


async def run_device(session_token: str, device_id: str) -> None:
    url = f"{WS}?device_id={device_id}&role=device"
    print("WS connect", WS, "device", device_id, flush=True)
    async with websockets.connect(url, ping_interval=20, ping_timeout=60) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "register",
                    "device_id": device_id,
                    "device_name": "prod-sim-emu",
                    "name": "prod-sim-emu",
                    "platform": "android",
                    "session_token": session_token,
                }
            )
        )
        print("WS registered", flush=True)

        async def heartbeat():
            while True:
                await asyncio.sleep(20)
                try:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "heartbeat",
                                "device_id": device_id,
                                "session_token": session_token,
                            }
                        )
                    )
                except Exception:
                    return

        hb = asyncio.create_task(heartbeat())
        try:
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                mtype = msg.get("type")
                if mtype == "command":
                    rid = msg.get("request_id")
                    cmd = msg.get("command")
                    params = msg.get("params") or {}
                    try:
                        result = handle_command(cmd, params)
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "response",
                                    "request_id": rid,
                                    "device_id": device_id,
                                    "result": result,
                                }
                            )
                        )
                    except Exception as e:
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "response",
                                    "request_id": rid,
                                    "device_id": device_id,
                                    "error": str(e),
                                }
                            )
                        )
                elif mtype == "agent_control":
                    print(
                        "agent_control",
                        msg.get("action"),
                        msg.get("step"),
                        flush=True,
                    )
        finally:
            hb.cancel()


def main() -> int:
    print("login…")
    token = http("POST", "/api/auth/login", {"username": USER, "password": PASSWORD})[
        "access_token"
    ]
    pair = http(
        "POST",
        "/api/auth/pair/create",
        {"device_name": "prod-sim-emu", "platform": "android"},
        token=token,
    )
    code = pair.get("code") or pair["token"]
    print("PAIR_CODE", code)
    claim = http(
        "POST",
        "/api/auth/pair/claim",
        {
            "token": code,
            "device_name": "prod-sim-emu",
            "device_id": DEVICE_ID,
            "platform": "android",
        },
    )
    session = claim["session_token"]
    did = claim["device_id"]
    print("CLAIMED", did)
    with open("/tmp/prod-e2e/sim_device.json", "w") as f:
        json.dump({"device_id": did, "session_token": session, "code": code}, f)
    # Run forever
    asyncio.run(run_device(session, did))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
