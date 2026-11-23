#!/usr/bin/env python3
"""Assert APK upgrades over installed phone build (package + version + signer)."""

from __future__ import annotations

import hashlib
import re
import struct
import subprocess
import sys
from pathlib import Path

EXPECTED_PACKAGE = "ai.mobilerun.selfhosted"
EXPECTED_SHA256 = "16AD2626AC90F0B72DB78BF1DABDBD0FA85205D24FBD35D89F6B1A2E774D3386"
MIN_VERSION_CODE = 490  # phone has 489


def u32(buf: bytes, i: int) -> tuple[int, int]:
    return struct.unpack_from("<I", buf, i)[0], i + 4


def lp(buf: bytes, i: int) -> tuple[bytes, int]:
    n, i = u32(buf, i)
    return buf[i : i + n], i + n


def keystore_sha256(keystore: Path) -> str:
    out = subprocess.check_output(
        [
            "keytool",
            "-list",
            "-v",
            "-keystore",
            str(keystore),
            "-storepass",
            "android",
            "-alias",
            "androiddebugkey",
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )
    print(out)
    m = re.search(r"SHA256:\s*([0-9A-Fa-f:]+)", out)
    if not m:
        raise SystemExit("keystore SHA256 not found")
    return m.group(1).replace(":", "").upper()


def aapt_badging(apk: Path) -> tuple[str, int, str]:
    out = subprocess.check_output(["aapt", "dump", "badging", str(apk)], text=True)
    print(out.splitlines()[0] if out else "")
    pkg = re.search(r"name='([^']+)'", out)
    vc = re.search(r"versionCode='(\d+)'", out)
    vn = re.search(r"versionName='([^']+)'", out)
    if not (pkg and vc and vn):
        raise SystemExit("aapt badging parse failed")
    return pkg.group(1), int(vc.group(1)), vn.group(1)


def apk_v2_cert_sha256(apk: Path) -> str:
    data = apk.read_bytes()
    eocd = data.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise SystemExit("APK EOCD not found")
    cd = struct.unpack_from("<I", data, eocd + 16)[0]
    magic = data.rfind(b"APK Sig Block 42", 0, cd)
    if magic < 0:
        raise SystemExit("APK Sig Block not found")
    size = struct.unpack_from("<Q", data, magic - 8)[0]
    pairs = data[cd - size : magic - 8]
    off = 0
    while off + 12 <= len(pairs):
        plen = struct.unpack_from("<Q", pairs, off)[0]
        off += 8
        if plen < 4 or off + plen > len(pairs):
            break
        pid = struct.unpack_from("<I", pairs, off)[0]
        val = pairs[off + 4 : off + plen]
        off += plen
        if pid != 0x7109871A:
            continue
        # length-prefixed sequence of signers
        seq, _ = lp(val, 0)
        signer, _ = lp(seq, 0)
        signed_data, _ = lp(signer, 0)
        _, k = lp(signed_data, 0)  # digests
        certs_blob, _ = lp(signed_data, k)
        cert, _ = lp(certs_blob, 0)
        if not cert or cert[0] != 0x30:
            raise SystemExit("APK v2 cert is not DER")
        return hashlib.sha256(cert).hexdigest().upper()
    raise SystemExit("APK v2 signer cert not found")


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "usage: verify_apk_upgrade.py <apk> <debug.keystore> [min_version_code]"
        )
    apk = Path(sys.argv[1])
    keystore = Path(sys.argv[2])
    min_vc = int(sys.argv[3]) if len(sys.argv) > 3 else MIN_VERSION_CODE

    pkg, vc, vn = aapt_badging(apk)
    print(f"PACKAGE={pkg} versionCode={vc} versionName={vn}")
    if pkg != EXPECTED_PACKAGE:
        raise SystemExit(f"package mismatch: {pkg}")
    if vc < min_vc:
        raise SystemExit(f"versionCode {vc} < min {min_vc} (phone has 489)")

    ks_fp = keystore_sha256(keystore)
    print(f"KEYSTORE_SHA256={ks_fp}")
    if ks_fp != EXPECTED_SHA256:
        raise SystemExit(f"keystore SHA-256 mismatch: {ks_fp}")

    apk_fp = apk_v2_cert_sha256(apk)
    print(f"APK_CERT_SHA256={apk_fp}")
    if apk_fp != EXPECTED_SHA256:
        raise SystemExit(f"APK signer SHA-256 mismatch: {apk_fp}")

    print(
        f"SIGNING_OK package={pkg} versionCode={vc} versionName={vn} SHA-256={EXPECTED_SHA256}"
    )


if __name__ == "__main__":
    main()
