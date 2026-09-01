"""Standard pressure-health classification mandated by the problem statement.

Pressure vs baseline ratio -> state:
    >= 95%          GREEN  - Healthy
    >= 80% & < 95%  YELLOW - Caution
    >= 60% & < 80%  ORANGE - Degraded
    <  60%          RED    - Critical
"""

from __future__ import annotations

from dataclasses import dataclass

GREEN, YELLOW, ORANGE, RED = "GREEN", "YELLOW", "ORANGE", "RED"

# ordered from healthy to critical so tiers can be compared by index
TIER_ORDER = [GREEN, YELLOW, ORANGE, RED]

TIER_LABEL = {
    GREEN: "Healthy",
    YELLOW: "Caution",
    ORANGE: "Degraded",
    RED: "Critical",
}


@dataclass(frozen=True)
class HealthState:
    tier: str
    label: str
    ratio: float  # pressure / baseline


def classify(ratio: float) -> HealthState:
    if ratio >= 0.95:
        tier = GREEN
    elif ratio >= 0.80:
        tier = YELLOW
    elif ratio >= 0.60:
        tier = ORANGE
    else:
        tier = RED
    return HealthState(tier=tier, label=TIER_LABEL[tier], ratio=ratio)


def worst(*tiers: str) -> str:
    return max(tiers, key=TIER_ORDER.index)
