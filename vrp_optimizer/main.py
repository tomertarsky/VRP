#!/usr/bin/env python3
"""
VRP Optimizer — Main Entry Point
Donation Pickup Network Route Optimization using Google OR-Tools.

Usage:
    python3 main.py                     # Full week optimization
    python3 main.py --day 0             # Monday only
    python3 main.py --depot wh          # WH depot only
    python3 main.py --solver-time 120   # 120 second solver limit
    python3 main.py --skip-geocode      # Skip geocoding (use cache only)
"""
import sys
import os
import argparse
import time

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math
from config import DEPOTS, SOLVER_TIME_LIMIT_SECONDS
from data_loader import load_sites
from geocoder import geocode_sites, geocode_depots, get_coordinates
from scheduler import get_weekly_schedule, get_depot_daily_visits, DAY_NAMES
from solver import solve_daily_vrp
from report import print_daily_report, print_weekly_summary, print_depot_pnl
from depot_selector import select_depots


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def assign_depots(sites, depots):
    """
    Assign each site to its nearest depot based on Haversine distance.
    Sets site["depot"] for each site.
    Depots must already have lat/lon geocoded.
    """
    depot_list = [
        (key, info) for key, info in depots.items()
        if info.get("lat") is not None and info.get("lon") is not None
    ]

    for site in sites:
        if site.get("lat") is None or site.get("lon") is None:
            site["depot"] = "wh"  # fallback
            continue

        best_depot = "wh"
        best_dist = float("inf")
        for depot_key, depot_info in depot_list:
            d = _haversine_km(site["lat"], site["lon"],
                              depot_info["lat"], depot_info["lon"])
            if d < best_dist:
                best_dist = d
                best_depot = depot_key

        site["depot"] = best_depot

    # Print depot assignment distribution
    from collections import Counter
    depot_counts = Counter(s["depot"] for s in sites)
    print("  Depot assignment (nearest):")
    for depot_key, count in sorted(depot_counts.items()):
        print(f"    {depot_key}: {count} sites")


