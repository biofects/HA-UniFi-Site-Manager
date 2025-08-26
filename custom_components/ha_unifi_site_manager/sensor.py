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

    # Build host map (existing logic)
    for host in coordinator.data.get("data", []):
        host_id = host.get("id")
        hostname = host.get("reportedState", {}).get("hostname", "").lower()
        hardware = host.get("reportedState", {}).get("hardware", {})
        shortname = hardware.get("shortname", "").lower()
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

    # Process sites from sites data (existing logic)
    for site in coordinator.data.get("sites", []):
        site_id = site.get("siteId")
        host_id = site.get("hostId")
        is_owner = site.get("isOwner", False)
        _LOGGER.debug("Processing site: %s, host_id: %s, is_owner: %s", site_id, host_id, is_owner)
        if site_id not in selected_sites:
            _LOGGER.debug("Skipping non-selected site: %s", site_id)
            continue
        if site_id and host_id and host_id in site_host_map:
            hostname = site_host_map[host_id]["hostname"]
            site_name = f"{hostname}-site"
            site_prefix = hostname
            _LOGGER.debug("Adding site sensor for %s with name %s", site_id, site_name)
            entities.append(UniFiSiteSensor(coordinator, site_id, site_name, host_id))
            host_devices = []
            for host_data in coordinator.data.get("devices", []):
                if host_data.get("hostId") == host_id and "devices" in host_data:
                    host_devices.extend(host_data.get("devices", []))
            _LOGGER.debug("Found devices for site %s: %s", site_id, host_devices)
            for device in host_devices:
                device_id = device.get("id")
                device_name = device.get("name", "").lower()
                device_mac = device.get("mac")
                _LOGGER.debug("Processing device: id=%s, name=%s, mac=%s", device_id, device_name, device_mac)
                if device_id and device_mac and device_name:
                    full_device_name = f"{site_prefix}-{device_name}"
                    _LOGGER.debug("Adding device sensor: %s", full_device_name)
                    entities.append(UniFiDeviceSensor(coordinator, site_id, site_name, device_id, full_device_name, device_mac))
            _LOGGER.debug("Adding ISP metrics sensor for site %s", site_id)
            entities.append(UniFiISPMetricsDevice(coordinator, site_id, site_name, host_id))

    # Enhanced SD-WAN debug logging
    _LOGGER.debug("=== Starting SD-WAN Sensor Setup ===")
    _LOGGER.debug("Full coordinator data keys: %s", list(coordinator.data.keys()) if coordinator.data else "No data")
    
    sdwan_configs = coordinator.data.get("sdwan_configs", []) if coordinator.data else []
    sdwan_statuses = coordinator.data.get("sdwan_statuses", {}) if coordinator.data else {}
    
    _LOGGER.debug("SD-WAN configs in coordinator: %d configs", len(sdwan_configs))
    _LOGGER.debug("SD-WAN statuses in coordinator: %d statuses", len(sdwan_statuses))
    
    if sdwan_configs:
        _LOGGER.info("Found %d SD-WAN configs, creating sensors", len(sdwan_configs))
        for i, config in enumerate(sdwan_configs):
            config_id = config.get("id")
            config_name = config.get("name", f"SDWAN-{config_id}")
            
            _LOGGER.debug("Processing SD-WAN config %d: id=%s, name=%s", i, config_id, config_name)
            _LOGGER.debug("Config data keys: %s", list(config.keys()))
            
            if config_id:
                # Add main config sensor
                _LOGGER.debug("Creating main SD-WAN config sensor for %s", config_name)
                try:
                    entities.append(UniFiSDWANConfigSensor(coordinator, config_id, config_name))
                    _LOGGER.debug("Successfully created main config sensor for %s", config_name)
                except Exception as err:
                    _LOGGER.error("Failed to create main config sensor for %s: %s", config_name, err)
                
                # Add hub sensors
                hubs = config.get("hubs", [])
                _LOGGER.debug("Found %d hubs for config %s", len(hubs), config_name)
                for j, hub in enumerate(hubs):
                    hub_id = hub.get("id")
                    hub_name = hub.get("name", f"Hub-{hub_id}")
                    _LOGGER.debug("Creating hub sensor %d: id=%s, name=%s, siteId=%s", 
                                j, hub_id, hub_name, hub.get("siteId"))
                    try:
                        entities.append(UniFiSDWANHubSensor(coordinator, config_id, hub, config_name))
                        _LOGGER.debug("Successfully created hub sensor for %s", hub_name)
                    except Exception as err:
                        _LOGGER.error("Failed to create hub sensor for %s: %s", hub_name, err)
                
                # Add spoke sensors
                spokes = config.get("spokes", [])
                _LOGGER.debug("Found %d spokes for config %s", len(spokes), config_name)
                for k, spoke in enumerate(spokes):
                    spoke_id = spoke.get("id")
                    spoke_name = spoke.get("name", f"Spoke-{spoke_id}")
                    _LOGGER.debug("Creating spoke sensor %d: id=%s, name=%s, siteId=%s", 
                                k, spoke_id, spoke_name, spoke.get("siteId"))
                    try:
                        entities.append(UniFiSDWANSpokeSensor(coordinator, config_id, spoke, config_name))
                        _LOGGER.debug("Successfully created spoke sensor for %s", spoke_name)
                    except Exception as err:
                        _LOGGER.error("Failed to create spoke sensor for %s: %s", spoke_name, err)
            else:
                _LOGGER.warning("SD-WAN config %d has no ID, skipping", i)
    else:
        _LOGGER.warning("No SD-WAN configs found in coordinator data")
        _LOGGER.debug("Available coordinator data: %s", coordinator.data)

    _LOGGER.debug("=== SD-WAN Sensor Setup Complete ===")
    _LOGGER.debug("Total entities created: %s", len(entities))
    async_add_entities(entities)

