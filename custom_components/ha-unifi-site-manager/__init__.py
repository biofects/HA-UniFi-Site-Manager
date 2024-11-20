"""The UniFi Site Manager integration."""
import logging
import asyncio
from datetime import timedelta
import aiohttp
from async_timeout import timeout as async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_API_KEY,
    API_BASE_URL,
    API_SITES_ENDPOINT,
    API_DEVICES_ENDPOINT,
    API_HOSTS_ENDPOINT,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up UniFi Site Manager from a config entry."""
    coordinator = UniFiSiteManagerDataUpdateCoordinator(
        hass,
        api_key=entry.data[CONF_API_KEY],
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

class UniFiSiteManagerDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the UniFi Network Controller."""

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self._session = async_get_clientsession(hass)
        self._api_key = api_key
        self.headers = {
            "X-API-KEY": api_key,
            "Accept": "application/json"
        }

    async def _async_update_data(self) -> dict:
        """Fetch data from UniFi Site Manager API."""
        try:
            async with aiohttp.ClientSession() as session:
                # Get sites data
                sites_response = await self._fetch_data(session, API_SITES_ENDPOINT)
                if not sites_response:
                    return {}

                # Get devices data
                devices_response = await self._fetch_data(session, API_DEVICES_ENDPOINT)
                if not devices_response:
                    devices_response = {"data": []}

                # Extract devices from nested structure
                all_devices = []
                for host_data in devices_response.get("data", []):
                    if isinstance(host_data, dict) and "devices" in host_data:
                        host_devices = host_data.get("devices", [])
                        host_id = host_data.get("hostId")
                        if isinstance(host_devices, list):
                            for device in host_devices:
                                if isinstance(device, dict):
                                    # Add host context to device
                                    device["hostId"] = host_id
                                    all_devices.append(device)

                # Get ISP metrics data for each site
                isp_metrics = {}
                for site in sites_response.get("data", []):
                    site_id = site.get("siteId")
                    if site_id:
                        # Get latency metrics
                        latency = await self._fetch_isp_metrics(session, "latency", site_id)
                        packet_loss = await self._fetch_isp_metrics(session, "packet-loss", site_id)
                        bandwidth = await self._fetch_isp_metrics(session, "bandwidth", site_id)
                        wan = await self._fetch_isp_metrics(session, "wan", site_id)
                        
                        isp_metrics[site_id] = {
                            "latency": latency.get("data", {}),
                            "packet_loss": packet_loss.get("data", {}),
                            "bandwidth": bandwidth.get("data", {}),
                            "wan": wan.get("data", {})
                        }

                # Get hosts data
                hosts_response = await self._fetch_data(session, API_HOSTS_ENDPOINT)
                if not hosts_response:
                    hosts_response = {"data": []}

                return {
                    "data": sites_response.get("data", []),
                    "devices": all_devices,
                    "isp_metrics": isp_metrics,
                    "clients": {"data": hosts_response.get("data", [])}
                }

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def _fetch_data(self, session: aiohttp.ClientSession, endpoint: str) -> dict:
        """Fetch data from a specific API endpoint."""
        try:
            url = f"{API_BASE_URL}{endpoint}"
            _LOGGER.debug("Fetching data from %s", url)
            
            async with session.get(
                url,
                headers=self.headers,
            ) as resp:
                if resp.status == 401:
                    _LOGGER.error("Authentication failed for %s: Invalid API key", url)
                    raise ConfigEntryAuthFailed("Invalid API key")
                resp.raise_for_status()
                data = await resp.json()
                _LOGGER.debug("Response from %s: %s", url, data)
                return data
        except aiohttp.ClientError as err:
            _LOGGER.error("Error fetching data from %s: %s", endpoint, err)
            raise UpdateFailed(f"Error fetching data from {endpoint}: {err}")

    async def _fetch_isp_metrics(
        self,
        session: aiohttp.ClientSession,
        metric_type: str,
        site_id: str,
    ) -> dict:
        """Fetch ISP metrics data."""
        try:
            params = {
                "duration": "24h",  # Get last 24 hours of 5-minute metrics
                "siteId": site_id
            }
            
            url = f"{API_BASE_URL}/ea/isp-metrics/{metric_type}"
            async with session.get(
                url,
                params=params,
                headers=self.headers,
                ssl=False,
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                _LOGGER.debug("ISP metrics response for %s: %s %s", metric_type, resp.status, await resp.text())
                return {"data": {}}
                
        except Exception as err:
            _LOGGER.error("Error fetching ISP metrics: %s", err)
            return {"data": {}}
