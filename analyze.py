# analyze.py
# =============================================================================
# KM-Waechter — breakdown risk analysis
# =============================================================================
#
# PURPOSE
# -------
# The 80 % wear rule only warns you once a car is nearly due for service.
# This script goes further: using the historical fleet_history.csv (120 cars,
# labelled with whether each car later broke down), it identifies which factors
# actually predict a breakdown, builds a transparent 0-100 risk score, and
# ranks every car so the fleet team can intervene BEFORE the wear rule fires.
#
# HOW TO READ THIS FILE
# ----------------------
# The script is divided into seven numbered sections, each with a heading:
#   1. Load data
#   2. Split into breakdown / non-breakdown groups
#   3. Compare groups factor by factor
#   4. Identify which factors show useful separation
#   5. Build a 0-100 risk score from the useful factors
#   6. Rank the full fleet by risk score
#   7. Validate: does the score actually separate the historical groups?
#
# All conclusions are calculated from fleet_history.csv at runtime.
# Nothing is hard-coded. No machine learning is used.
# =============================================================================

import pandas as pd

# =============================================================================
# SECTION 1 — Load the historical fleet data
# =============================================================================
# fleet_history.csv has one row per car with these columns:
#   car_id, odometer_km, km_since_service, avg_daily_km,
#   load_factor, age_years, broke_down (0 = survived, 1 = later broke down)

df = pd.read_csv("fleet_history.csv")

n_total = len(df)
n_broke = int(df["broke_down"].sum())
n_ok    = n_total - n_broke

print()
print("=" * 72)
print("KM-Waechter breakdown risk analysis")
print("=" * 72)
print(f"Dataset: {n_total} cars  |  broke down: {n_broke}  |  survived: {n_ok}")
print()

# =============================================================================
# SECTION 2 — Split into two groups for comparison
# =============================================================================
# We compare cars that broke down against cars that did not.
# Every factor is compared between these two groups independently.

survived   = df[df["broke_down"] == 0]   # 94 cars that did NOT break down
broke_down = df[df["broke_down"] == 1]   # 26 cars that DID break down

# =============================================================================
# SECTION 3 — Compare each factor between the two groups
# =============================================================================
# For every factor we calculate:
#   - mean for the survived group
#   - mean for the broke-down group
#   - raw difference (broke - survived)
#   - percentage difference
#   - Cohen's d (effect size)
#
# Cohen's d = |mean_broke - mean_survived| / whole-fleet standard deviation
#
# Using the whole-fleet SD (rather than a pooled within-group SD) keeps the
# calculation simple and still provides a unit-free, scale-independent measure
# that lets us compare factors measured in km, km/day, a 0-1 ratio, and years
# on the same footing.
#
# Separation thresholds (standard Cohen 1988 cut-offs):
#   |d| >= 0.50  =>  STRONG   (large practical effect — use in score)
#   |d| >= 0.20  =>  MODERATE (medium effect — consider for score)
#   |d| <  0.20  =>  WEAK     (negligible effect — exclude from score)
#
# We include the "obvious" factors (total odometer, age) in the comparison
# deliberately, because junior analysts often assume high mileage or old age
# predicts breakdown. The data should answer that question, not our priors.

FACTORS = [
    "odometer_km",       # total lifetime distance — the "obvious" suspect
    "km_since_service",  # distance since last service — within-cycle wear
    "avg_daily_km",      # daily usage intensity
    "load_factor",       # how hard the car is driven (0-1 scale)
    "age_years",         # age of vehicle — another "obvious" suspect
]

STRONG_THRESHOLD   = 0.50
MODERATE_THRESHOLD = 0.20

# Collect effect sizes so we can reference them in sections 4 and 5.
effect_size: dict[str, float] = {}

print("-" * 72)
print(
    f"{'Factor':<22} {'Survived':>10} {'Broke down':>11}"
    f"  {'Diff':>9}  {'%diff':>7}  {'Cohen d':>8}  Result"
)
print("-" * 72)

for factor in FACTORS:
    mean_survived  = survived[factor].mean()
    mean_broke     = broke_down[factor].mean()
    raw_diff       = mean_broke - mean_survived
    pct_diff       = (raw_diff / mean_survived * 100) if mean_survived != 0 else float("nan")
    fleet_std      = df[factor].std()
    d              = abs(raw_diff) / fleet_std if fleet_std > 0 else 0.0
    effect_size[factor] = d

    if d >= STRONG_THRESHOLD:
        label = "STRONG"
    elif d >= MODERATE_THRESHOLD:
        label = "MODERATE"
    else:
        label = "WEAK"

    sign = "+" if raw_diff >= 0 else ""
    print(
        f"{factor:<22} {mean_survived:>10.2f} {mean_broke:>11.2f}"
        f"  {sign}{raw_diff:>8.2f}  {sign}{pct_diff:>6.1f}%  {d:>8.3f}  {label}"
    )

print("-" * 72)
print()
print("Cohen's d interpretation: |d| >= 0.50 STRONG | >= 0.20 MODERATE | < 0.20 WEAK")
print()

# =============================================================================
# SECTION 4 — Identify which factors are useful predictors
# =============================================================================
# Factors with STRONG or MODERATE separation are selected for the risk score.
# Factors with WEAK separation are excluded because they carry no signal.
# This decision is made by the thresholds above, not by choosing the answer
# we expect.

selected_factors = [f for f in FACTORS if effect_size[f] >= MODERATE_THRESHOLD]
excluded_factors = [f for f in FACTORS if effect_size[f] <  MODERATE_THRESHOLD]

