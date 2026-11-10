"""Config flow for Heatmiser NetMonitor integration."""
from __future__ import annotations

import logging
from typing import Any

import requests
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .heatmiser_hub import HeatmiserHub

_LOGGER = logging.getLogger(__name__)


def options_schema(defaults: dict | None = None) -> vol.Schema:
    """Return the schema used by both the setup and options forms."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required("host", default=defaults.get("host", "")): str,
            vol.Required("username", default=defaults.get("username", "admin")): str,
            vol.Required("password", default=defaults.get("password", "")): str,
        }
    )


def options_data(user_input: dict) -> dict:
    """Return the dict stored in the config entry."""
    return {
        "host": user_input["host"].strip(),
        "username": user_input["username"],
        "password": user_input["password"],
    }


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate the user input allows us to connect."""
    hub = HeatmiserHub(data["host"].strip(), data["username"], data["password"], hass)
    try:
        result = await hub.authenticate()
    except requests.RequestException as err:
        raise CannotConnect from err
    if not result:
        raise InvalidAuth


async def _validate(hass: HomeAssistant, user_input: dict[str, Any]) -> dict[str, str]:
    """Validate and return an errors dict (empty on success)."""
    try:
        await validate_input(hass, user_input)
    except CannotConnect:
        return {"base": "cannot_connect"}
    except InvalidAuth:
        return {"base": "invalid_auth"}
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Unexpected exception")
        return {"base": "unknown"}
    return {}


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options for the component."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title="", data=options_data(user_input))
        defaults = user_input or {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=options_schema(defaults), errors=errors
        )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Heatmiser NetMonitor."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        """Get the options flow."""
        return OptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input["host"].strip())
            self._abort_if_unique_id_configured()
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(
                    title=f"Heatmiser NetMonitor ({user_input['host'].strip()})",
                    data=options_data(user_input),
                )
        return self.async_show_form(
            step_id="user", data_schema=options_schema(user_input), errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
