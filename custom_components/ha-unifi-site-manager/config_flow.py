"""Config flow for UniFi Site Manager integration."""
import logging
from typing import Any
import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from async_timeout import timeout

from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    CONF_API_KEY,
    API_BASE_URL,
    API_SITES_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)

class UniFiSiteManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Site Manager."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            valid = await self._test_credentials(user_input[CONF_API_KEY])
            if valid:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="UniFi Site Manager",
                    data={
                        CONF_API_KEY: user_input[CONF_API_KEY],
                    },
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
            }),
            errors=errors,
        )

    async def _test_credentials(self, api_key: str) -> bool:
        """Test if we can authenticate with the UniFi Network Controller."""
        try:
            url = f"{API_BASE_URL}{API_SITES_ENDPOINT}"
            headers = {
                "Accept": "application/json",
                "X-API-KEY": api_key,
            }

            async with timeout(10):
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 401:
                            return False
                        response.raise_for_status()
                        return True

        except (aiohttp.ClientError, timeout):
            return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for UniFi Site Manager."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
        )
