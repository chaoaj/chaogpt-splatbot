"""Run smarter_code against all bots in examples/ and report win/loss/margin stats."""
from __future__ import annotations

import os
import json
from collections import defaultdict
from simulate import run_match

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "examples")

def find_example_bots():
    files = sorted(f for f in os.listdir(EXAMPLES_DIR) if f.endswith(".py") and not f.startswith("__"))
    return [os.path.join("examples", f[:-3]) for f in files]


def run_tournament(matches_per_opponent: int = 20, radius: int = 3):
    bots = find_example_bots()
    results = {}

    for bot_path in bots:
        stats = defaultdict(int)
        margins = []
        for i in range(matches_per_opponent):
            counts = run_match("smarter_code", bot_path, radius=radius, seed=i, verbose=False)
            p1 = counts.get(1, 0)
            p2 = counts.get(2, 0)
            margin = p1 - p2
            margins.append(margin)
            if p1 > p2:
                stats["wins"] += 1
            elif p2 > p1:
                stats["losses"] += 1
            else:
                stats["draws"] += 1
            stats["p1_total_tiles"] += p1
            stats["p2_total_tiles"] += p2

        stats["matches"] = matches_per_opponent
        stats["avg_margin"] = sum(margins) / len(margins)
        stats["avg_p1_tiles"] = stats["p1_total_tiles"] / matches_per_opponent
        stats["avg_p2_tiles"] = stats["p2_total_tiles"] / matches_per_opponent
        results[bot_path] = stats
        print(f"Finished {bot_path}: wins={stats['wins']} losses={stats['losses']} draws={stats['draws']} avg_margin={stats['avg_margin']:.2f}")

    # Save results
    out_path = os.path.join(os.path.dirname(__file__), "tournament_results.json")
    with open(out_path, "w") as fh:
        json.dump({k: dict(v) for k, v in results.items()}, fh, indent=2)
    print(f"Saved results to {out_path}")
    return results


if __name__ == "__main__":
    run_tournament(matches_per_opponent=20, radius=3)