class UniFiSDWANConfigSensor(CoordinatorEntity, SensorEntity):
    """Representation of a UniFi SD-WAN Config sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator, config_id: str, config_name: str) -> None:
        super().__init__(coordinator)
        self._config_id = config_id
        self._attr_unique_id = f"sdwan_config_{config_id}"
        self._attr_name = f"{config_name} Config"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"sdwan_config_{config_id}")},
            name=f"SD-WAN: {config_name}",
            manufacturer=MANUFACTURER,
            model="SD-WAN Configuration",
        )
        _LOGGER.debug("Initialized SD-WAN config sensor: %s (ID: %s)", config_name, config_id)

    @property
    def native_value(self) -> str:
        """Return the state of the SD-WAN config sensor."""
        status = self._get_config_status()
        _LOGGER.debug("Getting native value for config %s, status data: %s", self._config_id, status)
        if status:
            generate_status = status.get("generateStatus", "unknown")
            _LOGGER.debug("Config %s generate status: %s", self._config_id, generate_status)
            return generate_status.lower()
        _LOGGER.debug("No status data for config %s", self._config_id)
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the SD-WAN config sensor."""
        config = self._get_config()
        status = self._get_config_status()
        
        attrs = {}
        
        if config:
            attrs.update({
                "id": self._config_id,
                "name": config.get("name"),
                "type": config.get("type"),
                "variant": config.get("variant"),
                "hub_count": len(config.get("hubs", [])),
                "spoke_count": len(config.get("spokes", [])),
            })
            
            # Add settings info
            settings = config.get("settings", {})
            if settings:
                attrs.update({
                    "hubs_interconnect": settings.get("hubsInterconnect"),
                    "spokes_isolate": settings.get("spokesIsolate"),
                    "spokes_auto_scale": settings.get("spokesAutoScaleAndNatEnabled"),
                })

        if status:
            attrs.update({
                "generate_status": status.get("generateStatus"),
                "last_generated_at": status.get("lastGeneratedAt"),
                "fingerprint": status.get("fingerprint"),
                "updated_at": status.get("updatedAt"),
                "total_errors": len(status.get("errors", [])),
                "total_warnings": len(status.get("warnings", [])),
                "hub_status_count": len(status.get("hubs", [])),
                "spoke_status_count": len(status.get("spokes", [])),
            })

        return attrs

    def _get_config(self) -> dict[str, Any] | None:
        """Get the SD-WAN config data from coordinator."""
        if not self.coordinator.data:
            _LOGGER.debug("No coordinator data for config %s", self._config_id)
            return None
        
        configs = self.coordinator.data.get("sdwan_configs", [])
        _LOGGER.debug("Searching %d configs for ID %s", len(configs), self._config_id)
        
        for config in configs:
            if config.get("id") == self._config_id:
                _LOGGER.debug("Found config data for %s", self._config_id)
                return config
        
        _LOGGER.debug("Config %s not found in coordinator data", self._config_id)
        return None

    def _get_config_status(self) -> dict[str, Any] | None:
        """Get the SD-WAN config status from coordinator."""
        if not self.coordinator.data:
            _LOGGER.debug("No coordinator data for config status %s", self._config_id)
            return None
        
        statuses = self.coordinator.data.get("sdwan_statuses", {})
        _LOGGER.debug("Available status keys: %s, looking for: %s", list(statuses.keys()), self._config_id)
        
        status = statuses.get(self._config_id)
        if status:
            _LOGGER.debug("Found status data for %s", self._config_id)
        else:
            _LOGGER.debug("No status data found for %s", self._config_id)
        
        return status


