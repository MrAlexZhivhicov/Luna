"""Movement, flash and radar workers."""

import threading

from ..engine import Cheats


def create_workers(cheats: Cheats) -> tuple[threading.Thread, ...]:
    return (
        threading.Thread(target=cheats.anti_flash_loop, name="misc-no-flash", daemon=True),
        threading.Thread(target=cheats.bunny_hop_loop, name="misc-bunnyhop", daemon=True),
        threading.Thread(target=cheats.radar_loop, name="misc-radar", daemon=True),
    )
