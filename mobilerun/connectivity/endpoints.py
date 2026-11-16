"""Wireless endpoint selection: prefer LAN, fall back to cloud.

No USB/ADB required — phone always dials out over WebSocket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

SERVICE_TYPE = "_mobilerun._tcp"
SERVICE_TYPE_FQDN = "_mobilerun._tcp.local."


@dataclass(frozen=True)
class Endpoint:
    """A reachable backend endpoint for the phone."""

    kind: str  # "lan" | "cloud" | "discovered"
    http_url: str
    ws_url: str
    host: str = ""
    port: int = 0
    latency_ms: Optional[float] = None

    def with_latency(self, latency_ms: float) -> "Endpoint":
        return Endpoint(
            kind=self.kind,
            http_url=self.http_url,
            ws_url=self.ws_url,
            host=self.host,
            port=self.port,
            latency_ms=latency_ms,
        )


@dataclass
class PairingBundle:
    """Stored after one QR scan — both LAN and cloud targets."""

    token: str
    lan: Optional[Endpoint] = None
    cloud: Optional[Endpoint] = None
    discovered: List[Endpoint] = field(default_factory=list)

    def all_candidates(self) -> List[Endpoint]:
        out: List[Endpoint] = []
        # Discovered LAN first (fresh mDNS), then QR LAN, then cloud
        out.extend(self.discovered)
        if self.lan:
            out.append(self.lan)
        if self.cloud:
            out.append(self.cloud)
        return out


def http_to_ws(url: str, path: str = "/api/devices/connect") -> str:
    u = urlparse(url)
    scheme = "wss" if u.scheme == "https" else "ws"
    base = urlunparse((scheme, u.netloc, "", "", "", ""))
    p = path if path.startswith("/") else f"/{path}"
    return base.rstrip("/") + p


def build_pairing_url(
    *,
    token: str,
    lan_http: Optional[str] = None,
    lan_ws: Optional[str] = None,
    cloud_http: Optional[str] = None,
    cloud_ws: Optional[str] = None,
    backend: Optional[str] = None,
    ws: Optional[str] = None,
) -> str:
    """Build mobilerun://pair deep link with dual endpoints."""
    params = {"token": token}
    # Primary (legacy) fields for older APKs
    if backend or lan_http or cloud_http:
        params["backend"] = backend or lan_http or cloud_http or ""
    if ws or lan_ws or cloud_ws:
        params["ws"] = ws or lan_ws or cloud_ws or ""
    if lan_http:
        params["lan"] = lan_http
    if lan_ws:
        params["lan_ws"] = lan_ws
    if cloud_http:
        params["cloud"] = cloud_http
    if cloud_ws:
        params["cloud_ws"] = cloud_ws
    return "mobilerun://pair?" + urlencode(params)


def parse_pairing_uri(uri: str) -> PairingBundle:
    """Parse mobilerun://pair?... into a PairingBundle."""
    u = urlparse(uri)
    q = parse_qs(u.query)

    def one(key: str) -> Optional[str]:
        vals = q.get(key) or []
        return vals[0] if vals else None

    token = one("token") or ""
    lan_http = one("lan") or one("backend")
    lan_ws = one("lan_ws") or one("ws")
    cloud_http = one("cloud")
    cloud_ws = one("cloud_ws")

    # If only cloud-style WEBSOCKET_API was put in ws= and backend is API Gateway HTTP
    backend = one("backend")
    ws = one("ws")
    lan: Optional[Endpoint] = None
    cloud: Optional[Endpoint] = None

    if lan_http or lan_ws:
        http = lan_http or ""
        wsu = lan_ws or (http_to_ws(http) if http else "")
        host = urlparse(http or wsu.replace("ws", "http")).hostname or ""
        port = urlparse(http or wsu.replace("ws", "http")).port or (
            443 if (http or "").startswith("https") else 8000
        )
        # Treat as LAN when host looks private / localhost / emulator
        kind = "lan" if _looks_lan(host) else "cloud"
        ep = Endpoint(kind=kind, http_url=http, ws_url=wsu, host=host, port=port or 0)
        if kind == "lan":
            lan = ep
        else:
            cloud = ep

    if cloud_http or cloud_ws:
        http = cloud_http or ""
        wsu = cloud_ws or (http_to_ws(http) if http else "")
        host = urlparse(http or wsu.replace("ws", "http")).hostname or ""
        port = urlparse(http or wsu.replace("ws", "http")).port or 443
        cloud = Endpoint(
            kind="cloud", http_url=http, ws_url=wsu, host=host, port=port or 0
        )
    elif ws and backend and cloud is None and lan is None:
        # Legacy single endpoint
        host = urlparse(backend).hostname or ""
        ep = Endpoint(
            kind="lan" if _looks_lan(host) else "cloud",
            http_url=backend,
            ws_url=ws,
            host=host,
            port=urlparse(backend).port or 0,
        )
        if ep.kind == "lan":
            lan = ep
        else:
            cloud = ep

    return PairingBundle(token=token, lan=lan, cloud=cloud)


def _looks_lan(host: str) -> bool:
    h = (host or "").lower()
    if h in ("localhost", "127.0.0.1", "10.0.2.2", "::1"):
        return True
    if h.startswith("192.168.") or h.startswith("10."):
        return True
    if h.startswith("172."):
        try:
            second = int(h.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (IndexError, ValueError):
            pass
    return False


def select_endpoint(
    candidates: Sequence[Endpoint],
    *,
    prefer_lan: bool = True,
    max_lan_latency_ms: float = 250.0,
) -> Optional[Endpoint]:
    """Pick best endpoint: measured LAN wins if under threshold, else lowest latency, else first cloud.

    Candidates without latency are ordered after measured ones of the same kind
    but still preferred over unmeasured cloud when prefer_lan.
    """
    if not candidates:
        return None

    measured = [c for c in candidates if c.latency_ms is not None]
    unmeasured = [c for c in candidates if c.latency_ms is None]

    if prefer_lan:
        lan_ok = [
            c
            for c in measured
            if c.kind in ("lan", "discovered")
            and c.latency_ms is not None
            and c.latency_ms <= max_lan_latency_ms
        ]
        if lan_ok:
            return min(lan_ok, key=lambda c: c.latency_ms or 1e9)

    if measured:
        return min(measured, key=lambda c: c.latency_ms or 1e9)

    if prefer_lan:
        for c in unmeasured:
            if c.kind in ("lan", "discovered"):
                return c
    for c in unmeasured:
        if c.kind == "cloud":
            return c
    return unmeasured[0] if unmeasured else None


def next_backoff_seconds(
    attempt: int,
    *,
    base: float = 1.0,
    factor: float = 2.0,
    max_delay: float = 60.0,
    jitter: float = 0.2,
    rng=None,
) -> float:
    """Exponential backoff with jitter for reconnect."""
    import random

    r = rng or random
    delay = min(max_delay, base * (factor ** max(0, attempt)))
    j = delay * jitter
    return max(0.2, delay + r.uniform(-j, j))


def merge_discovered(
    bundle: PairingBundle, discovered: Iterable[Endpoint]
) -> PairingBundle:
    seen = {(e.ws_url, e.host, e.port) for e in bundle.discovered}
    extra = list(bundle.discovered)
    for d in discovered:
        key = (d.ws_url, d.host, d.port)
        if key not in seen:
            seen.add(key)
            extra.append(d)
    return PairingBundle(
        token=bundle.token, lan=bundle.lan, cloud=bundle.cloud, discovered=extra
    )
