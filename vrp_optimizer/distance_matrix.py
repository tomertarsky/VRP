"""
Build distance (km) and travel time (minutes) matrices using Haversine formula.
"""
import math
import numpy as np
from config import AVERAGE_SPEED_KMH

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def build_matrices(locations, speed_kmh=None):
    """
    Build distance and time matrices for a list of locations.

    Args:
        locations: list of dicts with 'lat' and 'lon' keys.
                   Index 0.. are the nodes (depots first, then sites).
        speed_kmh: average driving speed (default from config)

    Returns:
        distance_matrix: 2D numpy array of distances in km
        time_matrix: 2D numpy array of travel times in minutes (integers)
    """
    speed = speed_kmh or AVERAGE_SPEED_KMH
    n = len(locations)
    dist_matrix = np.zeros((n, n), dtype=np.float64)
    time_matrix = np.zeros((n, n), dtype=np.int64)

    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(
                locations[i]["lat"], locations[i]["lon"],
                locations[j]["lat"], locations[j]["lon"],
            )
            # Apply road-distance correction factor (roads are ~1.3x straight line)
            road_d = d * 1.3
            travel_min = int(round((road_d / speed) * 60))

            dist_matrix[i][j] = road_d
            dist_matrix[j][i] = road_d
            time_matrix[i][j] = travel_min
            time_matrix[j][i] = travel_min

    return dist_matrix, time_matrix


def build_cost_matrix(distance_matrix, time_matrix, variable_cost_per_km, wage_per_hour):
    """
    Build a combined cost matrix in cents for the solver objective.
    Cost = distance_cost + driver_time_cost
    """
    n = len(distance_matrix)
    cost_matrix = np.zeros((n, n), dtype=np.int64)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            dist_cost = distance_matrix[i][j] * variable_cost_per_km  # dollars
            time_cost = (time_matrix[i][j] / 60.0) * wage_per_hour     # dollars
            cost_matrix[i][j] = int(round((dist_cost + time_cost) * 100))  # cents
    return cost_matrix
