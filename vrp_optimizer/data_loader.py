"""
Loads site data from the Route_Mapping.xlsx spreadsheet (Site_Table sheet)
and computes derived fields.
"""
import openpyxl
from config import (
    EXCEL_PATH, FREQUENCY_MAP,
    SERVICE_MINUTES_PER_BIN,
)


def load_sites(path=None):
    """
    Parse the Excel file (Site_Table sheet) and return a list of site dicts.

    Column layout (0-indexed from openpyxl values_only tuple):
      idx 1  = Site_ID (int)
      idx 2  = Address (str)
      idx 3  = FrequencyCode (D1-D5)
      idx 4  = Bins (int)
      idx 5  = Annual Lbs (float)
      idx 6  = RentAnnual (float)
      idx 7  = WasteAnnual (float)
      idx 8  = Annual_Visits (pre-calculated)
      idx 9  = Lbs/Visit (pre-calculated)
      idx 10 = RevenuePerVisit (pre-calculated)
      idx 11 = ServiceMinutes (ANNUAL total)
      idx 12 = AnnualSiteValue (pre-calculated)

    Depot assignment is deferred to after geocoding (set to None here).
    """
    path = path or EXCEL_PATH
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Site_Table"]

    sites = []
    seen_ids = set()

    for row in ws.iter_rows(min_row=3, values_only=True):
        site_id = row[1]
        address = row[2]

        # Skip rows with no Site_ID or no address
        if site_id is None or address is None or str(address).strip() == "":
            continue

        site_id = int(site_id)

        # Skip duplicate Site_ID (the stub row at the end with no data)
        annual_lbs = row[5]
        if site_id in seen_ids:
            if annual_lbs is None or annual_lbs == 0:
                continue  # skip the stub duplicate
        seen_ids.add(site_id)

        freq_code = str(row[3] or "D1").strip()
        freq_info = FREQUENCY_MAP.get(freq_code, FREQUENCY_MAP["D1"])

        bins = int(row[4] or 1)
        annual_lbs = float(annual_lbs or 0)
        rent_annual = float(row[6] or 0)
        waste_annual = float(row[7] or 0)

        # Use pre-calculated annual_visits from spreadsheet if available,
        # otherwise fall back to frequency map
        annual_visits_raw = row[8]
        if annual_visits_raw and float(annual_visits_raw) > 0:
            annual_visits = int(float(annual_visits_raw))
        else:
            annual_visits = freq_info["annual_visits"]

        weekly_visits = freq_info["weekly_visits"]

        # Use pre-calculated values from spreadsheet
        lbs_per_visit = float(row[9] or 0) if row[9] else (
            annual_lbs / annual_visits if annual_visits > 0 else 0
        )
        revenue_per_visit = float(row[10] or 0) if row[10] else (
            lbs_per_visit * 0.30
        )

        # Per-visit service time = bins × 15 minutes
        service_time_minutes = bins * SERVICE_MINUTES_PER_BIN

        # AnnualSiteValue from spreadsheet
        annual_site_value = float(row[12] or 0) if row[12] else 0

        # Net contribution per visit:
        # revenue_per_visit - (rent + waste) / annual_visits
        structural_cost_per_visit = (
            (rent_annual + waste_annual) / annual_visits if annual_visits > 0 else 0
        )
        net_contribution_per_visit = revenue_per_visit - structural_cost_per_visit

        site = {
            "id": site_id,
            "address": str(address).strip(),
            "frequency": freq_code,
            "freq_label": freq_info["label"],
            "bins": bins,
            "annual_lbs": annual_lbs,
            "rent_annual": rent_annual,
            "waste_annual": waste_annual,
            "annual_visits": annual_visits,
            "weekly_visits": weekly_visits,
            "lbs_per_visit": lbs_per_visit,
            "revenue_per_visit": revenue_per_visit,
            "service_time_minutes": service_time_minutes,
            "annual_site_value": annual_site_value,
            "structural_cost_per_visit": structural_cost_per_visit,
            "net_contribution_per_visit": net_contribution_per_visit,
            "demand_lbs": lbs_per_visit,  # per-visit demand
            "depot": None,  # assigned after geocoding via nearest-depot
        }
        sites.append(site)

    wb.close()

    print(f"Loaded {len(sites)} sites from {path}")

    # Print frequency distribution
    from collections import Counter
    freq_counts = Counter(s["frequency"] for s in sites)
    print(f"  Frequency distribution: {dict(freq_counts)}")

    return sites


if __name__ == "__main__":
    sites = load_sites()
    print(f"\nSample site: {sites[0]}")
