"""Advertise the local Mobilerun backend via mDNS/DNS-SD (_mobilerun._tcp)."""

from __future__ import annotations

import logging
import socket
from typing import Optional

from mobilerun.connectivity.endpoints import SERVICE_TYPE

logger = logging.getLogger("mobilerun.mdns")


def get_lan_ip(prefer: Optional[str] = None) -> str:
    """Best-effort LAN IPv4 for QR / mDNS (not 127.0.0.1)."""
    if prefer and prefer not in ("0.0.0.0", "::", "127.0.0.1"):
        return prefer
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


class MobilerunAdvertiser:
    """Zeroconf advertiser for laptop backend. No-op if zeroconf missing."""

    def __init__(
        self,
        *,
        port: int = 8000,
        host: str = "0.0.0.0",
        name: str = "Mobilerun",
        ws_path: str = "/api/devices/connect",
    ):
        self.port = port
        self.host = host
        self.name = name
        self.ws_path = ws_path
        self.lan_ip = get_lan_ip(None if host in ("0.0.0.0", "::") else host)
        self._zc = None
        self._info = None

    @property
    def lan_http(self) -> str:
        return f"http://{self.lan_ip}:{self.port}"

    @property
    def lan_ws(self) -> str:
        return f"ws://{self.lan_ip}:{self.port}{self.ws_path}"

    def start(self) -> bool:
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            logger.warning(
                "zeroconf not installed — LAN mDNS advertise disabled "
                "(pip install zeroconf)"
            )
            return False
        try:
            self._zc = Zeroconf()
            props = {
                b"path": self.ws_path.encode(),
                b"http": self.lan_http.encode(),
                b"ws": self.lan_ws.encode(),
                b"ver": b"1",
            }
            self._info = ServiceInfo(
                f"{SERVICE_TYPE}.local.",
                f"{self.name}.{SERVICE_TYPE}.local.",
                addresses=[socket.inet_aton(self.lan_ip)],
                port=self.port,
                properties=props,
                server=f"{self.name.lower().replace(' ', '-')}.local.",
            )
            self._zc.register_service(self._info)
            logger.info(
                "mDNS advertising %s on %s:%s (%s)",
                SERVICE_TYPE,
                self.lan_ip,
                self.port,
                self.lan_ws,
            )
            return True
        except Exception as e:
            logger.warning("mDNS advertise failed: %s", e)
            self.stop()
            return False

    def stop(self) -> None:
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
            if self._zc:
                self._zc.close()
        except Exception as e:
            logger.debug("mDNS stop: %s", e)
        self._zc = None
        self._info = None
