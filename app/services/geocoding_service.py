"""
Geocoding Service - Convert text addresses to coordinates and vice versa.

Uses OpenStreetMap Nominatim API (free, no API key required).
Rate limited to 1 request/second by Nominatim policy.
"""

import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = "AgentConnect/1.0"


async def forward_geocode(address: str) -> Optional[Dict[str, Any]]:
    """
    Convert text address to coordinates (forward geocoding).

    Args:
        address: Text address like "Hyderabad, India" or "123 Main St, NYC"

    Returns:
        Dict with 'latitude', 'longitude', 'display_name', 'original_input'
        Returns None if address is empty
        Returns dict with error if geocoding fails
    """
    if not address or not address.strip():
        return None

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            url = f"{NOMINATIM_BASE_URL}/search"
            params = {
                "q": address.strip(),
                "format": "json",
                "limit": 1
            }
            headers = {"User-Agent": USER_AGENT}

            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()

            results = response.json()
            if results and len(results) > 0:
                result = results[0]
                location_data = {
                    "latitude": float(result.get("lat", 0)),
                    "longitude": float(result.get("lon", 0)),
                    "display_name": result.get("display_name", address),
                    "original_input": address
                }
                logger.info(f"[Geocoding] '{address}' -> lat={location_data['latitude']}, lon={location_data['longitude']}")
                return location_data
            else:
                logger.warning(f"[Geocoding] No results found for '{address}'")
                return {
                    "latitude": None,
                    "longitude": None,
                    "display_name": address,
                    "original_input": address,
                    "error": "Location not found"
                }
        except Exception as e:
            logger.error(f"[Geocoding] Error geocoding '{address}': {e}")
            return {
                "latitude": None,
                "longitude": None,
                "display_name": address,
                "original_input": address,
                "error": str(e)
            }


async def reverse_geocode(latitude: float, longitude: float) -> Optional[Dict[str, Any]]:
    """
    Convert coordinates to address (reverse geocoding).

    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate

    Returns:
        Dict with 'address', 'display_name', 'latitude', 'longitude'
    """
    if latitude is None or longitude is None:
        return None

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            url = f"{NOMINATIM_BASE_URL}/reverse"
            params = {
                "lat": latitude,
                "lon": longitude,
                "format": "json"
            }
            headers = {"User-Agent": USER_AGENT}

            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()

            result = response.json()
            if result and "display_name" in result:
                address_data = {
                    "display_name": result.get("display_name"),
                    "address": result.get("address", {}),
                    "latitude": latitude,
                    "longitude": longitude
                }
                logger.info(f"[Reverse Geocoding] ({latitude}, {longitude}) -> {address_data['display_name'][:50]}...")
                return address_data
            else:
                logger.warning(f"[Reverse Geocoding] No results for ({latitude}, {longitude})")
                return {
                    "display_name": f"{latitude}, {longitude}",
                    "address": {},
                    "latitude": latitude,
                    "longitude": longitude,
                    "error": "Address not found"
                }
        except Exception as e:
            logger.error(f"[Reverse Geocoding] Error for ({latitude}, {longitude}): {e}")
            return {
                "display_name": f"{latitude}, {longitude}",
                "address": {},
                "latitude": latitude,
                "longitude": longitude,
                "error": str(e)
            }


def is_location_dict(value: Any) -> bool:
    """
    Check if a value is a location dictionary with coordinates.

    Args:
        value: Value to check

    Returns:
        True if value is a dict with latitude/longitude keys
    """
    if not isinstance(value, dict):
        return False
    return "latitude" in value or "lat" in value or "longitude" in value or "lon" in value


def normalize_location(value: Any) -> Dict[str, Any]:
    """
    Normalize different location formats to a standard format.
    Handles: WhatsApp location, dict with lat/lon, text address, etc.

    Args:
        value: Location value in various formats

    Returns:
        Normalized dict with latitude, longitude, display_name
    """
    if not value:
        return {"latitude": None, "longitude": None, "display_name": None, "is_text": True}

    if isinstance(value, str):
        # Text address - needs geocoding
        return {
            "latitude": None,
            "longitude": None,
            "display_name": value,
            "original_input": value,
            "is_text": True,
            "needs_geocoding": True
        }

    if isinstance(value, dict):
        # Already a location dict
        lat = value.get("latitude") or value.get("lat")
        lon = value.get("longitude") or value.get("lon") or value.get("lng")
        name = value.get("display_name") or value.get("name") or value.get("address")

        return {
            "latitude": float(lat) if lat else None,
            "longitude": float(lon) if lon else None,
            "display_name": name,
            "is_text": False,
            "needs_geocoding": lat is None or lon is None
        }

    return {"latitude": None, "longitude": None, "display_name": str(value), "is_text": True}
