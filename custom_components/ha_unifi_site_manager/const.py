"""Constants for the UniFi Site Manager integration."""
from typing import Final

# Domain
DOMAIN: Final = "ha_unifi_site_manager"
MANUFACTURER: Final = "Ubiquiti Inc."

API_BASE_URL: Final = "https://api.ui.com"
API_SITES_ENDPOINT: Final = "/ea/sites"
API_DEVICES_ENDPOINT: Final = "/ea/devices"
API_HOSTS_ENDPOINT: Final = "/ea/hosts"
API_CLIENTS_ENDPOINT: Final = "/ea/clients"
# SD-WAN Endpoints
API_SD_WAN_CONFIGS: Final = "/ea/sd-wan-configs"
API_SD_WAN_CONFIG_BY_ID: Final = "/ea/sd-wan-configs/{id}"
API_SD_WAN_CONFIG_STATUS: Final = "/ea/sd-wan-configs/{id}/status"

# Configuration
CONF_API_KEY: Final = "api_key"
CONF_SITES: Final = "sites"
CONF_CONTROLLER_URL: Final = "controller_url"
CONF_VERIFY_SSL: Final = "verify_ssl"

# Default Values
DEFAULT_VERIFY_SSL: Final = False

# Update Interval (15 minutes)
UPDATE_INTERVAL: Final = 900

# States
STATE_ONLINE: Final = "online"
STATE_OFFLINE: Final = "offline"
