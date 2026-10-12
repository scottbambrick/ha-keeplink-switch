"""Presence for wired devices, from the switch's MAC address table."""
from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_IGNORED_PORTS, CONF_PORT_NAMES, CONF_TRACK_DEVICES, DOMAIN
from .entity import KeepLinkEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
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


class KeepLinkTracker(KeepLinkEntity, ScannerEntity):
    """A MAC address that is (or was) learned on a non-ignored port."""

    _attr_has_entity_name = False

    def __init__(self, coordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._device_mac = mac
        self._attr_unique_id = f"{self._mac}_dev_{mac}"
        self._attr_name = mac.upper()
        self._attr_entity_registry_enabled_default = True

    @property
    def unique_id(self) -> str:
        # ScannerEntity defaults this to the bare MAC, which collides when two
        # switches both see the same device.
        return f"{self._mac}_dev_{self._device_mac}"

    @property
    def mac_address(self) -> str:
        return format_mac(self._device_mac)

    def _entry_info(self) -> dict | None:
        info = self.coordinator.data.macs.get(self._device_mac)
        ignored = {int(p) for p in self.coordinator.config_entry.options.get(CONF_IGNORED_PORTS, [])}
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
