"""
Phase 1: Depot Selection & Site Assignment.

Before running the VRP solver, evaluate which depots to keep open and how to
assign sites.  Uses a greedy closure algorithm:
  1. Start with all depots open, each site assigned to nearest depot
  2. Rank depots by estimated profitability
  3. Try closing the least profitable depot — reassign its sites to next-nearest
  4. If closure improves total network profit → keep it closed
  5. Repeat until no more closures improve profit

Returns the set of open depots and final site-to-depot mapping.
"""
import math
from config import (
    TRUCK_FIXED_WEEKLY, VARIABLE_COST_PER_KM, DRIVER_WAGE_PER_HOUR,
    AVERAGE_SPEED_KMH, REVENUE_PER_LB, DEPOTS,
)


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _estimate_depot_pnl(depot_key, depot_info, assigned_sites):
    """
    Estimate weekly P&L for a depot given its assigned sites.

    Returns dict with revenue, fixed_cost, variable_cost, net_profit, details.
    """
    if not assigned_sites:
        return {
            "depot": depot_key,
            "num_sites": 0,
            "weekly_revenue": 0,
            "fixed_cost": 0,
            "variable_cost": 0,
            "net_profit": 0,
            "total_weekly_lbs": 0,
        }

    trucks = depot_info["max_trucks"]
    fixed_cost = trucks * TRUCK_FIXED_WEEKLY

    total_weekly_revenue = 0
    total_weekly_lbs = 0
    total_variable_cost = 0

    for site in assigned_sites:
        weekly_visits = site["weekly_visits"]
        rev = site["revenue_per_visit"] * weekly_visits
        lbs = site["lbs_per_visit"] * weekly_visits
        total_weekly_revenue += rev
        total_weekly_lbs += lbs

        # Estimate variable cost: driving to/from site
        if (site.get("lat") is not None and site.get("lon") is not None
                and depot_info.get("lat") is not None):
            dist_km = _haversine_km(
                depot_info["lat"], depot_info["lon"],
                site["lat"], site["lon"],
            )
            # Round-trip factor ~1.3 (sites are chained, not round-tripped individually)
            # Plus driver time cost
            est_km_per_visit = dist_km * 1.3
            driving_cost = est_km_per_visit * VARIABLE_COST_PER_KM
            drive_hours = est_km_per_visit / AVERAGE_SPEED_KMH
            driver_cost = drive_hours * DRIVER_WAGE_PER_HOUR
            total_variable_cost += (driving_cost + driver_cost) * weekly_visits

    net_profit = total_weekly_revenue - fixed_cost - total_variable_cost

    return {
        "depot": depot_key,
        "num_sites": len(assigned_sites),
        "weekly_revenue": total_weekly_revenue,
        "fixed_cost": fixed_cost,
        "variable_cost": total_variable_cost,
        "net_profit": net_profit,
        "total_weekly_lbs": total_weekly_lbs,
    }


def _get_sorted_depot_distances(site, depots_dict):
    """Return list of (depot_key, distance_km) sorted by distance for a site."""
    distances = []
    for key, info in depots_dict.items():
        if info.get("lat") is None or info.get("lon") is None:
            continue
        if site.get("lat") is None or site.get("lon") is None:
            continue
        d = _haversine_km(site["lat"], site["lon"], info["lat"], info["lon"])
        distances.append((key, d))
    distances.sort(key=lambda x: x[1])
    return distances


