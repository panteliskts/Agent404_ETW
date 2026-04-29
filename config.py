from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"

for _d in (RAW_DIR, PROCESSED_DIR, MODELS_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

ENTSOE_API_KEY = os.getenv("ENTSOE_API_KEY", "")

GR_BIDDING_ZONE = "GR"
GR_TIMEZONE = "Europe/Athens"

# Greek DAM moved to 15-min MTU on 2025-10-01. Earlier history is hourly.
MTU_SWITCH_DATE = "2025-10-01"

# Athens, Thessaloniki, Patras — covers load + the main wind/solar regions.
WEATHER_LOCATIONS = [
    {"name": "Athens", "lat": 37.9838, "lon": 23.7275},
    {"name": "Thessaloniki", "lat": 40.6401, "lon": 22.9444},
    {"name": "Patras", "lat": 38.2466, "lon": 21.7346},
    {"name": "Crete", "lat": 35.3387, "lon": 25.1442},
]


@dataclass
class BatterySpec:
    power_mw: float = 50.0
    energy_mwh: float = 100.0
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    soc_min_frac: float = 0.05
    soc_max_frac: float = 0.95
    soc_init_frac: float = 0.50
    cyclic: bool = True
    max_cycles_per_day: float = 1.5
    degradation_eur_per_mwh: float = 2.0

    @property
    def soc_min(self) -> float:
        return self.soc_min_frac * self.energy_mwh

    @property
    def soc_max(self) -> float:
        return self.soc_max_frac * self.energy_mwh

    @property
    def soc_init(self) -> float:
        return self.soc_init_frac * self.energy_mwh


DEFAULT_BATTERY = BatterySpec()
