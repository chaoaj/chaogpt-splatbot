"""Random walk with occasional dash when the dash cooldown is ready."""

import random

from ..utils.actions import Actions
from ..utils.hex_grid import HexDirection

_DASH_DISTANCE_MIN = 2
_DASH_DISTANCE_MAX = 6


class Bot:
    def __init__(self):
        self._next_step_is_move = False

    def decide(self, game_state):
        player = game_state.me
        if player.stun > 0:
            return Actions.skip()

        if not self._next_step_is_move:
            self._next_step_is_move = True
            return Actions.face_direction(random.choice(list(HexDirection)))

        self._next_step_is_move = False
        if player.dash_cooldown == 0 and random.random() < 0.25:
            return Actions.dash(random.randint(_DASH_DISTANCE_MIN, _DASH_DISTANCE_MAX))
        return Actions.move()
