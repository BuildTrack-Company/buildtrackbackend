"""Best-effort IP geolocation for audit logs.

Uses the free ip-api.com batch endpoint (no key, ~45 req/min). Results are
cached in-process so repeat IPs cost nothing, and the whole thing fails open:
if the lookup errors or times out, locations just come back empty.
"""
from typing import Iterable
import ipaddress
import structlog
import httpx

logger = structlog.get_logger(__name__)

# cache maps ip -> {"location": str, "lat": float|None, "lon": float|None}
_cache: dict[str, dict] = {}


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local)
    except ValueError:
        return False


async def locate_ips(ips: Iterable[str]) -> dict[str, dict]:
    """Return {ip: {"location", "lat", "lon"}} for the given IPs, cached + one batch call."""
    unique = {ip for ip in ips if ip}
    result: dict[str, dict] = {}
    to_lookup: list[str] = []
    for ip in unique:
        if ip in _cache:
            result[ip] = _cache[ip]
        elif not _is_public(ip):
            _cache[ip] = {"location": "Local / Private network", "lat": None, "lon": None}
            result[ip] = _cache[ip]
        else:
            to_lookup.append(ip)

    if not to_lookup:
        return result

    try:
        payload = [{"query": ip, "fields": "status,country,city,lat,lon,query"} for ip in to_lookup[:100]]
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post("http://ip-api.com/batch", json=payload)
            for row in resp.json():
                ip = row.get("query")
                if not ip:
                    continue
                if row.get("status") == "success":
                    city, country = row.get("city"), row.get("country")
                    label = ", ".join([p for p in (city, country) if p]) or "Unknown location"
                    entry = {"location": label, "lat": row.get("lat"), "lon": row.get("lon")}
                else:
                    entry = {"location": "Unknown location", "lat": None, "lon": None}
                _cache[ip] = entry
                result[ip] = entry
    except Exception as e:  # fail open — never break the audit view over geo
        logger.warning("ipgeo_lookup_failed", error=str(e))
        for ip in to_lookup:
            result.setdefault(ip, {"location": "", "lat": None, "lon": None})

    return result
