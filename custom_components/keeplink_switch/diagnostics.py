"""Diagnostics (credentials and device MAC addresses are redacted)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

TO_REDACT = {CONF_HOST, CONF_PASSWORD, CONF_USERNAME, "mac"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry) -> dict[str, Any]:
    data = entry.runtime_data.data
    snapshot = asdict(data)
    snapshot["macs"] = {
        f"device-{i}": {"port": v["port"], "vlan": v["vlan"], "type": v["type"]}
        for i, v in enumerate(data.macs.values())
    }
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": async_redact_data(snapshot, TO_REDACT),
    }
