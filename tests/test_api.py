"""Parsing of the switch's CGI pages, against canned HTML."""
import asyncio

from custom_components.keeplink_switch.api import (
    KeepLinkClient,
    _cells,
    _counter,
    detect_poe,
)


def _table(*rows):
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<html><table>{body}</table></html>"


PAGES = {
    "info.cgi": _table(
        ["Device Model", "KP-9000-9XHPML-X-AC"],
        ["MAC Address", "AA:BB:CC:00:11:22"],
        ["Firmware Version", "V1.2"],
    ),
    "port.cgi": _table(
        ["Port", "State", "Speed/Duplex", "Link", "Flow"],  # header: skipped
        ["Port 1", "Enable", "Auto", "1000Full", "Off", "Off"],
        ["Port 2", "Disable", "100M/Full", "Link Down", "On", "On"],
        ["Port 9", "Enable", "Auto", "10G Full", "Off", "Off"],
    ),
    "port.cgi?page=stats": _table(
        ["Port 1", "Enable", "Up", "10", "0", "1-5", "2"],
        ["Port 2", "Disable", "Down", "0", "0", "0", "0"],
    ),
    "vlan.cgi?page=port_based": _table(["Port 1", "1"], ["Port 2", "x"]),
    "pse_port.cgi": _table(
        ["Port 1", "Enable", "On", "Class 2", "4.5", "53.1", "85"],
        ["Port 2", "Enable", "Off", "-", "0", "0", "0"],
    ),
    "pse_system.cgi": '<input name="pse_con_pwr" value="4.5">',
    "mac.cgi?page=fwd_tbl": _table(
        ["1", "aa:bb:cc:dd:ee:01", "1", "Dynamic", "1"],
        ["2", "AA:BB:CC:DD:EE:02", "1", "Dynamic", "9"],
        ["3", "not-a-mac", "1", "Dynamic", "1"],
    )
    + "<button id=next disabled>",
}


class FakeClient(KeepLinkClient):
    """Serves PAGES instead of talking to a switch."""

    def __init__(self):
        super().__init__(None, "192.0.2.1", "admin", "admin")
        self.requests = []

    async def _raw(self, method, path, data=None):
        self.requests.append((method, path, data))
        return PAGES.get(path, "")


def test_counter():
    assert _counter("42") == 42
    assert _counter("1-5") == 4294967296 + 5
    assert _counter("n/a") is None


def test_detect_poe():
    assert detect_poe("KP-9000-9XHPML-X-AC")
    assert not detect_poe("KP-9000-9XHML-X")


def test_cells_strips_tags_and_entities():
    rows = _cells("<tr><td><b>Port&nbsp;1</b></td><th> x </th></tr><tr></tr>")
    assert rows == [["Port\xa01", "x"]]


def test_fetch_parses_every_page():
    data = asyncio.run(FakeClient().fetch(want_poe=True, want_macs=True))
    assert (data.model, data.mac, data.firmware) == (
        "KP-9000-9XHPML-X-AC",
        "aa:bb:cc:00:11:22",
        "V1.2",
    )
    assert list(data.ports) == [1, 2, 9]
    p1, p2, p9 = data.ports[1], data.ports[2], data.ports[9]
    assert (p1.enabled, p1.link, p1.speed, p1.duplex) == (True, True, 1000, "full")
    assert (p2.enabled, p2.link, p2.speed_config, p2.flow_control) == (
        False,
        False,
        "100M/Full",
        True,
    )
    assert p9.speed == 10000
    assert (p1.tx_packets, p1.rx_packets, p1.rx_bad) == (10, 4294967301, 2)
    assert (p1.pvid, p2.pvid) == (1, None)
    assert (p1.poe_powered, p1.poe_class, p1.poe_power) == (True, "Class 2", 4.5)
    assert (p2.poe_powered, p2.poe_class, p2.poe_power) == (False, None, 0.0)
    assert data.poe_total == 4.5
    assert set(data.macs) == {"aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"}
    assert (p1.mac_count, p9.mac_count) == (1, 1)


def test_fetch_skips_optional_pages():
    client = FakeClient()
    data = asyncio.run(client.fetch(want_poe=False, want_macs=False))
    paths = {path for _, path, _ in client.requests}
    assert "pse_port.cgi" not in paths and "mac.cgi?page=fwd_tbl" not in paths
    assert data.ports[1].poe_enabled is None and not data.macs


def test_set_port_keeps_speed_and_flow_control():
    client = FakeClient()
    data = asyncio.run(client.fetch(want_poe=False, want_macs=False))
    asyncio.run(client.set_port(data.ports[2], True))
    posts = [r for r in client.requests if r[0] == "POST"]
    assert posts[0] == (
        "POST",
        "port.cgi",
        {
            "portid": "1",
            "state": "1",
            "speed_duplex": "4",
            "flow": "1",
            "cmd": "port",
        },
    )
    assert posts[1][1] == "save.cgi"  # auto-save is on by default
