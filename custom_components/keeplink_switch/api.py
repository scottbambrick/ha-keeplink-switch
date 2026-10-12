"""Client for KeepLink (Realtek web UI) managed switches."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import html
import re

import aiohttp

ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]*>")
SPEED_RE = re.compile(r"^(\d+)(G?)(Full|Half)$", re.I)


# <select name="speed_duplex"> option values in port.cgi
SPEED_VALUES = {
    "Auto": 0,
    "10M/Half": 1,
    "10M/Full": 2,
    "100M/Half": 3,
    "100M/Full": 4,
    "1000M/Full": 5,
    "2500M/Full": 6,
    "10G/Full": 8,
}
POE_MODEL_RE = re.compile(r"XHP|HP[A-Z]*L", re.I)


def detect_poe(model: str) -> bool:
    """Best guess from the model name (KP-9000-9XHPML-X-AC has PoE, 9XHML-X does not)."""
    return bool(POE_MODEL_RE.search(model))


class KeepLinkError(Exception):
    """Generic error talking to the switch."""


class KeepLinkAuthError(KeepLinkError):
    """Login rejected."""


@dataclass
class PortData:
    """Everything known about one front-panel port."""

    number: int
    enabled: bool = True
    link: bool = False
    speed: int | None = None  # Mbit/s
    duplex: str | None = None
    tx_packets: int | None = None
    rx_packets: int | None = None
    tx_bad: int | None = None
    rx_bad: int | None = None
    poe_enabled: bool | None = None
    poe_powered: bool | None = None
    poe_class: str | None = None
    poe_power: float | None = None
    poe_voltage: float | None = None
    poe_current: float | None = None
    mac_count: int = 0
    speed_config: str = "Auto"  # configured speed/duplex as the switch names it
    flow_control: bool = False  # configured flow control
    pvid: int | None = None


@dataclass
class SwitchData:
    """One refresh of a switch."""

    model: str = ""
    mac: str = ""
    firmware: str = ""
    ports: dict[int, PortData] = field(default_factory=dict)
    poe_total: float | None = None
    macs: dict[str, dict] = field(default_factory=dict)  # mac -> {port, vlan, type}


def _cells(text: str) -> list[list[str]]:
    rows = []
    for row in ROW_RE.findall(text):
        cells = [
            html.unescape(TAG_RE.sub("", c)).strip() for c in CELL_RE.findall(row)
        ]
        if cells:
            rows.append(cells)
    return rows


def _port_num(label: str) -> int | None:
    m = re.fullmatch(r"Port\s+(\d+)", label)
    return int(m.group(1)) if m else None


def _counter(value: str) -> int | None:
    """Parse a counter; some firmwares send 'hi-lo' 32-bit halves."""
    try:
        if "-" in value:
            hi, lo = value.split("-", 1)
            return int(hi) * 4294967296 + int(lo)
        return int(value)
    except ValueError:
        return None


def _float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


class KeepLinkClient:
    """Talk to the switch's CGI interface."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        save_after_change: bool = True,
    ) -> None:
        self.save_after_change = save_after_change
        self._session = session
        self._base = f"http://{host}"
        self._username = username
        self._password = password
        self._cookie = hashlib.md5(  # noqa: S324 - the switch dictates MD5
            (username + password).encode()
        ).hexdigest()
        self._lock = asyncio.Lock()

    async def _raw(self, method: str, path: str, data: dict | None = None) -> str:
        try:
            async with asyncio.timeout(15):
                async with self._session.request(
                    method,
                    f"{self._base}/{path}",
                    data=data,
                    headers={"Cookie": f"admin={self._cookie}"},
                ) as resp:
                    return await resp.text(errors="replace")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise KeepLinkError(f"Cannot reach switch: {err}") from err

    async def login(self) -> None:
        """Register this client with the switch (it keys the session on the cookie)."""
        text = await self._raw(
            "POST",
            "login.cgi",
            {
                "username": self._username,
                "password": self._password,
                "language": "EN",
                "Response": self._cookie,
            },
        )
        # login.cgi answers "OK" even for a wrong password; the real test is
        # whether a protected page then loads with our cookie.
        if 'replace("/")' not in text:
            raise KeepLinkAuthError("Login rejected")
        probe = await self._raw("GET", "info.cgi")
        if "Device Model" not in probe:
            raise KeepLinkAuthError("Invalid username or password")

    async def _page(
        self, method: str, path: str, data: dict | None = None
    ) -> str:
        text = await self._raw(method, path, data)
        if '"/login.cgi"' in text and len(text) < 600:
            await self.login()
            text = await self._raw(method, path, data)
            if '"/login.cgi"' in text and len(text) < 600:
                raise KeepLinkAuthError("Session rejected")
        return text

    async def get_info(self) -> tuple[str, str, str]:
        """Return (model, mac, firmware)."""
        text = await self._page("GET", "info.cgi")
        info = {r[0]: r[1] for r in _cells(text) if len(r) >= 2}
        return (
            info.get("Device Model", ""),
            info.get("MAC Address", "").lower(),
            info.get("Firmware Version", ""),
        )

    async def fetch(self, want_poe: bool, want_macs: bool) -> SwitchData:
        """Poll every page we need (sequentially - the switch is single threaded)."""
        async with self._lock:
            data = SwitchData()
            data.model, data.mac, data.firmware = await self.get_info()

            for row in _cells(await self._page("GET", "port.cgi")):
                n = _port_num(row[0]) if row else None
                if n is None or len(row) < 6:  # skips the selector rows above the table
                    continue
                port = data.ports.setdefault(n, PortData(n))
                port.enabled = row[1] == "Enable"
                port.speed_config = row[2]
                port.flow_control = row[4] == "On"
                m = SPEED_RE.match(row[3].replace(" ", ""))
                port.link = bool(m)
                if m:
                    port.speed = int(m.group(1)) * (1000 if m.group(2) else 1)
                    port.duplex = m.group(3).lower()

            for row in _cells(await self._page("GET", "port.cgi?page=stats")):
                n = _port_num(row[0]) if row else None
                if n is None or len(row) < 7 or n not in data.ports:
                    continue
                port = data.ports[n]
                port.tx_packets = _counter(row[3])
                port.tx_bad = _counter(row[4])
                port.rx_packets = _counter(row[5])
                port.rx_bad = _counter(row[6])

            for row in _cells(await self._page("GET", "vlan.cgi?page=port_based")):
                n = _port_num(row[0]) if row else None
                if n is not None and n in data.ports and len(row) >= 2 and row[1].isdigit():
                    data.ports[n].pvid = int(row[1])

            if want_poe:
                for row in _cells(await self._page("GET", "pse_port.cgi")):
                    n = _port_num(row[0]) if row else None
                    if n is None or len(row) < 7 or n not in data.ports:
                        continue
                    port = data.ports[n]
                    port.poe_enabled = row[1] == "Enable"
                    port.poe_powered = row[2] == "On"
                    port.poe_class = row[3] if row[3] != "-" else None
                    port.poe_power = _float(row[4]) if port.poe_powered else 0.0
                    port.poe_voltage = _float(row[5]) if port.poe_powered else 0.0
                    port.poe_current = _float(row[6]) if port.poe_powered else 0.0
                m = re.search(
                    r'name="pse_con_pwr"\s+value="([\d.]+)"',
                    await self._page("GET", "pse_system.cgi"),
                )
                data.poe_total = float(m.group(1)) if m else None

            if want_macs:
                text = await self._page("GET", "mac.cgi?page=fwd_tbl")
                for _ in range(10):  # follow pagination, bounded
                    for row in _cells(text):
                        if len(row) >= 5 and re.fullmatch(
                            r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", row[1]
                        ):
                            port = int(row[4]) if row[4].isdigit() else None
                            data.macs[row[1].lower()] = {
                                "port": port,
                                "vlan": row[2],
                                "type": row[3],
                            }
                            if port in data.ports:
                                data.ports[port].mac_count += 1
                    if re.search(r"id=next\s+disabled", text):
                        break
                    text = await self._page(
                        "POST", "mac.cgi?page=fwd_tbl", {"cmd": "nextpage"}
                    )
            data.ports = dict(sorted(data.ports.items()))
            return data

    async def _save_if_wanted(self) -> None:
        if self.save_after_change:
            await self._page("POST", "save.cgi", {"cmd": "save"})

    async def set_poe(self, port: int, enabled: bool) -> None:
        """Enable/disable PoE on a port (1-based)."""
        async with self._lock:
            await self._page(
                "POST",
                "pse_port.cgi",
                {"portid": str(port - 1), "state": "1" if enabled else "0", "cmd": "poe"},
            )
            await self._save_if_wanted()

    async def set_port(self, port: PortData, enabled: bool) -> None:
        """Enable/disable a port, keeping its configured speed and flow control."""
        speed = SPEED_VALUES.get(port.speed_config, 0)
        async with self._lock:
            await self._page(
                "POST",
                "port.cgi",
                {
                    "portid": str(port.number - 1),
                    "state": "1" if enabled else "0",
                    "speed_duplex": str(speed),
                    "flow": "1" if port.flow_control else "0",
                    "cmd": "port",
                },
            )
            await self._save_if_wanted()

    async def save(self) -> None:
        """Write the running configuration to flash."""
        async with self._lock:
            await self._page("POST", "save.cgi", {"cmd": "save"})

    async def reboot(self) -> None:
        """Reboot the switch."""
        async with self._lock:
            try:
                await self._page("POST", "reboot.cgi", {"cmd": "reboot"})
            except KeepLinkError:
                pass  # the switch may drop the connection as it goes down