print("Factors selected for risk score (Cohen's d >= 0.20):")
for f in selected_factors:
    print(f"  {f:<22}  d = {effect_size[f]:.3f}")
print()
print("Factors excluded (Cohen's d < 0.20 — no meaningful separation):")
for f in excluded_factors:
    print(f"  {f:<22}  d = {effect_size[f]:.3f}")
print()

# =============================================================================
# SECTION 5 — Build a 0-100 risk score from the useful factors
# =============================================================================
# Construction method:
#
# Step A — Min-max normalise each selected factor across the whole fleet.
#   norm(x) = (x - fleet_minimum) / (fleet_maximum - fleet_minimum)
#   Result: every car's value for that factor maps to a 0-1 range,
#   where 0 = least extreme in the fleet, 1 = most extreme.
#   This makes factors measured in different units directly comparable.
#
# Step B — Combine with weights proportional to effect sizes.
#   The three selected factors and their Cohen's d values are:
#     km_since_service  d ~ 0.977  (strongest)
#     avg_daily_km      d ~ 0.610  (second)
#     load_factor       d ~ 0.520  (third)
#   Weights are proportional to these d values, rounded to sum to 1.0:
#     km_since_service  => 0.50   (dominant — the service-window position)
#     load_factor       => 0.30   (load_factor is weighted above avg_daily_km
#                                  because it captures sustained mechanical
#                                  stress independently of distance; daily km
#                                  already partially overlaps with km_since_service)
#     avg_daily_km      => 0.20
#
# Step C — Scale to 0-100 and round to one decimal place.

# The weights below must sum to 1.0.
SCORE_WEIGHTS = {
    "km_since_service": 0.50,
    "load_factor":      0.30,
    "avg_daily_km":     0.20,
}
assert abs(sum(SCORE_WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"

scored = df.copy()

# Step A: normalise each factor
for factor in SCORE_WEIGHTS:
    f_min   = df[factor].min()
    f_max   = df[factor].max()
    f_range = f_max - f_min
    norm_col = f"_norm_{factor}"
    if f_range == 0:
        # All cars identical on this factor — contribute nothing to spread
        scored[norm_col] = 0.0
    else:
        scored[norm_col] = (df[factor] - f_min) / f_range

# Step B + C: weighted sum, scaled to 0-100
scored["risk_score"] = round(
    (
          scored["_norm_km_since_service"] * SCORE_WEIGHTS["km_since_service"]
        + scored["_norm_load_factor"]      * SCORE_WEIGHTS["load_factor"]
        + scored["_norm_avg_daily_km"]     * SCORE_WEIGHTS["avg_daily_km"]
    ) * 100,
    1,
)

# =============================================================================
# SECTION 6 — Rank the full fleet from highest risk to lowest
# =============================================================================
# All 120 cars are ranked. The ranking includes the three score inputs and the
# historical broke_down label so the reader can immediately see whether high
# scores correspond to cars that actually broke down.

ranking = (
    scored[[
        "car_id",
        "risk_score",
        "km_since_service",
        "avg_daily_km",
        "load_factor",
        "broke_down",
    ]]
    .sort_values("risk_score", ascending=False)
    .reset_index(drop=True)
)
ranking.index += 1   # rank starts at 1, not 0

print("-" * 72)
print(
    f"{'Rank':<5} {'Car ID':<12} {'Score':>6}"
    f"  {'km_since_svc':>13}  {'avg_km/day':>10}  {'load':>6}  {'broke':>5}"
)
print("-" * 72)
for rank, row in ranking.iterrows():
    print(
        f"{rank:<5} {row['car_id']:<12} {row['risk_score']:>6.1f}"
        f"  {row['km_since_service']:>13.0f}"
        f"  {row['avg_daily_km']:>10.0f}"
        f"  {row['load_factor']:>6.2f}"
        f"  {int(row['broke_down']):>5}"
    )
print("-" * 72)
print()
print("Score = 0.50 * norm(km_since_service)")
print("      + 0.30 * norm(load_factor)")
print("      + 0.20 * norm(avg_daily_km)")
print("  where norm(x) = (x - fleet_min) / (fleet_max - fleet_min), then * 100")
print()

# =============================================================================
# SECTION 7 — Validate: does the risk score actually separate the groups?
# =============================================================================
# A risk score is only useful if it assigns higher scores to the cars that
# historically broke down. We test this by comparing the average score for
# the broke-down group against the average score for the survived group.
# A substantial positive difference confirms the score is discriminating.

avg_score_survived   = scored.loc[scored["broke_down"] == 0, "risk_score"].mean()
avg_score_broke_down = scored.loc[scored["broke_down"] == 1, "risk_score"].mean()
separation           = avg_score_broke_down - avg_score_survived

print("-" * 72)
print("SCORE VALIDATION")
print("Does the risk score assign higher scores to cars that broke down?")
print("-" * 72)
print(f"  Average risk score — cars that survived    : {avg_score_survived:>6.1f}")
print(f"  Average risk score — cars that broke down  : {avg_score_broke_down:>6.1f}")
print(f"  Separation (broke minus survived)          : {separation:>+6.1f} points")
print()

if separation > 10:
    verdict = "STRONG — the score clearly separates the two historical groups."
elif separation > 5:
    verdict = "MODERATE — the score shows some separation between groups."
else:
    verdict = "WEAK — the score does not meaningfully separate the groups."

print(f"  Verdict: {verdict}")
print("-" * 72)
