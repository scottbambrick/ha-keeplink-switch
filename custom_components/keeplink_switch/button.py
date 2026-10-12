"""Reboot and save-configuration buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import KeepLinkEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([KeepLinkSaveButton(coordinator), KeepLinkRebootButton(coordinator)])


class KeepLinkSaveButton(KeepLinkEntity, ButtonEntity):
    """Write the running configuration to flash (unsaved changes are lost on reboot)."""

    _attr_name = "Save configuration"
    _attr_icon = "mdi:content-save"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._mac}_save"

    async def async_press(self) -> None:
        await self.coordinator.client.save()


class KeepLinkRebootButton(KeepLinkEntity, ButtonEntity):
    _attr_name = "Reboot"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._mac}_reboot"

    async def async_press(self) -> None:
        await self.coordinator.client.reboot()
