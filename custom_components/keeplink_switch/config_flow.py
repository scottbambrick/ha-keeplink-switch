"""Config, reauth, reconfigure and options flows."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import DummyCookieJar
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import KeepLinkAuthError, KeepLinkClient, KeepLinkError, detect_poe
from .const import (
    CONF_AUTO_SAVE,
    CONF_HAS_POE,
    CONF_IGNORED_PORTS,
    CONF_PORT_NAMES,
    CONF_SCAN_INTERVAL,
    CONF_TRACK_DEVICES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _probe(
    hass: HomeAssistant, host: str, username: str, password: str
) -> tuple[str, str]:
    """Log in and read the device identity. Returns (model, mac)."""
    # Outside entry setup nothing would detach the session for us
    session = async_create_clientsession(
        hass, auto_cleanup=False, cookie_jar=DummyCookieJar()
    )
    try:
        client = KeepLinkClient(session, host, username, password)
        await client.login()
        model, mac, _ = await client.get_info()
    finally:
        session.detach()
    return model, mac


class KeepLinkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a switch by address and web login."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the address and login, check them, create the entry."""
        errors: dict[str, str] = {}
        if user_input:
            try:
                model, mac = await _probe(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except KeepLinkAuthError:
                errors["base"] = "invalid_auth"
            except KeepLinkError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: user_input[CONF_HOST]}
                )
                title = user_input.get("name") or f"Switch {user_input[CONF_HOST]}"
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_HAS_POE: detect_poe(model),
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_USERNAME, default="admin"): str,
                vol.Required(CONF_PASSWORD, default="admin"): PASSWORD,
                vol.Optional("name"): str,
            }
        )
        if user_input:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """The switch rejected the saved login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new login."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input:
            try:
                _, mac = await _probe(
                    self.hass,
                    entry.data[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except KeepLinkAuthError:
                errors["base"] = "invalid_auth"
            except KeepLinkError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=entry.data[CONF_USERNAME]
                    ): str,
                    vol.Required(CONF_PASSWORD): PASSWORD,
                }
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address or login (a blank password keeps the saved one)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input:
            user_input = {
                **user_input,
                CONF_PASSWORD: user_input.get(CONF_PASSWORD)
                or entry.data[CONF_PASSWORD],
            }
            try:
                _, mac = await _probe(
                    self.hass,
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except KeepLinkAuthError:
                errors["base"] = "invalid_auth"
            except KeepLinkError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        d = entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=d[CONF_HOST]): str,
                    vol.Required(CONF_USERNAME, default=d[CONF_USERNAME]): str,
                    vol.Optional(CONF_PASSWORD): PASSWORD,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Port descriptions, ignored ports and polling options."""
        return KeepLinkOptionsFlow()


class KeepLinkOptionsFlow(OptionsFlow):
    """Options; the port list comes from the running integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show or save the options."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        opts = self.config_entry.options
        ports = list(self.config_entry.runtime_data.data.ports)
        if user_input is not None:
            names = {str(n): user_input.get(f"port_{n}", "").strip() for n in ports}
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    CONF_AUTO_SAVE: user_input[CONF_AUTO_SAVE],
                    CONF_HAS_POE: user_input[CONF_HAS_POE],
                    CONF_TRACK_DEVICES: user_input[CONF_TRACK_DEVICES],
                    CONF_IGNORED_PORTS: user_input.get(CONF_IGNORED_PORTS, []),
                    CONF_PORT_NAMES: {k: v for k, v in names.items() if v},
                }
            )
        names = opts.get(CONF_PORT_NAMES, {})
        has_poe = opts.get(
            CONF_HAS_POE, self.config_entry.data.get(CONF_HAS_POE, False)
        )
        schema: dict = {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(int, vol.Range(min=10, max=600)),
            vol.Required(
                CONF_AUTO_SAVE, default=opts.get(CONF_AUTO_SAVE, True)
            ): bool,
            vol.Required(CONF_HAS_POE, default=has_poe): bool,
            vol.Required(
                CONF_TRACK_DEVICES, default=opts.get(CONF_TRACK_DEVICES, True)
            ): bool,
            vol.Optional(
                CONF_IGNORED_PORTS, default=opts.get(CONF_IGNORED_PORTS, [])
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[str(n) for n in ports],
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
        for n in ports:
            key = vol.Optional(
                f"port_{n}", description={"suggested_value": names.get(str(n), "")}
            )
            schema[key] = str
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
