#!/usr/bin/env python3
"""
Run OpenDRIVE Digital Twin experiment on all CARLA town files.

Generates aggregated results across all towns.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.experiment_2_digital_twin import run_experiment  # noqa: E402


def main():
    """Run experiment on all town files and aggregate results."""
    opendrive_dir = Path("data/opendrive")
    town_files = sorted(opendrive_dir.glob("Town*.xodr"))

    if not town_files:
        print("No OpenDRIVE files found in data/opendrive/")
        return

    print("=" * 70)
    print("OpenDRIVE Digital Twin Experiment - All CARLA Towns")
    print("=" * 70)
    print()

    all_results = []
    totals = {
        "roads_parsed": 0,
        "geometries_total": 0,
        "geometries_arc": 0,
        "geometries_line": 0,
        "lanes_driving": 0,
        "elevations_total": 0,
        "parameters_total": 0,
        "parameters_valid": 0,
        "parameters_invalid": 0,
    }

    for town_file in town_files:
        print(f"\n--- Processing {town_file.name} ---")
        result = run_experiment(input_file=str(town_file), verbose=False)
        all_results.append(
            {
                "town": town_file.stem,
                "file": town_file.name,
                **result,
            }
        )

        # Aggregate totals
        totals["roads_parsed"] += result["parsing"]["roads_parsed"]
        totals["geometries_total"] += result["mapping"]["geometries_total"]
        totals["geometries_arc"] += result["mapping"]["geometries_arc"]
        totals["geometries_line"] += result["mapping"]["geometries_line"]
        totals["lanes_driving"] += result["mapping"]["lanes_driving"]
        totals["elevations_total"] += result["mapping"]["elevations_total"]
        totals["parameters_total"] += result["validation"]["parameters_total"]
        totals["parameters_valid"] += result["validation"]["parameters_valid"]
        totals["parameters_invalid"] += result["validation"]["parameters_invalid"]

    # Calculate aggregate metrics
    validation_pass_rate = (
        totals["parameters_valid"] / totals["parameters_total"]
        if totals["parameters_total"] > 0
        else 0
    )

    # Print summary
    print("\n")
    print("=" * 70)
    print("AGGREGATED RESULTS - ALL CARLA TOWNS")
    print("=" * 70)
    print()

    print("Parsing Summary:")
    print(f"  Total Towns:            {len(town_files)}")
    print(f"  Total Roads:            {totals['roads_parsed']}")
    print(f"  Total Geometries:       {totals['geometries_total']}")
    print(f"    - Arc (curves):       {totals['geometries_arc']}")
    print(f"    - Line (straight):    {totals['geometries_line']}")
    print(f"  Total Driving Lanes:    {totals['lanes_driving']}")
    print(f"  Total Elevations:       {totals['elevations_total']}")
    print()

    print("Validation Summary:")
    print(f"  Parameters Checked:     {totals['parameters_total']}")
    print(f"  Parameters Valid:       {totals['parameters_valid']}")
    print(f"  Parameters Invalid:     {totals['parameters_invalid']}")
    print(f"  Validation Pass Rate:   {validation_pass_rate:.2%}")
    print()

    print("Per-Town Results:")
    print("-" * 70)
    print(f"{'Town':<10} {'Roads':>8} {'Params':>10} {'Valid':>10} {'Invalid':>10} {'Pass%':>10}")
    print("-" * 70)
    for r in all_results:
        town = r["town"]
        roads = r["parsing"]["roads_parsed"]
        params = r["validation"]["parameters_total"]
        valid = r["validation"]["parameters_valid"]
        invalid = r["validation"]["parameters_invalid"]
        rate = r["validation"]["validation_pass_rate"]
        print(f"{town:<10} {roads:>8} {params:>10} {valid:>10} {invalid:>10} {rate:>9.2%}")
    print("-" * 70)
    print(
        f"{'TOTAL':<10} {totals['roads_parsed']:>8} {totals['parameters_total']:>10} {totals['parameters_valid']:>10} {totals['parameters_invalid']:>10} {validation_pass_rate:>9.2%}"
    )
    print()

    # Save aggregated results
    output_path = Path("experiments/results/digital_twin_all_towns.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    aggregated = {
        "experiment": "digital_twin_all_carla_towns",
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "towns_processed": len(town_files),
            **totals,
            "validation_pass_rate": validation_pass_rate,
        },
        "per_town_results": [
            {
                "town": r["town"],
                "roads": r["parsing"]["roads_parsed"],
                "parameters_total": r["validation"]["parameters_total"],
                "parameters_valid": r["validation"]["parameters_valid"],
                "parameters_invalid": r["validation"]["parameters_invalid"],
                "validation_pass_rate": r["validation"]["validation_pass_rate"],
            }
            for r in all_results
        ],
    }

    with open(output_path, "w") as f:
        json.dump(aggregated, f, indent=2)

    print(f"Results saved to: {output_path}")

    return aggregated


if __name__ == "__main__":
    main()
