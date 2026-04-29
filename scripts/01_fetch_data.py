from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import entsoe_client, fuels, henex, weather


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2026-04-30")
    p.add_argument("--henex-years", default="2024,2025", help="comma-separated years for HEnEx archive")
    p.add_argument("--skip-entsoe", action="store_true")
    p.add_argument("--skip-weather", action="store_true")
    p.add_argument("--skip-fuels", action="store_true")
    p.add_argument("--skip-henex", action="store_true")
    args = p.parse_args()

    if not args.skip_henex:
        years = [int(y) for y in args.henex_years.split(",")]
        print(f"[HEnEx]   archive years={years} + recent")
        henex.save(years)
    if not args.skip_entsoe:
        print(f"[ENTSO-E] {args.start} -> {args.end}")
        entsoe_client.save_all(args.start, args.end)
    if not args.skip_weather:
        print(f"[weather] {args.start} -> {args.end}")
        weather.save(args.start, args.end)
    if not args.skip_fuels:
        print(f"[fuels]   {args.start} -> {args.end}")
        fuels.save(args.start, args.end)
    print("done.")


if __name__ == "__main__":
    main()
