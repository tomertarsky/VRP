"""
Configuration for VRP Optimizer.
All costs, depot definitions, fleet parameters, and solver settings.
"""

# ─────────────────────────────────────────────
# GOOGLE MAPS API
# ─────────────────────────────────────────────
GOOGLE_MAPS_API_KEY = "AIzaSyBeg4aywIlP14E-jX1LMA5a8fLShF8lNQg"

# ─────────────────────────────────────────────
# DEPOT DEFINITIONS
# Addresses provided — lat/lon will be geocoded via Google Maps
# ─────────────────────────────────────────────
DEPOTS = {
    "wh": {
        "name": "Main Warehouse (GTA)",
        "address": "37 Alexdon Rd, North York, ON, Canada",
        "lat": None,  # geocoded at runtime
        "lon": None,
        "max_trucks": 20,
    },
    "barrie": {
        "name": "Barrie Depot",
        "address": "320 Bayfield St, Barrie, ON L4M 3C1, Canada",
        "lat": None,
        "lon": None,
        "max_trucks": 1,
    },
    "london": {
        "name": "London Depot",
        "address": "1345 Huron St #1a, London, ON N5V 2E3, Canada",
        "lat": None,
        "lon": None,
        "max_trucks": 1,
    },
    "newmarket": {
        "name": "Newmarket Depot",
        "address": "570 Steven Ct, Newmarket, ON, Canada",
        "lat": None,
        "lon": None,
        "max_trucks": 1,
    },
    "ottawa": {
        "name": "Ottawa Depot",
        "address": "995 Moodie Dr, Ottawa, ON, Canada",
        "lat": None,
        "lon": None,
        "max_trucks": 2,
    },
    "hamilton": {
        "name": "Hamilton Depot",
        "address": "1400 Upper James St, Hamilton, ON L9B 1K3, Canada",
        "lat": None,
        "lon": None,
        "max_trucks": 1,
    },
    "kitchener": {
        "name": "Kitchener Depot",
        "address": "1144 Courtland Ave E, Kitchener, ON N2C 1N2, Canada",
        "lat": None,
        "lon": None,
        "max_trucks": 1,
    },
}

# ─────────────────────────────────────────────
# FLEET / VEHICLE PARAMETERS
# ─────────────────────────────────────────────
MAX_LEGAL_PAYLOAD_LBS = 6000
TARGET_DAILY_PAYLOAD_LBS = 4000  # practical daily max

# ─────────────────────────────────────────────
# COST PARAMETERS
# ─────────────────────────────────────────────
DRIVER_WAGE_PER_HOUR = 24.0
OT_MULTIPLIER = 1.5
OT_WEEKLY_THRESHOLD_HOURS = 44

TRUCK_LEASE_MONTHLY = 2077.0
INSURANCE_ANNUAL = 8166.0
FUEL_PER_KM = 0.25
MAINTENANCE_PER_KM = 0.05
MILEAGE_PER_KM = 0.09
VARIABLE_COST_PER_KM = FUEL_PER_KM + MAINTENANCE_PER_KM + MILEAGE_PER_KM  # $0.39/km

# Annualized fixed cost per truck
TRUCK_FIXED_ANNUAL = (TRUCK_LEASE_MONTHLY * 12) + INSURANCE_ANNUAL  # $33,090
TRUCK_FIXED_DAILY = TRUCK_FIXED_ANNUAL / 365  # ~$90.66/day
TRUCK_FIXED_WEEKLY = TRUCK_FIXED_ANNUAL / 52   # ~$636.35/week
# Solver fixed cost per vehicle: daily heuristic (in cents) to discourage extra
# trucks per day.  Real fleet-level cost is handled by depot_selector & report
# using TRUCK_FIXED_WEEKLY.
TRUCK_FIXED_COST_SOLVER = int(TRUCK_FIXED_DAILY * 100)   # 9,066 cents

REVENUE_PER_LB = 0.30  # $/lb

# ─────────────────────────────────────────────
# DRIVER / TIME CONSTRAINTS
# ─────────────────────────────────────────────
MAX_SHIFT_HOURS = 12
MAX_SHIFT_MINUTES = MAX_SHIFT_HOURS * 60  # 720 minutes
BREAK_INTERVAL_MINUTES = 240  # 30 min break every 4 hours
BREAK_DURATION_MINUTES = 30
TOTAL_BREAK_MINUTES = 60  # 1 hour total break in 12-hour shift
EFFECTIVE_DRIVING_MINUTES = MAX_SHIFT_MINUTES - TOTAL_BREAK_MINUTES  # 660 minutes

# ─────────────────────────────────────────────
# SERVICE TIME
# ─────────────────────────────────────────────
SERVICE_MINUTES_PER_BIN = 15

# ─────────────────────────────────────────────
# FREQUENCY MAPPING
# Maps frequency codes to annual visits and weekly visits
# ─────────────────────────────────────────────
FREQUENCY_MAP = {
    "D1": {"annual_visits": 364, "weekly_visits": 7,  "label": "Daily"},
    "D2": {"annual_visits": 728, "weekly_visits": 14, "label": "2x Daily"},
    "D3": {"annual_visits": 104, "weekly_visits": 2,  "label": "2x Week"},
    "D4": {"annual_visits": 156, "weekly_visits": 3,  "label": "3x Week"},
    "D5": {"annual_visits": 52,  "weekly_visits": 1,  "label": "Weekly"},
}

# ─────────────────────────────────────────────
# DAY-OF-WEEK VISIT PATTERNS
# For each frequency, which days of the week (0=Mon ... 6=Sun)
# ─────────────────────────────────────────────
FREQUENCY_DAY_PATTERNS = {
    "D1": [0, 1, 2, 3, 4, 5, 6],          # Daily — every day
    "D2": [0, 1, 2, 3, 4, 5, 6],          # 2x Daily — 2 visits each day
    "D3": [1, 3],                           # 2x Week — Tue, Thu
    "D4": [0, 2, 4],                        # 3x Week — Mon, Wed, Fri
    "D5": None,                             # Weekly — assigned by scheduler
}

# ─────────────────────────────────────────────
# DISTANCE / SPEED
# ─────────────────────────────────────────────
AVERAGE_SPEED_KMH = 40  # urban average including stops/traffic

# ─────────────────────────────────────────────
# SOLVER PARAMETERS
# ─────────────────────────────────────────────
SOLVER_TIME_LIMIT_SECONDS = 60      # per daily sub-problem
SOLVER_SOLUTION_LIMIT = 100

# ─────────────────────────────────────────────
# INPUT FILE
# ─────────────────────────────────────────────
EXCEL_PATH = "/Users/tomertarsky/Downloads/Route_Mapping.xlsx"
GEOCODE_CACHE_PATH = "/Users/tomertarsky/vrp_optimizer/geocode_cache.json"
DISTANCE_CACHE_PATH = "/Users/tomertarsky/vrp_optimizer/distance_cache.json"