def main():
    parser = argparse.ArgumentParser(description="VRP Route Optimizer")
    parser.add_argument("--day", type=int, default=None,
                        help="Optimize single day only (0=Mon..6=Sun)")
    parser.add_argument("--depot", type=str, default=None,
                        help="Optimize single depot only (e.g., 'wh', 'barrie')")
    parser.add_argument("--week", type=int, default=0,
                        help="Week number for monthly rotation (default: 0)")
    parser.add_argument("--solver-time", type=int, default=SOLVER_TIME_LIMIT_SECONDS,
                        help=f"Solver time limit per sub-problem in seconds (default: {SOLVER_TIME_LIMIT_SECONDS})")
    parser.add_argument("--skip-geocode", action="store_true",
                        help="Skip geocoding, use cache only")
    parser.add_argument("--holidays", type=int, nargs="*", default=[],
                        help="Day indices that are holidays (0=Mon..6=Sun)")
    args = parser.parse_args()

    # Override solver time if specified
    if args.solver_time != SOLVER_TIME_LIMIT_SECONDS:
        import config
        config.SOLVER_TIME_LIMIT_SECONDS = args.solver_time

    print("=" * 80)
    print("  VRP ROUTE OPTIMIZER — Google OR-Tools")
    print("  Donation Pickup Network Optimization")
    print("=" * 80)

    # ── Step 1: Load site data ──────────────────────────────
    print("\n[1/8] Loading site data...")
    t0 = time.time()
    sites = load_sites()
    print(f"     Done in {time.time()-t0:.1f}s")

    # ── Step 2: Geocode depots ────────────────────────────
    print("\n[2/8] Geocoding depot addresses (Google Maps API)...")
    t0 = time.time()
    geocode_depots()
    print(f"     Done in {time.time()-t0:.1f}s")

    # ── Step 3: Geocode site addresses ────────────────────
    print("\n[3/8] Geocoding site addresses (Google Maps API)...")
    t0 = time.time()
    if args.skip_geocode:
        from geocoder import load_cache
        geocode_cache = load_cache()
        print(f"     Using cached geocodes ({len(geocode_cache)} entries)")
    else:
        geocode_cache = geocode_sites(sites)
    sites = get_coordinates(sites, geocode_cache)
    print(f"     {len(sites)} sites with coordinates, done in {time.time()-t0:.1f}s")

    # ── Step 3b: Assign sites to nearest depot ────────────
    print("\n[3b/8] Assigning sites to nearest depot...")
    assign_depots(sites, DEPOTS)

    # ── Step 4: Depot selection (profit-maximizing) ──────
    print("\n[4/8] Running depot profitability analysis...")
    t0 = time.time()
    open_depots, closed_depots, depot_pnl_estimates = select_depots(sites, DEPOTS)
    print(f"     Done in {time.time()-t0:.1f}s")

    if closed_depots:
        print("\n  Depot closures:")
        for dk, reason in closed_depots.items():
            print(f"    CLOSED: {dk} — {reason}")

    # ── Step 5: Build weekly schedule ───────────────────────
    print("\n[5/8] Building weekly schedule...")
    t0 = time.time()
    schedule = get_weekly_schedule(sites, week_number=args.week, holidays=args.holidays)
    print(f"     Done in {time.time()-t0:.1f}s")

    # ── Step 6: Solve VRP per day per depot ─────────────────
    print("\n[6/8] Solving VRP (this may take several minutes)...")
    t0 = time.time()

    days_to_solve = [args.day] if args.day is not None else range(7)
    # Only solve for open depots (unless user specified a specific depot)
    if args.depot:
        depots_to_solve = [args.depot]
    else:
        depots_to_solve = [d for d in DEPOTS.keys() if d in open_depots]

    # Validate
    for d in depots_to_solve:
        if d not in DEPOTS:
            print(f"ERROR: Unknown depot '{d}'. Available: {list(DEPOTS.keys())}")
            sys.exit(1)

    weekly_results = {}  # {day_idx: {depot_key: result}}
    all_dropped = []

    for day_idx in days_to_solve:
        day_visits = schedule[day_idx]
        print(f"\n  Solving {DAY_NAMES[day_idx]} ({len(day_visits)} total visits)...")

        day_results = {}
        for depot_key in depots_to_solve:
            depot_visits = get_depot_daily_visits(day_visits, depot_key)
            if not depot_visits:
                day_results[depot_key] = {
                    "routes": [], "dropped": [],
                    "stats": {"trucks_used": 0, "total_lbs": 0,
                              "total_km": 0, "total_minutes": 0,
                              "total_cost_cents": 0},
                }
                continue

            print(f"    Depot {depot_key}: {len(depot_visits)} visits, "
                  f"{DEPOTS[depot_key]['max_trucks']} trucks available...")

            result = solve_daily_vrp(depot_key, depot_visits)
            day_results[depot_key] = result
            all_dropped.extend(result["dropped"])

            s = result["stats"]
            print(f"      → {s['trucks_used']} trucks | "
                  f"{s['total_lbs']:,.0f} lbs | "
                  f"{s['total_km']:.1f} km | "
                  f"{len(result['dropped'])} dropped")

        weekly_results[day_idx] = day_results

    print(f"\n     Solver done in {time.time()-t0:.1f}s")

    # ── Step 7: Report ──────────────────────────────────────
    print("\n[7/8] Generating report...")

    for day_idx in days_to_solve:
        print_daily_report(day_idx, weekly_results[day_idx])

    summary = print_weekly_summary(weekly_results, all_dropped)

    # ── Step 8: Depot P&L Report ─────────────────────────
    print("\n[8/8] Depot profitability report...")
    depot_pnl_actual = print_depot_pnl(
        weekly_results, open_depots, closed_depots, DEPOTS
    )

    print(f"\n{'='*80}")
    print(f"  OPTIMIZATION COMPLETE (Profit-Maximizing Model v2)")
    print(f"{'='*80}")

    return summary


if __name__ == "__main__":
    main()
