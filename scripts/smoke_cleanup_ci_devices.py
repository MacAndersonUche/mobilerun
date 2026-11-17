#!/usr/bin/env python3
"""Delete all devices for the current CI user (deploy smoke cleanup)."""

from __future__ import annotations

import json
import os
import sys
import urllib.request


def main() -> int:
    api = (os.environ.get("API_URL") or "").rstrip("/")
    token = os.environ.get("TOKEN") or ""
    if not api or not token:
        print("API_URL and TOKEN required", file=sys.stderr)
        return 2
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_devices.json"
    ds = json.load(open(path))
    for d in ds or []:
        did = d.get("device_id") or ""
        if not did:
            continue
        req = urllib.request.Request(
            api + "/api/devices/" + did,
            method="DELETE",
            headers={"Authorization": "Bearer " + token},
        )
        try:
            urllib.request.urlopen(req, timeout=30).read()
            print("deleted", did)
        except Exception as e:
            print("delete_failed", did, e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
