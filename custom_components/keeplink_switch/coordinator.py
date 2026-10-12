"""Data coordinator for a KeepLink switch."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import KeepLinkAuthError, KeepLinkClient, KeepLinkError, SwitchData
from .const import (
    CONF_HAS_POE,
    CONF_SCAN_INTERVAL,
    CONF_TRACK_DEVICES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class KeepLinkCoordinator(DataUpdateCoordinator[SwitchData]):
    """Poll the switch."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: KeepLinkClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client

    @property
    def has_poe(self) -> bool:
        return bool(
            self.config_entry.options.get(
                CONF_HAS_POE, self.config_entry.data.get(CONF_HAS_POE)
            )
        )

    async def _async_update_data(self) -> SwitchData:
        try:
            return await self.client.fetch(
                want_poe=self.has_poe,
                want_macs=self.config_entry.options.get(CONF_TRACK_DEVICES, True),
            )
        except KeepLinkAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except KeepLinkError as err:
            raise UpdateFailed(str(err)) from err
