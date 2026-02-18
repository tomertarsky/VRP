"""
Google Maps Distance Matrix API integration with disk caching.
Builds drive-time and drive-distance matrices for VRP sub-problems.

Batches requests (max 10 origins × 10 destinations = 100 elements per request)
and caches results to minimize API costs.
"""
import json
import os
import time
import math
import numpy as np
from config import GOOGLE_MAPS_API_KEY, DISTANCE_CACHE_PATH, AVERAGE_SPEED_KMH

# Google Distance Matrix API limits
MAX_ORIGINS = 10
MAX_DESTINATIONS = 10
MAX_ELEMENTS_PER_REQUEST = 100


def _cache_key(lat1, lon1, lat2, lon2):
    """Create a deterministic cache key from two coordinate pairs."""
    return f"{lat1:.6f},{lon1:.6f}|{lat2:.6f},{lon2:.6f}"


def load_distance_cache():
    if os.path.exists(DISTANCE_CACHE_PATH):
        with open(DISTANCE_CACHE_PATH, "r") as f:
            return json.load(f)
    return {}


def save_distance_cache(cache):
    with open(DISTANCE_CACHE_PATH, "w") as f:
        json.dump(cache, f)


def build_google_matrices(locations):
    """
    Build distance (km) and time (minutes) matrices using Google Maps
    Distance Matrix API for a list of locations.

    Args:
        locations: list of dicts with 'lat' and 'lon' keys

    Returns:
        distance_matrix: 2D numpy array of distances in km
        time_matrix: 2D numpy array of travel times in minutes (integers)
    """
    n = len(locations)
    dist_matrix = np.zeros((n, n), dtype=np.float64)
    time_matrix = np.zeros((n, n), dtype=np.int64)

    if n <= 1:
        return dist_matrix, time_matrix

    # Try to initialize Google Maps client; fall back to Haversine if unavailable
    gmaps = None
    google_works = False
    try:
        import googlemaps as _googlemaps
        gmaps = _googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
        # Quick test to verify API key works
        test = gmaps.distance_matrix(
            origins=["Toronto, ON"],
            destinations=["Mississauga, ON"],
            mode="driving",
        )
        if test.get("status") == "REQUEST_DENIED" or (
            test.get("rows") and test["rows"][0]["elements"][0].get("status") == "REQUEST_DENIED"
        ):
            raise RuntimeError("REQUEST_DENIED")
        google_works = True
    except Exception as e:
        print(f"      Google Distance Matrix API unavailable ({e}), using Haversine fallback")

    if not google_works:
        # Build matrices using Haversine with 1.3× road correction
        for i in range(n):
            for j in range(i + 1, n):
                d = _haversine_km(
                    locations[i]["lat"], locations[i]["lon"],
                    locations[j]["lat"], locations[j]["lon"],
                ) * 1.3  # road correction factor
                t = int(round((d / AVERAGE_SPEED_KMH) * 60))
                dist_matrix[i][j] = d
                dist_matrix[j][i] = d
                time_matrix[i][j] = t
                time_matrix[j][i] = t
        print(f"      Distance matrix: {n}x{n} built with Haversine (1.3× correction)")
        return dist_matrix, time_matrix

    cache = load_distance_cache()

    # Identify which pairs we need to fetch
    pairs_needed = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            key = _cache_key(locations[i]["lat"], locations[i]["lon"],
                             locations[j]["lat"], locations[j]["lon"])
            if key in cache:
                dist_matrix[i][j] = cache[key]["dist_km"]
                time_matrix[i][j] = cache[key]["time_min"]
            else:
                pairs_needed.append((i, j))

    if not pairs_needed:
        print(f"      Distance matrix: {n}x{n} fully cached")
        return dist_matrix, time_matrix

    total_elements = len(pairs_needed)
    print(f"      Distance matrix: {n}x{n}, {total_elements} pairs to fetch from Google Maps...")

    # Group by origin for efficient batching
    origins_map = {}
    for i, j in pairs_needed:
        if i not in origins_map:
            origins_map[i] = []
        origins_map[i].append(j)

    fetched = 0
    origin_indices = list(origins_map.keys())

    # Batch origins in groups of MAX_ORIGINS
    for o_start in range(0, len(origin_indices), MAX_ORIGINS):
        o_batch = origin_indices[o_start:o_start + MAX_ORIGINS]

        # Collect all unique destinations for this origin batch
        all_dests = set()
        for oi in o_batch:
            all_dests.update(origins_map[oi])
        dest_list = sorted(all_dests)

        # Batch destinations in groups of MAX_DESTINATIONS
        for d_start in range(0, len(dest_list), MAX_DESTINATIONS):
            d_batch = dest_list[d_start:d_start + MAX_DESTINATIONS]

            origins = [f"{locations[i]['lat']},{locations[i]['lon']}" for i in o_batch]
            destinations = [f"{locations[j]['lat']},{locations[j]['lon']}" for j in d_batch]

            try:
                result = gmaps.distance_matrix(
                    origins=origins,
                    destinations=destinations,
                    mode="driving",
                    units="metric",
                )

                for oi_idx, oi in enumerate(o_batch):
                    for dj_idx, dj in enumerate(d_batch):
                        if oi == dj:
                            continue
                        element = result["rows"][oi_idx]["elements"][dj_idx]
                        if element["status"] == "OK":
                            dist_km = element["distance"]["value"] / 1000.0
                            time_min = int(math.ceil(element["duration"]["value"] / 60.0))

                            dist_matrix[oi][dj] = dist_km
                            time_matrix[oi][dj] = time_min

                            key = _cache_key(locations[oi]["lat"], locations[oi]["lon"],
                                             locations[dj]["lat"], locations[dj]["lon"])
                            cache[key] = {"dist_km": dist_km, "time_min": time_min}
                            fetched += 1
                        else:
                            # Fallback: use haversine estimate
                            dist_km = _haversine_km(
                                locations[oi]["lat"], locations[oi]["lon"],
                                locations[dj]["lat"], locations[dj]["lon"]
                            ) * 1.3
                            time_min = int(round((dist_km / 40) * 60))
                            dist_matrix[oi][dj] = dist_km
                            time_matrix[oi][dj] = time_min

                # Brief pause to avoid rate limiting
                time.sleep(0.1)

            except Exception as e:
                print(f"      API error (using haversine fallback): {e}")
                # Fallback to haversine for this batch
                for oi in o_batch:
                    for dj in d_batch:
                        if oi == dj:
                            continue
                        if dist_matrix[oi][dj] == 0:
                            dist_km = _haversine_km(
                                locations[oi]["lat"], locations[oi]["lon"],
                                locations[dj]["lat"], locations[dj]["lon"]
                            ) * 1.3
                            time_min = int(round((dist_km / 40) * 60))
                            dist_matrix[oi][dj] = dist_km
                            time_matrix[oi][dj] = time_min

        # Save cache periodically
        if fetched > 0 and fetched % 500 == 0:
            save_distance_cache(cache)

    save_distance_cache(cache)
    print(f"      Fetched {fetched} distance pairs from Google Maps API")

    return dist_matrix, time_matrix


def _haversine_km(lat1, lon1, lat2, lon2):
    """Fallback haversine distance in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))
