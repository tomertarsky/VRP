"""
Report generator for VRP optimization results.
Outputs: routes per truck/day, cost breakdown, dropped sites, weekly summary.
"""
from config import (
    VARIABLE_COST_PER_KM, DRIVER_WAGE_PER_HOUR, OT_MULTIPLIER,
    OT_WEEKLY_THRESHOLD_HOURS, TRUCK_FIXED_DAILY, TRUCK_FIXED_WEEKLY,
    TRUCK_FIXED_ANNUAL, REVENUE_PER_LB, FUEL_PER_KM, MAINTENANCE_PER_KM,
    MILEAGE_PER_KM, TRUCK_LEASE_MONTHLY, INSURANCE_ANNUAL,
)
from scheduler import DAY_NAMES


def print_daily_report(day_index, depot_results):
    """Print routes for a single day across all depots."""
    day_name = DAY_NAMES[day_index]
    print(f"\n{'='*80}")
    print(f"  {day_name.upper()}")
    print(f"{'='*80}")

    day_trucks = 0
    day_lbs = 0
    day_km = 0.0
    day_minutes = 0
    day_dropped = 0

    for depot_key, result in sorted(depot_results.items()):
        stats = result["stats"]
        if stats["trucks_used"] == 0 and not result["dropped"]:
            continue

        print(f"\n  Depot: {depot_key.upper()}")
        print(f"  Trucks used: {stats['trucks_used']} | "
              f"Lbs: {stats['total_lbs']:,.0f} | "
              f"Km: {stats['total_km']:,.1f} | "
              f"Time: {stats['total_minutes']} min | "
              f"Dropped: {len(result['dropped'])}")

        for route in result["routes"]:
            print(f"\n    Truck #{route['vehicle_id']+1}: "
                  f"{route['num_stops']} stops | "
                  f"{route['total_lbs']:,.0f} lbs | "
                  f"{route['total_km']:.1f} km | "
                  f"{route['total_minutes']} min")
            for stop in route["stops"]:
                v = stop["visit"]
                net = v["site"]["net_contribution_per_visit"]
                print(f"      -> {v['node_label']:<45} "
                      f"{stop['demand']:>5} lbs | "
                      f"{stop['service_time']:>3} min | "
                      f"net ${net:>6,.2f}")

        day_trucks += stats["trucks_used"]
        day_lbs += stats["total_lbs"]
        day_km += stats["total_km"]
        day_minutes += stats["total_minutes"]
        day_dropped += len(result["dropped"])

    print(f"\n  DAY TOTAL: {day_trucks} trucks | "
          f"{day_lbs:,.0f} lbs | "
          f"{day_km:,.1f} km | "
          f"{day_minutes} min driving | "
          f"{day_dropped} dropped visits")

    return {
        "trucks": day_trucks,
        "lbs": day_lbs,
        "km": day_km,
        "minutes": day_minutes,
        "dropped": day_dropped,
    }


