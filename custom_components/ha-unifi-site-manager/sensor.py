"""Support for UniFi Site Manager sensors."""
from __future__ import annotations
from datetime import datetime
import zoneinfo
from typing import Any, cast

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

from .const import DOMAIN, MANUFACTURER, STATE_ONLINE, STATE_OFFLINE

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
    
    # First, build a mapping of host IDs to hostnames
    for host in coordinator.data.get("data", []):
        host_id = host.get("id")
        hostname = host.get("reportedState", {}).get("hostname", "")
        location = host.get("reportedState", {}).get("location", {}).get("text", "")
        if hostname and host_id:
            site_host_map[host_id] = {
                "hostname": hostname,
                "location": location.split(",")[0] if location else ""
            }
    
    for site in coordinator.data.get("data", []):
        site_id = site.get("siteId")
        host_id = site.get("hostId")
        
        if site_id and host_id:
            # Get site name from meta, default to 'default' if not available
            site_raw_name = site.get("meta", {}).get("name", "default").lower()
            
            # Map 'default' to appropriate name based on permissions
            if site_raw_name == "default":
                # Check if this is the owned/admin site
                is_admin = site.get("permission") == "admin"
                site_name = "tfam-home" if is_admin else "default"
            else:
                site_name = site_raw_name
            
            site_name = f"{site_name}-site"
            
            # Add site sensor
            entities.append(
                UniFiSiteSensor(
                    coordinator,
                    site_id,
                    site_name,
                    host_id,
                )
            )
            
            # Create device sensors for this site
            site_devices = [
                device for device in coordinator.data.get("devices", [])
                if device.get("hostId") == host_id
            ]
            
            # Add device sensors for this site
            for device in site_devices:
                device_id = device.get("id")
                device_name = device.get("name", "Unknown Device")
                device_mac = device.get("mac")
                
                if device_id and device_mac:
                    entities.append(
                        UniFiDeviceSensor(
                            coordinator,
                            site_id,
                            site_name,
                            device_id,
                            device_name,
                            device_mac,
                        )
                    )

            # Add ISP metrics sensor for this site
            entities.append(
                UniFiISPMetricsDevice(
                    coordinator,
                    site_id,
                    site_name,
                    host_id,
                )
            )

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
        for site in self.coordinator.data.get("data", []):
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

        # Set unique ID
        self._attr_unique_id = f"{site_id}_{device_mac}"
        
        # Set name
        self._attr_name = f"{site_name} - {device_name}"
        
        # Set device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_mac)},
            name=self._device_name,
            manufacturer="Ubiquiti",
            model=self._get_device_model(),
            sw_version=self._get_device_version(),
            via_device=(DOMAIN, f"site_{site_id}"),  # Link to site device
        )

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        device = self._get_device_data()
        if device:
            return STATE_ONLINE if device.get("state", {}).get("up", False) else STATE_OFFLINE
        return STATE_OFFLINE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        device = self._get_device_data()
        if not device:
            return {}

        return {
            "site_id": self._site_id,
            "site_name": self._site_name,
            "device_id": self._device_id,
            "mac_address": self._device_mac,
            "model": self._get_device_model(),
            "version": self._get_device_version(),
            "ip_address": device.get("config", {}).get("mgmt", {}).get("ip"),
            "last_seen": device.get("state", {}).get("lastSeen"),
            "uptime": device.get("state", {}).get("uptime"),
        }

    def _get_device_data(self) -> dict[str, Any] | None:
        """Get the current device data."""
        if not self.coordinator.data:
            return None

        # Find the device in the coordinator data
        for device in self.coordinator.data.get("devices", []):
            if device.get("mac") == self._device_mac:
                return device
        return None

    def _get_device_model(self) -> str:
        """Get the device model."""
        device = self._get_device_data()
        if device:
            return device.get("model", "Unknown Model")
        return "Unknown Model"

    def _get_device_version(self) -> str:
        """Get the device firmware version."""
        device = self._get_device_data()
        if device:
            return device.get("version", "Unknown Version")
        return "Unknown Version"

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
