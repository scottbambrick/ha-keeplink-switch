"""PoE port control."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import KeepLinkPortEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        KeepLinkPoeSwitch(coordinator, n)
        for n, p in coordinator.data.ports.items()
        if p.poe_enabled is not None
    ]
    entities += [KeepLinkPortSwitch(coordinator, n) for n in coordinator.data.ports]
    async_add_entities(entities)


class KeepLinkPoeSwitch(KeepLinkPortEntity, SwitchEntity):
    _attr_icon = "mdi:ethernet-cable"

    def __init__(self, coordinator, port: int) -> None:
        super().__init__(coordinator, port, "poe", "PoE")

    @property
    def is_on(self) -> bool:
        return bool(self.port_data.poe_enabled)

    @property
    def extra_state_attributes(self) -> dict:
        p = self.port_data
        if not p.poe_enabled:
            summary = "PoE disabled"
        elif not p.poe_powered:
            summary = "Enabled, no device drawing power"
        else:
            summary = (
                f"{p.poe_power:g} W · {p.poe_voltage:g} V · "
                f"{p.poe_current:g} mA · {p.poe_class or 'unknown class'}"
            )
        return {
            **super().extra_state_attributes,
            "powered": p.poe_powered,
            "poe_class": p.poe_class,
            "power_w": p.poe_power,
            "voltage_v": p.poe_voltage,
            "current_ma": p.poe_current,
            "summary": summary,
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.client.set_poe(self.port, True)
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.client.set_poe(self.port, False)
        await self.coordinator.async_refresh()


class KeepLinkPortSwitch(KeepLinkPortEntity, SwitchEntity):
    """Administrative state of the port itself (off = port shut down).

    Disabled by default: switching off the port your Home Assistant (or the
    uplink) is connected through cuts you off from the switch.
    """

    _attr_icon = "mdi:ethernet"
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, port: int) -> None:
        super().__init__(coordinator, port, "port_enabled", "enabled")

    @property
    def is_on(self) -> bool:
        return self.port_data.enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.client.set_port(self.port_data, True)
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.client.set_port(self.port_data, False)
        await self.coordinator.async_refresh()
