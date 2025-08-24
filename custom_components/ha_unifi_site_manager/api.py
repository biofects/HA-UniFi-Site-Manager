"""UniFi Site Manager API client."""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

import httpx

from .const import (
    API_BASE_URL,
    API_SITES,
    API_HOSTS,
    API_HOST_BY_ID,
    API_ISP_METRICS,
    API_SD_WAN_CONFIGS,
    API_SD_WAN_CONFIG_BY_ID,
    API_SD_WAN_CONFIG_STATUS,
)

_LOGGER = logging.getLogger(__name__)

class UniFiSiteManagerAPIError(Exception):
    """Exception raised for API errors."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize the exception."""
        self.status_code = status_code
        self.message = message
        super().__init__(f"API error {status_code}: {message}")


class UniFiSiteManagerAPI:
    async def list_sdwan_configs(self) -> List[Dict[str, Any]]:
        """List all SD-WAN configs."""
        _LOGGER.debug("Fetching SD-WAN configs")
        try:
            response = await self._make_request("GET", API_SD_WAN_CONFIGS)
            configs = response.get("data", [])
            _LOGGER.debug("Found %d SD-WAN configs", len(configs))
            return configs
        except UniFiSiteManagerAPIError as exc:
            _LOGGER.error("Failed to fetch SD-WAN configs: %s", exc)
            return []

    async def get_sdwan_config_by_id(self, config_id: str) -> Optional[Dict[str, Any]]:
        """Get SD-WAN config by ID."""
        _LOGGER.debug("Fetching SD-WAN config %s", config_id)
        try:
            response = await self._make_request(
                "GET",
                API_SD_WAN_CONFIG_BY_ID.format(id=config_id),
            )
            config = response.get("data")
            if config:
                _LOGGER.debug("Found SD-WAN config %s", config_id)
            else:
                _LOGGER.warning("SD-WAN config %s not found", config_id)
            return config
        except UniFiSiteManagerAPIError as exc:
            _LOGGER.error("Failed to fetch SD-WAN config %s: %s", config_id, exc)
            return None

    async def get_sdwan_config_status(self, config_id: str) -> Optional[Dict[str, Any]]:
        """Get SD-WAN config status by ID."""
        _LOGGER.debug("Fetching SD-WAN config status for %s", config_id)
        try:
            response = await self._make_request(
                "GET",
                API_SD_WAN_CONFIG_STATUS.format(id=config_id),
            )
            status = response.get("data")
            if status:
                _LOGGER.debug("Found SD-WAN config status for %s", config_id)
            else:
                _LOGGER.warning("SD-WAN config status for %s not found", config_id)
            return status
        except UniFiSiteManagerAPIError as exc:
            _LOGGER.error("Failed to fetch SD-WAN config status for %s: %s", config_id, exc)
            return None
    """UniFi Site Manager API client."""

    def __init__(self, api_key: str) -> None:
        """Initialize the API client."""
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=API_BASE_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-KEY": api_key,
            },
            timeout=30.0,
        )

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an API request."""
        try:
            response = await self._client.request(
                method,
                endpoint,
                params=params,
                json=json,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            _LOGGER.error(
                "HTTP error occurred while making request to %s: %s",
                endpoint,
                exc.response.text,
            )
            raise UniFiSiteManagerAPIError(
                exc.response.status_code,
                exc.response.text,
            ) from exc
        except httpx.RequestError as exc:
            _LOGGER.error(
                "Error occurred while making request to %s: %s",
                endpoint,
                str(exc),
            )
            raise UniFiSiteManagerAPIError(
                500,
                str(exc),
            ) from exc

    async def get_sites(self) -> List[Dict[str, Any]]:
        """Get all sites."""
        _LOGGER.debug("Fetching sites")
        try:
            response = await self._make_request("GET", API_SITES)
            sites = response.get("data", [])
            _LOGGER.debug("Found %d sites", len(sites))
            return sites
        except UniFiSiteManagerAPIError as exc:
            _LOGGER.error("Failed to fetch sites: %s", exc)
            return []

    async def get_hosts(self) -> List[Dict[str, Any]]:
        """Get all hosts."""
        _LOGGER.debug("Fetching hosts")
        try:
            response = await self._make_request("GET", API_HOSTS)
            hosts = response.get("data", [])
            _LOGGER.debug("Found %d hosts", len(hosts))
            return hosts
        except UniFiSiteManagerAPIError as exc:
            _LOGGER.error("Failed to fetch hosts: %s", exc)
            return []

    async def get_host_by_id(self, host_id: str) -> Optional[Dict[str, Any]]:
        """Get host by ID."""
        _LOGGER.debug("Fetching host %s", host_id)
        try:
            response = await self._make_request(
                "GET",
                API_HOST_BY_ID.format(id=host_id),
            )
            host = response.get("data")
            if host:
                _LOGGER.debug("Found host %s", host_id)
            else:
                _LOGGER.warning("Host %s not found", host_id)
            return host
        except UniFiSiteManagerAPIError as exc:
            _LOGGER.error("Failed to fetch host %s: %s", host_id, exc)
            return None

    async def get_isp_metrics(self, metric_type: str) -> Optional[Dict[str, Any]]:
        """Get ISP metrics."""
        _LOGGER.debug("Fetching ISP metrics for type %s", metric_type)
        try:
            response = await self._make_request(
                "GET",
                API_ISP_METRICS.format(type=metric_type),
            )
            metrics = response.get("data")
            if metrics:
                _LOGGER.debug("Found ISP metrics for type %s", metric_type)
            else:
                _LOGGER.warning("No ISP metrics found for type %s", metric_type)
            return metrics
        except UniFiSiteManagerAPIError as exc:
            _LOGGER.error("Failed to fetch ISP metrics for type %s: %s", metric_type, exc)
            return None

    async def close(self) -> None:
        """Close the API client."""
        await self._client.aclose()
