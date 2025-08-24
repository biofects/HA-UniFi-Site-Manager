"""The UniFi Site Manager integration."""
import logging
import asyncio
from datetime import datetime, timedelta
import zoneinfo
import aiohttp
from async_timeout import timeout as async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_SITES,
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
        hass=hass,
        api_key=entry.data[CONF_API_KEY],
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for config entry updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Remove entities and devices for sites that are no longer selected
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    
    # Get current selected sites
    selected_sites = entry.data.get(CONF_SITES, {})
    
    # Get all devices for this config entry
    devices = async_entries_for_config_entry_device(device_registry, entry.entry_id)
    
    # Remove devices that don't belong to selected sites
    for device in devices:
        # Check if device's identifiers contain a site ID we're removing
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                # Device ID format is "{site_id}_{mac}"
                site_id = identifier[1].split("_")[0]
                if site_id not in selected_sites:
                    _LOGGER.debug("Removing device %s for non-selected site %s", device.id, site_id)
                    device_registry.async_remove_device(device.id)
                break
    
    # Remove entities that don't belong to selected sites
    entries = async_entries_for_config_entry(entity_registry, entry.entry_id)
    for entity_entry in entries:
        # Extract site ID from unique ID (format: "site_{site_id}" or "{site_id}_{device_mac}")
        unique_id = entity_entry.unique_id
        site_id = None
        
        if unique_id.startswith("site_"):
            site_id = unique_id[5:]  # Remove "site_" prefix
        else:
            # For device sensors, the site ID is before the underscore
            site_id = unique_id.split("_")[0]
        
        if site_id and site_id not in selected_sites:
            _LOGGER.debug("Removing entity %s for non-selected site %s", entity_entry.entity_id, site_id)
            entity_registry.async_remove(entity_entry.entity_id)

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when it changed."""
    await hass.config_entries.async_reload(entry.entry_id)

def async_entries_for_config_entry(
    entity_registry, config_entry_id: str
) -> list:
    """Return entries for a config entry."""
    return [
        entry
        for entry in entity_registry.entities.values()
        if config_entry_id == entry.config_entry_id
    ]

def async_entries_for_config_entry_device(
    device_registry, config_entry_id: str
) -> list:
    """Return device entries for a config entry."""
    return [
        device
        for device in device_registry.devices.values()
        if config_entry_id in device.config_entries
    ]

class UniFiSiteManagerDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the UniFi Network Controller."""

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        """Initialize the coordinator."""
        self._api_key = api_key
        self._session = async_get_clientsession(hass)
        self.headers = {
            "X-API-KEY": api_key,
            "Accept": "application/json"
        }

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _async_update_data(self) -> dict:
        """Fetch data from UniFi Site Manager API."""
        try:
            async with aiohttp.ClientSession() as session:
                # Get sites data
                sites_response = await self._fetch_data(session, API_SITES_ENDPOINT)
                if not sites_response:
                    return {}

                # Get hosts data
                hosts_response = await self._fetch_data(session, API_HOSTS_ENDPOINT)
                if not hosts_response:
                    hosts_response = {"data": []}

                # Get devices data
                devices_response = await self._fetch_data(session, API_DEVICES_ENDPOINT)
                if not devices_response:
                    devices_response = {"data": []}

                # Fetch SD-WAN configs
                sdwan_configs_response = await self._fetch_data(session, "/ea/sd-wan-configs")
                if not sdwan_configs_response:
                    sdwan_configs = []
                else:
                    sdwan_configs = sdwan_configs_response.get("data", [])

                # Fetch ISP metrics for each site
                isp_metrics = {}
                for site in sites_response.get("data", []):
                    site_id = site.get("siteId")
                    if site_id:
                        try:
                            metrics = {
                                "latency": await self._fetch_isp_metrics(session, "latency", site_id),
                                "packet_loss": await self._fetch_isp_metrics(session, "packet-loss", site_id),
                                "bandwidth": await self._fetch_isp_metrics(session, "bandwidth", site_id),
                                "wan": await self._fetch_isp_metrics(session, "wan", site_id)
                            }
                            isp_metrics[site_id] = metrics
                        except Exception as err:
                            _LOGGER.debug("Error fetching ISP metrics for site %s: %s", site_id, err)
                            isp_metrics[site_id] = {}

                return {
                    "data": hosts_response.get("data", []),
                    "sites": sites_response.get("data", []),
                    "devices": devices_response.get("data", []),
                    "isp_metrics": isp_metrics,
                    "sdwan_configs": sdwan_configs,
                }

        except Exception as err:
            _LOGGER.exception("Error fetching data: %s", err)
            raise UpdateFailed from err

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
                    _LOGGER.debug("Authentication failed for %s: Invalid API key", url)
                    raise ConfigEntryAuthFailed("Invalid API key")
                resp.raise_for_status()
                data = await resp.json()
                _LOGGER.debug("Response from %s: %s", url, data)
                return data
        except aiohttp.ClientError as err:
            _LOGGER.debug("Error fetching data from %s: %s", endpoint, err)
            raise UpdateFailed(f"Error fetching data from {endpoint}: {err}")

    async def _fetch_isp_metrics(
        self,
        session: aiohttp.ClientSession,
        metric_type: str,
        site_id: str,
    ) -> dict:
        """Fetch ISP metrics data."""
        try:
            # Calculate timestamps explicitly
            end_time = datetime.now(tz=zoneinfo.ZoneInfo("UTC"))
            begin_time = end_time - timedelta(hours=24)

            params = {
                "beginTimestamp": begin_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endTimestamp": end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            }

            url = f"{API_BASE_URL}/ea/isp-metrics/5m"  # Always fetch 5m metrics
            _LOGGER.debug("Attempting ISP metrics fetch:")
            _LOGGER.debug("URL: %s", url)
            _LOGGER.debug("Metric Type: %s", metric_type)
            _LOGGER.debug("Site ID: %s", site_id)

            async with session.get(
                url,
                params=params,
                headers=self.headers,
            ) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        
                        # Prepare a dictionary to store metrics for this site
                        site_metrics = {}

                        # Process each entry in the data
                        for entry in data.get('data', []):
                            # Explicitly check if the entry is for the correct site
                            if entry.get('siteId') == site_id:
                                # Process each period
                                for period in entry.get('periods', []):
                                    metric_time = period.get('metricTime')
                                    period_data = period.get('data', {})
                                    
                                    # Extract WAN metrics
                                    wan_metrics = period_data.get('wan', {})
                                    
                                    # Create a metrics dictionary for this timestamp
                                    timestamp_metrics = {
                                        'metric_type': entry.get('metricType'),
                                        'host_id': entry.get('hostId'),
                                        'avg_latency': wan_metrics.get('avgLatency'),
                                        'max_latency': wan_metrics.get('maxLatency'),
                                        'download_kbps': wan_metrics.get('download_kbps'),
                                        'upload_kbps': wan_metrics.get('upload_kbps'),
                                        'packet_loss': wan_metrics.get('packetLoss'),
                                        'isp_name': wan_metrics.get('ispName'),
                                        'isp_asn': wan_metrics.get('ispAsn'),
                                        'uptime': wan_metrics.get('uptime'),
                                        'downtime': wan_metrics.get('downtime')
                                    }
                                    
                                    # Store metrics by timestamp
                                    if metric_time:
                                        site_metrics[metric_time] = timestamp_metrics

                        # If a specific metric type is requested, filter the results
                        if metric_type != '5m':
                            filtered_metrics = {}
                            for timestamp, metrics in site_metrics.items():
                                if metric_type == 'latency':
                                    filtered_metrics[timestamp] = {
                                        'avg_latency': metrics.get('avg_latency'),
                                        'max_latency': metrics.get('max_latency')
                                    }
                                elif metric_type == 'packet-loss':
                                    filtered_metrics[timestamp] = {
                                        'packet_loss': metrics.get('packet_loss')
                                    }
                                elif metric_type == 'bandwidth':
                                    filtered_metrics[timestamp] = {
                                        'download_kbps': metrics.get('download_kbps'),
                                        'upload_kbps': metrics.get('upload_kbps')
                                    }
                                elif metric_type == 'wan':
                                    filtered_metrics[timestamp] = metrics
                            
                            site_metrics = filtered_metrics

                        _LOGGER.debug("Processed ISP metrics for %s: %s", metric_type, site_metrics)
                        return site_metrics

                    except ValueError as json_err:
                        _LOGGER.debug("Failed to parse JSON response for %s: %s", metric_type, json_err)
                        return {}

                # Log error if request was not successful
                response_text = await resp.text()
                _LOGGER.debug(
                    "Failed to fetch ISP metrics: %s %s",
                    resp.status,
                    response_text
                )
                return {}

        except Exception as err:
            _LOGGER.debug("Error fetching ISP metrics: %s", err)
            return {}