def select_depots(sites, depots):
    """
    Run the greedy depot closure algorithm.

    Args:
        sites: list of site dicts (must have lat/lon and depot already assigned)
        depots: dict of depot configs (DEPOTS from config)

    Returns:
        (open_depots, closed_depots, depot_pnl)
        - open_depots: set of depot keys to keep
        - closed_depots: dict of {depot_key: reason_string}
        - depot_pnl: dict of {depot_key: pnl_dict} for open depots
    Also mutates site["depot"] for reassigned sites.
    """
    open_depots = set(depots.keys())
    closed_depots = {}

    # Pre-compute sorted depot distances for each site (for reassignment)
    site_depot_dists = {}
    for site in sites:
        site_depot_dists[site["id"]] = _get_sorted_depot_distances(site, depots)

    def _get_sites_by_depot():
        by_depot = {k: [] for k in open_depots}
        for site in sites:
            if site["depot"] in open_depots:
                by_depot[site["depot"]].append(site)
        return by_depot

    def _compute_network_profit():
        sites_by_depot = _get_sites_by_depot()
        total = 0
        pnl = {}
        for dk in open_depots:
            p = _estimate_depot_pnl(dk, depots[dk], sites_by_depot[dk])
            pnl[dk] = p
            total += p["net_profit"]
        return total, pnl

    # Initial state
    current_profit, current_pnl = _compute_network_profit()

    print(f"\n  Initial network estimate: ${current_profit:,.0f}/week")
    print(f"  Per-depot estimates:")
    for dk in sorted(current_pnl.keys()):
        p = current_pnl[dk]
        print(f"    {dk:<12} {p['num_sites']:>3} sites | "
              f"Rev ${p['weekly_revenue']:>8,.0f} | "
              f"Fixed ${p['fixed_cost']:>6,.0f} | "
              f"Var ${p['variable_cost']:>8,.0f} | "
              f"Net ${p['net_profit']:>+9,.0f}")

    # Greedy closure iterations
    iteration = 0
    while True:
        iteration += 1

        # Rank open depots by net profit (worst first)
        ranked = sorted(current_pnl.items(), key=lambda x: x[1]["net_profit"])
        worst_key, worst_pnl = ranked[0]

        # Don't try closing the main warehouse
        candidates = [(k, p) for k, p in ranked if k != "wh"]
        if not candidates:
            break

        worst_key, worst_pnl = candidates[0]

        print(f"\n  Iteration {iteration}: evaluating closure of '{worst_key}' "
              f"(net ${worst_pnl['net_profit']:+,.0f}/week)")

        # Simulate closure: reassign sites to next-nearest open depot
        reassignments = {}  # site_id -> new_depot
        sites_by_depot = _get_sites_by_depot()
        affected_sites = sites_by_depot.get(worst_key, [])

        for site in affected_sites:
            dists = site_depot_dists[site["id"]]
            new_depot = None
            for dk, _ in dists:
                if dk in open_depots and dk != worst_key:
                    new_depot = dk
                    break
            if new_depot:
                reassignments[site["id"]] = new_depot
            # else: site cannot be reassigned (no other depot) — will be dropped

        # Apply reassignments temporarily
        old_depots = {}
        for site in sites:
            if site["id"] in reassignments:
                old_depots[site["id"]] = site["depot"]
                site["depot"] = reassignments[site["id"]]

        # Temporarily close the depot
        open_depots.discard(worst_key)
        new_profit, new_pnl = _compute_network_profit()

        print(f"    Network profit if closed: ${new_profit:,.0f}/week "
              f"(change: ${new_profit - current_profit:+,.0f})")
        print(f"    Sites reassigned: {len(reassignments)}, "
              f"sites orphaned: {len(affected_sites) - len(reassignments)}")

        if new_profit > current_profit:
            # Closure improves profit — keep it closed
            closed_depots[worst_key] = (
                f"Closing saves ${new_profit - current_profit:,.0f}/week; "
                f"{len(reassignments)} sites reassigned"
            )
            current_profit = new_profit
            current_pnl = new_pnl
            print(f"    → CLOSING {worst_key}")
        else:
            # Closure hurts profit — revert and stop
            open_depots.add(worst_key)
            for site in sites:
                if site["id"] in old_depots:
                    site["depot"] = old_depots[site["id"]]
            print(f"    → KEEPING {worst_key} (closure hurts profit)")
            break

    print(f"\n  Final depot selection:")
    print(f"    Open:   {sorted(open_depots)}")
    print(f"    Closed: {sorted(closed_depots.keys()) if closed_depots else 'none'}")
    print(f"    Estimated network profit: ${current_profit:,.0f}/week")

    return open_depots, closed_depots, current_pnl
