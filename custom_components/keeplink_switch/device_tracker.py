"""Presence for wired devices, from the switch's MAC address table."""
from __future__ import annotations

import asyncio
import logging
import re
import socket

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_IGNORED_PORTS,
    CONF_PORT_NAMES,
    CONF_TRACK_DEVICES,
    DOMAIN,
)
from .entity import KeepLinkEntity

_LOGGER = logging.getLogger(__name__)
RENAME_EVERY = 600  # seconds between name look-ups per device
GENERIC_HOSTS = ("localhost", "unknown")
IPV4_RE = re.compile(r"\d{1,3}(\.\d{1,3}){3}")


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add a tracker per MAC learned on a non-ignored port (and known ones)."""
    coordinator = entry.runtime_data
    if not entry.options.get(CONF_TRACK_DEVICES, True):
        return
    ignored = {int(p) for p in entry.options.get(CONF_IGNORED_PORTS, [])}
    known: set[str] = set()

    # Restore devices seen before (so they show as "away" after a restart).
    registry = er.async_get(hass)
    prefix = f"{coordinator.data.mac}_dev_"
    for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg.domain == "device_tracker" and reg.unique_id.startswith(prefix):
            known.add(reg.unique_id[len(prefix):])
    async_add_entities(KeepLinkTracker(coordinator, mac) for mac in sorted(known))

    @callback
    def _discover() -> None:
        own = {coordinator.data.mac}
        new = [
            mac
            for mac, info in coordinator.data.macs.items()
            if mac not in known and mac not in own and info["port"] not in ignored
        ]
        if new:
            known.update(new)
            async_add_entities(KeepLinkTracker(coordinator, mac) for mac in new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


def _arp_ip(mac: str) -> str | None:
    """IP for a MAC from the host's ARP table (blocking; run in the executor)."""
    try:
        with open("/proc/net/arp", encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                parts = line.split()
                complete = parts[2] != "0x0" if len(parts) >= 4 else False
                if complete and parts[3].lower() == mac:
                    return parts[0]
    except OSError:
        return None
    return None


def _reverse_dns(ip: str) -> str | None:
    """Host name label from a PTR record (blocking; run in the executor)."""
    try:
        host = socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        return None
    if host == ip or IPV4_RE.fullmatch(host):
        return None  # no PTR record: the resolver just echoed the address
    label = host.split(".")[0]
    if (
        not label
        or label.lower() in GENERIC_HOSTS
        or IPV4_RE.fullmatch(label.replace("-", "."))
    ):
        return None
    return label


class KeepLinkTracker(KeepLinkEntity, ScannerEntity):
    """A MAC address that is (or was) learned on a non-ignored port."""

    # the friendly name is the device's name, which we keep updated with whatever
    # we can discover about the MAC (see _discover_name)
    _attr_name = None

    def __init__(self, coordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._device_mac = mac
        self._attr_entity_registry_enabled_default = True
        self._found: str | None = None
        self._last_lookup = 0.0

    @property
    def unique_id(self) -> str:
        # ScannerEntity defaults this to the bare MAC, which collides when two
        # switches both see the same device.
        return f"{self._mac}_dev_{self._device_mac}"

    @property
    def mac_address(self) -> str:
        return format_mac(self._device_mac)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            connections={(CONNECTION_NETWORK_MAC, format_mac(self._device_mac))},
            name=self._display_name(),
        )

    def _display_name(self) -> str:
        return f"{self._found} (wired)" if self._found else self._device_mac.upper()

    def _registry_name(self) -> tuple[str, str] | None:
        """Names other integrations already know for this MAC (UniFi etc.)."""
        hass = self.coordinator.hass
        mac = self._device_mac
        ours = self.coordinator.config_entry.entry_id
        devices = dr.async_get(hass).async_get_devices(
            connections={(CONNECTION_NETWORK_MAC, mac)}
        )
        for dev in devices:
            if dev.config_entry_id != ours and (name := dev.name_by_user or dev.name):
                return name, "device registry"
        compact = mac.replace(":", "")
        for ent in er.async_get(hass).entities.values():
            if ent.domain != "device_tracker" or ent.platform == DOMAIN:
                continue
            uid = ent.unique_id.lower().replace(":", "").replace("-", "")
            if compact in uid and (name := ent.name or ent.original_name):
                return name, f"{ent.platform} tracker"
        return None

    async def _discover_name(self) -> None:
        found = self._registry_name()
        if not found:
            hass = self.coordinator.hass
            ip = await hass.async_add_executor_job(_arp_ip, self._device_mac)
            if ip:
                # Stops waiting, but the look-up thread may run on until the
                # resolver itself gives up
                try:
                    async with asyncio.timeout(4):
                        host = await hass.async_add_executor_job(_reverse_dns, ip)
                except TimeoutError:
                    host = None
                if host:
                    found = (host, f"reverse DNS of {ip}")
            if not found:
                info = self.coordinator.data.macs.get(self._device_mac)
                names = self.coordinator.config_entry.options.get(
                    CONF_PORT_NAMES, {}
                )
                desc = info and names.get(str(info["port"]))
                macs = self.coordinator.data.macs.values()
                alone = info and sum(i["port"] == info["port"] for i in macs) == 1
                if desc and alone:
                    found = (desc, "port description")
        if found and found[0] != self._found:
            _LOGGER.debug(
                "Named %s %r from %s", self._device_mac, found[0], found[1]
            )
            self._found = found[0]
            self._push_name()

    def _push_name(self) -> None:
        """Keep the device-registry name current unless the user renamed it."""
        registry = dr.async_get(self.coordinator.hass)
        name = self._display_name()
        for device in registry.async_get_devices(
            connections={(CONNECTION_NETWORK_MAC, format_mac(self._device_mac))},
            config_entry_id=self.coordinator.config_entry.entry_id,
        ):
            if not device.name_by_user and device.name != name:
                registry.async_update_device(device.id, name=name)

    def _start_name_lookup(self) -> None:
        self._last_lookup = self.hass.loop.time()
        self.coordinator.config_entry.async_create_background_task(
            self.hass, self._discover_name(), f"keeplink name {self._device_mac}"
        )

    async def async_added_to_hass(self) -> None:
        """Look the name up once added, then every RENAME_EVERY seconds."""
        await super().async_added_to_hass()
        self._start_name_lookup()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.hass.loop.time() - self._last_lookup > RENAME_EVERY:
            self._start_name_lookup()
        super()._handle_coordinator_update()

    def _entry_info(self) -> dict | None:
        info = self.coordinator.data.macs.get(self._device_mac)
        options = self.coordinator.config_entry.options
        ignored = {int(p) for p in options.get(CONF_IGNORED_PORTS, [])}
        if info and info["port"] not in ignored:
            return info
        return None

    @property
    def is_connected(self) -> bool:
        return self._entry_info() is not None

    @property
    def extra_state_attributes(self) -> dict:
        info = self._entry_info()
        if not info:
            return {}
        names = self.coordinator.config_entry.options.get(CONF_PORT_NAMES, {})
        return {
            "switch": self.coordinator.config_entry.title,
            "port": info["port"],
            "port_description": names.get(str(info["port"])) or None,
            "vlan": info["vlan"],
        }
