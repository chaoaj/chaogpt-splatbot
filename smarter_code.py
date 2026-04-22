# ChaoGPT - a smarter bot that precomputes a spiral path covering every tile, then follows it while splatting and dashing when advantageous.
# A template for legal bot actions
from utils.actions import Actions

# Hex grid helpers (construct HexUtils each turn with game_state)
from utils.hex_grid import HexDirection, HexUtils, HexVector

# Optional typing references for editor hints
from utils.splatbot_data_types import GameState

import math


class Bot:
    def __init__(self):
        self.path = None   # pre-computed inward-then-outward spiral over every tile
        self.path_idx = 0  # index of the current navigation target
        # Post-spiral vertical sweep state (built once when spiral finishes)
        self.vertical_path = None
        self.vertical_idx = 0

    # ------------------------------------------------------------------ #
    #  Spiral path construction (runs once on the first tick)             #
    # ------------------------------------------------------------------ #

    def _build_spiral_path(self, game_state):
        """Build a spiral-first path: outward from centre to outermost,
        then back inward, and finally append six radial spokes as extra
        coverage to be followed after the initial spiral completes.
        """
        hex_utils = HexUtils(game_state)
        tiles = list(game_state.grid)

        # centre anchor (closest to geometric centroid)
        avg_q = sum(h.q for h in tiles) / len(tiles)
        avg_r = sum(h.r for h in tiles) / len(tiles)
        centre = min(tiles, key=lambda h: (h.q - avg_q) ** 2 + (h.r - avg_r) ** 2)

        # Group tiles by ring distance from centre
        rings: dict[int, list] = {}
        for h in tiles:
            d = hex_utils.hex_distance(h, centre)
            rings.setdefault(d, []).append(h)

        # Sort each ring clockwise by angle (negate r: axial r increases downward)
        for ring in rings.values():
            ring.sort(key=lambda h: math.atan2(
                -(h.r - centre.r),
                h.q - centre.q
            ))

        # Inward pass: outermost ring first → centre
        inward = []
        for d in sorted(rings.keys(), reverse=True):
            inward.extend(rings[d])

        # Outward pass: centre → outermost ring
        outward = []
        for d in sorted(rings.keys()):
            outward.extend(rings[d])

        # Compose spiral path: outward then inward
        path = outward + inward

        # Build 6 radial spokes from centre outward (one per HexDirection)
        spokes = []
        for d in HexDirection:
            cursor = centre
            while True:
                cursor = hex_utils.hex_neighbor(cursor, d)
                if cursor not in game_state.grid:
                    break
                spokes.append(cursor)

        # Append spokes while avoiding duplicates
        seen = {(t.q, t.r) for t in path}
        for s in spokes:
            key = (s.q, s.r)
            if key not in seen:
                path.append(s)
                seen.add(key)

        self.path = path

    def _build_vertical_path(self, game_state):
        """Build a boustrophedon vertical sweep (top->bottom, then bottom->top).

        The vertical path lists tiles row-by-row (grouped by r). Each row is
        traversed left-to-right or right-to-left alternately to maintain
        adjacency between successive rows. The returned cycle is top->bottom
        then reversed (bottom->top) so the bot can repeat it indefinitely.
        """
        tiles = list(game_state.grid)

        # Group tiles by r (row), sort rows top-to-bottom (small r -> large r)
        rows: dict[int, list] = {}
        for h in tiles:
            rows.setdefault(h.r, []).append(h)

        ordered_rows: list[list] = []
        for i, r in enumerate(sorted(rows.keys())):
            row = sorted(rows[r], key=lambda h: h.q)
            # Alternate direction per row for a continuous sweep
            if i % 2 == 1:
                row.reverse()
            ordered_rows.append(row)

        vertical = []
        for row in ordered_rows:
            vertical.extend(row)

        # cycle = top->bottom then bottom->top
        self.vertical_path = vertical + list(reversed(vertical))
        self.vertical_idx = 0

    # ------------------------------------------------------------------ #
    #  Navigation helpers                                                  #
    # ------------------------------------------------------------------ #

    def _closest_dir_to(self, target, pos, hex_utils, grid):
        """Return the HexDirection whose in-grid neighbour is closest to target."""
        best_dir, best_dist = None, hex_utils.hex_distance(pos, target) + 1
        for d in HexDirection:
            nb = hex_utils.hex_neighbor(pos, d)
            if nb not in grid:
                continue
            dist = hex_utils.hex_distance(nb, target)
            if dist < best_dist:
                best_dist, best_dir = dist, d
        return best_dir

    def _dash_steps_to(self, target, pos, facing, hex_utils, grid):
        """Return dash distance if target is straight ahead within 2-6 in-grid steps, else None."""
        for steps in range(2, 7):
            nb = pos + HexVector.from_direction_and_distance(facing, steps)
            if nb not in grid:
                return None   # path exits the grid before reaching target
            if nb == target:
                return steps
        return None

    # ------------------------------------------------------------------ #
    #  Main decision                                                       #
    # ------------------------------------------------------------------ #

    def decide(self, game_state: GameState):
        player = game_state.me

        if player.stun:
            return Actions.skip()

        hex_utils = HexUtils(game_state)
        pos = player.position
        facing = player.facing
        grid = game_state.grid

        # Tunable thresholds (chosen from sweep)
        # Use exact-target dash by default (no best-ahead scoring)
        DASH_USE_SCORING = False
        DASH_SCORE_THRESHOLD = 16  # only used when DASH_USE_SCORING is True
        # Paintball: number of neutral tiles straight ahead required to fire
        PAINTBALL_NEUTRAL_AHEAD_THRESHOLD = 3

        # (Legacy helpers kept for experimentation)
        def tile_score(h):
            tile = hex_utils.hex_at(h)
            score = len(hex_utils.in_grid_neighbors(h)) * 2
            if tile is not None and not tile.is_controlled_by(player):
                score += 3
            return score

        # Build the spiral on the very first tick (grid is available here, not in __init__)
        if self.path is None:
            self._build_spiral_path(game_state)

        # Advance past tiles we already own, are currently standing on, or left the grid
        while self.path_idx < len(self.path):
            tgt_tile = hex_utils.hex_at(self.path[self.path_idx])
            if (tgt_tile is None
                    or self.path[self.path_idx] == pos
                    or tgt_tile.is_controlled_by(player)):
                self.path_idx += 1
            else:
                break

        # ---- Splat ----
        # Prefer splatting when it converts many non-player tiles (opponent or neutral).
        if player.splat_cooldown == 0:
            neighbours = hex_utils.in_grid_neighbors(pos)
            if neighbours:
                unowned = sum(1 for t in neighbours if t.controller is None)
                opponent_control = sum(
                    1 for t in neighbours
                    if (t.controller is not None and not t.is_controlled_by(player))
                )
                # Weight converting opponent tiles higher than claiming neutral tiles
                weighted_gain = unowned + opponent_control * 2
                # Heuristics: be more aggressive — convert back areas with 2+ opponent tiles
                # or any spot with meaningful net gain.
                if opponent_control >= 2 or weighted_gain >= 3 or (len(neighbours) >= 5 and weighted_gain >= 2):
                    return Actions.splat()

        # ---- Paintball: use when it will convert multiple tiles ahead ----
        if player.paintball_cooldown == 0:
            unowned_ahead = 0
            cursor = hex_utils.hex_neighbor(pos, facing)
            while cursor in grid:
                tile = hex_utils.hex_at(cursor)
                if tile and tile.controller is None:
                    unowned_ahead += 1
                cursor = hex_utils.hex_neighbor(cursor, facing)
            if unowned_ahead >= PAINTBALL_NEUTRAL_AHEAD_THRESHOLD:
                return Actions.shoot_paintball()

        # ---- Follow the spiral path ----
        if self.path_idx < len(self.path):
            target = self.path[self.path_idx]
            best_dir = self._closest_dir_to(target, pos, hex_utils, grid)
            if best_dir is not None:
                # Dash if target is directly ahead and reachable in 2-6 steps
                if best_dir == facing and player.dash_cooldown == 0:
                    steps = self._dash_steps_to(target, pos, facing, hex_utils, grid)
                    if steps is not None:
                        return Actions.dash(steps)

                if facing != best_dir:
                    return Actions.face_direction(best_dir)
                return Actions.move()

        # ---- Post-spiral vertical sweep ----
        # When the spiral path is exhausted, build and follow a repeating
        # top->bottom then bottom->top vertical sweep that runs until the
        # match ends. This keeps coverage systematic and predictable.
        if self.path_idx >= len(self.path):
            if self.vertical_path is None:
                self._build_vertical_path(game_state)

            # Advance past tiles we already control, stand on, or which vanished
            while self.vertical_idx < len(self.vertical_path):
                tgt_tile = hex_utils.hex_at(self.vertical_path[self.vertical_idx])
                if (tgt_tile is None
                        or self.vertical_path[self.vertical_idx] == pos
                        or tgt_tile.is_controlled_by(player)):
                    self.vertical_idx += 1
                else:
                    break

            # Loop the sweep if we've reached the end
            if self.vertical_idx >= len(self.vertical_path):
                self.vertical_idx = 0

            if self.vertical_idx < len(self.vertical_path):
                target = self.vertical_path[self.vertical_idx]
                best_dir = self._closest_dir_to(target, pos, hex_utils, grid)
                if best_dir is not None:
                    # Dash if target is directly ahead and reachable in 2-6 steps
                    if best_dir == facing and player.dash_cooldown == 0:
                        steps = self._dash_steps_to(target, pos, facing, hex_utils, grid)
                        if steps is not None:
                            return Actions.dash(steps)

                    if facing != best_dir:
                        return Actions.face_direction(best_dir)
                    return Actions.move()

        # ---- Fallback: move forward or turn toward most interior on-grid tile ----
        forward = hex_utils.hex_neighbor(pos, facing)
        if forward in grid:
            return Actions.move()

        best_dir = max(
            (d for d in HexDirection if hex_utils.hex_neighbor(pos, d) in grid),
            key=lambda d: len(hex_utils.in_grid_neighbors(hex_utils.hex_neighbor(pos, d))),
            default=None,
        )
        return Actions.face_direction(best_dir) if best_dir else Actions.skip()
