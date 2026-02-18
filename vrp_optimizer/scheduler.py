"""
Weekly scheduler: assigns sites to specific days based on their service frequency.
Handles 2x daily duplication, weekly/monthly rotation, and holiday constraints.
"""
from config import FREQUENCY_DAY_PATTERNS


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def assign_weekly_day(site_id, num_weekdays=5):
    """Deterministically assign a weekly/monthly site to a weekday based on its ID."""
    return site_id % num_weekdays


def get_daily_site_list(sites, day_of_week, week_number=0, is_holiday=False):
    """
    For a given day (0=Mon..6=Sun) and week number, return list of site-visit dicts.

    For '2x Daily' sites, two entries are returned (each with half the demand).
    For holiday days, only sites with positive net contribution are included.

    Returns list of visit dicts:
      - site: reference to original site dict
      - visit_demand_lbs: demand for this specific visit
      - visit_number: 1 or 2 (for 2x daily)
    """
    visits = []

    for site in sites:
        freq = site["frequency"]
        pattern = FREQUENCY_DAY_PATTERNS.get(freq)

        # Determine if site should be visited today
        should_visit = False

        if pattern is not None:
            # Fixed pattern (daily, 2x daily, 3x week, 2x week)
            should_visit = day_of_week in pattern
        elif freq == "D5":
            # Weekly — assign to a specific day deterministically
            assigned_day = assign_weekly_day(site["id"], num_weekdays=7)
            should_visit = day_of_week == assigned_day
        else:
            # Unknown frequency — treat as weekly
            assigned_day = assign_weekly_day(site["id"], num_weekdays=7)
            should_visit = day_of_week == assigned_day

        if not should_visit:
            continue

        # Holiday filter: only serve profitable sites
        if is_holiday and site["net_contribution_per_visit"] <= 0:
            continue

        if freq == "D2":
            # Create two visit nodes, each with half the demand
            half_demand = site["demand_lbs"] / 2.0
            visits.append({
                "site": site,
                "visit_demand_lbs": half_demand,
                "visit_number": 1,
                "node_label": f"{site['address'][:40]} (visit 1)",
            })
            visits.append({
                "site": site,
                "visit_demand_lbs": half_demand,
                "visit_number": 2,
                "node_label": f"{site['address'][:40]} (visit 2)",
            })
        else:
            visits.append({
                "site": site,
                "visit_demand_lbs": site["demand_lbs"],
                "visit_number": 1,
                "node_label": f"{site['address'][:40]}",
            })

    return visits


def get_weekly_schedule(sites, week_number=0, holidays=None):
    """
    Build a full 7-day schedule.
    Returns dict: {day_index: [visit_dicts]}
    """
    holidays = holidays or []
    schedule = {}
    for day in range(7):
        is_holiday = day in holidays
        day_visits = get_daily_site_list(sites, day, week_number, is_holiday)
        schedule[day] = day_visits
        profitable = sum(1 for v in day_visits if v["site"]["net_contribution_per_visit"] > 0)
        print(f"  {DAY_NAMES[day]}: {len(day_visits)} visits"
              f" ({profitable} profitable)")
    return schedule


def get_depot_daily_visits(daily_visits, depot_key):
    """Filter daily visits to only those assigned to a specific depot."""
    return [v for v in daily_visits if v["site"]["depot"] == depot_key]
