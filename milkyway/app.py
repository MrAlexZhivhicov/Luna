"""Application assembly and lifecycle management."""

import logging
import threading

import pymem.exception
import requests

from .core import (
    APP_NAME,
    APP_VERSION,
    LOG_PATH,
    PROCESS_NAME,
    Cheats,
    OffsetError,
    Settings,
    StateStore,
    configure_logging,
    connect,
    show_startup_error,
)
from .features import create_aim_workers, create_esp_workers, create_misc_workers, create_skinchanger_workers
from .ui.menu import Menu


def main() -> int:
    configure_logging()
    logging.info("Starting %s %s", APP_NAME, APP_VERSION)
    try:
        pm, client = connect()
        state = StateStore(Settings.load())
        stop = threading.Event()
        cheats = Cheats(pm, client, state, stop)
    except requests.RequestException as exc:
        logging.exception("Offset download failed")
        show_startup_error(f"Не удалось загрузить актуальные смещения.\n\n{exc}\n\nЛог: {LOG_PATH}")
        return 2
    except (pymem.exception.PymemError, ProcessLookupError, RuntimeError) as exc:
        logging.exception("Game connection failed")
        show_startup_error(f"Не удалось подключиться к {PROCESS_NAME}.\nСначала запустите игру.\n\n{exc}")
        return 3
    except (OffsetError, KeyError, TypeError) as exc:
        logging.exception("Offset format changed")
        show_startup_error(f"Формат смещений изменился.\n\n{exc}\n\nЛог: {LOG_PATH}")
        return 4

    workers = (
        *create_aim_workers(cheats),
        *create_esp_workers(cheats),
        *create_misc_workers(cheats),
        *create_skinchanger_workers(cheats),
    )
    for worker in workers:
        worker.start()

    try:
        Menu(cheats, state, stop, f"Подключено к {PROCESS_NAME}").run()
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=0.4)
        try:
            pm.close_process()
        except Exception:
            logging.exception("Process close failed")
        logging.info("Application stopped")
    return 0
