# VRP Optimizer — Comprehensive Guide

A donation pickup route optimization system for a network of depots across Ontario. This tool determines which depots to keep open, which sites to serve, and how to build efficient daily routes for a fleet of collection trucks — all driven by a profit-maximizing objective.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Prerequisites & Setup](#2-prerequisites--setup)
3. [Google Maps API Setup](#3-google-maps-api-setup)
4. [Input Data Format](#4-input-data-format)
5. [Configuration Reference](#5-configuration-reference)
6. [How to Run](#6-how-to-run)
7. [Architecture & Data Flow](#7-architecture--data-flow)
8. [How Google OR-Tools Works](#8-how-google-or-tools-works)
9. [Key Algorithms](#9-key-algorithms)
10. [Output](#10-output)
11. [Cost Model](#11-cost-model)
12. [Caching](#12-caching)
13. [File Reference](#13-file-reference)

---

## 1. Project Overview

This system optimizes donation-pickup logistics for an organization that collects goods (measured in pounds) from ~300 sites across Ontario, Canada. The sites are served by trucks dispatched from up to 7 depots (a main warehouse in North York plus 6 regional depots in Barrie, London, Newmarket, Ottawa, Hamilton, and Kitchener).

### The Problem

Each site has a service frequency (daily, twice daily, 2×/week, 3×/week, or weekly), a number of bins to service, and associated revenue (based on pounds collected) and costs (rent, waste disposal). The system must decide:

- **Which depots to keep open** (each depot has fixed truck costs — closing an unprofitable depot and reassigning its sites can save money).
- **Which sites to serve** (some sites cost more to visit than the revenue they generate).
- **How to build daily truck routes** that respect payload limits, shift-time constraints, and fleet size while maximizing profit.

### Two-Phase Approach

1. **Phase 1 — Depot Selection**: A greedy closure algorithm evaluates whether closing each regional depot (and reassigning its sites to the next-nearest depot) improves total network profit. The main warehouse is never closed.

2. **Phase 2 — Route Optimization**: For each open depot on each day of the week, Google OR-Tools solves a Vehicle Routing Problem (VRP) that simultaneously optimizes route efficiency and decides which sites are worth visiting based on their profitability.

---

## 2. Prerequisites & Setup

### Python Version

- Python **3.10** or higher

### Required Packages

Install all dependencies with:

```bash
pip install ortools openpyxl geopy numpy googlemaps
```

| Package | Purpose |
|---------|---------|
| `ortools` | Google OR-Tools — the VRP solver engine |
| `openpyxl` | Read/write Excel files (input data and exported results) |
| `geopy` | Nominatim geocoding fallback (free, rate-limited) |
| `numpy` | Distance and cost matrix operations |
| `googlemaps` | Google Maps Geocoding and Distance Matrix API client |

### Optional but Recommended

- A **Google Maps API key** with Distance Matrix API and Geocoding API enabled (see next section). Without it, the system falls back to Haversine straight-line distances with a 1.3× road correction factor, which is less accurate.

---

## 3. Google Maps API Setup

The Google Maps API provides real driving distances and travel times (with traffic patterns), which dramatically improves route quality compared to straight-line estimates. Once fetched, results are cached to disk so API costs are essentially one-time.

### Step-by-Step

1. **Create a Google Cloud Project**
   - Go to [console.cloud.google.com](https://console.cloud.google.com/)
   - Click "Select a project" → "New Project"
   - Name it (e.g., "VRP Optimizer") and create it

2. **Enable Required APIs**
   - In the Cloud Console, go to **APIs & Services → Library**
   - Search for and enable:
     - **Distance Matrix API** (provides driving distance and travel time between pairs of locations)
     - **Geocoding API** (converts street addresses to latitude/longitude coordinates)

3. **Create an API Key**
   - Go to **APIs & Services → Credentials**
   - Click **"Create Credentials" → "API Key"**
   - Copy the generated key
   - (Recommended) Click "Restrict Key" and limit it to only the Distance Matrix API and Geocoding API

4. **Set Up Billing**
   - Go to **Billing** in the Cloud Console
   - Link a billing account to your project
   - Google provides $200/month free credit, which is more than enough for typical usage
   - **Billing is required** — the Distance Matrix API will return `REQUEST_DENIED` without it

5. **Add the Key to `config.py`**
   - Open `config.py` and set:
     ```python
     GOOGLE_MAPS_API_KEY = "your-api-key-here"
     ```

6. **Verify It Works**
   - Run a quick test:
     ```bash
     python3 -c "import googlemaps; g = googlemaps.Client(key='YOUR_KEY'); print(g.geocode('Toronto, ON'))"
     ```
   - If it returns location data, you're set

### Cost Expectations

- **Geocoding**: $5 per 1,000 requests. ~300 sites = ~$1.50 one-time (cached after first run).
- **Distance Matrix**: $5 per 1,000 elements. A 50-node daily sub-problem needs ~2,500 elements = ~$12.50. Across all days/depots, expect $50–150 for the first run. All results are cached, so subsequent runs are free.
- The $200/month free tier covers typical usage entirely.

### Without Google Maps

If you don't configure an API key (or the key is invalid), the system automatically falls back to **Haversine distances** (straight-line × 1.3 road correction factor) at 40 km/h average speed. This works but produces less accurate routes.

---

## 4. Input Data Format

The optimizer reads from an Excel file (default path configured in `config.py` as `EXCEL_PATH`).

### Expected File: `Route_Mapping.xlsx`

The file must contain a sheet named **`Site_Table`** with data starting at **row 3** (rows 1–2 are headers).

### Column Layout (0-indexed)

| Column Index | Field | Type | Description |
|:---:|---------|------|-------------|
| 1 | Site_ID | int | Unique site identifier |
| 2 | Address | str | Full street address (used for geocoding) |
| 3 | FrequencyCode | str | Service frequency: D1, D2, D3, D4, or D5 |
| 4 | Bins | int | Number of collection bins at the site |
| 5 | Annual Lbs | float | Total pounds collected per year |
| 6 | RentAnnual | float | Annual rent cost for bin placement ($) |
| 7 | WasteAnnual | float | Annual waste disposal cost ($) |
| 8 | Annual_Visits | int | Pre-calculated annual visit count |
| 9 | Lbs/Visit | float | Pre-calculated pounds per visit |
| 10 | RevenuePerVisit | float | Pre-calculated revenue per visit ($) |
| 11 | ServiceMinutes | float | Annual total service time (not used directly) |
| 12 | AnnualSiteValue | float | Pre-calculated annual site value ($) |

### Frequency Codes

| Code | Label | Weekly Visits | Annual Visits | Day Pattern |
|------|-------|:---:|:---:|-------------|
| D1 | Daily | 7 | 364 | Every day (Mon–Sun) |
| D2 | 2× Daily | 14 | 728 | Every day, 2 visits per day (each with half demand) |
| D3 | 2× Week | 2 | 104 | Tuesday and Thursday |
| D4 | 3× Week | 3 | 156 | Monday, Wednesday, Friday |
| D5 | Weekly | 1 | 52 | Assigned deterministically by `site_id % 7` |

---

## 5. Configuration Reference

All key constants live in `config.py`. Here is a complete reference:

### Google Maps API

| Constant | Default | Description |
|----------|---------|-------------|
| `GOOGLE_MAPS_API_KEY` | `"..."` | Your Google Maps API key |

### Depot Definitions

| Constant | Description |
|----------|-------------|
| `DEPOTS` | Dictionary of depot configs. Each entry has: `name`, `address`, `lat` (geocoded at runtime), `lon`, `max_trucks` |

**Defined depots:**

| Key | Name | Address | Max Trucks |
|-----|------|---------|:---:|
| `wh` | Main Warehouse (GTA) | 37 Alexdon Rd, North York, ON | 20 |
| `barrie` | Barrie Depot | 320 Bayfield St, Barrie, ON | 1 |
| `london` | London Depot | 1345 Huron St #1a, London, ON | 1 |
| `newmarket` | Newmarket Depot | 570 Steven Ct, Newmarket, ON | 1 |
| `ottawa` | Ottawa Depot | 995 Moodie Dr, Ottawa, ON | 2 |
| `hamilton` | Hamilton Depot | 1400 Upper James St, Hamilton, ON | 1 |
| `kitchener` | Kitchener Depot | 1144 Courtland Ave E, Kitchener, ON | 1 |

### Fleet / Vehicle Parameters

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_LEGAL_PAYLOAD_LBS` | 6,000 | Legal maximum payload per truck (lbs) |
| `TARGET_DAILY_PAYLOAD_LBS` | 4,000 | Practical daily payload limit used by solver (lbs) |

### Cost Parameters

| Constant | Default | Description |
|----------|---------|-------------|
| `DRIVER_WAGE_PER_HOUR` | $24.00 | Regular hourly driver wage |
| `OT_MULTIPLIER` | 1.5× | Overtime wage multiplier |
| `OT_WEEKLY_THRESHOLD_HOURS` | 44 | Hours per week before overtime kicks in |
| `TRUCK_LEASE_MONTHLY` | $2,077 | Monthly truck lease cost |
| `INSURANCE_ANNUAL` | $8,166 | Annual insurance per truck |
| `FUEL_PER_KM` | $0.25 | Fuel cost per kilometer |
| `MAINTENANCE_PER_KM` | $0.05 | Maintenance cost per kilometer |
| `MILEAGE_PER_KM` | $0.09 | Mileage/depreciation per kilometer |
| `VARIABLE_COST_PER_KM` | $0.39 | Total variable vehicle cost (fuel + maintenance + mileage) |
| `TRUCK_FIXED_ANNUAL` | $33,090 | Annualized fixed cost per truck (lease × 12 + insurance) |
| `TRUCK_FIXED_DAILY` | ~$90.66 | Daily fixed cost per truck (annual ÷ 365) |
| `TRUCK_FIXED_WEEKLY` | ~$636.35 | Weekly fixed cost per truck (annual ÷ 52) |
| `TRUCK_FIXED_COST_SOLVER` | 9,066 | Daily fixed cost in cents, used by solver to discourage extra trucks |
| `REVENUE_PER_LB` | $0.30 | Revenue earned per pound of donations collected |

### Driver / Time Constraints

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_SHIFT_HOURS` | 12 | Maximum driver shift length |
| `MAX_SHIFT_MINUTES` | 720 | Same, in minutes |
| `BREAK_INTERVAL_MINUTES` | 240 | Break required every 4 hours |
| `BREAK_DURATION_MINUTES` | 30 | Duration of each break |
| `TOTAL_BREAK_MINUTES` | 60 | Total break time in a 12-hour shift |
| `EFFECTIVE_DRIVING_MINUTES` | 660 | Usable driving/service time (720 − 60) |

### Service Time

| Constant | Default | Description |
|----------|---------|-------------|
| `SERVICE_MINUTES_PER_BIN` | 15 | Minutes required to service one bin at a stop |

### Distance / Speed

| Constant | Default | Description |
|----------|---------|-------------|
| `AVERAGE_SPEED_KMH` | 40 | Urban average speed including stops/traffic |

### Solver Parameters

| Constant | Default | Description |
|----------|---------|-------------|
| `SOLVER_TIME_LIMIT_SECONDS` | 60 | Max seconds the solver runs per daily sub-problem |
| `SOLVER_SOLUTION_LIMIT` | 100 | Maximum number of solutions to explore |

### File Paths

| Constant | Default | Description |
|----------|---------|-------------|
| `EXCEL_PATH` | `.../Route_Mapping.xlsx` | Path to input Excel file |
| `GEOCODE_CACHE_PATH` | `.../geocode_cache.json` | Geocoding results cache |
| `DISTANCE_CACHE_PATH` | `.../distance_cache.json` | Distance Matrix API results cache |

---

## 6. How to Run

### Basic Usage

```bash
# Full week optimization (all depots, all 7 days)
python3 main.py

# Monday only
python3 main.py --day 0

# Single depot
python3 main.py --depot wh

# Combine: Monday, main warehouse only
python3 main.py --day 0 --depot wh
```

### All CLI Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--day` | int | None (all days) | Optimize a single day only. 0=Monday, 1=Tuesday, ..., 6=Sunday |
| `--depot` | str | None (all open depots) | Optimize a single depot only. Use depot key: `wh`, `barrie`, `london`, `newmarket`, `ottawa`, `hamilton`, `kitchener` |
| `--solver-time` | int | 60 | Solver time limit per sub-problem in seconds. Increase for better solutions on large problems |
| `--skip-geocode` | flag | False | Skip live geocoding; use only cached results from `geocode_cache.json` |
| `--holidays` | int list | [] | Day indices that are holidays (0=Mon..6=Sun). Holiday days only serve profitable sites |
| `--week` | int | 0 | Week number for monthly rotation (currently unused but available for future scheduling logic) |

### Examples

```bash
# Give the solver 3 minutes per sub-problem for better solutions
python3 main.py --solver-time 180

# Skip geocoding (all addresses already cached from a prior run)
python3 main.py --skip-geocode

# Mark Tuesday and Thursday as holidays
python3 main.py --holidays 1 3

# Quick test: just Monday at the main warehouse, 30-second solver
python3 main.py --day 0 --depot wh --solver-time 30
```

### Typical Runtime

- **Geocoding** (first run): 1–5 minutes depending on how many addresses need to be geocoded.
- **Distance Matrix** (first run): 2–10 minutes depending on the number of nodes per sub-problem.
- **Solver**: 60 seconds × (number of days) × (number of open depots). A full week with 5 open depots at the default 60s limit takes ~35 minutes. Most sub-problems finish faster.
- **Subsequent runs** (with caches populated): Geocoding and distance lookups are instant; total runtime is dominated by the solver.

---

## 7. Architecture & Data Flow

### The 8-Step Pipeline

The optimizer runs as a sequential pipeline, printed as steps `[1/8]` through `[8/8]`:

```
[1/8] Load site data         → Parse Excel into site dicts
[2/8] Geocode depots          → Convert depot addresses to lat/lon
[3/8] Geocode sites           → Convert site addresses to lat/lon
[3b]  Assign sites to depots  → Each site → nearest depot (Haversine)
[4/8] Depot selection          → Greedy closure algorithm (Phase 1)
[5/8] Build weekly schedule    → Determine which sites to visit each day
[6/8] Solve VRP                → OR-Tools solver per day per depot (Phase 2)
[7/8] Generate report          → Console output with routes and cost breakdown
[8/8] Depot P&L report         → Post-solve profitability per depot
```

### Data Flow Diagram

```
Route_Mapping.xlsx
        │
        ▼
   data_loader.py ──→ [site dicts with address, freq, bins, lbs, costs]
        │
        ▼
   geocoder.py ──→ [site dicts + lat/lon coordinates]
        │               ▲
        │         geocode_cache.json
        ▼
   main.py: assign_depots() ──→ [site dicts + depot assignment]
        │
        ▼
   depot_selector.py ──→ [open depots set, closed depots, reassigned sites]
        │
        ▼
   scheduler.py ──→ [7-day schedule: {day → [visit dicts]}]
        │
        ▼
   solver.py (per day, per depot)
        │    ├── google_distance.py ──→ distance & time matrices
        │    │         ▲
        │    │   distance_cache.json
        │    │
        │    └── distance_matrix.py ──→ cost matrix (combines distance + time costs)
        │
        ▼
   [solution: routes with stops, dropped sites, stats]
        │
        ├── report.py ──→ console output (daily routes, weekly summary, depot P&L)
        └── export_results.py ──→ VRP_Results.xlsx (6 sheets)
```

### Module-by-Module Breakdown

**`data_loader.py`** — Reads the `Site_Table` sheet from the Excel file. Computes derived fields like `net_contribution_per_visit` (revenue minus structural costs), `service_time_minutes` (bins × 15 min), and `demand_lbs`. Deduplicates sites by ID.

**`geocoder.py`** — Converts addresses to lat/lon coordinates. Tries Google Maps Geocoding API first; falls back to Nominatim (free, rate-limited at ~1 request/sec). All results are cached to `geocode_cache.json`. Also geocodes depot addresses.

**`scheduler.py`** — Builds a 7-day schedule. For each day, determines which sites need a visit based on their frequency code. D2 (2× daily) sites produce two visit nodes, each with half the normal demand. D5 (weekly) sites are assigned to a specific day deterministically via `site_id % 7`.

**`depot_selector.py`** — Phase 1 of the optimization. Evaluates each depot's estimated profitability and runs a greedy closure algorithm. Sites from closed depots are reassigned to the next-nearest open depot. The main warehouse is never closed.

**`google_distance.py`** — Builds NxN distance (km) and time (minutes) matrices using the Google Maps Distance Matrix API. Batches requests in groups of 10×10 (API limit). All results are cached to `distance_cache.json`. Falls back to Haversine × 1.3 if the API is unavailable.

**`distance_matrix.py`** — Provides the Haversine fallback for distance/time matrices and the `build_cost_matrix()` function that combines distance costs and driver time costs into a single cost matrix in cents (used as the solver's arc cost).

**`solver.py`** — The core OR-Tools VRP model. Sets up capacity constraints, time constraints, disjunctions (optional stops), and fixed vehicle costs. Runs the solver and extracts routes. Includes a post-solve profitability filter that drops entire routes where revenue doesn't cover costs.

**`report.py`** — Generates all console output: per-day route details (every stop on every truck), weekly summary (lbs, km, hours, fleet size), full cost breakdown (driver wages, vehicle costs, fixed costs, revenue, net contribution), dropped sites list, fleet utilization stats, and per-depot P&L with keep/close recommendations.

**`export_results.py`** — Parses the console output and generates a formatted Excel workbook (`VRP_Results.xlsx`) with 5 sheets: Weekly_Summary, Route_Details, Dropped_Sites, Cost_Breakdown, Depot_PnL, and Logic_Constraints.

**`main.py`** — Orchestrates the entire pipeline. Parses CLI arguments, calls each module in sequence, and ties everything together.

---

## 8. How Google OR-Tools Works

Google OR-Tools is an open-source optimization library. This project uses its **Constraint Programming VRP solver** (`pywrapcp`). Here's how the model is set up, explained in plain English.

### Nodes and Vehicles

- **Node 0** is the depot (where all trucks start and end their routes).
- **Nodes 1..N** are the sites to potentially visit that day.
- **Vehicles** represent trucks. Each depot has a fixed number of available trucks (e.g., the main warehouse has up to 20).

### The Routing Model

The solver creates a `RoutingModel` that asks: *"Given N locations and V vehicles, what's the best assignment of locations to vehicles (and the best visit order within each vehicle's route) to minimize total cost?"*

### Cost Callback (Arc Cost)

Every time a truck travels from node A to node B, it incurs a cost. The cost matrix combines:
- **Distance cost**: `distance_km × $0.39/km` (fuel + maintenance + mileage)
- **Driver time cost**: `(travel_minutes / 60) × $24.00/hr`

Both are converted to **cents** (integer) because OR-Tools works with integers. The solver minimizes the total arc cost across all routes.

### Capacity Dimension

Each site has a demand in pounds (the `visit_demand_lbs`). Each truck has a capacity of 4,000 lbs. The solver ensures no truck exceeds its payload limit.

### Time Dimension

Each arc has a transit time (travel time between locations). Each site also has a **service time** (bins × 15 minutes). The solver tracks cumulative time per truck and ensures no truck exceeds 660 minutes (11 hours effective driving after breaks). A slack of 30 minutes is allowed for waiting/scheduling flexibility.

### Disjunctions (Optional Stops)

This is the key profit-maximizing mechanism. Every site is added as a **disjunction** — meaning the solver is allowed to skip it, but at a cost (the "penalty").

- **Penalty = max(0, net_contribution_per_visit × 100)** (in cents)
- Sites with **positive** net contribution have a penalty equal to the profit the optimizer "loses" by not visiting them. The solver will visit these sites if the cost of reaching them is less than this penalty.
- Sites with **negative** net contribution (costs more to serve than the revenue) have a penalty of 0, meaning the solver can drop them for free.

This elegantly lets the solver decide which sites are worth visiting based on their profitability relative to the routing cost.

### Fixed Vehicle Cost

Each truck has a fixed daily cost of ~$90.66 (9,066 cents). This discourages the solver from using more trucks than necessary — it will only dispatch an additional truck if the profit from serving more sites outweighs the fixed cost.

### Search Strategy

1. **First solution strategy: `PATH_CHEAPEST_ARC`** — Builds an initial solution greedily by always extending the current route to the nearest unvisited node (nearest-neighbor heuristic). This gives a reasonable starting point quickly.

2. **Local search metaheuristic: `GUIDED_LOCAL_SEARCH`** — Iteratively improves the solution by making local changes (moving stops between trucks, reordering stops, adding/removing optional stops). "Guided" means it penalizes features of recently explored solutions to escape local optima and explore more of the solution space.

3. **Time limit**: The solver runs for up to `SOLVER_TIME_LIMIT_SECONDS` (default 60s) per sub-problem. Longer limits generally find better solutions.

### What the Solver Minimizes

The objective function is:

```
Minimize: Σ(arc costs) + Σ(fixed vehicle costs) − Σ(dropped site penalties)
```

Or equivalently, the solver maximizes the net benefit of serving sites minus routing costs and truck costs.

---

## 9. Key Algorithms

### 9.1 Greedy Depot Closure (Phase 1)

**File**: `depot_selector.py`

**Purpose**: Determine which depots to keep open to maximize total network profit.

**Algorithm**:

1. Start with all 7 depots open. Each site is assigned to its nearest depot (by Haversine distance).
2. Estimate each depot's weekly P&L:
   - Revenue = Σ(revenue_per_visit × weekly_visits) for all assigned sites
   - Fixed cost = number of trucks × $636.35/week
   - Variable cost = Σ(estimated driving cost + driver time cost) for all assigned sites
   - Net profit = revenue − fixed cost − variable cost
3. Rank depots by net profit (worst first). The main warehouse (`wh`) is never a candidate for closure.
4. Simulate closing the worst depot:
   - Reassign each of its sites to the next-nearest open depot
   - Recompute total network profit
5. If closure improves total profit → keep it closed and repeat from step 3.
6. If closure hurts profit → revert and stop.

The variable cost estimate uses a 1.3× round-trip factor (since sites are chained in routes, not visited individually round-trip from the depot).

### 9.2 OR-Tools Profit-Optimizing VRP (Phase 2)

**File**: `solver.py`

See [Section 8](#8-how-google-or-tools-works) for the full explanation. In summary:

- All sites are optional (disjunctions with profit-based penalties)
- Solver minimizes routing cost + fixed truck cost − dropped site penalty
- Capacity constraint: 4,000 lbs per truck
- Time constraint: 660 minutes per truck (including service time)
- Search: PATH_CHEAPEST_ARC initial → GUIDED_LOCAL_SEARCH improvement

### 9.3 Post-Solve Route Profitability Filter

**File**: `solver.py` (within `solve_daily_vrp`)

After the OR-Tools solver returns a solution, each route is checked for profitability:

```
route_revenue = Σ(net_contribution_per_visit × 100) for all stops
route_cost = arc_cost + fixed_daily_truck_cost
```

If `route_revenue < route_cost`, the entire route is dropped — all its stops become "dropped sites." This catches edge cases where the solver assigns marginally profitable stops to a truck that isn't cost-justified.

### 9.4 Scheduling Logic

**File**: `scheduler.py`

The scheduler determines which sites need a visit on each day of the week:

- **D1 (Daily)**: Visit every day, Mon–Sun.
- **D2 (2× Daily)**: Visit every day, but create **two visit nodes** per day, each with **half the demand**. This ensures both visits can be on different trucks or at different times.
- **D3 (2× Week)**: Visit on Tuesday and Thursday (fixed pattern).
- **D4 (3× Week)**: Visit on Monday, Wednesday, and Friday (fixed pattern).
- **D5 (Weekly)**: Visit on one specific day, determined by `site_id % 7`. This distributes weekly sites evenly across all 7 days.

**Holiday handling**: On holiday days, only sites with `net_contribution_per_visit > 0` are included. Unprofitable sites are skipped on holidays.

---

## 10. Output

### Console Output

Running the optimizer produces detailed console output with each pipeline step:

1. **Loading summary**: Number of sites loaded, frequency distribution
2. **Geocoding progress**: Cached vs. newly geocoded addresses
3. **Depot assignment**: How many sites assigned to each depot
4. **Depot selection**: Initial P&L estimates, closure iterations, final depot set
5. **Schedule**: Number of visits per day (total and profitable)
6. **Solver progress**: Per-depot results (trucks used, lbs, km, dropped)
7. **Daily routes**: Each truck's stop sequence with addresses, lbs, service time, and net contribution
8. **Weekly summary**: Totals by day (trucks, lbs, km, hours)
9. **Cost breakdown**: Full financial analysis:
   - Driver cost (regular + overtime)
   - Vehicle variable costs (fuel, maintenance, mileage)
   - Fixed truck costs (lease, insurance)
   - Total weekly cost, revenue, net contribution
   - Annualized projections
10. **Dropped sites**: All sites not served, ranked by lost net value
11. **Fleet utilization**: Fleet size, average trucks/day, average lbs and km per truck
12. **Depot P&L**: Per-depot revenue, costs, and net profit with keep/close recommendation

### Excel Export: `VRP_Results.xlsx`

Generated by `export_results.py`, this workbook has 6 sheets:

| Sheet | Contents |
|-------|----------|
| **Weekly_Summary** | Daily totals by depot: visits scheduled, trucks used, lbs collected, km driven, visits dropped. Includes day totals and week total. |
| **Route_Details** | Every stop on every route, in order: day, depot, truck ID, stop sequence, address, lbs, service time. This is the driver's route sheet. |
| **Dropped_Sites** | Sites not served: address, net $/visit, annual lbs, frequency, inferred reason (low value or too far). |
| **Cost_Breakdown** | Full financial picture: driver costs, vehicle costs, fixed costs, revenue, net contribution, fleet utilization stats. |
| **Depot_PnL** | Per-depot profitability: lbs, km, hours, trucks, revenue, driver cost, vehicle variable, fixed cost, total cost, net profit. |
| **Logic_Constraints** | Documentation of the model: objective, data source, frequency codes, depot selection, fleet constraints, vehicle constraints, cost model, solver strategy. |

### Weekly Routes Export: `weekly_routes.xlsx`

If generated, this contains the optimized route assignments in a format suitable for operational use.

---

## 11. Cost Model

### Revenue

| Component | Rate | Description |
|-----------|------|-------------|
| Donation revenue | $0.30/lb | Revenue earned per pound of donations collected |

### Variable Costs (per kilometer)

| Component | Rate | Description |
|-----------|------|-------------|
| Fuel | $0.25/km | Diesel/gas cost |
| Maintenance | $0.05/km | Wear and tear, repairs |
| Mileage | $0.09/km | Depreciation/other per-km costs |
| **Total** | **$0.39/km** | Combined variable vehicle cost |

### Driver Costs

| Component | Rate | Description |
|-----------|------|-------------|
| Regular wage | $24.00/hr | Standard hourly rate |
| Overtime wage | $36.00/hr | 1.5× multiplier after 44 hrs/week |
| OT threshold | 44 hrs/week | Per-driver weekly threshold |

### Fixed Costs (per truck)

| Component | Amount | Period |
|-----------|--------|--------|
| Truck lease | $2,077 | Monthly |
| Insurance | $8,166 | Annual |
| **Total fixed** | **$33,090** | **Annual** |
| | ~$636.35 | Weekly |
| | ~$90.66 | Daily |

A truck that is dispatched even once in a week incurs the full weekly fixed cost (since the lease and insurance are paid regardless).

### Net Contribution Per Visit (Site Level)

For each site, the data loader computes:

```
structural_cost_per_visit = (rent_annual + waste_annual) / annual_visits
net_contribution_per_visit = revenue_per_visit − structural_cost_per_visit
```

This is the profit from visiting a site before accounting for routing costs. Sites with negative net contribution are candidates for dropping (the solver can skip them for free).

### Route-Level Profitability

After solving, each route is checked:

```
route_revenue = Σ(net_contribution_per_visit) for all stops on the route
route_cost = Σ(arc_costs) + fixed_daily_truck_cost
```

If `route_revenue < route_cost`, the entire route is dropped.

### Network-Level P&L

The weekly summary computes:

```
total_cost = driver_wages + vehicle_variable_costs + fixed_truck_costs
total_revenue = total_lbs_collected × $0.30/lb
net_contribution = total_revenue − total_cost
```

This is also broken down per depot in the Depot P&L report.

---

## 12. Caching

The system uses two JSON cache files to avoid redundant API calls.

### `geocode_cache.json`

- **Location**: Set by `GEOCODE_CACHE_PATH` in `config.py` (default: `vrp_optimizer/geocode_cache.json`)
- **Contents**: `{ "address string": { "lat": float, "lon": float, "resolved": "formatted address", "source": "google"|"nominatim" } }`
- **When populated**: On the first run when addresses are geocoded. Saved incrementally (every 50 addresses) and at completion.
- **When to clear**: If addresses in your input data have changed, or if you suspect incorrect geocoding results. Delete the file and re-run without `--skip-geocode`.

### `distance_cache.json`

- **Location**: Set by `DISTANCE_CACHE_PATH` in `config.py` (default: `vrp_optimizer/distance_cache.json`)
- **Contents**: `{ "lat1,lon1|lat2,lon2": { "dist_km": float, "time_min": int } }` — keyed by coordinate pairs with 6 decimal places.
- **When populated**: During solver runs when the Google Distance Matrix API is called. Saved periodically (every 500 pairs) and at completion.
- **When to clear**: If you want to refresh driving times (e.g., road network changes, seasonal traffic patterns). Delete the file and re-run. Note: this will incur API costs for all uncached pairs.

### Cache Behavior

- The system always checks the cache before making an API call.
- If all needed data is cached, no API calls are made (instant).
- Partial cache hits are handled: only missing pairs are fetched.
- Caches grow over time and never expire automatically.
- The `--skip-geocode` flag skips live geocoding entirely and relies solely on the cache. Useful for subsequent runs after the first.

---

## 13. File Reference

| File | Role |
|------|------|
| `main.py` | Pipeline orchestrator and CLI entry point. Ties all modules together in an 8-step sequence. |
| `config.py` | All configuration constants: costs, fleet params, depot definitions, solver settings, file paths. |
| `data_loader.py` | Parses the Excel input file (`Site_Table` sheet) into a list of site dictionaries with derived fields. |
| `geocoder.py` | Converts addresses to lat/lon using Google Maps API (primary) or Nominatim (fallback). Manages the geocode cache. |
| `scheduler.py` | Builds the weekly schedule: determines which sites are visited on which days based on frequency codes. |
| `depot_selector.py` | Phase 1: greedy depot closure algorithm that decides which depots to keep open for maximum network profit. |
| `google_distance.py` | Fetches driving distances and times from the Google Maps Distance Matrix API with batching and disk caching. |
| `distance_matrix.py` | Haversine-based distance/time matrix (fallback) and the cost matrix builder that combines distance + time costs. |
| `solver.py` | Phase 2: sets up and runs the Google OR-Tools VRP model with capacity, time, disjunctions, and fixed vehicle costs. |
| `report.py` | Generates all console output: daily routes, weekly summary, cost breakdown, dropped sites, depot P&L. |
| `export_results.py` | Parses console output and generates the formatted `VRP_Results.xlsx` Excel workbook with 6 sheets. |
| `geocode_cache.json` | Cached geocoding results (auto-generated, do not edit). |
| `distance_cache.json` | Cached Google Maps distance/time results (auto-generated, do not edit). |
