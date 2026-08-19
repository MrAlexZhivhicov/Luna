"""Player-visual workers used by the ESP and GPU overlay."""

import threading

from ..engine import Cheats


def create_workers(cheats: Cheats) -> tuple[threading.Thread, ...]:
    return (
        threading.Thread(target=cheats.glow_loop, name="esp-glow", daemon=True),
    )
