"""Local active-weapon finish override worker."""

import threading

from ..engine import Cheats


def create_workers(cheats: Cheats) -> tuple[threading.Thread, ...]:
    return (
        threading.Thread(target=cheats.skin_changer_loop, name="skin-changer", daemon=True),
    )
