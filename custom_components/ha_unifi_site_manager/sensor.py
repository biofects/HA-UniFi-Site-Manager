"""Support for UniFi Site Manager sensors."""
from __future__ import annotations
from datetime import datetime
import zoneinfo
from typing import Any, cast
import logging

_LOGGER = logging.getLogger(__name__)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt

from .const import DOMAIN, MANUFACTURER, STATE_ONLINE, STATE_OFFLINE, CONF_SITES

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Site Manager sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Add site sensors
    entities = []
    site_host_map = {}
    
    _LOGGER.debug("Building host map from data: %s", coordinator.data)
    
    # First, build a mapping of host IDs to hostnames
    for host in coordinator.data.get("data", []):  # This is hosts data
        host_id = host.get("id")
        hostname = host.get("reportedState", {}).get("hostname", "").lower()
        hardware = host.get("reportedState", {}).get("hardware", {})
        shortname = hardware.get("shortname", "").lower()
        
        # Use hostname if available, otherwise use shortname
        device_name = hostname if hostname else shortname
        
        if host_id and device_name:
            site_host_map[host_id] = {
                "hostname": device_name,
                "hardware": hardware
            }
    
    _LOGGER.debug("Site host map: %s", site_host_map)
    
    # Get the selected sites from config entry
    selected_sites = entry.data.get(CONF_SITES, {})
    _LOGGER.debug("Selected sites from config: %s", selected_sites)
    
    # Process sites from sites data
    for site in coordinator.data.get("sites", []):  # Changed from "data" to "sites"
        site_id = site.get("siteId")
        host_id = site.get("hostId")
        is_owner = site.get("isOwner", False)
        
        _LOGGER.debug("Processing site: %s, host_id: %s, is_owner: %s", site_id, host_id, is_owner)
        
        # Only process selected sites
        if site_id not in selected_sites:
            _LOGGER.debug("Skipping non-selected site: %s", site_id)
            continue
            
        if site_id and host_id and host_id in site_host_map:
            # Get the hostname for this site
            hostname = site_host_map[host_id]["hostname"]
            site_name = f"{hostname}-site"
            site_prefix = hostname  # Use hostname as prefix for device names
            
            _LOGGER.debug("Adding site sensor for %s with name %s", site_id, site_name)
            
            # Add site sensor
            entities.append(
                UniFiSiteSensor(
                    coordinator,
                    site_id,
                    site_name,
                    host_id,
                )
            )
            
            # Get devices for this host from devices data
            host_devices = []
            for host_data in coordinator.data.get("devices", []):
                if host_data.get("hostId") == host_id and "devices" in host_data:
                    host_devices.extend(host_data.get("devices", []))
            
            _LOGGER.debug("Found devices for site %s: %s", site_id, host_devices)
            
            # Add device sensors for this site
            for device in host_devices:
                device_id = device.get("id")
                device_name = device.get("name", "").lower()
                device_mac = device.get("mac")
                
                _LOGGER.debug("Processing device: id=%s, name=%s, mac=%s", device_id, device_name, device_mac)
                
                if device_id and device_mac and device_name:
                    # Create device name with site prefix
                    full_device_name = f"{site_prefix}-{device_name}"
                    
                    _LOGGER.debug("Adding device sensor: %s", full_device_name)
                    
                    entities.append(
                        UniFiDeviceSensor(
                            coordinator,
                            site_id,
                            site_name,
                            device_id,
                            full_device_name,
                            device_mac,
                        )
                    )

            # Add ISP metrics sensor for this site
            _LOGGER.debug("Adding ISP metrics sensor for site %s", site_id)
            entities.append(
                UniFiISPMetricsDevice(
                    coordinator,
                    site_id,
                    site_name,
                    host_id,
                )
            )
    
    _LOGGER.debug("Total entities created: %s", len(entities))
    async_add_entities(entities)

