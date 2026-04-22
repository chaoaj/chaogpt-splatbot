#!/usr/bin/env python3
"""Parameter sweep for `smarter_code` dash/paintball thresholds.

Creates a temporary bot file `smarter_code_trial.py` for each parameter
combination, runs several matches vs `examples/random_everything_bot`, and
records aggregated results to `sweep_results.json`.
"""

import os
import json
import itertools

from simulate import run_match

BASE_DIR = os.path.dirname(__file__)
ORIG_FILE = os.path.join(BASE_DIR, "smarter_code.py")
TRIAL_FILE = os.path.join(BASE_DIR, "smarter_code_trial.py")
OUT_FILE = os.path.join(BASE_DIR, "sweep_results.json")

NUM_MATCHES = 20
RADIUS = 3
OPPONENT = "examples/random_everything_bot"

with open(ORIG_FILE, "r") as fh:
    orig_src = fh.read()

# Locate thresholds marker and legacy helper marker
start_idx = orig_src.find("# Tunable thresholds")
legacy_marker = "# (Legacy helpers kept for experimentation)"
legacy_idx = orig_src.find(legacy_marker, start_idx) if start_idx != -1 else -1
if start_idx == -1 or legacy_idx == -1:
    raise SystemExit("Could not locate thresholds block in smarter_code.py")

dash_snippet_orig = (
    "                # Dash if target is directly ahead and reachable in 2-6 steps\n"
    "                if best_dir == facing and player.dash_cooldown == 0:\n"
    "                    steps = self._dash_steps_to(target, pos, facing, hex_utils, grid)\n"
    "                    if steps is not None:\n"
    "                        return Actions.dash(steps)\n"
)

# Replacement snippet supports optional best-ahead scoring controlled by
# DASH_USE_SCORING and threshold DASH_SCORE_THRESHOLD.
dash_snippet_repl_template = '''                # Dash decision: optionally use best-ahead scoring, otherwise exact-target dash
                if best_dir == facing and player.dash_cooldown == 0:
                    if DASH_USE_SCORING:
                        best_steps = None
                        best_score = -1
                        for s in range(2, 7):
                            nb = pos + HexVector.from_direction_and_distance(facing, s)
                            if nb not in grid:
                                break
                            tile = hex_utils.hex_at(nb)
                            sscore = len(hex_utils.in_grid_neighbors(nb)) * 2
                            if tile is not None and not tile.is_controlled_by(player):
                                sscore += 3
                            if sscore > best_score:
                                best_score = sscore
                                best_steps = s
                        if best_steps is not None and best_score >= DASH_SCORE_THRESHOLD:
                            return Actions.dash(best_steps)
                        # fallback to exact-target dash
                        steps = self._dash_steps_to(target, pos, facing, hex_utils, grid)
                        if steps is not None:
                            return Actions.dash(steps)
                    else:
                        steps = self._dash_steps_to(target, pos, facing, hex_utils, grid)
                        if steps is not None:
                            return Actions.dash(steps)
'''

# We'll vary dash mode (exact vs score) and paintball neutral-ahead threshold.
dash_modes = ["exact", "score"]
dash_thresholds = [4, 8, 12, 16]
paint_thresholds = [2, 3, 4]

results = []
combo_id = 0

try:
    for dash_mode in dash_modes:
        for paint_th in paint_thresholds:
            thresh_iter = dash_thresholds if dash_mode == "score" else [None]
            for dth in thresh_iter:
                combo_id += 1
                dash_use = dash_mode == "score"
                dash_thresh = dth if dth is not None else 99999

                # build thresholds block to inject
                new_block = (
                    "        # Tunable thresholds (injected by sweep)\n"
                    f"        DASH_USE_SCORING = {dash_use}\n"
                    f"        DASH_SCORE_THRESHOLD = {dash_thresh}\n"
                    f"        PAINTBALL_NEUTRAL_AHEAD_THRESHOLD = {paint_th}\n\n"
                    f"        {legacy_marker}"
                )

                # create trial source
                trial_src = orig_src[:start_idx] + new_block + orig_src[legacy_idx:]

                # replace dash snippets (both occurrences)
                trial_src = trial_src.replace(dash_snippet_orig, dash_snippet_repl_template)

                # replace paintball numeric threshold (>= 3) with the variable
                trial_src = trial_src.replace("if unowned_ahead >= 3:", "if unowned_ahead >= PAINTBALL_NEUTRAL_AHEAD_THRESHOLD:")

                # write trial file
                with open(TRIAL_FILE, "w") as fh:
                    fh.write(trial_src)

                # run matches
                wins = losses = draws = 0
                sum_margin = 0
                print(f"Running combo {combo_id}: dash_mode={dash_mode} dash_thresh={dth} paint_th={paint_th}")
                for seed in range(NUM_MATCHES):
                    counts = run_match("smarter_code_trial", OPPONENT, radius=RADIUS, seed=seed, verbose=False)
                    p1 = counts.get(1, 0)
                    p2 = counts.get(2, 0)
                    if p1 > p2:
                        wins += 1
                    elif p2 > p1:
                        losses += 1
                    else:
                        draws += 1
                    sum_margin += (p1 - p2)

                avg_margin = sum_margin / NUM_MATCHES
                result = {
                    "combo_id": combo_id,
                    "dash_mode": dash_mode,
                    "dash_threshold": (dth if dth is not None else None),
                    "paint_threshold": paint_th,
                    "wins": wins,
                    "losses": losses,
                    "draws": draws,
                    "avg_margin": avg_margin,
                    "num_matches": NUM_MATCHES,
                }
                print("  ->", result)
                results.append(result)

finally:
    # cleanup trial file if present
    try:
        if os.path.exists(TRIAL_FILE):
            os.remove(TRIAL_FILE)
    except Exception:
        pass

# save results
with open(OUT_FILE, "w") as fh:
    json.dump(results, fh, indent=2)

# print a short summary of top combos by wins then avg_margin
results_sorted = sorted(results, key=lambda r: (r['wins'], r['avg_margin']), reverse=True)
print("\nTop combos:")
for r in results_sorted[:5]:
    print(r)

print(f"Saved results to {OUT_FILE}")
