"""Simple Splatbot match simulator for testing bots in this repo.

This is a lightweight, not-perfect reproduction of the game's rules but
accurate enough to exercise bot decision logic (movement, dash, splat,
paintball lines, and simple cooldown/stun handling).

Run as:
    python simulate.py

It will run a single match between `smarter_code.Bot` (player 1) and
`random.Bot` (player 2) and print a turn-by-turn summary and final scores.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from types import MappingProxyType
from collections import defaultdict

from utils.hex_grid import Hex, HexDirection, HexVector, HexUtils
from utils.splatbot_data_types import BotInfo, GameState
from utils.actions import (
    MoveAction,
    SkipAction,
    SplatAction,
    DashAction,
    ShootPaintballAction,
    TurnLeftAction,
    TurnRightAction,
    FaceDirectionAction,
    Turn180Action,
    Actions,
)

# Tuning constants (match defaults from docs)
SPLAT_COOLDOWN = 10
SPLAT_STUN = 3
PAINTBALL_COOLDOWN = 20
PAINTBALL_STUN = 7
DASH_COOLDOWN = 7
MAX_TURNS = 400


def generate_hex_grid(radius: int) -> list[Hex]:
    tiles: list[Hex] = []
    for q in range(-radius, radius + 1):
        for r in range(-radius, radius + 1):
            s = -q - r
            if abs(s) <= radius:
                tiles.append(Hex(q, r, None))
    return tiles


def run_match(bot1_module_name: str = "smarter_code", bot2_module_name: str = "random", radius: int = 3, seed: int | None = None, verbose: bool = False):
    # seed is ignored here because the repository contains a local `random.py`
    # which would shadow the standard library; use deterministic behaviour
    # by setting explicit seeds inside bot modules if needed.

    # Load bot modules from file paths to avoid name conflicts with standard
    # library modules (e.g. a local random.py). Load each bot under a unique
    # module name so their internal imports resolve to stdlib where expected.
    def _load_bot_module(filename, mod_name):
        path = os.path.join(os.path.dirname(__file__), f"{filename}.py")
        # read source and rewrite relative imports that expect a package
        with open(path, "r") as fh:
            src = fh.read()
        # example files use `from ..utils.xxx import ...` which fails when
        # executed as a standalone module; rewrite to absolute imports.
        src = src.replace("from ..utils.", "from utils.")
        src = src.replace("from ..utils import", "from utils import")
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        # execute transformed source in module namespace
        exec(compile(src, path, "exec"), mod.__dict__)
        return mod

    # Ensure the stdlib `random` is available under the name 'random' so bot
    # modules that `import random` get the real stdlib module rather than the
    # local file `random.py` that lives in the repo.
    std_random = None
    if seed is not None:
        # Temporarily remove the repo root / current working directory from
        # sys.path so importing 'random' loads the stdlib module.
        saved_path = list(sys.path)
        try:
            cwd = os.path.abspath(os.getcwd())
            sys.path = [p for p in sys.path if p and os.path.abspath(p) != cwd]
            std_random = importlib.import_module("random")
            std_random.seed(seed)
        finally:
            sys.path = saved_path
    else:
        # Load stdlib random without modifying sys.path in the common case
        std_random = importlib.import_module("random")

    # Put the stdlib random module into sys.modules['random'] so bot files
    # that do `import random` get the stdlib implementation.
    sys.modules["random"] = std_random

    bot1_mod = _load_bot_module(bot1_module_name, f"bot_{bot1_module_name}")
    bot2_mod = _load_bot_module(bot2_module_name, f"bot_{bot2_module_name}")
    bot1 = bot1_mod.Bot()
    bot2 = bot2_mod.Bot()

    tiles = generate_hex_grid(radius)
    grid = { (t.q, t.r): Hex(t.q, t.r, None) for t in tiles }

    # place players on opposite sides (min q and max q)
    west = min(tiles, key=lambda h: h.q)
    east = max(tiles, key=lambda h: h.q)

    p1_pos = grid[(west.q, west.r)]
    p2_pos = grid[(east.q, east.r)]

    p1 = BotInfo(pid=1, position=p1_pos, facing=HexDirection.E)
    p2 = BotInfo(pid=2, position=p2_pos, facing=HexDirection.W)

    # initial controllers (None)
    turn = 0

    def snapshot_for(player_info: BotInfo, other_info: BotInfo):
        return GameState(
            me=player_info,
            opponents=MappingProxyType({other_info.pid: other_info}),
            opponent=other_info,
            grid=frozenset(grid.values()),
            turn=turn,
            max_turns=MAX_TURNS,
        )

    def hex_at_key(key):
        return grid.get((key.q, key.r))

    # run
    for turn in range(MAX_TURNS):
        gs1 = snapshot_for(p1, p2)
        gs2 = snapshot_for(p2, p1)

        a1 = bot1.decide(gs1)
        a2 = bot2.decide(gs2)

        # compute intended destinations and facing updates
        hex_utils = HexUtils(gs1)

        intents = {}
        for pid, pinfo, action in ((1, p1, a1), (2, p2, a2)):
            dest = pinfo.position
            new_facing = pinfo.facing
            used_splat = False
            used_paintball = False
            used_dash = False

            if isinstance(action, SkipAction):
                pass
            elif isinstance(action, MoveAction):
                nb = hex_utils.hex_neighbor(pinfo.position, pinfo.facing)
                if nb in gs1.grid:
                    # map neighbor object to our canonical grid instance
                    dest = hex_at_key(nb)
            elif isinstance(action, DashAction):
                used_dash = True
                # walk forward until distance or edge
                last = pinfo.position
                for s in range(1, action.distance + 1):
                    nb = pinfo.position + HexVector.from_direction_and_distance(pinfo.facing, s)
                    if nb not in gs1.grid:
                        break
                    last = hex_at_key(nb)
                dest = last
            elif isinstance(action, SplatAction):
                used_splat = True
            elif isinstance(action, ShootPaintballAction):
                used_paintball = True
            elif isinstance(action, FaceDirectionAction):
                new_facing = action.direction
            elif isinstance(action, TurnLeftAction):
                new_facing = HexDirection((int(pinfo.facing) + action.steps) % 6)
            elif isinstance(action, TurnRightAction):
                new_facing = HexDirection((int(pinfo.facing) - action.steps) % 6)
            elif isinstance(action, Turn180Action):
                new_facing = HexDirection((int(pinfo.facing) + 3) % 6)

            intents[pid] = {
                "action": action,
                "dest": dest,
                "facing": new_facing,
                "used_splat": used_splat,
                "used_paintball": used_paintball,
                "used_dash": used_dash,
                "start_pos": pinfo.position,
            }

        # paint claims: map (q,r) -> set of pids claiming this tick
        claims: dict[tuple[int,int], set[int]] = defaultdict(set)

        # First: handle splats and paintballs (they paint from original positions)
        for pid, info in ((1, intents[1]), (2, intents[2])):
            action = info["action"]
            start = info["start_pos"]
            if isinstance(action, SplatAction):
                for n in HexUtils(GameState(me=BotInfo(pid=pid, position=start, facing=info['facing']), opponents=MappingProxyType({}), opponent=None, grid=frozenset(grid.values()), turn=turn, max_turns=MAX_TURNS)).in_grid_neighbors(start):
                    claims[(n.q, n.r)].add(pid)
            if isinstance(action, ShootPaintballAction):
                # cast ray until map edge or opponent's destination
                cursor = hex_utils.hex_neighbor(start, info["facing"])
                other_dest = intents[3 - pid]["dest"]
                while cursor in gs1.grid:
                    # stop if hitting opponent's destination
                    if cursor == other_dest:
                        claims[(cursor.q, cursor.r)].add(pid)
                        break
                    claims[(cursor.q, cursor.r)].add(pid)
                    cursor = hex_utils.hex_neighbor(cursor, info["facing"])

        # Second: handle moves and dashes (they paint destination)
        for pid, info in ((1, intents[1]), (2, intents[2])):
            action = info["action"]
            dest = info["dest"]
            if isinstance(action, MoveAction) or isinstance(action, DashAction):
                claims[(dest.q, dest.r)].add(pid)

        # Third: bots that didn't move (dest == start_pos) also claim their tile
        for pid, info in ((1, intents[1]), (2, intents[2])):
            if info["dest"] == info["start_pos"]:
                claims[(info["start_pos"].q, info["start_pos"].r)].add(pid)

        # Resolve claims into new grid controllers
        new_grid = {}
        for key, tile in grid.items():
            claimers = claims.get(key, set())
            if len(claimers) == 1:
                # assign to the single pid
                owner_pid = next(iter(claimers))
                new_grid[key] = Hex(tile.q, tile.r, BotInfo(pid=owner_pid, position=Hex(tile.q, tile.r), facing=HexDirection.E))
            else:
                # contested or untouched -> neutral
                new_grid[key] = Hex(tile.q, tile.r, None)

        grid = new_grid

        # Update players' positions/facings/cooldowns/stuns
        def update_player(old: BotInfo, intent: dict):
            # cooldowns decrement
            splat_cd = max(0, getattr(old, "splat_cooldown", 0) - 1)
            dash_cd = max(0, getattr(old, "dash_cooldown", 0) - 1)
            paintball_cd = max(0, getattr(old, "paintball_cooldown", 0) - 1)
            stun = max(0, getattr(old, "stun", 0) - 1)

            action = intent["action"]
            if isinstance(action, SplatAction):
                splat_cd = SPLAT_COOLDOWN
                stun = SPLAT_STUN
            if isinstance(action, ShootPaintballAction):
                paintball_cd = PAINTBALL_COOLDOWN
                stun = PAINTBALL_STUN
            if isinstance(action, DashAction):
                dash_cd = DASH_COOLDOWN

            new_pos = intent["dest"]
            new_facing = intent["facing"]

            return BotInfo(pid=old.pid, position=new_pos, facing=new_facing, stun=stun, splat_cooldown=splat_cd, dash_cooldown=dash_cd, paintball_cooldown=paintball_cd)

        p1 = update_player(p1, intents[1])
        p2 = update_player(p2, intents[2])

        # Logging small summary per turn (only when verbose)
        if verbose and (turn % 10 == 0 or turn < 10):
            counts = defaultdict(int)
            for t in grid.values():
                if t.controller is None:
                    counts[None] += 1
                else:
                    counts[t.controller.pid] += 1
            print(f"Turn {turn}: P1={counts.get(1,0)} P2={counts.get(2,0)} Neutral={counts.get(None,0)}")

        # Check termination: if no neutral tiles exist and one player controls all tiles, finish early
        owners = { (t.controller.pid if t.controller is not None else None) for t in grid.values() }
        if owners == {1} or owners == {2}:
            if verbose:
                print(f"Early finish on turn {turn}: single-owner {owners}")
            break

    # final score
    counts = defaultdict(int)
    for t in grid.values():
        if t.controller is None:
            counts[None] += 1
        else:
            counts[t.controller.pid] += 1
    print("FINAL:", f"P1={counts.get(1,0)} P2={counts.get(2,0)} Neutral={counts.get(None,0)}")
    return counts


if __name__ == "__main__":
    run_match("smarter_code", "random", radius=3, seed=1)
