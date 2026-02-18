"""
Core VRP solver using Google OR-Tools.
Solves a single-day, single-depot VRP with:
  - Capacity dimension (lbs)
  - Time dimension (minutes, including service time)
  - Disjunctions for optional (non-mandatory) sites
  - Fixed vehicle cost to minimize truck count
  - Combined cost objective (distance + time)
"""
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import numpy as np
from google_distance import build_google_matrices
from distance_matrix import build_cost_matrix
from config import (
    TARGET_DAILY_PAYLOAD_LBS, EFFECTIVE_DRIVING_MINUTES,
    VARIABLE_COST_PER_KM, DRIVER_WAGE_PER_HOUR,
    TRUCK_FIXED_COST_SOLVER, SOLVER_TIME_LIMIT_SECONDS,
    REVENUE_PER_LB, DEPOTS,
)


def solve_daily_vrp(depot_key, visits, depot_info=None):
    """
    Solve VRP for one depot on one day.

    Args:
        depot_key: depot identifier string
        visits: list of visit dicts from scheduler
        depot_info: depot config dict (lat, lon, max_trucks)

    Returns:
        solution dict with routes, stats, dropped sites
        or None if no feasible solution
    """
    if not visits:
        return {"routes": [], "dropped": [], "stats": {
            "trucks_used": 0, "total_lbs": 0, "total_km": 0,
            "total_minutes": 0, "total_cost_cents": 0,
        }}

    depot_info = depot_info or DEPOTS[depot_key]
    num_vehicles = depot_info["max_trucks"]

    # Build node list: index 0 = depot, then visits
    nodes = [{"lat": depot_info["lat"], "lon": depot_info["lon"],
              "label": f"DEPOT ({depot_key})"}]
    demands = [0]  # depot has zero demand
    service_times = [0]  # no service at depot
    visit_refs = [None]  # no visit reference for depot

    for v in visits:
        nodes.append({"lat": v["site"]["lat"], "lon": v["site"]["lon"],
                       "label": v["node_label"]})
        demands.append(int(round(v["visit_demand_lbs"])))
        service_times.append(v["site"]["service_time_minutes"])
        visit_refs.append(v)

    num_nodes = len(nodes)

    if num_nodes <= 1:
        return {"routes": [], "dropped": [], "stats": {
            "trucks_used": 0, "total_lbs": 0, "total_km": 0,
            "total_minutes": 0, "total_cost_cents": 0,
        }}

    # Build distance and time matrices using Google Maps API
    dist_matrix, time_matrix = build_google_matrices(nodes)
    cost_matrix = build_cost_matrix(
        dist_matrix, time_matrix, VARIABLE_COST_PER_KM, DRIVER_WAGE_PER_HOUR
    )

    # ── OR-Tools Setup ──────────────────────────────────────
    # All vehicles start and end at depot (node 0)
    manager = pywrapcp.RoutingIndexManager(num_nodes, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # ── Cost callback ───────────────────────────────────────
    def cost_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(cost_matrix[from_node][to_node])

    transit_cost_idx = routing.RegisterTransitCallback(cost_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cost_idx)

    # ── Capacity dimension ──────────────────────────────────
    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    demand_cb_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb_idx,
        0,                                              # no slack
        [TARGET_DAILY_PAYLOAD_LBS] * num_vehicles,      # vehicle capacities
        True,                                           # start cumul to zero
        "Capacity",
    )

    # ── Time dimension ──────────────────────────────────────
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = int(time_matrix[from_node][to_node])
        service = service_times[from_node]
        return travel + service

    time_cb_idx = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(
        time_cb_idx,
        30,                          # slack: allow up to 30 min waiting
        EFFECTIVE_DRIVING_MINUTES,   # max time per vehicle (660 min)
        True,                        # force start cumul to zero
        "Time",
    )

    # ── Fixed vehicle cost (to minimize truck count) ────────
    for v in range(num_vehicles):
        routing.SetFixedCostOfVehicle(TRUCK_FIXED_COST_SOLVER, v)

    # ── Disjunctions — profit-maximizing (all sites optional) ──
    for node_idx in range(1, num_nodes):
        visit = visit_refs[node_idx]
        net = visit["site"]["net_contribution_per_visit"]
        # Penalty = lost net contribution in cents; unprofitable sites free to drop
        penalty = max(0, int(round(net * 100)))

        routing.AddDisjunction(
            [manager.NodeToIndex(node_idx)],
            penalty,
        )

    # ── Search parameters ───────────────────────────────────
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.FromSeconds(SOLVER_TIME_LIMIT_SECONDS)

    # ── Solve ───────────────────────────────────────────────
    solution = routing.SolveWithParameters(search_params)

    if not solution:
        print(f"    WARNING: No solution found for depot {depot_key}")
        # Return all sites as dropped
        dropped = [visit_refs[i] for i in range(1, num_nodes)]
        return {
            "routes": [],
            "dropped": dropped,
            "stats": {
                "trucks_used": 0, "total_lbs": 0, "total_km": 0,
                "total_minutes": 0, "total_cost_cents": 0,
            },
        }

    # ── Extract solution ────────────────────────────────────
    routes = []
    total_lbs = 0
    total_km = 0.0
    total_minutes = 0
    total_cost_cents = 0
    trucks_used = 0
    dropped = []

    for vehicle_id in range(num_vehicles):
        index = routing.Start(vehicle_id)
        route_nodes = []
        route_lbs = 0
        route_km = 0.0
        route_minutes = 0
        route_cost = 0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            next_index = solution.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)

            if node != 0:  # not depot
                route_nodes.append({
                    "node": node,
                    "visit": visit_refs[node],
                    "demand": demands[node],
                    "service_time": service_times[node],
                })
                route_lbs += demands[node]

            route_km += dist_matrix[node][next_node]
            route_minutes += int(time_matrix[node][next_node]) + service_times[node]
            route_cost += int(cost_matrix[node][next_node])

            index = next_index

        if route_nodes:
            # Route-level profitability check: does revenue cover costs?
            route_revenue_cents = sum(
                stop["visit"]["site"]["net_contribution_per_visit"] * 100
                for stop in route_nodes
            )
            route_total_cost = route_cost + TRUCK_FIXED_COST_SOLVER

            if route_revenue_cents < route_total_cost:
                # Unprofitable route — drop all stops
                print(f"    Dropping unprofitable truck {vehicle_id}: "
                      f"revenue ${route_revenue_cents/100:.0f} < cost ${route_total_cost/100:.0f}")
                for stop in route_nodes:
                    dropped.append(stop["visit"])
                continue

            trucks_used += 1
            route_info = {
                "vehicle_id": vehicle_id,
                "stops": route_nodes,
                "num_stops": len(route_nodes),
                "total_lbs": route_lbs,
                "total_km": round(route_km, 1),
                "total_minutes": route_minutes,
                "cost_cents": route_cost + TRUCK_FIXED_COST_SOLVER,
            }
            routes.append(route_info)
            total_lbs += route_lbs
            total_km += route_km
            total_minutes += route_minutes
            total_cost_cents += route_cost + TRUCK_FIXED_COST_SOLVER

    # Find sites dropped by the solver (disjunction)
    for node_idx in range(1, num_nodes):
        idx = manager.NodeToIndex(node_idx)
        if solution.Value(routing.NextVar(idx)) == idx:
            # Node routes to itself — it was dropped
            dropped.append(visit_refs[node_idx])

    return {
        "depot": depot_key,
        "routes": routes,
        "dropped": dropped,
        "stats": {
            "trucks_used": trucks_used,
            "total_lbs": total_lbs,
            "total_km": round(total_km, 1),
            "total_minutes": total_minutes,
            "total_cost_cents": total_cost_cents,
        },
    }
