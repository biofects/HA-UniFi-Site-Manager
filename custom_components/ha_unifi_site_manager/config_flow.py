"""Config flow for UniFi Site Manager integration."""
import logging
from typing import Any
import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from async_timeout import timeout

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_SITES,
    API_BASE_URL,
    API_SITES_ENDPOINT,
    API_DEVICES_ENDPOINT,
    API_HOSTS_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)

class UniFiSiteManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Site Manager."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api_key: str | None = None
        self._sites: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                self._api_key = user_input[CONF_API_KEY]
                # Fetch sites and devices
                await self._fetch_sites_and_devices(self._api_key)
                
                if self._sites:
                    return await self.async_step_sites()
                else:
                    _LOGGER.warning("No valid sites found in response")
                    errors["base"] = "no_sites"
                    
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
            }),
            errors=errors,
        )

    async def async_step_sites(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the sites step."""
        if user_input is not None:
            selected_sites = user_input[CONF_SITES]
            _LOGGER.debug("Selected sites: %s", selected_sites)
            
            # Filter to only include selected sites
            selected_sites_dict = {
                site_id: self._sites[site_id]
                for site_id in selected_sites
                if site_id in self._sites
            }
            
            # Create the config entry with only selected sites
            return self.async_create_entry(
                title="UniFi Site Manager",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_SITES: selected_sites_dict,
                },
            )

        sites_schema = {
            vol.Required(CONF_SITES): cv.multi_select(self._sites),
        }

        return self.async_show_form(
            step_id="sites",
            data_schema=vol.Schema(sites_schema),
        )

    async def _fetch_sites_and_devices(self, api_key: str) -> None:
        """Fetch sites and devices from the UniFi API."""
        try:
            # First get all sites
            sites_response = await self._fetch_sites(api_key)
            _LOGGER.debug("Sites API Response: %s", sites_response)

            if not sites_response or "data" not in sites_response:
                _LOGGER.error("No sites data found in response")
                return

            # Get hosts information for hostname mapping
            hosts_response = await self._fetch_hosts(api_key)
            _LOGGER.debug("Hosts API Response: %s", hosts_response)

            # Create mapping of hostId to hostname
            host_info = {}
            if hosts_response and "data" in hosts_response:
                for host in hosts_response["data"]:
                    host_id = host.get("id")
                    if host_id:
                        hostname = host.get("reportedState", {}).get("hostname", "").lower()
                        if hostname:
                            host_info[host_id] = hostname

            # Process each site
            sites_data = sites_response["data"]
            for site in sites_data:
                site_id = site.get("siteId")
                host_id = site.get("hostId")
                
                if site_id and host_id:
                    # Get hostname for this site
                    hostname = host_info.get(host_id, "unknown")
                    
                    # Create site name
                    site_name = f"{hostname}-site"
                    self._sites[site_id] = site_name
                    _LOGGER.debug("Added site %s: %s", site_id, site_name)

            _LOGGER.debug("Final sites dict: %s", self._sites)

        except Exception as err:
            _LOGGER.exception("Failed to fetch data: %s", err)
            raise

    async def _fetch_sites(self, api_key: str) -> dict:
        """Fetch sites from the API."""
        try:
            url = f"{API_BASE_URL}{API_SITES_ENDPOINT}"
            headers = {
                "Accept": "application/json",
                "X-API-KEY": api_key,
            }
            
            _LOGGER.debug("Making sites API request to %s", url)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 401:
                        raise InvalidAuth
                    response.raise_for_status()
                    return await response.json()

        except aiohttp.ClientResponseError as err:
            _LOGGER.error("Sites API request failed with status %s: %s", err.status, err.message)
            raise CannotConnect from err
        except aiohttp.ClientError as err:
            _LOGGER.error("Sites connection error: %s", str(err))
            raise CannotConnect from err
        except Exception as err:
            _LOGGER.exception("Unexpected error during sites API request: %s", err)
            raise InvalidAuth from err

    async def _fetch_hosts(self, api_key: str) -> dict:
        """Fetch hosts from the API."""
        try:
            url = f"{API_BASE_URL}{API_HOSTS_ENDPOINT}"
            headers = {
                "Accept": "application/json",
                "X-API-KEY": api_key,
            }
            
            _LOGGER.debug("Making hosts API request to %s", url)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 401:
                        raise InvalidAuth
                    response.raise_for_status()
                    return await response.json()

        except aiohttp.ClientResponseError as err:
            _LOGGER.error("Hosts API request failed with status %s: %s", err.status, err.message)
            raise CannotConnect from err
        except aiohttp.ClientError as err:
            _LOGGER.error("Hosts connection error: %s", str(err))
            raise CannotConnect from err
        except Exception as err:
            _LOGGER.exception("Unexpected error during hosts API request: %s", err)
            raise InvalidAuth from err

    async def _fetch_devices(self, api_key: str) -> dict:
        """Fetch devices from the API."""
        try:
            url = f"{API_BASE_URL}{API_DEVICES_ENDPOINT}"
            headers = {
                "Accept": "application/json",
                "X-API-KEY": api_key,
            }
            
            _LOGGER.debug("Making devices API request to %s", url)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 401:
                        raise InvalidAuth
                    response.raise_for_status()
                    return await response.json()

        except aiohttp.ClientResponseError as err:
            _LOGGER.error("Devices API request failed with status %s: %s", err.status, err.message)
            raise CannotConnect from err
        except aiohttp.ClientError as err:
            _LOGGER.error("Devices connection error: %s", str(err))
            raise CannotConnect from err
        except Exception as err:
            _LOGGER.exception("Unexpected error during devices API request: %s", err)
            raise InvalidAuth from err

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for UniFi Site Manager."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self._api_key = config_entry.data[CONF_API_KEY]
        self._sites = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        errors = {}

        if user_input is not None:
            # Get the current sites configuration
            current_sites = dict(self.config_entry.data.get(CONF_SITES, {}))
            selected_sites = user_input.get(CONF_SITES, [])

            # Update the sites configuration
            new_sites = {}
            for site_id in selected_sites:
                if site_id in self._sites:
                    new_sites[site_id] = self._sites[site_id]

            # Update the config entry
            new_data = dict(self.config_entry.data)
            new_data[CONF_SITES] = new_sites

            # If sites have changed, update the config entry
            if new_sites != current_sites:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=new_data,
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data=new_data)

        try:
            # Fetch current sites
            await self._fetch_sites_and_devices(self._api_key)
            
            # Get currently selected sites
            current_sites = self.config_entry.data.get(CONF_SITES, {})
            _LOGGER.debug("Current sites in config: %s", current_sites)
            _LOGGER.debug("Available sites: %s", self._sites)

            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({
                    vol.Required(
                        CONF_SITES,
                        default=list(current_sites.keys())
                    ): cv.multi_select(self._sites)
                }),
                errors=errors,
            )

        except Exception as err:
            _LOGGER.exception("Error in options flow: %s", err)
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({}),
                errors=errors,
            )

    async def _fetch_sites_and_devices(self, api_key: str) -> None:
        """Fetch sites and devices from the UniFi API."""
        try:
            # First get all sites
            sites_response = await self._fetch_sites(api_key)
            _LOGGER.debug("Sites API Response: %s", sites_response)

            if not sites_response or "data" not in sites_response:
                _LOGGER.error("No sites data found in response")
                return

            # Get hosts information for hostname mapping
            hosts_response = await self._fetch_hosts(api_key)
            _LOGGER.debug("Hosts API Response: %s", hosts_response)

            # Create mapping of hostId to hostname
            host_info = {}
            if hosts_response and "data" in hosts_response:
                for host in hosts_response["data"]:
                    host_id = host.get("id")
                    if host_id:
                        hostname = host.get("reportedState", {}).get("hostname", "").lower()
                        hardware = host.get("reportedState", {}).get("hardware", {})
                        shortname = hardware.get("shortname", "").lower()
                        device_name = hostname if hostname else shortname
                        if device_name:
                            host_info[host_id] = device_name

            # Process each site
            sites_data = sites_response["data"]
            for site in sites_data:
                site_id = site.get("siteId")
                host_id = site.get("hostId")
                
                if site_id and host_id and host_id in host_info:
                    # Get hostname for this site
                    hostname = host_info[host_id]
                    # Create site name
                    site_name = f"{hostname}-site"
                    self._sites[site_id] = site_name
                    _LOGGER.debug("Added site %s: %s", site_id, site_name)

            _LOGGER.debug("Final sites dict: %s", self._sites)

        except Exception as err:
            _LOGGER.exception("Failed to fetch data: %s", err)
            raise

    async def _fetch_sites(self, api_key: str) -> dict:
        """Fetch sites from the API."""
        try:
            url = f"{API_BASE_URL}{API_SITES_ENDPOINT}"
            headers = {
                "Accept": "application/json",
                "X-API-KEY": api_key,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 401:
                        raise InvalidAuth
                    response.raise_for_status()
                    return await response.json()

        except aiohttp.ClientResponseError as err:
            raise CannotConnect from err
        except aiohttp.ClientError as err:
            raise CannotConnect from err

    async def _fetch_hosts(self, api_key: str) -> dict:
        """Fetch hosts from the API."""
        try:
            url = f"{API_BASE_URL}{API_HOSTS_ENDPOINT}"
            headers = {
                "Accept": "application/json",
                "X-API-KEY": api_key,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 401:
                        raise InvalidAuth
                    response.raise_for_status()
                    return await response.json()

        except aiohttp.ClientResponseError as err:
            raise CannotConnect from err
        except aiohttp.ClientError as err:
            raise CannotConnect from err


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
