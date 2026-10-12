"""KeepLink managed switch integration."""
from __future__ import annotations

from aiohttp import DummyCookieJar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import KeepLinkClient
from .const import CONF_AUTO_SAVE, CONF_IGNORED_PORTS, DOMAIN
from .coordinator import KeepLinkCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
]

type KeepLinkConfigEntry = ConfigEntry[KeepLinkCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: KeepLinkConfigEntry) -> bool:
    """Set up one switch."""
    # The switch is authenticated by a cookie we send ourselves. Created during
    # entry setup, the session is detached again when the entry unloads.
    session = async_create_clientsession(hass, cookie_jar=DummyCookieJar())
    client = KeepLinkClient(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        save_after_change=entry.options.get(CONF_AUTO_SAVE, True),
    )
    coordinator = KeepLinkCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: KeepLinkConfigEntry) -> None:
    """Apply changed options by reloading."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: KeepLinkConfigEntry) -> bool:
    """Unload a switch."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: KeepLinkConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Let the user delete stale tracked-device entries (never the switch itself)."""
    coordinator = entry.runtime_data
    if any(ident[0] == DOMAIN for ident in device_entry.identifiers):
        return False
    live = any(
        e.config_entry_id == entry.entry_id
        for e in er.async_entries_for_device(er.async_get(hass), device_entry.id)
    )
    if not live:
        return True  # nothing of ours is attached any more
    ignored = {int(p) for p in entry.options.get(CONF_IGNORED_PORTS, [])}
    macs = {
        c[1] for c in device_entry.connections if c[0] == dr.CONNECTION_NETWORK_MAC
    }
    # refuse while the device is still present on a tracked port
    return not any(
        (info := coordinator.data.macs.get(m)) and info["port"] not in ignored
        for m in macs
    )
