"""Base entities."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import PortData
from .const import CONF_PORT_NAMES, DOMAIN
from .coordinator import KeepLinkCoordinator


class KeepLinkEntity(CoordinatorEntity[KeepLinkCoordinator]):
    """Entity attached to the switch device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KeepLinkCoordinator) -> None:
        super().__init__(coordinator)
        d = coordinator.data
        self._mac = d.mac
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, d.mac)},
            connections={(CONNECTION_NETWORK_MAC, d.mac)},
            manufacturer="KeepLink",
            model=d.model,
            sw_version=d.firmware,
            name=coordinator.config_entry.title,
            configuration_url=f"http://{coordinator.config_entry.data['host']}",
        )


class KeepLinkPortEntity(KeepLinkEntity):
    """Entity for one port; the user-supplied description is part of the name."""

    def __init__(self, coordinator: KeepLinkCoordinator, port: int, key: str, label: str) -> None:
        super().__init__(coordinator)
        self.port = port
        self._label = label
        self._attr_unique_id = f"{self._mac}_port{port}_{key}"

    @property
    def port_data(self) -> PortData:
        return self.coordinator.data.ports[self.port]

    @property
    def port_description(self) -> str:
        names = self.coordinator.config_entry.options.get(CONF_PORT_NAMES, {})
        return (names.get(str(self.port)) or "").strip()

    @property
    def name(self) -> str:
        desc = self.port_description
        base = f"Port {self.port}" + (f" {desc}" if desc else "")
        return f"{base} {self._label}"

    @property
    def available(self) -> bool:
        return super().available and self.port in self.coordinator.data.ports

    @property
    def extra_state_attributes(self) -> dict:
        return {"port": self.port, "description": self.port_description or None}