class UniFiSiteSensor(CoordinatorEntity, SensorEntity):
    """Representation of a UniFi site sensor."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        site_id: str,
        site_name: str,
        host_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._site_id = site_id
        self._site_name = site_name
        self._host_id = host_id

        # Set unique ID
        self._attr_unique_id = f"site_{site_id}"
        
        # Set name
        self._attr_name = site_name
        
        # Set device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"site_{site_id}")},
            name=site_name,
            manufacturer="Ubiquiti",
            model="UniFi Site",
        )

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        site = self._get_site_data()
        if site:
            stats = site.get("statistics", {})
            counts = stats.get("counts", {})
            offline_devices = counts.get("offlineDevice", 0)
            return STATE_OFFLINE if offline_devices > 0 else STATE_ONLINE
        return STATE_OFFLINE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        site = self._get_site_data()
        if not site:
            return {}

        stats = site.get("statistics", {})
        counts = stats.get("counts", {})
        percentages = stats.get("percentages", {})
        isp_info = stats.get("ispInfo", {})

        return {
            "site_id": self._site_id,
            "host_id": self._host_id,
            "description": site.get("meta", {}).get("desc"),
            "gateway_mac": site.get("meta", {}).get("gatewayMac"),
            "timezone": site.get("meta", {}).get("timezone"),
            "total_devices": counts.get("totalDevice", 0),
            "offline_devices": counts.get("offlineDevice", 0),
            "wifi_clients": counts.get("wifiClient", 0),
            "wired_clients": counts.get("wiredClient", 0),
            "guest_clients": counts.get("guestClient", 0),
            "wan_uptime": percentages.get("wanUptime", 0),
            "isp_name": isp_info.get("name"),
            "isp_organization": isp_info.get("organization"),
        }

    def _get_site_data(self) -> dict[str, Any] | None:
        """Get the current site data."""
        if not self.coordinator.data:
            return None

        # Find the site in the coordinator data
        for site in self.coordinator.data.get("sites", []):  # Changed from "data" to "sites"
            if site.get("siteId") == self._site_id:
                return site
        return None

class UniFiDeviceSensor(CoordinatorEntity, SensorEntity):
    """Representation of a UniFi device sensor."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        site_id: str,
        site_name: str,
        device_id: str,
        device_name: str,
        device_mac: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._site_id = site_id
        self._site_name = site_name
        self._device_id = device_id
        self._device_name = device_name
        self._device_mac = device_mac
        self._attr_unique_id = f"{site_id}_{device_mac}"
        self._attr_name = device_name
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        device = self._get_device()
        if not device:
            return None

        # Get device model and manufacturer info
        model = device.get("model", "Unknown Model")
        shortname = device.get("shortname", model)
        product_line = device.get("productLine", "network").title()

        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._site_id}_{self._device_mac}")},
            name=self._device_name,
            manufacturer=MANUFACTURER,
            model=model,
            sw_version=device.get("version"),
            suggested_area=product_line,
            via_device=(DOMAIN, f"{self._site_id}"),  # Link to site as parent device
        )

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        device = self._get_device()
        if not device:
            return STATE_OFFLINE
        return STATE_ONLINE if device.get("status") == "online" else STATE_OFFLINE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        device = self._get_device()
        if not device:
            return {}

        attrs = {
            "id": self._device_id,
            "mac": self._device_mac,
            "model": device.get("model", "Unknown"),
            "type": device.get("shortname", "Unknown"),
            "product_line": device.get("productLine", "network").title(),
            "ip": device.get("ip", "Unknown"),
            "firmware_version": device.get("version", "Unknown"),
            "status": device.get("status", "Unknown"),
            "site_name": self._site_name,
            "site_id": self._site_id,
            "last_seen": device.get("lastSeen", None),
            "adoption_time": device.get("adoptionTime", None),
            "is_managed": device.get("isManaged", False),
            "firmware_status": device.get("firmwareStatus", "Unknown"),
        }

        # Add connection info
        if device.get("status") == "online":
            attrs["uptime"] = device.get("uptime", 0)
            attrs["last_seen"] = device.get("lastSeen", None)

        return attrs

    def _get_device(self) -> dict:
        """Get the device data from coordinator."""
        if not self.coordinator.data:
            return None

        # Look through all devices in all hosts
        for host_data in self.coordinator.data.get("devices", []):
            if "devices" in host_data:
                for device in host_data["devices"]:
                    if (
                        device.get("mac") == self._device_mac 
                        or device.get("id") == self._device_id
                    ):
                        return device
        return None

class UniFiISPMetricsDevice(CoordinatorEntity, SensorEntity):
    """Representation of a UniFi ISP Metrics device."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        site_id: str,
        site_name: str,
        host_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._site_id = site_id
        self._host_id = host_id
        self._attr_name = f"{site_name} ISP Metrics"
        self._attr_unique_id = f"{site_id}_isp_metrics"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._site_id)},
            manufacturer=MANUFACTURER,
            name=self._attr_name,
            via_device=(DOMAIN, self._host_id),
        )

    @property
    def native_value(self) -> datetime:
        """Return the state of the sensor."""
        return dt.now()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        site_metrics = self.coordinator.data.get("isp_metrics", {}).get(self._site_id, {})
        metrics = {}
        
        if site_metrics:
            # Process latency data
            latency = site_metrics.get("latency", {})
            if latency:
                metrics.update({
                    "latency_avg": latency.get("latencyAvg"),
                    "latency_min": latency.get("latencyMin"),
                    "latency_max": latency.get("latencyMax"),
                })
            
            # Process packet loss data
            packet_loss = site_metrics.get("packet_loss", {})
            if packet_loss:
                metrics.update({
                    "packet_loss_percentage": packet_loss.get("packetLossPercentage"),
                    "packet_loss_count": packet_loss.get("packetLossCount"),
                })
            
            # Process bandwidth data
            bandwidth = site_metrics.get("bandwidth", {})
            if bandwidth:
                metrics.update({
                    "download_mbps": bandwidth.get("downloadMbps"),
                    "upload_mbps": bandwidth.get("uploadMbps"),
                })

            # Process WAN data
            wan = site_metrics.get("wan", {})
            if wan:
                metrics.update({
                    "wan_latency_avg": wan.get("avgLatency"),
                    "wan_latency_max": wan.get("maxLatency"),
                    "wan_download_kbps": wan.get("download_kbps"),
                    "wan_upload_kbps": wan.get("upload_kbps"),
                    "wan_packet_loss": wan.get("packetLoss"),
                    "wan_uptime": wan.get("uptime"),
                    "wan_downtime": wan.get("downtime"),
                    "isp_name": wan.get("ispName"),
                    "isp_asn": wan.get("ispAsn"),
                })

        return metrics

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and bool(self.coordinator.data)