def print_weekly_summary(weekly_results, all_dropped_visits):
    """Print aggregated weekly stats and cost breakdown."""
    print(f"\n{'='*80}")
    print(f"  WEEKLY SUMMARY")
    print(f"{'='*80}")

    total_lbs = 0
    total_km = 0.0
    total_hours = 0.0
    trucks_per_day = []

    # Track per-depot max trucks across the week (= fleet size needed)
    depot_max_trucks = {}

    for day_idx in range(7):
        day_data = weekly_results.get(day_idx, {})
        day_trucks = sum(r["stats"]["trucks_used"] for r in day_data.values())
        day_lbs = sum(r["stats"]["total_lbs"] for r in day_data.values())
        day_km = sum(r["stats"]["total_km"] for r in day_data.values())
        day_min = sum(r["stats"]["total_minutes"] for r in day_data.values())

        # Track per-depot peak usage
        for depot_key, result in day_data.items():
            prev = depot_max_trucks.get(depot_key, 0)
            depot_max_trucks[depot_key] = max(prev, result["stats"]["trucks_used"])

        trucks_per_day.append(day_trucks)
        total_lbs += day_lbs
        total_km += day_km
        total_hours += day_min / 60.0

        print(f"  {DAY_NAMES[day_idx]:<12} {day_trucks:>3} trucks | "
              f"{day_lbs:>10,.0f} lbs | "
              f"{day_km:>8,.1f} km | "
              f"{day_min/60:>6.1f} hrs")

    # Fleet size = sum of per-depot max trucks (each depot's trucks are independent)
    total_fleet_size = sum(depot_max_trucks.values())

    print(f"\n  {'TOTAL':<12} {total_fleet_size:>3} fleet trucks | "
          f"{total_lbs:>10,.0f} lbs | "
          f"{total_km:>8,.1f} km | "
          f"{total_hours:>6.1f} hrs")
    print(f"  (Fleet = sum of per-depot peak trucks; "
          f"each truck dispatched even once incurs full annual cost)")

    # ── Cost Breakdown ──────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  WEEKLY COST BREAKDOWN")
    print(f"{'='*80}")

    # Driver cost (regular + OT)
    # Per-truck OT calculation: assume hours spread evenly across fleet
    avg_hours_per_truck = total_hours / total_fleet_size if total_fleet_size > 0 else 0
    per_truck_ot = max(0, avg_hours_per_truck - OT_WEEKLY_THRESHOLD_HOURS)
    total_ot_hours_refined = per_truck_ot * total_fleet_size
    driver_regular_refined = (total_hours - total_ot_hours_refined) * DRIVER_WAGE_PER_HOUR
    driver_ot_refined = total_ot_hours_refined * DRIVER_WAGE_PER_HOUR * OT_MULTIPLIER
    driver_total_refined = driver_regular_refined + driver_ot_refined

    # Vehicle costs
    fuel_cost = total_km * FUEL_PER_KM
    maintenance_cost = total_km * MAINTENANCE_PER_KM
    mileage_cost = total_km * MILEAGE_PER_KM
    variable_vehicle_cost = total_km * VARIABLE_COST_PER_KM

    # Fixed costs — each truck dispatched even once incurs full annual cost
    fixed_truck_weekly = TRUCK_FIXED_WEEKLY * total_fleet_size
    lease_weekly = (TRUCK_LEASE_MONTHLY * 12 / 52) * total_fleet_size
    insurance_weekly = (INSURANCE_ANNUAL / 52) * total_fleet_size

    total_weekly_cost = driver_total_refined + variable_vehicle_cost + fixed_truck_weekly

    # Revenue
    total_revenue = total_lbs * REVENUE_PER_LB
    net_contribution = total_revenue - total_weekly_cost

    print(f"\n  Driver Cost (regular):    ${driver_regular_refined:>12,.2f}  ({total_hours - total_ot_hours_refined:.1f} hrs @ ${DRIVER_WAGE_PER_HOUR}/hr)")
    print(f"  Driver Cost (OT):         ${driver_ot_refined:>12,.2f}  ({total_ot_hours_refined:.1f} hrs @ ${DRIVER_WAGE_PER_HOUR * OT_MULTIPLIER}/hr)")
    print(f"  Driver Total:             ${driver_total_refined:>12,.2f}")
    print(f"")
    print(f"  Fuel ({FUEL_PER_KM}/km):           ${fuel_cost:>12,.2f}")
    print(f"  Maintenance ({MAINTENANCE_PER_KM}/km):     ${maintenance_cost:>12,.2f}")
    print(f"  Mileage ({MILEAGE_PER_KM}/km):         ${mileage_cost:>12,.2f}")
    print(f"  Vehicle Variable Total:   ${variable_vehicle_cost:>12,.2f}")
    print(f"")
    print(f"  Fixed Truck Cost (weekly): ${fixed_truck_weekly:>11,.2f}  ({total_fleet_size} trucks in fleet)")
    print(f"    Lease component:        ${lease_weekly:>12,.2f}")
    print(f"    Insurance component:    ${insurance_weekly:>12,.2f}")
    print(f"")
    print(f"  ──────────────────────────────────────")
    print(f"  TOTAL WEEKLY COST:        ${total_weekly_cost:>12,.2f}")
    print(f"  TOTAL WEEKLY REVENUE:     ${total_revenue:>12,.2f}")
    print(f"  NET WEEKLY CONTRIBUTION:  ${net_contribution:>12,.2f}")
    print(f"")
    print(f"  Cost per pound:           ${total_weekly_cost/total_lbs if total_lbs else 0:>12,.4f}")
    print(f"  Revenue per pound:        ${REVENUE_PER_LB:>12,.2f}")
    print(f"  Net per pound:            ${net_contribution/total_lbs if total_lbs else 0:>12,.4f}")
    print(f"")
    print(f"  ANNUALIZED:")
    print(f"    Total cost:             ${total_weekly_cost * 52:>12,.0f}")
    print(f"    Total revenue:          ${total_revenue * 52:>12,.0f}")
    print(f"    Net contribution:       ${net_contribution * 52:>12,.0f}")
    print(f"    Total lbs collected:    {total_lbs * 52:>12,.0f}")

    # ── Dropped Sites ───────────────────────────────────────
    if all_dropped_visits:
        unique_dropped = {}
        for v in all_dropped_visits:
            addr = v["site"]["address"]
            if addr not in unique_dropped:
                unique_dropped[addr] = v["site"]

        print(f"\n{'='*80}")
        print(f"  DROPPED SITES ({len(unique_dropped)} unique)")
        print(f"{'='*80}")
        sorted_dropped = sorted(unique_dropped.values(),
                                key=lambda s: s["net_contribution_per_visit"])
        for s in sorted_dropped:
            print(f"  {s['address'][:55]:<57} "
                  f"Net/visit: ${s['net_contribution_per_visit']:>8,.2f} | "
                  f"Lbs/yr: {s['annual_lbs']:>10,.0f} | "
                  f"{s['freq_label']}")

    # ── Pounds per truck per week ───────────────────────────
    print(f"\n{'='*80}")
    print(f"  TRUCKS UTILIZATION")
    print(f"{'='*80}")
    print(f"  Fleet size (trucks needed):{total_fleet_size}")
    print(f"  Avg trucks per day:       {sum(trucks_per_day)/7:.1f}")
    print(f"  Avg lbs per truck/day:    {total_lbs / sum(trucks_per_day) if sum(trucks_per_day) else 0:,.0f}")
    print(f"  Avg km per truck/day:     {total_km / sum(trucks_per_day) if sum(trucks_per_day) else 0:,.1f}")

    return {
        "total_fleet_size": total_fleet_size,
        "total_lbs_weekly": total_lbs,
        "total_km_weekly": total_km,
        "total_hours_weekly": total_hours,
        "total_weekly_cost": total_weekly_cost,
        "total_weekly_revenue": total_revenue,
        "net_weekly_contribution": net_contribution,
        "cost_per_lb": total_weekly_cost / total_lbs if total_lbs else 0,
        "dropped_count": len(all_dropped_visits),
    }


