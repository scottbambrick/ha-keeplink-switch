"""Port link-state binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import KeepLinkPortEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        KeepLinkLink(coordinator, n) for n in coordinator.data.ports
    )


class KeepLinkLink(KeepLinkPortEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, port: int) -> None:
        super().__init__(coordinator, port, "link", "link")

    @property
    def is_on(self) -> bool:
        return self.port_data.link

    @property
    def extra_state_attributes(self) -> dict:
        p = self.port_data
        return {
            **super().extra_state_attributes,
            "admin_enabled": p.enabled,
            "duplex": p.duplex,
            "learned_macs": p.mac_count,
            "configured_speed": p.speed_config,
            "flow_control": p.flow_control,
            "pvid": p.pvid,
        }
