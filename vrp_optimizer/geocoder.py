"""
Geocode addresses with Google Maps API (primary) or Nominatim (fallback).
All results cached to JSON file for instant re-use.
"""
import json
import os
import time
from config import GEOCODE_CACHE_PATH, GOOGLE_MAPS_API_KEY, DEPOTS


def load_cache(cache_path=None):
    cache_path = cache_path or GEOCODE_CACHE_PATH
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache, cache_path=None):
    cache_path = cache_path or GEOCODE_CACHE_PATH
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)


def _try_google_geocode(gmaps, address):
    """Try geocoding with Google Maps API. Returns (lat, lon, resolved) or None."""
    try:
        result = gmaps.geocode(address)
        if result:
            loc = result[0]["geometry"]["location"]
            return loc["lat"], loc["lng"], result[0]["formatted_address"]
    except Exception:
        pass
    return None


def _try_nominatim_geocode(geocode_fn, address):
    """Try geocoding with Nominatim. Returns (lat, lon, resolved) or None."""
    try:
        location = geocode_fn(address)
        if location:
            return location.latitude, location.longitude, location.address
    except Exception:
        pass
    return None


def geocode_sites(sites, cache_path=None):
    """
    Geocode all site addresses. Tries Google Maps first, falls back to Nominatim.
    Returns dict of {address: {lat, lon, resolved, source}}.
    """
    cache_path = cache_path or GEOCODE_CACHE_PATH
    cache = load_cache(cache_path)

    addresses = list({s["address"] for s in sites})
    total = len(addresses)
    to_geocode = [a for a in addresses if a not in cache]
    cached_count = total - len(to_geocode)

    print(f"  {total} unique addresses, {cached_count} cached, {len(to_geocode)} to geocode")

    if not to_geocode:
        return cache

    # Try Google Maps first
    gmaps = None
    google_works = False
    try:
        import googlemaps
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
        test = gmaps.geocode("Toronto, ON, Canada")
        if test:
            google_works = True
            print("  Using Google Maps Geocoding API")
    except Exception as e:
        print(f"  Google Maps API unavailable ({e}), using Nominatim fallback")

    # Setup Nominatim as fallback
    nominatim_geocode = None
    if not google_works:
        from geopy.geocoders import Nominatim
        from geopy.extra.rate_limiter import RateLimiter
        geolocator = Nominatim(user_agent="vrp_optimizer_v2", timeout=10)
        nominatim_geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1)
        print("  Using Nominatim (free, ~1 addr/sec)")
        print(f"  Estimated time: ~{len(to_geocode)} seconds")

    failed = []
    for i, address in enumerate(to_geocode):
        clean_addr = address.replace("\t", ", ").strip()
        if not clean_addr.lower().endswith("canada"):
            clean_addr += ", Canada"

        result = None
        source = None

        if google_works:
            r = _try_google_geocode(gmaps, clean_addr)
            if r:
                result = r
                source = "google"
        else:
            r = _try_nominatim_geocode(nominatim_geocode, clean_addr)
            if r:
                result = r
                source = "nominatim"

        # Retry with simplified address
        if not result and "," in clean_addr:
            parts = clean_addr.split(",")
            simplified = ", ".join(parts[-3:]).strip()
            if google_works:
                r = _try_google_geocode(gmaps, simplified)
                if r:
                    result = r
                    source = "google"
            elif nominatim_geocode:
                r = _try_nominatim_geocode(nominatim_geocode, simplified)
                if r:
                    result = r
                    source = "nominatim"

        if result:
            cache[address] = {
                "lat": result[0], "lon": result[1],
                "resolved": result[2], "source": source,
            }
            status = "OK"
        else:
            failed.append(address)
            status = "FAILED"

        print(f"  [{i+1}/{len(to_geocode)}] {status}: {address[:60]}...")

        if (i + 1) % 50 == 0:
            save_cache(cache, cache_path)

    save_cache(cache, cache_path)

    if failed:
        print(f"\n  WARNING: {len(failed)} addresses failed:")
        for a in failed:
            print(f"    - {a}")

    print(f"  Geocoding complete: {len(cache)} total cached")
    return cache


def geocode_depots(cache_path=None):
    """Geocode depot addresses and update DEPOTS config in-place."""
    cache = load_cache(cache_path)

    # Try Google Maps first
    gmaps = None
    google_works = False
    try:
        import googlemaps
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
        test = gmaps.geocode("Toronto, ON, Canada")
        if test:
            google_works = True
    except Exception:
        pass

    # Setup Nominatim as fallback
    nominatim_geocode = None
    if not google_works:
        from geopy.geocoders import Nominatim
        from geopy.extra.rate_limiter import RateLimiter
        geolocator = Nominatim(user_agent="vrp_optimizer_v2", timeout=10)
        nominatim_geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1)

    for key, depot in DEPOTS.items():
        addr = depot.get("address", "")
        if not addr:
            continue

        # Check cache first
        if addr in cache:
            depot["lat"] = cache[addr]["lat"]
            depot["lon"] = cache[addr]["lon"]
            print(f"  {key}: {cache[addr].get('resolved', addr)} (cached)")
            continue

        result = None
        if google_works:
            result = _try_google_geocode(gmaps, addr)
        elif nominatim_geocode:
            result = _try_nominatim_geocode(nominatim_geocode, addr)

        if result:
            depot["lat"] = result[0]
            depot["lon"] = result[1]
            cache[addr] = {"lat": result[0], "lon": result[1],
                           "resolved": result[2], "source": "google" if google_works else "nominatim"}
            print(f"  {key}: {result[2]}")
        else:
            print(f"  WARNING: Failed to geocode depot {key}: {addr}")

    save_cache(cache, cache_path)
    return DEPOTS


def get_coordinates(sites, geocode_cache):
    """Attach lat/lon to each site from the geocode cache."""
    missing = 0
    for site in sites:
        geo = geocode_cache.get(site["address"])
        if geo:
            site["lat"] = geo["lat"]
            site["lon"] = geo["lon"]
        else:
            site["lat"] = None
            site["lon"] = None
            missing += 1

    if missing:
        print(f"  WARNING: {missing} sites missing coordinates (excluded from routing)")

    return [s for s in sites if s["lat"] is not None]