def print_depot_pnl(weekly_results, open_depots, closed_depots, depots_config):
    """
    Post-solve per-depot P&L report.
    Computes actual revenue/cost from solved routes (not estimates).
    """
    print(f"\n{'='*80}")
    print(f"  DEPOT PROFITABILITY REPORT (Post-Solve)")
    print(f"{'='*80}")

    depot_pnl = {}
    total_network_profit = 0

    for depot_key in sorted(open_depots):
        depot_lbs = 0
        depot_km = 0.0
        depot_minutes = 0
        depot_trucks_max = 0

        for day_idx, day_data in weekly_results.items():
            result = day_data.get(depot_key)
            if not result:
                continue
            s = result["stats"]
            depot_lbs += s["total_lbs"]
            depot_km += s["total_km"]
            depot_minutes += s["total_minutes"]
            depot_trucks_max = max(depot_trucks_max, s["trucks_used"])

        depot_hours = depot_minutes / 60.0
        # Fleet = max trucks used on any day; if dispatched even once, full annual cost
        fleet = depot_trucks_max

        # Revenue
        revenue = depot_lbs * REVENUE_PER_LB

        # Variable costs
        fuel_cost = depot_km * FUEL_PER_KM
        maint_cost = depot_km * MAINTENANCE_PER_KM
        mileage_cost = depot_km * MILEAGE_PER_KM
        variable_vehicle = fuel_cost + maint_cost + mileage_cost
        driver_cost = depot_hours * DRIVER_WAGE_PER_HOUR

        # Fixed costs — full weekly cost per truck in fleet
        fixed_cost = TRUCK_FIXED_WEEKLY * fleet

        total_cost = driver_cost + variable_vehicle + fixed_cost
        net_profit = revenue - total_cost

        status = "KEEP"
        if net_profit < 0:
            status = "MARGINAL — consider closing"

        depot_pnl[depot_key] = {
            "status": status,
            "lbs": depot_lbs,
            "km": depot_km,
            "hours": depot_hours,
            "trucks": fleet,
            "revenue": revenue,
            "driver_cost": driver_cost,
            "variable_vehicle": variable_vehicle,
            "fixed_cost": fixed_cost,
            "total_cost": total_cost,
            "net_profit": net_profit,
        }
        total_network_profit += net_profit

        print(f"\n  {depot_key.upper()} ({depots_config[depot_key]['name']})")
        print(f"    Lbs: {depot_lbs:>10,.0f} | Km: {depot_km:>8,.1f} | "
              f"Hours: {depot_hours:>6.1f} | Fleet: {fleet} trucks")
        print(f"    Revenue:       ${revenue:>10,.2f}")
        print(f"    Driver cost:   ${driver_cost:>10,.2f}")
        print(f"    Vehicle var:   ${variable_vehicle:>10,.2f}")
        print(f"    Fixed cost:    ${fixed_cost:>10,.2f}")
        print(f"    TOTAL COST:    ${total_cost:>10,.2f}")
        print(f"    NET PROFIT:    ${net_profit:>+10,.2f}  [{status}]")

    # Closed depots
    if closed_depots:
        print(f"\n  CLOSED DEPOTS:")
        for dk, reason in sorted(closed_depots.items()):
            print(f"    {dk.upper()}: {reason}")

    # Network summary
    print(f"\n  {'─'*60}")
    print(f"  NETWORK TOTAL NET PROFIT:  ${total_network_profit:>+12,.2f}/week")
    print(f"  ANNUALIZED:                ${total_network_profit * 52:>+12,.0f}/year")
    print(f"  Open depots: {len(open_depots)} | Closed: {len(closed_depots)}")

    return depot_pnl
