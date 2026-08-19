"""Aim, recoil, visibility, trigger and automatic-fire workers."""

import threading

from ..engine import Cheats


def create_workers(cheats: Cheats) -> tuple[threading.Thread, ...]:
    return (
        threading.Thread(target=cheats.no_recoil_loop, name="aim-rcs", daemon=True),
        threading.Thread(target=cheats.no_shake_loop, name="aim-visual-recoil", daemon=True),
        threading.Thread(target=cheats.vector_aim_loop, name="aimbot", daemon=True),
        threading.Thread(target=cheats.triggerbot_loop, name="trigger-auto-fire", daemon=True),
    )
