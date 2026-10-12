"""Port and switch sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfDataRate,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import PortData
from .entity import KeepLinkEntity, KeepLinkPortEntity


@dataclass(frozen=True, kw_only=True)
class PortSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PortData], float | int | str | None]
    poe: bool = False


def _status(p: PortData) -> str:
    if not p.enabled:
        return "Disabled"
    if not p.link or not p.speed:
        return "Down"
    gbit = p.speed / 1000
    return f"{gbit:g} Gbit/s" if p.speed >= 1000 else f"{p.speed} Mbit/s"


PORT_SENSORS: tuple[PortSensorDescription, ...] = (
    PortSensorDescription(
        key="status",
        name="status",
        icon="mdi:ethernet",
        value_fn=_status,
    ),
    PortSensorDescription(
        key="speed",
        name="speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        icon="mdi:speedometer",
        value_fn=lambda p: p.speed or 0,
    ),
    # The switch only exposes packet counters, not byte counters.
    PortSensorDescription(
        key="tx_packets",
        entity_registry_enabled_default=False,
        name="TX packets",
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:upload-network",
        suggested_display_precision=0,
        value_fn=lambda p: p.tx_packets,
    ),
    PortSensorDescription(
        key="rx_packets",
        entity_registry_enabled_default=False,
        name="RX packets",
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:download-network",
        suggested_display_precision=0,
        value_fn=lambda p: p.rx_packets,
    ),
    PortSensorDescription(
        key="tx_bad",
        name="TX bad packets",
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda p: p.tx_bad,
    ),
    PortSensorDescription(
        key="rx_bad",
        name="RX bad packets",
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda p: p.rx_bad,
    ),
    PortSensorDescription(
        key="poe_power",
        name="PoE power",
        poe=True,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p: p.poe_power,
    ),
    PortSensorDescription(
        key="poe_voltage",
        name="PoE voltage",
        poe=True,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.poe_voltage,
    ),
    PortSensorDescription(
        key="poe_current",
        name="PoE current",
        poe=True,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.poe_current,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for n, port in coordinator.data.ports.items():
        for desc in PORT_SENSORS:
            if desc.poe and port.poe_enabled is None:
                continue
            entities.append(KeepLinkPortSensor(coordinator, n, desc))
    if coordinator.has_poe:
        entities.append(KeepLinkPoeTotal(coordinator))
    async_add_entities(entities)


class KeepLinkPortSensor(KeepLinkPortEntity, SensorEntity):
    entity_description: PortSensorDescription

    def __init__(
        self, coordinator, port: int, description: PortSensorDescription
    ) -> None:
        super().__init__(coordinator, port, description.key, description.name)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.port_data)


class KeepLinkPoeTotal(KeepLinkEntity, SensorEntity):
    _attr_name = "PoE power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._mac}_poe_total"

    @property
    def native_value(self):
        return self.coordinator.data.poe_total