class UniFiSDWANHubSensor(CoordinatorEntity, SensorEntity):
    """Representation of a UniFi SD-WAN Hub sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator, config_id: str, hub_data: dict, config_name: str) -> None:
        super().__init__(coordinator)
        self._config_id = config_id
        self._hub_id = hub_data.get("id")
        self._site_id = hub_data.get("siteId")
        self._host_id = hub_data.get("hostId")
        hub_name = hub_data.get("name", f"Hub-{self._hub_id}")
        
        self._attr_unique_id = f"sdwan_hub_{config_id}_{self._hub_id}"
        self._attr_name = f"{config_name} Hub: {hub_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"sdwan_hub_{config_id}_{self._hub_id}")},
            name=f"SD-WAN Hub: {hub_name}",
            manufacturer=MANUFACTURER,
            model="SD-WAN Hub",
            via_device=(DOMAIN, f"sdwan_config_{config_id}"),
        )

    @property
    def native_value(self) -> str:
        """Return the state of the SD-WAN hub sensor."""
        hub_status = self._get_hub_status()
        if hub_status:
            apply_status = hub_status.get("applyStatus", "unknown")
            return apply_status.lower() if isinstance(apply_status, str) else str(apply_status).lower()
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the SD-WAN hub sensor."""
        hub_status = self._get_hub_status()
        if not hub_status:
            return {}

        attrs = {
            "hub_id": self._hub_id,
            "site_id": self._site_id,
            "host_id": self._host_id,
            "apply_status": hub_status.get("applyStatus"),
            "error_count": len(hub_status.get("errors", [])),
            "warning_count": len(hub_status.get("warnings", [])),
            "network_count": len(hub_status.get("networks", [])),
            "route_count": len(hub_status.get("routes", [])),
            "tunnels_used_by_other_features": hub_status.get("numberOfTunnelsUsedByOtherFeatures", 0),
        }

        # Add WAN status information
        primary_wan = hub_status.get("primaryWanStatus")
        if primary_wan:
            attrs.update({
                "primary_wan_ip": primary_wan.get("ip"),
                "primary_wan_latency": primary_wan.get("latency"),
                "primary_wan_id": primary_wan.get("wanId"),
                "primary_wan_issues": len(primary_wan.get("internetIssues", [])),
            })

        secondary_wan = hub_status.get("secondaryWanStatus")
        if secondary_wan:
            attrs.update({
                "secondary_wan_ip": secondary_wan.get("ip"),
                "secondary_wan_latency": secondary_wan.get("latency"),
                "secondary_wan_id": secondary_wan.get("wanId"),
                "secondary_wan_issues": len(secondary_wan.get("internetIssues", [])),
            })

        return attrs

    def _get_hub_status(self) -> dict[str, Any] | None:
        """Get the hub status from coordinator data."""
        if not self.coordinator.data:
            return None
        
        statuses = self.coordinator.data.get("sdwan_statuses", {})
        config_status = statuses.get(self._config_id)
        
        if not config_status:
            return None

        for hub in config_status.get("hubs", []):
            if hub.get("id") == self._hub_id:
                return hub
        return None


class UniFiSDWANSpokeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a UniFi SD-WAN Spoke sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator, config_id: str, spoke_data: dict, config_name: str) -> None:
        super().__init__(coordinator)
        self._config_id = config_id
        self._spoke_id = spoke_data.get("id")
        self._site_id = spoke_data.get("siteId")
        self._host_id = spoke_data.get("hostId")
        spoke_name = spoke_data.get("name", f"Spoke-{self._spoke_id}")
        
        self._attr_unique_id = f"sdwan_spoke_{config_id}_{self._spoke_id}"
        self._attr_name = f"{config_name} Spoke: {spoke_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"sdwan_spoke_{config_id}_{self._spoke_id}")},
            name=f"SD-WAN Spoke: {spoke_name}",
            manufacturer=MANUFACTURER,
            model="SD-WAN Spoke",
            via_device=(DOMAIN, f"sdwan_config_{config_id}"),
        )

    @property
    def native_value(self) -> str:
        """Return the state of the SD-WAN spoke sensor."""
        spoke_status = self._get_spoke_status()
        if spoke_status:
            apply_status = spoke_status.get("applyStatus", "unknown")
            return apply_status.lower() if isinstance(apply_status, str) else str(apply_status).lower()
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the SD-WAN spoke sensor."""
        spoke_status = self._get_spoke_status()
        if not spoke_status:
            return {}

        attrs = {
            "spoke_id": self._spoke_id,
            "site_id": self._site_id,
            "host_id": self._host_id,
            "apply_status": spoke_status.get("applyStatus"),
            "error_count": len(spoke_status.get("errors", [])),
            "warning_count": len(spoke_status.get("warnings", [])),
            "network_count": len(spoke_status.get("networks", [])),
            "route_count": len(spoke_status.get("routes", [])),
            "connection_count": len(spoke_status.get("connections", [])),
            "tunnels_used_by_other_features": spoke_status.get("numberOfTunnelsUsedByOtherFeatures", 0),
        }

        # Add WAN status information
        primary_wan = spoke_status.get("primaryWanStatus")
        if primary_wan:
            attrs.update({
                "primary_wan_ip": primary_wan.get("ip"),
                "primary_wan_latency": primary_wan.get("latency"),
                "primary_wan_id": primary_wan.get("wanId"),
                "primary_wan_issues": len(primary_wan.get("internetIssues", [])),
            })

        secondary_wan = spoke_status.get("secondaryWanStatus")
        if secondary_wan:
            attrs.update({
                "secondary_wan_ip": secondary_wan.get("ip"),
                "secondary_wan_latency": secondary_wan.get("latency"),
                "secondary_wan_id": secondary_wan.get("wanId"),
                "secondary_wan_issues": len(secondary_wan.get("internetIssues", [])),
            })

        # Add connection status
        connections = spoke_status.get("connections", [])
        connected_hubs = 0
        total_tunnels = 0
        connected_tunnels = 0

        for connection in connections:
            tunnels = connection.get("tunnels", [])
            total_tunnels += len(tunnels)
            hub_connected = any(tunnel.get("status") == "connected" for tunnel in tunnels)
            if hub_connected:
                connected_hubs += 1
                connected_tunnels += len([t for t in tunnels if t.get("status") == "connected"])

        attrs.update({
            "connected_hubs": connected_hubs,
            "total_tunnels": total_tunnels,
            "connected_tunnels": connected_tunnels,
            "tunnel_success_rate": round((connected_tunnels / total_tunnels * 100), 2) if total_tunnels > 0 else 0,
        })

        return attrs

    def _get_spoke_status(self) -> dict[str, Any] | None:
        """Get the spoke status from coordinator data."""
        if not self.coordinator.data:
            return None
        
        statuses = self.coordinator.data.get("sdwan_statuses", {})
        config_status = statuses.get(self._config_id)
        
        if not config_status:
            return None

        for spoke in config_status.get("spokes", []):
            if spoke.get("id") == self._spoke_id:
                return spoke
        return None


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

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_state_class = None  # Remove state class entirely
    _attr_native_unit_of_measurement = None

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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._site_id)},
            manufacturer=MANUFACTURER,
            name=self._attr_name,
        )

    @property
    def native_value(self) -> datetime:
        """Return the state of the sensor."""
        return dt.now()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        # Log the entire coordinator data for debugging
        _LOGGER.debug("Full coordinator data: %s", self.coordinator.data)

        # Get ISP metrics for this specific site
        site_metrics = self.coordinator.data.get("isp_metrics", {}) if self.coordinator.data else {}
        site_specific_metrics = site_metrics.get(self._site_id, {})
        
        # Log the site-specific metrics
        _LOGGER.debug("Site-specific ISP metrics for %s: %s", self._site_id, site_specific_metrics)

        metrics = {}
        
        # Function to get the most recent timestamp's metrics
        def get_latest_metrics(metric_type):
            type_metrics = site_specific_metrics.get(metric_type, {})
            if not type_metrics:
                return {}
            
            # Get the most recent timestamp
            try:
                latest_timestamp = max(type_metrics.keys()) if type_metrics else None
                return type_metrics.get(latest_timestamp, {}) if latest_timestamp else {}
            except Exception as e:
                _LOGGER.debug(f"Error getting latest metrics for {metric_type}: {e}")
                return {}

        # Process latency metrics
        latency_metrics = get_latest_metrics('latency')
        metrics.update({
            "latency_avg": latency_metrics.get('avg_latency'),
            "latency_min": latency_metrics.get('min_latency', latency_metrics.get('avg_latency')),
            "latency_max": latency_metrics.get('max_latency'),
        })
        
        # Process packet loss metrics
        packet_loss_metrics = get_latest_metrics('packet-loss')
        packet_loss_value = packet_loss_metrics.get('packet_loss')

        # Ensure packet_loss_value is a number, default to 0 if not
        try:
            packet_loss_percentage = float(packet_loss_value) if packet_loss_value is not None else 0
        except (TypeError, ValueError):
            packet_loss_percentage = 0

        metrics.update({
            "packet_loss_percentage": packet_loss_percentage,
        })
        
        # Process bandwidth metrics
        bandwidth_metrics = get_latest_metrics('bandwidth')
        metrics.update({
            "download_mbps": bandwidth_metrics.get('download_kbps', 0) / 1000,  # Convert kbps to Mbps
            "upload_mbps": bandwidth_metrics.get('upload_kbps', 0) / 1000,  # Convert kbps to Mbps
        })

        # Process WAN metrics
        wan_metrics = get_latest_metrics('wan')
        metrics.update({
            "wan_latency_avg": wan_metrics.get('avg_latency'),
            "wan_latency_max": wan_metrics.get('max_latency'),
            "wan_download_kbps": wan_metrics.get('download_kbps'),
            "wan_upload_kbps": wan_metrics.get('upload_kbps'),
            "wan_packet_loss": wan_metrics.get('packet_loss'),
            "wan_uptime": wan_metrics.get('uptime'),
            "wan_downtime": wan_metrics.get('downtime'),
            "isp_name": wan_metrics.get('isp_name'),
            "isp_asn": wan_metrics.get('isp_asn'),
        })

        # Log the final metrics
        _LOGGER.debug("Final metrics for site %s: %s", self._site_id, metrics)
        return metrics

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and bool(self.coordinator.data)
