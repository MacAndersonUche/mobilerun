#!/usr/bin/env python3
"""Verify hosted-site short codes pair via AWS with no LAN (Mac's phone path).

Simulates claim order: optional dead LAN (≤2s timeout) → baked prod API → Remove.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

PROD = sys.argv[1] if len(sys.argv) > 1 else (
    "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com"
)
DEAD_LAN = "http://203.0.113.1:9"


def post(path: str, body: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(
        PROD + path,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def main() -> None:
    tok = post("/api/auth/login", {"username": "ci-e2e", "password": "admin"})[
        "access_token"
    ]
    pair = post(
        "/api/auth/pair/create",
        {"device_name": "cloud-only-host", "platform": "android"},
        tok,
    )
    code = pair.get("code") or pair["token"]
    assert 6 <= len(code) <= 8, code
    short = pair.get("short_link") or pair.get("https_link") or ""
    assert f"/p/{code}" in short, pair

    # Dead LAN must fail quickly (≤2s) — mirrors claimClient connectTimeout
    t0 = time.time()
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                DEAD_LAN + "/api/auth/pair/claim",
                data=json.dumps({"token": code}).encode(),
                headers={"Content-Type": "application/json"},
            ),
            timeout=2,
        )
        raise SystemExit("dead LAN unexpectedly succeeded")
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"dead_lan_fail_in={elapsed:.2f}s ({type(exc).__name__})")
        assert elapsed <= 2.5, elapsed

    # Code-only claim against baked AWS (no LAN host)
    claim = post(
        "/api/auth/pair/claim",
        {
            "token": code,
            "device_name": "Pixel-cloud-only",
            "device_id": "device_cloud_only_host",
        },
    )
    did = claim["device_id"]
    assert claim.get("session_token"), claim
    print("claimed", did, "owner", claim.get("owner"))

    devices: list = []
    for _ in range(8):
        req = urllib.request.Request(
            PROD + "/api/devices", headers={"Authorization": f"Bearer {tok}"}
        )
        devices = json.load(urllib.request.urlopen(req, timeout=15))
        if any(d.get("device_id") == did for d in devices):
            break
        time.sleep(0.5)
    assert any(d.get("device_id") == did for d in devices), devices

    req = urllib.request.Request(
        PROD + f"/api/devices/{did}",
        method="DELETE",
        headers={"Authorization": f"Bearer {tok}"},
    )
    print("remove", json.load(urllib.request.urlopen(req, timeout=15)))
    left = json.load(
        urllib.request.urlopen(
            urllib.request.Request(
                PROD + "/api/devices", headers={"Authorization": f"Bearer {tok}"}
            ),
            timeout=15,
        )
    )
    assert not any(d.get("device_id") == did for d in left), left
    print("PROD_CLOUD_ONLY_PAIR_OK", code)


if __name__ == "__main__":
    main()
