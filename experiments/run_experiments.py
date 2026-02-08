#!/usr/bin/env python3
"""
Unified Experiment Runner for CrossTraffic Journal Extension

This script provides a unified framework for running all three experiments:
- Experiment 1: Semantic Firewall Stress Test (Section 4.2)
- Experiment 2: Digital Twin Mapping Test (Section 4.1)
- Experiment 3: Agent Benchmark (Section 4.3 - qualitative)

Usage:
    python experiments/run_experiments.py --exp firewall --samples 1000
    python experiments/run_experiments.py --exp digital-twin --input sample.xodr
    python experiments/run_experiments.py --exp all
    python experiments/run_experiments.py --list
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure imports work
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_firewall_experiment(
    samples: int = 1000,
    use_api: bool = False,
    base_url: str = "http://localhost:8000",
    seed: int = 42,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run Experiment 1: Semantic Firewall Stress Test."""
    from experiments.experiment_1_firewall import run_experiment

    return run_experiment(
        samples=samples,
        use_api=use_api,
        base_url=base_url,
        seed=seed,
        verbose=verbose,
    )


def run_digital_twin_experiment(
    input_file: str | None = None,
    input_xml: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run Experiment 2: Digital Twin Mapping Test."""
    from experiments.experiment_2_digital_twin import run_experiment

    return run_experiment(
        input_file=input_file,
        input_xml=input_xml,
        verbose=verbose,
    )


def run_agent_benchmark(
    verbose: bool = False,
) -> dict[str, Any]:
    """Run Experiment 3: Agent Benchmark (qualitative)."""
    # This experiment is primarily qualitative and requires manual evaluation
    # Here we provide a framework for documenting results

    results = {
        "experiment": "agent_benchmark",
        "timestamp": datetime.now().isoformat(),
        "description": "Qualitative agent benchmark comparing LLM performance with/without KG schema",
        "methodology": {
            "agents_tested": [
                "GPT-4",
                "Claude-3.5-Sonnet",
                "Llama-3-70B",
            ],
            "conditions": [
                "Baseline (no KG schema)",
                "With KG schema provided",
                "With KG + validation feedback",
            ],
            "metrics": [
                "Tool accuracy (correct function calls)",
                "Hallucination rate (fabricated values)",
                "Citation accuracy (correct source references)",
                "Response consistency (same query, multiple runs)",
            ],
        },
        "test_prompts": [
            {
                "id": "P1",
                "prompt": "What is the minimum curve radius for a 55 mph design speed?",
                "expected_answer": "835 ft (AASHTO Green Book Table 3-7)",
                "results": {},
            },
            {
                "id": "P2",
                "prompt": "Is a 10 ft lane width valid for a two-lane highway?",
                "expected_answer": "Yes, valid (HCM Exhibit 15-8 allows 9-12 ft)",
                "results": {},
            },
            {
                "id": "P3",
                "prompt": "What passing types are defined in HCM Chapter 15?",
                "expected_answer": "Three types: Constrained (0), Zone (1), Lane (2)",
                "results": {},
            },
            {
                "id": "P4",
                "prompt": "Validate these parameters: lane_width=11ft, shoulder_width=6ft, speed=55mph, radius=800ft",
                "expected_answer": "Invalid - radius 800ft below minimum 835ft for 55mph",
                "results": {},
            },
        ],
        "status": "pending_manual_evaluation",
        "instructions": """
To complete this experiment:
1. Run each test prompt against each agent (with and without KG)
2. Record responses in the 'results' field for each prompt
3. Code responses for accuracy, hallucination, and citation correctness
4. Calculate aggregate metrics
5. Update status to 'completed' when done
        """,
    }

    print("=" * 70)
    print("Experiment 3: Agent Benchmark")
    print("=" * 70)
    print()
    print("This experiment requires manual evaluation.")
    print("A template has been generated with test prompts and expected answers.")
    print()
    print("Test Prompts:")
    for prompt in results["test_prompts"]:
        print(f"  {prompt['id']}: {prompt['prompt']}")
        print(f"      Expected: {prompt['expected_answer']}")
        print()

    return results


def list_experiments() -> None:
    """List available experiments."""
    print("Available Experiments:")
    print()
    print("  firewall     Experiment 1: Semantic Firewall Stress Test")
    print("               Tests 5 hard constraints against adversarial inputs")
    print("               Metrics: Rejection rate, false positive rate, execution time")
    print()
    print("  digital-twin Experiment 2: Digital Twin Mapping Test")
    print("               Parses OpenDRIVE files and validates against KG")
    print("               Metrics: Mapping success rate, traceability score")
    print()
    print("  agent        Experiment 3: Agent Benchmark (qualitative)")
    print("               Compares LLM performance with/without KG schema")
    print("               Metrics: Tool accuracy, hallucination rate, citation accuracy")
    print()
    print("  all          Run all experiments")


def save_results(results: dict[str, Any], output_path: Path) -> None:
    """Save experiment results to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run CrossTraffic journal experiments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available experiments
  python experiments/run_experiments.py --list

  # Run Semantic Firewall stress test
  python experiments/run_experiments.py --exp firewall --samples 1000

  # Run Digital Twin mapping test
  python experiments/run_experiments.py --exp digital-twin --input sample.xodr

  # Run all experiments
  python experiments/run_experiments.py --exp all

  # Run with API mode (requires server running)
  python experiments/run_experiments.py --exp firewall --api-mode --samples 5000
        """,
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available experiments",
    )
    parser.add_argument(
        "--exp",
        choices=["firewall", "digital-twin", "agent", "all"],
        help="Experiment to run",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=1000,
        help="Number of samples for firewall test (default: 1000)",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Input file for digital-twin test",
    )
    parser.add_argument(
        "--api-mode",
        action="store_true",
        help="Use API endpoint for firewall test",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="experiments/results",
        help="Output directory for results",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if args.list:
        list_experiments()
        return

    if not args.exp:
        parser.print_help()
        return

    output_dir = Path(args.output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_results = {}

    if args.exp in ["firewall", "all"]:
        print("\n" + "=" * 70)
        print("Running Experiment 1: Semantic Firewall Stress Test")
        print("=" * 70 + "\n")

        results = run_firewall_experiment(
            samples=args.samples,
            use_api=args.api_mode,
            base_url=args.base_url,
            seed=args.seed,
            verbose=args.verbose,
        )
        all_results["firewall"] = results
        save_results(results, output_dir / f"firewall_results_{timestamp}.json")

    if args.exp in ["digital-twin", "all"]:
        print("\n" + "=" * 70)
        print("Running Experiment 2: Digital Twin Mapping Test")
        print("=" * 70 + "\n")

        results = run_digital_twin_experiment(
            input_file=args.input,
            verbose=args.verbose,
        )
        all_results["digital_twin"] = results
        save_results(results, output_dir / f"digital_twin_results_{timestamp}.json")

    if args.exp in ["agent", "all"]:
        print("\n" + "=" * 70)
        print("Running Experiment 3: Agent Benchmark")
        print("=" * 70 + "\n")

        results = run_agent_benchmark(verbose=args.verbose)
        all_results["agent"] = results
        save_results(results, output_dir / f"agent_benchmark_{timestamp}.json")

    if args.exp == "all":
        # Save combined results
        combined = {
            "timestamp": datetime.now().isoformat(),
            "experiments": all_results,
        }
        save_results(combined, output_dir / f"all_experiments_{timestamp}.json")

    print("\n" + "=" * 70)
    print("Experiment run complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
