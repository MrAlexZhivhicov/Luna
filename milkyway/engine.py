"""Luna — compact external CS2 utility.

The application intentionally contains no anti-cheat bypass or process-hiding code.
Use only where game/server rules allow it.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import colorsys
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
import os
import queue
import random
import struct
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import keyboard
import dearpygui.dearpygui as dpg
import pymem
import pymem.process
import requests
import tkinter as tk
from tkinter import messagebox, ttk

from . import design

APP_NAME = "Luna"
APP_VERSION = "v1"
CONFIG_SCHEMA_VERSION = 1
PROCESS_NAME = "cs2.exe"
MOUSE_VKEYS = {"mouse1": 0x01, "mouse2": 0x02, "mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06}
MOVEMENT_VKEYS = (0x57, 0x41, 0x53, 0x44)  # W, A, S, D
# CS2 player hierarchy: head/torso, both arms, then complete leg chains.
SKELETON_BONES = (7, 6, 8, 1, 13, 14, 15, 9, 10, 11, 17, 18, 19, 20, 21, 22)
SKELETON_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3),
    (3, 10), (10, 11), (11, 12),
    (3, 13), (13, 14), (14, 15),
    (1, 4), (4, 5), (5, 6),
    (1, 7), (7, 8), (8, 9),
)
OFFSETS_URL = "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json"
CLIENT_URL = "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json"
PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_DIR / "configs"
OFFSET_CACHE_DIR = PROJECT_DIR / "cache"
LOG_DIR = PROJECT_DIR / "logs"
SCRIPTS_DIR = PROJECT_DIR / "scripts"
ASSET_DIR = PROJECT_DIR / "assets"
CONFIG_PATH = CONFIG_DIR / "default.json"
LOG_PATH = LOG_DIR / "luna.log"

WEAPON_NAMES_BY_ID = {
    1: "Desert Eagle", 2: "Dual Berettas", 3: "Five-SeveN", 4: "Glock-18",
    7: "AK-47", 8: "AUG", 9: "AWP", 10: "FAMAS", 11: "G3SG1", 13: "Galil AR",
    16: "M4A4", 17: "MAC-10", 19: "P90", 24: "UMP-45", 30: "Tec-9",
    33: "MP7", 34: "MP9", 36: "P250", 38: "SCAR-20", 39: "SG 553",
    40: "SSG 08", 60: "M4A1-S", 61: "USP-S", 64: "R8 Revolver",
    500: "Bayonet", 507: "Karambit", 515: "Butterfly Knife",
}

CS2_ICON_BY_WEAPON = {
    "Desert Eagle": "deagle", "Dual Berettas": "elite", "Five-SeveN": "fiveseven",
    "Glock-18": "glock", "AK-47": "ak47", "AUG": "aug", "AWP": "awp",
    "FAMAS": "famas", "G3SG1": "g3sg1", "Galil AR": "galilar", "M4A4": "m4a1",
    "MAC-10": "mac10", "P90": "p90", "UMP-45": "ump45", "Tec-9": "tec9",
    "MP7": "mp7", "MP9": "mp9", "P250": "p250", "SCAR-20": "scar20",
    "SG 553": "sg556", "SSG 08": "ssg08", "M4A1-S": "m4a1_silencer",
    "USP-S": "usp_silencer", "R8 Revolver": "revolver", "Bayonet": "bayonet",
    "Karambit": "knife_karambit", "Butterfly Knife": "knife_butterfly",
}

KNIFE_DEFINITIONS = frozenset((42, 59, *range(500, 526)))


@dataclass(frozen=True)
class SkinFinish:
    accepted_definitions: frozenset[int]
    target_definition: int
    paint_kit: int


def _finish(definition: int, paint_kit: int) -> SkinFinish:
    return SkinFinish(frozenset((definition,)), definition, paint_kit)


def _knife(definition: int, paint_kit: int) -> SkinFinish:
    return SkinFinish(KNIFE_DEFINITIONS, definition, paint_kit)


SKIN_CATALOG: dict[str, dict[str, SkinFinish]] = {
    "AK-47": {
        "Redline": _finish(7, 282), "Vulcan": _finish(7, 302), "Asiimov": _finish(7, 801),
        "Fuel Injector": _finish(7, 524), "Neon Revolution": _finish(7, 600),
        "Bloodsport": _finish(7, 639), "Slate": _finish(7, 1035),
    },
    "M4A1-S": {
        "Hyper Beast": _finish(60, 430), "Golden Coil": _finish(60, 497),
        "Chantico's Fire": _finish(60, 548), "Printstream": _finish(60, 984),
        "Decimator": _finish(60, 644),
    },
    "M4A4": {
        "Howl": _finish(16, 309), "Asiimov": _finish(16, 255),
        "Desolate Space": _finish(16, 588), "The Emperor": _finish(16, 844),
        "Neo-Noir": _finish(16, 695),
    },
    "AWP": {
        "Dragon Lore": _finish(9, 344), "Asiimov": _finish(9, 279),
        "Redline": _finish(9, 259), "Hyper Beast": _finish(9, 475),
        "Fade": _finish(9, 1026), "Lightning Strike": _finish(9, 51),
        "Neo-Noir": _finish(9, 803),
    },
    "Glock-18": {
        "Fade": _finish(4, 38), "Water Elemental": _finish(4, 353),
        "Wasteland Rebel": _finish(4, 586), "Vogue": _finish(4, 963),
    },
    "USP-S": {
        "Kill Confirmed": _finish(61, 504), "Orion": _finish(61, 313),
        "Neo-Noir": _finish(61, 653), "Printstream": _finish(61, 1142),
        "Cortex": _finish(61, 705),
    },
    "Desert Eagle": {
        "Blaze": _finish(1, 37), "Code Red": _finish(1, 711),
        "Kumicho Dragon": _finish(1, 527), "Printstream": _finish(1, 962),
    },
    "MP7": {"Nemesis": _finish(33, 481), "Fade": _finish(33, 1023)},
    "MP9": {"Hydra": _finish(34, 910), "Starlight Protector": _finish(34, 1134)},
    "Bayonet": {
        "Fade": _knife(500, 38), "Doppler": _knife(500, 415),
        "Tiger Tooth": _knife(500, 409), "Lore": _knife(500, 558),
    },
    "Karambit": {
        "Fade": _knife(507, 38), "Doppler": _knife(507, 415),
        "Gamma Doppler": _knife(507, 568), "Autotronic": _knife(507, 573),
        "Lore": _knife(507, 558),
    },
    "Butterfly Knife": {
        "Fade": _knife(515, 38), "Doppler": _knife(515, 415),
        "Tiger Tooth": _knife(515, 409), "Gamma Doppler": _knife(515, 568),
        "Slaughter": _knife(515, 59),
    },
}


def enable_dpi_awareness() -> None:
    """Ask Windows for native-resolution text before the first Tk window exists."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def input_is_pressed(name: str) -> bool:
    """Support keyboard keys and all five common mouse buttons."""
    normalized = name.strip().lower()
    virtual_key = MOUSE_VKEYS.get(normalized)
    if virtual_key is not None:
        return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)
    return keyboard.is_pressed(normalized)


def virtual_key_is_pressed(virtual_key: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)


class HotkeyGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pressed: dict[str, bool] = {}
        self._toggled: dict[str, bool] = {}

    def active(self, feature: str, key: str, mode: str) -> bool:
        try:
            down = input_is_pressed(key)
        except (ValueError, KeyError, OSError):
            down = False
        if mode.lower() != "toggle":
            return down
        with self._lock:
            previous = self._pressed.get(feature, False)
            if down and not previous:
                self._toggled[feature] = not self._toggled.get(feature, False)
            self._pressed[feature] = down
            return self._toggled.get(feature, False)


def send_virtual_key(virtual_key: int, pressed: bool) -> None:
    """Send one exact Windows virtual key without keyboard-library remapping."""
    keybd_event = ctypes.windll.user32.keybd_event
    keybd_event.argtypes = (ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_size_t)
    scan = ctypes.windll.user32.MapVirtualKeyW(virtual_key, 0)
    keybd_event(virtual_key, scan, 0 if pressed else 0x0002, 0)


def configure_logging() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    OFFSET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class Settings:
    enabled: bool = True
    glow: bool = True
    anti_flash: bool = True
    bunny_hop: bool = False
    bhop_key: str = "space"
    bhop_key_mode: str = "hold"
    no_recoil: bool = False
    recoil_strength: float = 100.0
    recoil_smooth: float = 1.0
    rcs_mode: str = "Memory RCS"
    rcs_start_bullet: int = 2
    rcs_x: float = 100.0
    rcs_y: float = 100.0
    rcs_enabled_pistol: bool = True
    rcs_enabled_rifle: bool = True
    rcs_enabled_sniper: bool = False
    rcs_enabled_smg: bool = True
    rcs_amount_pistol: float = 95.0
    rcs_amount_rifle: float = 100.0
    rcs_amount_sniper: float = 80.0
    rcs_amount_smg: float = 95.0
    rcs_smooth_pistol: float = 1.75
    rcs_smooth_rifle: float = 1.5
    rcs_smooth_sniper: float = 2.0
    rcs_smooth_smg: float = 1.5
    rcs_start_pistol: int = 2
    rcs_start_rifle: int = 2
    rcs_start_sniper: int = 2
    rcs_start_smg: int = 2
    rcs_x_pistol: float = 75.0
    rcs_x_rifle: float = 82.0
    rcs_x_sniper: float = 70.0
    rcs_x_smg: float = 80.0
    rcs_y_pistol: float = 95.0
    rcs_y_rifle: float = 100.0
    rcs_y_sniper: float = 80.0
    rcs_y_smg: float = 95.0
    no_shake: bool = True
    aim_enabled: bool = False
    aim_key: str = "alt"
    aim_key_mode: str = "hold"
    aim_smooth: float = 8.0
    aim_fov: float = 6.0
    aim_target: str = "head"
    aim_lock: bool = True
    dynamic_fov: bool = True
    aim_fov_pistol: float = 7.0
    aim_fov_rifle: float = 5.0
    aim_fov_sniper: float = 3.0
    aim_fov_smg: float = 6.0
    aim_smooth_pistol: float = 6.0
    aim_smooth_rifle: float = 9.0
    aim_smooth_sniper: float = 12.0
    aim_smooth_smg: float = 7.0
    first_shot_delay: float = 45.0
    target_switch_delay: float = 120.0
    lock_timeout: float = 1800.0
    aim_dead_zone: float = 0.12
    aim_max_step: float = 2.5
    target_priority: str = "Crosshair"
    hitbox_fallback: bool = True
    ignore_teammates: bool = True
    visibility_check: bool = True
    triggerbot: bool = False
    trigger_delay: float = 35.0
    shoot_in_smoke: bool = False
    auto_shoot: bool = False
    auto_stop: bool = True
    show_fov: bool = True
    box_esp: bool = False
    box_style: str = "classic"
    esp_preset: str = "Custom"
    box_thickness: float = 1.5
    box_fill_alpha: float = 14.0
    corner_length: float = 26.0
    esp_name: bool = True
    esp_health: bool = True
    esp_weapon: bool = True
    esp_armor: bool = True
    esp_distance: bool = True
    esp_snapline: bool = False
    esp_head_dot: bool = False
    esp_skeleton: bool = False
    world_bomb_esp: bool = True
    world_bomb_info: bool = True
    world_weapon_esp: bool = False
    weapon_filter_active: bool = True
    weapon_filter_grenades: bool = True
    weapon_filter_c4: bool = True
    weapon_filter_knives: bool = False
    esp_enemies: bool = True
    esp_allies: bool = False
    esp_bots: bool = True
    esp_state_indicators: bool = True
    hud_enabled: bool = True
    keybind_list: bool = True
    performance_panel: bool = False
    esp_rate: int = 144
    world_rate: int = 30
    hud_rate: int = 10
    cinema_bars: bool = False
    cinema_bar_size: float = 9.0
    screenshot_cleanup: bool = True
    disable_cosmetics_in_menu: bool = True
    watermark_x: float = 12.0
    watermark_y: float = 12.0
    hud_x: float = 20.0
    hud_y: float = 50.0
    bomb_hud_x: float = 20.0
    bomb_hud_y: float = 86.0
    keybind_hud_x: float = 20.0
    keybind_hud_y: float = 150.0
    box_color: str = "#9b5cff"
    name_color: str = "#f4f4f7"
    hp_color: str = "#55dd77"
    armor_color: str = "#58a6ff"
    weapon_color: str = "#c8cad3"
    fov_color: str = "#9b5cff"
    line_color: str = "#ffffff"
    skeleton_color: str = "#ffffff"
    world_color: str = "#ffd24a"
    profile_low_hp_color: str = "#ff4d4d"
    profile_bomb_color: str = "#ffd24a"
    world_filter: bool = False
    world_filter_color: str = "#7895c7"
    world_filter_strength: float = 12.0
    world_night_mode: bool = False
    skybox_name: str = "Dust / Mirage"
    crosshair_enabled: bool = False
    crosshair_color: str = "#ffffff"
    crosshair_size: float = 6.0
    watermark: bool = True
    overlay_fps: bool = False
    overlay_clock: bool = True
    aim_indicator: bool = True
    esp_fill: bool = False
    radar_hack: bool = False
    skin_changer: bool = False
    skin_weapon: str = "AK-47"
    skin_name: str = "Redline"
    skin_wear: float = 0.08
    skin_seed: int = 1
    skin_stattrak: bool = False
    skin_loadout: dict[str, dict[str, object]] = field(default_factory=dict)
    health_color: bool = True
    custom_color: str = "#00e5ff"
    menu_scale: int = 100
    menu_theme: str = "Nightware"
    esp_preview_enabled: bool = False

    @classmethod
    def load(cls) -> "Settings":
        try:
            source = CONFIG_PATH
            legacy = Path(os.getenv("LOCALAPPDATA", Path.home())) / "MilkyWay" / "settings.json"
            if not source.exists() and legacy.exists():
                source = legacy
            raw = json.loads(source.read_text(encoding="utf-8"))
            return settings_from_payload(raw)
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        write_settings(CONFIG_PATH, self)


def settings_from_payload(raw: object) -> Settings:
    """Load every valid field independently and retain defaults for bad values."""
    if not isinstance(raw, dict):
        raise ValueError("CFG root must be a JSON object")
    defaults = Settings()
    values: dict[str, object] = {}
    for name in Settings.__annotations__:
        if name not in raw:
            continue
        value = raw[name]
        fallback = getattr(defaults, name)
        valid = False
        if isinstance(fallback, bool):
            valid = isinstance(value, bool)
        elif isinstance(fallback, int):
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(fallback, float):
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
            if valid:
                value = float(value)
        elif isinstance(fallback, str):
            valid = isinstance(value, str)
        elif isinstance(fallback, dict):
            valid = isinstance(value, dict)
        if name.endswith("_color") and (not isinstance(value, str) or not valid_hex_color(value)):
            valid = False
        if valid:
            values[name] = value
        else:
            logging.warning("Invalid CFG field %s=%r; using default", name, value)
    return Settings(**values)


def write_settings(path: Path, settings: Settings) -> None:
    """Atomically replace a CFG so an interrupted write cannot corrupt it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": CONFIG_SCHEMA_VERSION, **settings.__dict__}
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


class ConfigManager:
    def __init__(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = "".join(char for char in name.strip() if char.isalnum() or char in "-_ ").strip()
        return cleaned[:32] or "default"

    def path(self, name: str) -> Path:
        return CONFIG_DIR / f"{self._safe_name(name)}.json"

    def names(self) -> list[str]:
        names = sorted(path.stem for path in CONFIG_DIR.glob("*.json") if path.is_file())
        return sorted(names, key=lambda value: (value.casefold() != "default", value.casefold()))

    def save(self, name: str, settings: Settings) -> str:
        safe = self._safe_name(name)
        write_settings(self.path(safe), settings)
        return safe

    def load(self, name: str) -> Settings:
        path = self.path(name)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return settings_from_payload(raw)

    def delete(self, name: str) -> None:
        path = self.path(name)
        if path.exists() and path != CONFIG_PATH:
            path.unlink()


def valid_hex_color(value: str) -> bool:
    if len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
        return True
    except ValueError:
        return False


class StateStore:
    """Thread-safe settings snapshot for worker threads."""

    def __init__(self, settings: Settings):
        self._value = settings
        self._lock = threading.Lock()

    def get(self) -> Settings:
        with self._lock:
            return self._value

    def set(self, **changes: object) -> Settings:
        with self._lock:
            self._value = replace(self._value, **changes)
            return self._value


class OffsetError(RuntimeError):
    pass


def nested_int(data: dict, *path: str) -> int:
    value: object = data
    try:
        for key in path:
            value = value[key]  # type: ignore[index]
        result = int(value)  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError) as exc:
        raise OffsetError(f"Не найдено поле: {' → '.join(path)}") from exc
    if result < 0:
        raise OffsetError(f"Некорректное смещение: {' → '.join(path)}")
    return result


def download_json(url: str, cache_name: str) -> dict:
    """Update schema data when possible and fall back to the last valid copy."""
    cache_path = OFFSET_CACHE_DIR / cache_name
    if cache_path.exists():
        try:
            age = time.time() - cache_path.stat().st_mtime
            if age < 21600.0:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
        except (OSError, ValueError, TypeError):
            logging.exception("Invalid offset cache: %s", cache_path)
    try:
        response = requests.get(url, timeout=(2.0, 5.0),
                                headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise OffsetError("Сервер вернул данные неизвестного формата")
        OFFSET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(cache_path)
        return payload
    except Exception:
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    logging.warning("Offset update failed; using cached %s", cache_name)
                    return payload
            except (OSError, ValueError, TypeError):
                logging.exception("Invalid offset cache: %s", cache_path)
        raise


class Cheats:
    def __init__(self, pm: pymem.Pymem, client: int, state: StateStore, stop: threading.Event):
        self.pm = pm
        self.client = client
        self.state = state
        self.stop = stop
        self._view_angle_lock = threading.Lock()
        self.hotkeys = HotkeyGate()
        self._records_lock = threading.Lock()
        self._records_cache: list[tuple[int, int]] = []
        self._records_cache_time = 0.0
        self._local_controller_cache = 0
        self._local_player_index_cache = 0
        self._skin_apply_event = threading.Event()
        # Both independent dumps are fetched concurrently to avoid a frozen-looking startup.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="offsets") as pool:
            offsets_job = pool.submit(download_json, OFFSETS_URL, "offsets.json")
            client_job = pool.submit(download_json, CLIENT_URL, "client_dll.json")
            offsets = offsets_job.result()
            client_dll = client_job.result()

        self.dw_entity_list = nested_int(offsets, "client.dll", "dwEntityList")
        self.dw_local_controller = nested_int(offsets, "client.dll", "dwLocalPlayerController")
        self.dw_local_player = nested_int(offsets, "client.dll", "dwLocalPlayerPawn")
        self.dw_view_angles = nested_int(offsets, "client.dll", "dwViewAngles")
        self.dw_view_matrix = nested_int(offsets, "client.dll", "dwViewMatrix")
        self.dw_global_vars = nested_int(offsets, "client.dll", "dwGlobalVars")
        self.dw_planted_c4 = nested_int(offsets, "client.dll", "dwPlantedC4")
        self.dw_highest_entity_index = nested_int(offsets, "client.dll", "dwGameEntitySystem_highestEntityIndex")
        classes = client_dll["client.dll"]["classes"]
        self.team = nested_int(classes, "C_BaseEntity", "fields", "m_iTeamNum")
        self.player_pawn = nested_int(classes, "CCSPlayerController", "fields", "m_hPlayerPawn")
        self.flash_duration = nested_int(classes, "C_CSPlayerPawnBase", "fields", "m_flFlashDuration")
        self.life_state = nested_int(classes, "C_BaseEntity", "fields", "m_lifeState")
        self.health = nested_int(classes, "C_BaseEntity", "fields", "m_iHealth")
        self.flags = nested_int(classes, "C_BaseEntity", "fields", "m_fFlags")
        self.shots_fired = nested_int(classes, "C_CSPlayerPawn", "fields", "m_iShotsFired")
        # Aim-punch data was moved into a dedicated service in recent CS2 builds.
        self.aim_punch_services = nested_int(classes, "C_CSPlayerPawn", "fields", "m_pAimPunchServices")
        self.predictable_punch = nested_int(classes, "CCSPlayer_AimPunchServices", "fields", "m_predictableBaseAngle")
        self.unpredictable_punch = nested_int(classes, "CCSPlayer_AimPunchServices", "fields", "m_unpredictableBaseAngle")
        self.camera_services = nested_int(classes, "C_BasePlayerPawn", "fields", "m_pCameraServices")
        self.view_punch = nested_int(classes, "CPlayer_CameraServices", "fields", "m_vecCsViewPunchAngle")
        self.scene_node = nested_int(classes, "C_BaseEntity", "fields", "m_pGameSceneNode")
        self.owner_entity = nested_int(classes, "C_BaseEntity", "fields", "m_hOwnerEntity")
        self.abs_origin = nested_int(classes, "CGameSceneNode", "fields", "m_vecAbsOrigin")
        self.c4_ticking = nested_int(classes, "C_PlantedC4", "fields", "m_bBombTicking")
        self.c4_site = nested_int(classes, "C_PlantedC4", "fields", "m_nBombSite")
        self.c4_blow_time = nested_int(classes, "C_PlantedC4", "fields", "m_flC4Blow")
        self.c4_timer_length = nested_int(classes, "C_PlantedC4", "fields", "m_flTimerLength")
        self.c4_defusing = nested_int(classes, "C_PlantedC4", "fields", "m_bBeingDefused")
        self.c4_defuse_end = nested_int(classes, "C_PlantedC4", "fields", "m_flDefuseCountDown")
        self.c4_defused = nested_int(classes, "C_PlantedC4", "fields", "m_bBombDefused")
        self.c4_exploded = nested_int(classes, "C_PlantedC4", "fields", "m_bHasExploded")
        try:
            self.model_state = nested_int(classes, "CSkeletonInstance", "fields", "m_modelState")
        except OffsetError:
            self.model_state = 0x170
        self.armor = nested_int(classes, "C_CSPlayerPawn", "fields", "m_ArmorValue")
        self.player_name = nested_int(classes, "CCSPlayerController", "fields", "m_sSanitizedPlayerName")
        self.spotted_state = nested_int(classes, "C_CSPlayerPawn", "fields", "m_entitySpottedState")
        self.spotted = nested_int(classes, "EntitySpottedState_t", "fields", "m_bSpotted")
        self.spotted_by_mask = nested_int(classes, "EntitySpottedState_t", "fields", "m_bSpottedByMask")
        self.movement_services = nested_int(classes, "C_BasePlayerPawn", "fields", "m_pMovementServices")
        self.duck_amount = nested_int(classes, "CCSPlayer_MovementServices", "fields", "m_flDuckAmount")
        self.crosshair_entity = nested_int(classes, "C_CSPlayerPawn", "fields", "m_iIDEntIndex")
        self.weapon_services = nested_int(classes, "C_BasePlayerPawn", "fields", "m_pWeaponServices")
        self.active_weapon = nested_int(classes, "CPlayer_WeaponServices", "fields", "m_hActiveWeapon")
        self.my_weapons = nested_int(classes, "CPlayer_WeaponServices", "fields", "m_hMyWeapons")
        self.attribute_manager = nested_int(classes, "C_EconEntity", "fields", "m_AttributeManager")
        self.econ_item = nested_int(classes, "C_AttributeContainer", "fields", "m_Item")
        self.item_definition = nested_int(classes, "C_EconItemView", "fields", "m_iItemDefinitionIndex")
        self.item_id_high = nested_int(classes, "C_EconItemView", "fields", "m_iItemIDHigh")
        self.entity_quality = nested_int(classes, "C_EconItemView", "fields", "m_iEntityQuality")
        self.item_initialized = nested_int(classes, "C_EconItemView", "fields", "m_bInitialized")
        self.restore_custom_material = nested_int(
            classes, "C_EconItemView", "fields", "m_bRestoreCustomMaterialAfterPrecache"
        )
        self.fallback_paint_kit = nested_int(classes, "C_EconEntity", "fields", "m_nFallbackPaintKit")
        self.fallback_seed = nested_int(classes, "C_EconEntity", "fields", "m_nFallbackSeed")
        self.fallback_wear = nested_int(classes, "C_EconEntity", "fields", "m_flFallbackWear")
        self.fallback_stattrak = nested_int(classes, "C_EconEntity", "fields", "m_nFallbackStatTrak")
        self.glow = nested_int(classes, "C_BaseModelEntity", "fields", "m_Glow")
        self.glowing = nested_int(classes, "CGlowProperty", "fields", "m_bGlowing")
        self.glow_color = nested_int(classes, "CGlowProperty", "fields", "m_glowColorOverride")
        self.glow_type = nested_int(classes, "CGlowProperty", "fields", "m_iGlowType")

    def _pause(self, seconds: float) -> bool:
        return self.stop.wait(seconds)

    def _pawns(self) -> list[int]:
        return [pawn for _controller, pawn in self._player_records()]

    def _is_player_pawn(self, pawn: int) -> bool:
        """Use stable pawn identity fields; volatile combat state is checked later."""
        if not self._valid_user_pointer(pawn):
            return False
        try:
            team = self.pm.read_int(pawn + self.team)
            health = self.pm.read_int(pawn + self.health)
            node = self.pm.read_longlong(pawn + self.scene_node)
            return (team in (2, 3) and 0 <= health <= 100
                    and self._valid_user_pointer(node))
        except Exception:
            return False

    def _player_records(self) -> list[tuple[int, int]]:
        now = time.monotonic()
        with self._records_lock:
            if now - self._records_cache_time < 0.010:
                return list(self._records_cache)
        result: list[tuple[int, int]] = []
        entity_list = self.pm.read_longlong(self.client + self.dw_entity_list)
        if not entity_list:
            return result
        for index in range(1, 65):
            entry = self.pm.read_longlong(entity_list + 8 * ((index & 0x7FFF) >> 9) + 16)
            if not entry:
                continue
            controller = self.pm.read_longlong(entry + 112 * (index & 0x1FF))
            if not self._valid_user_pointer(controller):
                continue
            handle = self.pm.read_uint(controller + self.player_pawn)
            entity_index = handle & 0x7FFF
            if not handle or not 1 <= entity_index <= 0x7FFE:
                continue
            pawn_entry = self.pm.read_longlong(entity_list + 8 * ((handle & 0x7FFF) >> 9) + 16)
            if pawn_entry:
                pawn = self.pm.read_longlong(pawn_entry + 112 * (handle & 0x1FF))
                if (self._is_player_pawn(pawn)
                        and self.pm.read_int(controller + self.team)
                        == self.pm.read_int(pawn + self.team)):
                    result.append((controller, pawn))
        with self._records_lock:
            self._records_cache = result
            self._records_cache_time = now
        return list(result)

    def _entity_from_handle(self, handle: int) -> int:
        entity_list = self.pm.read_longlong(self.client + self.dw_entity_list)
        if not entity_list or not handle:
            return 0
        entry = self.pm.read_longlong(entity_list + 8 * ((handle & 0x7FFF) >> 9) + 16)
        return self.pm.read_longlong(entry + 112 * (handle & 0x1FF)) if entry else 0

    def _current_local_pawn(self) -> int:
        controller = self.pm.read_longlong(self.client + self.dw_local_controller)
        if not self._valid_user_pointer(controller):
            return 0
        pawn_handle = self.pm.read_uint(controller + self.player_pawn)
        pawn = self._entity_from_handle(pawn_handle)
        return pawn if self._valid_user_pointer(pawn) else 0

    def _game_time(self) -> float | None:
        globals_ptr = self.pm.read_longlong(self.client + self.dw_global_vars)
        if not self._valid_user_pointer(globals_ptr):
            return None
        current_time = self.pm.read_float(globals_ptr + 0x30)
        return current_time if math.isfinite(current_time) and current_time >= 0.0 else None

    def _local_weapon_entities(self, services: int) -> list[tuple[int, int]]:
        handles: list[int] = []
        vector = services + self.my_weapons
        count = self.pm.read_int(vector)
        data = self.pm.read_longlong(vector + 8)
        if self._valid_user_pointer(data) and 0 < count <= 64:
            handles.extend(self.pm.read_uint(data + index * 4) for index in range(count))
        active = self.pm.read_uint(services + self.active_weapon)
        if active not in (0, 0xFFFFFFFF):
            handles.append(active)
        result: list[tuple[int, int]] = []
        seen: set[int] = set()
        for handle in handles:
            if handle in seen or handle in (0, 0xFFFFFFFF):
                continue
            seen.add(handle)
            entity = self._entity_from_handle(handle)
            if self._valid_user_pointer(entity):
                result.append((handle, entity))
        return result

    def _active_weapon_class(self, pawn: int) -> str:
        try:
            definition = self._active_weapon_definition(pawn)
            if not definition:
                return "rifle"
            name = WEAPON_NAMES_BY_ID.get(definition, "").lower()
            if any(value in name for value in ("awp", "ssg", "scar", "g3sg")):
                return "sniper"
            if any(value in name for value in ("mp", "mac", "ump", "p90", "bizon")):
                return "smg"
            if any(value in name for value in ("glock", "usp", "p2000", "p250", "deagle",
                                                "revolver", "tec", "five-seven", "cz75", "elite")):
                return "pistol"
        except Exception:
            pass
        return "rifle"

    def _active_weapon_definition(self, pawn: int) -> int:
        try:
            services = self.pm.read_longlong(pawn + self.weapon_services)
            handle = self.pm.read_uint(services + self.active_weapon) if services else 0
            weapon = self._entity_from_handle(handle)
            if not weapon:
                return 0
            item = weapon + self.attribute_manager + self.econ_item
            return self.pm.read_short(item + self.item_definition) & 0xFFFF
        except Exception:
            return 0

    @staticmethod
    def _valid_user_pointer(address: int) -> bool:
        return 0x10000000000 <= address <= 0x7FFFFFFFFFFF

    def _process_alive(self) -> bool:
        code = ctypes.c_ulong()
        handle = getattr(self.pm, "process_handle", None)
        return bool(handle and ctypes.windll.kernel32.GetExitCodeProcess(
            handle, ctypes.byref(code)) and code.value == 259)

    def _visible_to_local(self, pawn: int, local_player_index: int) -> bool:
        """Use CS2's per-player spotted mask as an external visibility check."""
        if not pawn or not 1 <= local_player_index <= 64:
            return False
        mask = self.pm.read_ulonglong(pawn + self.spotted_state + self.spotted_by_mask)
        return bool(mask & (1 << (local_player_index - 1)))

    def _local_player_index(self) -> int:
        """Resolve the controller slot used by m_bSpottedByMask (not the pawn handle)."""
        controller = self.pm.read_longlong(self.client + self.dw_local_controller)
        if not controller:
            return 0
        if controller == self._local_controller_cache and 1 <= self._local_player_index_cache <= 64:
            return self._local_player_index_cache
        entity_list = self.pm.read_longlong(self.client + self.dw_entity_list)
        if not entity_list:
            return 0
        for index in range(1, 65):
            entry = self.pm.read_longlong(entity_list + 8 * (index >> 9) + 16)
            candidate = self.pm.read_longlong(entry + 112 * (index & 0x1FF)) if entry else 0
            if candidate == controller:
                self._local_controller_cache = controller
                self._local_player_index_cache = index
                return index
        return 0

    def _bone_position(self, pawn: int, bone: int) -> tuple[float, float, float] | None:
        node = self.pm.read_longlong(pawn + self.scene_node)
        if not node:
            return None
        origin = (
            self.pm.read_float(node + self.abs_origin),
            self.pm.read_float(node + self.abs_origin + 4),
            self.pm.read_float(node + self.abs_origin + 8),
        )
        if not all(math.isfinite(value) and abs(value) < 100000.0 for value in origin):
            return None
        bones = self.pm.read_longlong(node + self.model_state + 0x80)
        if not bones or bones < 0x10000:
            return None
        address = bones + bone * 32
        point = (self.pm.read_float(address), self.pm.read_float(address + 4), self.pm.read_float(address + 8))
        if not all(math.isfinite(value) and abs(value) < 100000.0 for value in point):
            return None
        # Reject zeroed, stale or mismatched skeleton data. Every live player
        # bone must remain close to the entity origin and inside player height.
        horizontal_offset = math.hypot(point[0] - origin[0], point[1] - origin[1])
        vertical_offset = point[2] - origin[2]
        if horizontal_offset > 48.0 or vertical_offset < -8.0 or vertical_offset > 90.0:
            return None
        return point

    def _bone_positions(self, node: int, origin: tuple[float, float, float],
                        bone_ids: tuple[int, ...]) -> tuple[tuple[float, float, float] | None, ...]:
        """Fetch the complete requested skeleton with two RPM calls."""
        bones = self.pm.read_longlong(node + self.model_state + 0x80)
        if not bones or bones < 0x10000 or not bone_ids:
            return tuple(None for _ in bone_ids)
        first, last = min(bone_ids), max(bone_ids)
        raw = self.pm.read_bytes(bones + first * 32, (last - first + 1) * 32)
        result: list[tuple[float, float, float] | None] = []
        for bone in bone_ids:
            offset = (bone - first) * 32
            point = struct.unpack_from("<3f", raw, offset)
            horizontal = math.hypot(point[0] - origin[0], point[1] - origin[1])
            vertical = point[2] - origin[2]
            valid = (all(math.isfinite(value) and abs(value) < 100000.0 for value in point)
                     and horizontal <= 48.0 and -8.0 <= vertical <= 90.0)
            result.append(point if valid else None)
        return tuple(result)

    @staticmethod
    def _argb(red: int, green: int, blue: int, alpha: int = 180) -> int:
        unsigned = (alpha << 24) | (blue << 16) | (green << 8) | red
        return ctypes.c_int32(unsigned).value

    def _color(self, settings: Settings, health: int) -> int:
        if settings.health_color:
            health = max(0, min(100, health))
            return self._argb(int(255 * (1 - health / 100)), int(255 * health / 100), 0)
        value = settings.custom_color if valid_hex_color(settings.custom_color) else "#ffffff"
        return self._argb(int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))

    def glow_loop(self) -> None:
        self._guarded_loop("Glow", self._glow_tick, 0.040)

    def _glow_tick(self) -> None:
        settings = self.state.get()
        if not settings.enabled or not settings.glow:
            for pawn in self._pawns():
                try:
                    self.pm.write_bool(pawn + self.glow + self.glowing, False)
                except Exception:
                    continue
            self._pause(0.12)
            return
        local = self._current_local_pawn()
        if not local:
            self._pause(0.12)
            return
        local_team = self.pm.read_int(local + self.team)
        local_index = self._local_player_index()
        for pawn in self._pawns():
            if self.pm.read_int(pawn + self.life_state) != 256:
                continue
            same_team = self.pm.read_int(pawn + self.team) == local_team
            if (same_team and (settings.ignore_teammates or not settings.esp_allies)
                    or not same_team and not settings.esp_enemies):
                self.pm.write_bool(pawn + self.glow + self.glowing, False)
                continue
            color = self._color(settings, self.pm.read_int(pawn + self.health))
            glow = pawn + self.glow
            self.pm.write_int(glow + self.glow_color, color)
            self.pm.write_int(glow + self.glow_type, 3)
            self.pm.write_bool(glow + self.glowing, True)

    def anti_flash_loop(self) -> None:
        self._guarded_loop("Anti-Flash", self._flash_tick, 0.05)

    def _flash_tick(self) -> None:
        settings = self.state.get()
        if not settings.enabled or not settings.anti_flash:
            self._pause(0.12)
            return
        local = self._current_local_pawn()
        if local:
            self.pm.write_float(local + self.flash_duration, 0.0)

    def bunny_hop_loop(self) -> None:
        self._guarded_loop("Bunny Hop", self._bhop_tick, 0.004)

    def _bhop_tick(self) -> None:
        settings = self.state.get()
        if (not settings.enabled or not settings.bunny_hop
                or not self.hotkeys.active("bhop", settings.bhop_key, settings.bhop_key_mode)):
            self._pause(0.02)
            return
        local = self._current_local_pawn()
        now = time.monotonic()
        last_jump = getattr(self, "_bhop_last_jump", 0.0)
        if local and self.pm.read_int(local + self.flags) & 1 and now - last_jump >= 0.018:
            # Wheel jump does not release the physical Space hotkey and stays
            # independent from A/D strafing input.
            ctypes.windll.user32.mouse_event(0x0800, 0, 0, 120, 0)
            self._bhop_last_jump = now

    def no_recoil_loop(self) -> None:
        """Compensate the weapon's real aim-punch pattern during a burst."""
        applied_pitch = applied_yaw = 0.0
        pattern_last_shot = 0
        last_tick = time.perf_counter()
        last_log = 0.0
        while not self.stop.is_set():
            if not self._process_alive():
                self.stop.set()
                break
            try:
                settings = self.state.get()
                if not settings.enabled or not settings.no_recoil:
                    applied_pitch = applied_yaw = 0.0
                    last_tick = time.perf_counter()
                    self._pause(0.06)
                    continue
                local = self._current_local_pawn()
                shots = self.pm.read_int(local + self.shots_fired) if local else 0
                weapon_class = self._active_weapon_class(local) if local else "rifle"
                profile_enabled = bool(getattr(
                    settings, f"rcs_enabled_{weapon_class}", settings.no_recoil))
                profile_amount = float(getattr(
                    settings, f"rcs_amount_{weapon_class}", settings.recoil_strength))
                profile_smooth = float(getattr(
                    settings, f"rcs_smooth_{weapon_class}", settings.recoil_smooth))
                profile_start = int(getattr(
                    settings, f"rcs_start_{weapon_class}", settings.rcs_start_bullet))
                profile_x = float(getattr(
                    settings, f"rcs_x_{weapon_class}", settings.rcs_x))
                profile_y = float(getattr(
                    settings, f"rcs_y_{weapon_class}", settings.rcs_y))
                if not profile_enabled or shots < max(1, profile_start):
                    applied_pitch = applied_yaw = 0.0
                    pattern_last_shot = shots
                    last_tick = time.perf_counter()
                    self._pause(0.008)
                    continue

                if settings.rcs_mode == "Pattern RCS":
                    if shots != pattern_last_shot:
                        pattern = ((0, 3), (-1, 4), (1, 4), (-2, 5), (2, 5),
                                   (-2, 6), (1, 6), (2, 5), (-3, 5), (3, 4))
                        px, py = pattern[min(max(shots-1, 0), len(pattern)-1)]
                        strength = max(0.0, min(2.0, profile_amount / 100.0))
                        dx = round(px * strength * profile_x / 100.0)
                        dy = round(py * strength * profile_y / 100.0)
                        if dx or dy:
                            ctypes.windll.user32.mouse_event(0x0001, dx, dy, 0, 0)
                        pattern_last_shot = shots
                    applied_pitch = applied_yaw = 0.0
                    last_tick = time.perf_counter()
                    self._pause(0.002)
                    continue

                punch_service = self.pm.read_longlong(local + self.aim_punch_services)
                if not punch_service or punch_service < 0x10000:
                    applied_pitch = applied_yaw = 0.0
                    last_tick = time.perf_counter()
                    self._pause(0.008)
                    continue
                punch_pitch = (
                    self.pm.read_float(punch_service + self.predictable_punch)
                    + self.pm.read_float(punch_service + self.unpredictable_punch)
                )
                punch_yaw = (
                    self.pm.read_float(punch_service + self.predictable_punch + 4)
                    + self.pm.read_float(punch_service + self.unpredictable_punch + 4)
                )
                if (not math.isfinite(punch_pitch) or not math.isfinite(punch_yaw)
                        or abs(punch_pitch) > 20.0 or abs(punch_yaw) > 20.0):
                    applied_pitch = applied_yaw = 0.0
                    last_tick = time.perf_counter()
                    self._pause(0.02)
                    continue

                now = time.perf_counter()
                delta_time = max(0.0005, min(0.05, now - last_tick))
                last_tick = now
                # 100% is exact Source 2 aim-punch cancellation. Values above
                # 100 intentionally overdrive the correction for aggressive
                # profiles and compensate residual weapon/view-model rise.
                strength = max(0.0, min(2.0, profile_amount / 100.0))
                smooth = max(1.0, min(5.0, profile_smooth))
                # Both predictable recoil and the random aim-punch component are
                # already present in punch_pitch/yaw. Track their combined center.
                target_pitch = punch_pitch * 2.0 * strength * max(0.0, profile_y) / 100.0
                target_yaw = punch_yaw * 2.0 * strength * max(0.0, profile_x) / 100.0
                pitch_error = target_pitch - applied_pitch
                yaw_error = target_yaw - applied_yaw
                # Always filter the noisy punch component. A zero time constant
                # made low-smoothing profiles copy every sample directly and
                # produced visible downward jolts during automatic fire.
                time_constant = 0.002 + (smooth - 1.0) * 0.012
                alpha = 1.0 - math.exp(-delta_time / time_constant)
                next_pitch = applied_pitch + pitch_error * alpha
                next_yaw = applied_yaw + yaw_error * alpha

                # Apply only newly accumulated compensation so mouse movement
                # made between samples passes through untouched.
                pitch_correction = applied_pitch - next_pitch
                yaw_correction = applied_yaw - next_yaw
                # The previous 18 deg/s limiter lagged behind rifle punch and
                # made RCS look weak even at 100%. Keep spike protection while
                # allowing the controller to catch up inside the current shot.
                max_correction = max(0.05, 120.0 * delta_time)
                pitch_correction = max(-max_correction, min(max_correction, pitch_correction))
                yaw_correction = max(-max_correction, min(max_correction, yaw_correction))
                next_pitch = applied_pitch - pitch_correction
                next_yaw = applied_yaw - yaw_correction
                if abs(pitch_correction) > 14.0 or abs(yaw_correction) > 14.0:
                    applied_pitch, applied_yaw = target_pitch, target_yaw
                    self._pause(0.008)
                    continue
                with self._view_angle_lock:
                    angle_address = self.client + self.dw_view_angles
                    view_pitch, view_yaw = struct.unpack(
                        "<2f", self.pm.read_bytes(angle_address, 8))
                    new_pitch = max(-89.0, min(89.0, view_pitch + pitch_correction))
                    new_yaw = self._normalize_angle(view_yaw + yaw_correction)
                    if math.isfinite(new_pitch) and math.isfinite(new_yaw):
                        self.pm.write_bytes(
                            angle_address, struct.pack("<2f", new_pitch, new_yaw), 8)
                        applied_pitch, applied_yaw = next_pitch, next_yaw
            except Exception:
                now = time.monotonic()
                if now - last_log > 3:
                    logging.exception("RCS worker failed")
                    last_log = now
                applied_pitch = applied_yaw = 0.0
                last_tick = time.perf_counter()
                self._pause(0.1)
            self._pause(0.001)

    def no_shake_loop(self) -> None:
        def clear_view_punch() -> None:
            settings = self.state.get()
            if not settings.enabled or not settings.no_shake:
                self._pause(0.06)
                return
            local = self._current_local_pawn()
            if not local or self.pm.read_int(local + self.shots_fired) <= 0:
                self._pause(0.02)
                return
            camera = self.pm.read_longlong(local + self.camera_services) if local else 0
            if camera and camera > 0x10000:
                for offset in (0, 4, 8):
                    address = camera + self.view_punch + offset
                    if abs(self.pm.read_float(address)) > 0.0001:
                        self.pm.write_float(address, 0.0)

        self._guarded_loop("No Shake", clear_view_punch, 0.016)

    @staticmethod
    def _normalize_angle(value: float) -> float:
        while value > 180.0:
            value -= 360.0
        while value < -180.0:
            value += 360.0
        return value

    def vector_aim_loop(self) -> None:
        """Bone-based selection with sticky locking and adaptive smoothing."""
        locked_target = 0
        lock_started = 0.0
        last_target_lost = 0.0
        activation_started = 0.0
        pending_target = 0
        pending_since = 0.0
        aim_velocity_pitch = 0.0
        aim_velocity_yaw = 0.0
        last_aim_tick = 0.0

        def aim_tick() -> None:
            nonlocal locked_target, lock_started, last_target_lost, activation_started
            nonlocal pending_target, pending_since
            nonlocal aim_velocity_pitch, aim_velocity_yaw, last_aim_tick
            settings = self.state.get()
            if not settings.enabled or not (settings.aim_enabled or settings.auto_shoot):
                locked_target = 0
                activation_started = 0.0
                aim_velocity_pitch = aim_velocity_yaw = 0.0
                last_aim_tick = 0.0
                self._pause(0.06)
                return
            if (settings.aim_enabled and not settings.auto_shoot
                    and not self.hotkeys.active("aim", settings.aim_key, settings.aim_key_mode)):
                locked_target = 0
                activation_started = 0.0
                aim_velocity_pitch = aim_velocity_yaw = 0.0
                last_aim_tick = 0.0
                self._pause(0.008)
                return
            local = self._current_local_pawn()
            if not local:
                return
            now = time.monotonic()
            if activation_started <= 0.0:
                activation_started = now
            if (now - activation_started) * 1000.0 < max(0.0, settings.first_shot_delay):
                return
            weapon_class = self._active_weapon_class(local)
            base_fov = max(0.1, float(getattr(settings, f"aim_fov_{weapon_class}")))
            configured_smooth = max(1.0, float(getattr(settings, f"aim_smooth_{weapon_class}")))
            if locked_target and settings.lock_timeout > 0 and (now-lock_started)*1000.0 >= settings.lock_timeout:
                locked_target = 0
                last_target_lost = now
            local_node = self.pm.read_longlong(local + self.scene_node)
            if not local_node:
                return
            lx = self.pm.read_float(local_node + self.abs_origin)
            ly = self.pm.read_float(local_node + self.abs_origin + 4)
            local_origin_z = self.pm.read_float(local_node + self.abs_origin + 8)
            movement = self.pm.read_longlong(local + self.movement_services)
            duck_amount = (self.pm.read_float(movement + self.duck_amount)
                           if movement and movement > 0x10000 else 0.0)
            if not math.isfinite(duck_amount):
                duck_amount = 0.0
            duck_amount = max(0.0, min(1.0, duck_amount))
            # CS2 lowers the camera by about 18 units while crouching.
            lz = local_origin_z + 64.0 - duck_amount * 18.0
            current_pitch = self.pm.read_float(self.client + self.dw_view_angles)
            current_yaw = self.pm.read_float(self.client + self.dw_view_angles + 4)
            punch_pitch = punch_yaw = 0.0
            # Memory RCS already writes the punch delta to view angles. Applying
            # it here as well would double the vertical compensation.
            rcs_active = (settings.no_recoil and bool(getattr(
                settings, f"rcs_enabled_{weapon_class}", True)))
            if self.pm.read_int(local + self.shots_fired) > 0 and not rcs_active:
                punch_service = self.pm.read_longlong(local + self.aim_punch_services)
                if punch_service and punch_service > 0x10000:
                    punch_pitch = (self.pm.read_float(punch_service + self.predictable_punch)
                                   + self.pm.read_float(punch_service + self.unpredictable_punch))
                    punch_yaw = (self.pm.read_float(punch_service + self.predictable_punch + 4)
                                 + self.pm.read_float(punch_service + self.unpredictable_punch + 4))
                    if not math.isfinite(punch_pitch) or abs(punch_pitch) > 20.0:
                        punch_pitch = 0.0
                    if not math.isfinite(punch_yaw) or abs(punch_yaw) > 20.0:
                        punch_yaw = 0.0
            local_team = self.pm.read_int(local + self.team)
            local_player_index = self._local_player_index() if settings.visibility_check else 0
            if settings.visibility_check and not local_player_index:
                locked_target = 0
                return
            best: tuple[float, float, float, int] | None = None
            target_bones = {
                "head": 7,
                "neck": 6,
                "chest": 5,
                "stomach": 4,
                "pelvis": 3,
                "left shoulder": 8,
                "left arm": 9,
                "right shoulder": 13,
                "right arm": 14,
            }
            target_heights = {
                "head": 64.0,
                "neck": 58.0,
                "chest": 48.0,
                "stomach": 40.0,
                "pelvis": 34.0,
                "left shoulder": 52.0,
                "left arm": 45.0,
                "right shoulder": 52.0,
                "right arm": 45.0,
            }
            # Older configs used "body" for the lower torso.
            configured_part = settings.aim_target.strip().lower()
            selected_part = "stomach" if configured_part == "body" else configured_part
            nearest_part = selected_part == "nearest part"

            for pawn in self._pawns():
                health = self.pm.read_int(pawn + self.health)
                if (pawn == local or self.pm.read_int(pawn + self.life_state) != 256
                        or health <= 0 or health > 100):
                    continue
                if settings.ignore_teammates and self.pm.read_int(pawn + self.team) == local_team:
                    continue
                if (settings.visibility_check
                        and not self._visible_to_local(pawn, local_player_index)):
                    continue
                node = self.pm.read_longlong(pawn + self.scene_node)
                if not node:
                    continue
                origin_x = self.pm.read_float(node + self.abs_origin)
                origin_y = self.pm.read_float(node + self.abs_origin + 4)
                origin_z = self.pm.read_float(node + self.abs_origin + 8)
                movement = self.pm.read_longlong(pawn + self.movement_services)
                duck = self.pm.read_float(movement + self.duck_amount) if movement and movement > 0x10000 else 0.0
                duck = max(0.0, min(1.0, duck))
                if nearest_part:
                    parts = tuple(target_bones)
                elif settings.hitbox_fallback:
                    parts = tuple(dict.fromkeys((selected_part, "chest", "pelvis")))
                else:
                    parts = (selected_part,)
                if not nearest_part:
                    # A configured hitbox is strict. Fallback reconstructs that
                    # same point from origin; it does not compete with pelvis.
                    parts = (selected_part,)
                for part in parts:
                    bone_point = self._bone_position(pawn, target_bones.get(part, 6))
                    if bone_point:
                        dx, dy = bone_point[0] - lx, bone_point[1] - ly
                        point_z = bone_point[2]
                    elif nearest_part or not settings.hitbox_fallback:
                        continue
                    else:
                        dx, dy = origin_x - lx, origin_y - ly
                        crouch_drop = {
                            "head": 18.0, "neck": 16.0, "chest": 12.0,
                            "stomach": 8.0, "pelvis": 6.0,
                            "left shoulder": 13.0, "left arm": 10.0,
                            "right shoulder": 13.0, "right arm": 10.0,
                        }.get(part, 18.0)
                        point_z = origin_z + target_heights.get(part, 64.0) - duck * crouch_drop
                    horizontal = math.hypot(dx, dy)
                    if horizontal < 0.01:
                        continue
                    # Head keeps its existing multipoint coverage. Nearest-part
                    # compares bone centers so the chosen anatomical part is stable.
                    points = ((0.0, 0.0),)
                    if part == "head" and not nearest_part:
                        points = ((0.0, 0.0), (-3.2, 0.0), (3.2, 0.0),
                                  (-2.0, -2.0), (2.0, -2.0), (0.0, -2.5),
                                  (-1.2, -4.0), (1.2, -4.0))
                    side_x, side_y = -dy / horizontal, dx / horizontal
                    for lateral, vertical in points:
                        point_dx = dx + side_x * lateral
                        point_dy = dy + side_y * lateral
                        point_horizontal = math.hypot(point_dx, point_dy)
                        dz = point_z + vertical - lz
                        target_pitch = -math.degrees(math.atan2(dz, point_horizontal))
                        target_yaw = math.degrees(math.atan2(point_dy, point_dx))
                        pitch_delta = self._normalize_angle(target_pitch - punch_pitch * 2.0 - current_pitch)
                        yaw_delta = self._normalize_angle(target_yaw - punch_yaw * 2.0 - current_yaw)
                        angular_distance = math.hypot(pitch_delta, yaw_delta)
                        world_distance = math.sqrt(dx*dx + dy*dy + dz*dz) / 52.49
                        effective_fov = base_fov
                        if settings.dynamic_fov:
                            effective_fov *= max(0.55, min(1.35, 1.2 - world_distance / 220.0))
                        lock_bonus = min(2.0, effective_fov * 0.28) if settings.aim_lock and pawn == locked_target else 0.0
                        priority = settings.target_priority.lower()
                        if priority == "distance":
                            score = world_distance + angular_distance * 0.2
                        elif priority == "lowest hp":
                            score = health + angular_distance * 0.2
                        else:
                            score = angular_distance
                        score -= lock_bonus
                        switching = locked_target and pawn != locked_target
                        if switching and (now-last_target_lost)*1000.0 < settings.target_switch_delay:
                            continue
                        if angular_distance <= effective_fov and (best is None or score < best[0]):
                            best = score, pitch_delta, yaw_delta, pawn

            if best:
                if not locked_target and last_target_lost and (
                        now-last_target_lost)*1000.0 < max(0.0, settings.target_switch_delay):
                    return
                if locked_target and best[3] != locked_target:
                    if pending_target != best[3]:
                        pending_target, pending_since = best[3], now
                        return
                    if (now-pending_since)*1000.0 < max(0.0, settings.target_switch_delay):
                        return
                else:
                    pending_target = 0
                if best[3] != locked_target:
                    lock_started = now
                    aim_velocity_pitch = aim_velocity_yaw = 0.0
                    last_aim_tick = now
                locked_target = best[3]
                distance = math.hypot(best[1], best[2])
                if distance <= max(0.0, settings.aim_dead_zone):
                    aim_velocity_pitch = aim_velocity_yaw = 0.0
                    return
                dt = 0.004 if last_aim_tick <= 0.0 else max(0.001, min(0.025, now - last_aim_tick))
                last_aim_tick = now
                # Smooth 1 is the exact-lock profile. Higher values use a fast
                # velocity response without the old long inertial tail.
                if configured_smooth <= 1.05:
                    pitch_step, yaw_step = best[1], best[2]
                    aim_velocity_pitch = aim_velocity_yaw = 0.0
                else:
                    smooth_time = 0.008 + (configured_smooth - 1.0) * 0.012
                    response_time = max(0.006, smooth_time * 0.42)
                    velocity_blend = 1.0 - math.exp(-dt / response_time)
                    max_step = max(0.05, min(10.0, settings.aim_max_step))
                    max_speed = max_step / 0.004
                    desired_pitch_velocity = max(-max_speed, min(max_speed, best[1] / smooth_time))
                    desired_yaw_velocity = max(-max_speed, min(max_speed, best[2] / smooth_time))
                    aim_velocity_pitch += (desired_pitch_velocity - aim_velocity_pitch) * velocity_blend
                    aim_velocity_yaw += (desired_yaw_velocity - aim_velocity_yaw) * velocity_blend
                    pitch_step = aim_velocity_pitch * dt
                    yaw_step = aim_velocity_yaw * dt
                    if abs(pitch_step) >= abs(best[1]):
                        pitch_step = best[1]
                        aim_velocity_pitch = 0.0
                    if abs(yaw_step) >= abs(best[2]):
                        yaw_step = best[2]
                        aim_velocity_yaw = 0.0
                # With visibility filtering enabled, revalidate immediately
                # before writing so a stale lock cannot pull through a wall.
                if (settings.visibility_check
                        and not self._visible_to_local(locked_target, local_player_index)):
                    locked_target = 0
                    return
                with self._view_angle_lock:
                    angle_address = self.client + self.dw_view_angles
                    latest_pitch, latest_yaw = struct.unpack(
                        "<2f", self.pm.read_bytes(angle_address, 8))
                    if configured_smooth <= 1.05:
                        new_pitch = current_pitch + best[1]
                        new_yaw = current_yaw + best[2]
                    else:
                        new_pitch = latest_pitch + pitch_step
                        new_yaw = latest_yaw + yaw_step
                    new_pitch = max(-89.0, min(89.0, new_pitch))
                    new_yaw = self._normalize_angle(new_yaw)
                    self.pm.write_bytes(
                        angle_address, struct.pack("<2f", new_pitch, new_yaw), 8)
            else:
                if locked_target:
                    last_target_lost = now
                locked_target = 0
                aim_velocity_pitch = aim_velocity_yaw = 0.0
                last_aim_tick = 0.0

        self._guarded_loop("Vector Aim", aim_tick, 0.004)

    def radar_loop(self) -> None:
        def radar_tick() -> None:
            settings = self.state.get()
            if not settings.enabled or not settings.radar_hack:
                self._pause(0.12)
                return
            local = self._current_local_pawn()
            if not local:
                return
            local_team = self.pm.read_int(local + self.team)
            for pawn in self._pawns():
                if self.pm.read_int(pawn + self.life_state) == 256 and self.pm.read_int(pawn + self.team) != local_team:
                    self.pm.write_bool(pawn + self.spotted_state + self.spotted, True)

        self._guarded_loop("Radar Hack", radar_tick, 0.10)

    def skin_changer_loop(self) -> None:
        """Apply the selected finish to matching weapons owned by the current pawn."""
        last_apply: dict[int, tuple[tuple[object, ...], float]] = {}
        pending_initialize: set[int] = set()

        def skin_tick() -> None:
            settings = self.state.get()
            if not settings.enabled or not settings.skin_changer:
                last_apply.clear()
                pending_initialize.clear()
                self._pause(0.15)
                return
            raw_loadout = settings.skin_loadout or {
                settings.skin_weapon: {
                    "skin": settings.skin_name, "wear": settings.skin_wear,
                    "seed": settings.skin_seed, "stattrak": settings.skin_stattrak,
                }
            }
            selections: list[tuple[SkinFinish, tuple[object, ...], float, int, bool]] = []
            for weapon_name, entry in raw_loadout.items():
                if not isinstance(entry, dict):
                    continue
                skin_name = str(entry.get("skin", ""))
                finish = SKIN_CATALOG.get(weapon_name, {}).get(skin_name)
                if finish is None:
                    continue
                wear = max(0.0001, min(1.0, float(entry.get("wear", 0.08))))
                seed = max(0, min(1000, int(entry.get("seed", 1))))
                stattrak = bool(entry.get("stattrak", False))
                signature = (weapon_name, skin_name, wear, seed, stattrak)
                selections.append((finish, signature, wear, seed, stattrak))
            if not selections:
                return
            local = self._current_local_pawn()
            if not local:
                return
            services = self.pm.read_longlong(local + self.weapon_services)
            if not self._valid_user_pointer(services):
                return
            forced = self._skin_apply_event.is_set()
            if forced:
                self._skin_apply_event.clear()
            now = time.monotonic()
            live_handles: set[int] = set()
            for handle, weapon in self._local_weapon_entities(services):
                live_handles.add(handle)
                item = weapon + self.attribute_manager + self.econ_item
                definition = self.pm.read_short(item + self.item_definition) & 0xFFFF
                selection = next((value for value in selections
                                  if definition in value[0].accepted_definitions
                                  or definition == value[0].target_definition), None)
                if selection is None:
                    continue
                selected, signature, wear, seed, stattrak = selection
                previous = last_apply.get(handle)
                finishing_refresh = handle in pending_initialize
                configuration_changed = forced or previous is None or previous[0] != signature
                if not finishing_refresh and not configuration_changed and previous and now - previous[1] < 0.5:
                    continue
                self.pm.write_int(item + self.item_id_high, -1)
                quality = 3 if selected.target_definition in KNIFE_DEFINITIONS else (9 if stattrak else 0)
                self.pm.write_short(item + self.entity_quality, quality)
                if definition != selected.target_definition:
                    self.pm.write_short(item + self.item_definition, selected.target_definition)
                self.pm.write_int(weapon + self.fallback_paint_kit, selected.paint_kit)
                self.pm.write_int(weapon + self.fallback_seed, seed)
                self.pm.write_float(weapon + self.fallback_wear, wear)
                self.pm.write_int(weapon + self.fallback_stattrak, 1337 if stattrak else -1)
                self.pm.write_bool(item + self.restore_custom_material, True)
                if finishing_refresh:
                    self.pm.write_bool(item + self.item_initialized, True)
                    pending_initialize.discard(handle)
                elif configuration_changed:
                    self.pm.write_bool(item + self.item_initialized, False)
                    pending_initialize.add(handle)
                last_apply[handle] = (signature, now)
            for stale_handle in last_apply.keys() - live_handles:
                del last_apply[stale_handle]
                pending_initialize.discard(stale_handle)

        self._guarded_loop("Skin Changer", skin_tick, 0.08)

    def request_skin_refresh(self) -> None:
        self._skin_apply_event.set()

    def triggerbot_loop(self) -> None:
        semi_auto_cycle = {
            1: 0.225,   # Desert Eagle
            2: 0.120, 3: 0.150, 4: 0.150, 30: 0.120, 36: 0.150,
            61: 0.170, 64: 0.250,
            9: 0.950, 40: 0.800,
        }
        last_shot = 0.0
        candidate = 0
        candidate_since = 0.0
        mouse_down = False
        last_log = 0.0

        def release_fire() -> None:
            nonlocal mouse_down
            if mouse_down:
                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                mouse_down = False
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        ctypes.windll.user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        while not self.stop.is_set():
            try:
                settings = self.state.get()
                trigger_active = settings.triggerbot
                if not settings.enabled or not (trigger_active or settings.auto_shoot):
                    release_fire()
                    self._pause(0.08)
                    continue
                foreground = ctypes.windll.user32.GetForegroundWindow()
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
                if pid.value != self.pm.process_id:
                    release_fire()
                    self._pause(0.05)
                    continue
                local = self._current_local_pawn()
                index = self.pm.read_int(local + self.crosshair_entity) if local else 0
                target = self._entity_from_handle(index)
                if (not target or target == local or not self._is_player_pawn(target)
                        or not 1 <= self.pm.read_int(target + self.health) <= 100):
                    release_fire()
                    candidate = 0
                    self._pause(0.001)
                    continue
                if self.pm.read_int(target + self.life_state) != 256:
                    release_fire()
                    self._pause(0.001)
                    continue
                if settings.ignore_teammates and self.pm.read_int(target + self.team) == self.pm.read_int(local + self.team):
                    release_fire()
                    self._pause(0.001)
                    continue
                now = time.monotonic()
                if target != candidate:
                    candidate = target
                    candidate_since = now
                required_hold = max(0.0, min(0.20, settings.trigger_delay / 1000.0))
                if now - candidate_since < required_hold:
                    self._pause(0.002)
                    continue
                weapon_definition = self._active_weapon_definition(local)
                shot_interval = semi_auto_cycle.get(weapon_definition, 0.0)
                automatic_weapon = shot_interval <= 0.0
                if not automatic_weapon and now - last_shot < shot_interval:
                    self._pause(0.001)
                    continue

                released_movement: list[int] = []
                try:
                    if settings.auto_shoot and settings.auto_stop:
                        released_movement = [key for key in MOVEMENT_VKEYS if virtual_key_is_pressed(key)]
                        for key in released_movement:
                            send_virtual_key(key, False)
                        if released_movement:
                            self._pause(0.008)
                    # Confirm the direct game trace again after stopping/delay.
                    # If a wall or another entity entered the ray, cancel shot.
                    confirmed_index = self.pm.read_int(local + self.crosshair_entity)
                    confirmed_target = self._entity_from_handle(confirmed_index)
                    if (confirmed_target != target
                            or not self._is_player_pawn(confirmed_target)):
                        release_fire()
                        continue
                    if automatic_weapon:
                        if not mouse_down:
                            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                            mouse_down = True
                            last_shot = time.monotonic()
                    else:
                        release_fire()
                        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                        self._pause(0.008)
                        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                        last_shot = time.monotonic()
                finally:
                    for key in released_movement:
                        send_virtual_key(key, True)
            except Exception:
                release_fire()
                now = time.monotonic()
                if now - last_log > 3.0:
                    logging.exception("TriggerBot worker failed")
                    last_log = now
                self._pause(0.010)
            self._pause(0.001)
        release_fire()

    def _guarded_loop(self, name: str, action: Callable[[], None], interval: float) -> None:
        last_log = 0.0
        while not self.stop.is_set():
            if not self._process_alive():
                self.stop.set()
                break
            try:
                action()
            except Exception:
                now = time.monotonic()
                if now - last_log > 3:
                    logging.exception("Ошибка модуля %s", name)
                    last_log = now
                self._pause(0.1)
            self._pause(interval)


class FovOverlay:
    KEY = "#010101"

    def __init__(self, root: tk.Tk, cheats: Cheats, state: StateStore):
        self.root, self.cheats, self.state = root, cheats, state
        self.game_hwnd = 0
        self.snapshot_lock = threading.Lock()
        self.snapshot: list[tuple[
            float, float, float, int, int, str, str, float,
            tuple[tuple[float, float, float] | None, ...], int,
        ]] = []
        self.snapshot_matrix: list[float] = []
        self.world_snapshot: list[tuple[float, float, float, str]] = []
        self.bomb_snapshot: tuple[float, float, float, float, str, bool, float] | None = None
        self.snapshot_time = 0.0
        self.read_time_ms = 0.0
        self.entities_processed = 0
        self._screenshot_hidden_until = 0.0
        self.frame_counter = 0
        self.fps_value = 0
        self.fps_timer = time.monotonic()
        self.is_visible = False
        self.last_geometry = ""
        self.menu_visible_getter: Callable[[], bool] = lambda: False
        self.menu_hwnd_getter: Callable[[], int] = lambda: 0
        self.splash_state_getter: Callable[[], tuple[bool, float, float]] = lambda: (False, 1.0, 0.0)
        self.last_window_alpha = 1.0
        self.menu_particles = [
            [random.random(), random.random(), random.uniform(0.00015, 0.00055), random.choice((1, 1, 1, 2))]
            for _ in range(28)
        ]
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=self.KEY)
        self.window.wm_attributes("-transparentcolor", self.KEY)
        self.canvas = tk.Canvas(self.window, bg=self.KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.window.update_idletasks()
        # winfo_id may point to Tk's child wrapper; styles must be applied to
        # the real top-level HWND or the transparent canvas will eat clicks.
        get_ancestor = ctypes.windll.user32.GetAncestor
        get_ancestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        get_ancestor.restype = ctypes.c_void_p
        hwnd = get_ancestor(self.window.winfo_id(), 2)
        self.overlay_hwnd = hwnd or self.window.winfo_id()
        get_style = ctypes.windll.user32.GetWindowLongPtrW
        set_style = ctypes.windll.user32.SetWindowLongPtrW
        get_style.argtypes = (ctypes.c_void_p, ctypes.c_int)
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
        set_style.restype = ctypes.c_ssize_t
        style = get_style(self.overlay_hwnd, -20)
        set_style(self.overlay_hwnd, -20, style | 0x20 | 0x80 | 0x80000 | 0x08000000)
        set_window_pos = ctypes.windll.user32.SetWindowPos
        set_window_pos.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_uint)
        set_window_pos.restype = ctypes.c_bool
        set_window_pos(
            self.overlay_hwnd, -1, 0, 0, 0, 0,
            0x0001 | 0x0002 | 0x0010 | 0x0020 | 0x0040,
        )
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        threading.Thread(target=self._collect_loop, name="esp-snapshot", daemon=True).start()
        root.after(50, self.update)

    def _collect_loop(self) -> None:
        next_world_update = 0.0
        while not self.cheats.stop.is_set():
            started = time.perf_counter()
            try:
                settings = self.state.get()
                if not settings.enabled or not (
                        settings.box_esp or settings.esp_skeleton or settings.world_bomb_esp
                        or settings.world_bomb_info or settings.world_weapon_esp):
                    with self.snapshot_lock:
                        self.snapshot = []
                    self.cheats.stop.wait(0.10)
                    continue
                local = self.cheats._current_local_pawn()
                if not local:
                    self.cheats.stop.wait(0.05)
                    continue
                local_team = self.cheats.pm.read_int(local + self.cheats.team)
                lx = ly = lz = 0.0
                if settings.esp_distance:
                    local_node = self.cheats.pm.read_longlong(local + self.cheats.scene_node)
                    if local_node:
                        lx = self.cheats.pm.read_float(local_node + self.cheats.abs_origin)
                        ly = self.cheats.pm.read_float(local_node + self.cheats.abs_origin + 4)
                        lz = self.cheats.pm.read_float(local_node + self.cheats.abs_origin + 8)
                entities: list[tuple[
                    float, float, float, int, int, str, str, float,
                    tuple[tuple[float, float, float] | None, ...], int,
                ]] = []
                for controller, pawn in self.cheats._player_records():
                    if pawn == local or self.cheats.pm.read_int(pawn + self.cheats.life_state) != 256:
                        continue
                    same_team = self.cheats.pm.read_int(pawn + self.cheats.team) == local_team
                    if (same_team and (settings.ignore_teammates or not settings.esp_allies)
                            or not same_team and not settings.esp_enemies):
                        continue
                    node = self.cheats.pm.read_longlong(pawn + self.cheats.scene_node)
                    if not node:
                        continue
                    px = self.cheats.pm.read_float(node + self.cheats.abs_origin)
                    py = self.cheats.pm.read_float(node + self.cheats.abs_origin + 4)
                    pz = self.cheats.pm.read_float(node + self.cheats.abs_origin + 8)
                    hp = max(0, min(100, self.cheats.pm.read_int(pawn + self.cheats.health))) if settings.esp_health else 100
                    armor = max(0, min(100, self.cheats.pm.read_int(pawn + self.cheats.armor))) if settings.esp_armor else 0
                    name = "Enemy"
                    if settings.esp_name:
                        name_ptr = self.cheats.pm.read_longlong(controller + self.cheats.player_name)
                        name = self.cheats.pm.read_string(name_ptr, 32) if name_ptr > 0x10000 else "Enemy"
                    weapon_name = "Weapon"
                    if settings.esp_weapon:
                        services = self.cheats.pm.read_longlong(pawn + self.cheats.weapon_services)
                        handle = self.cheats.pm.read_int(services + self.cheats.active_weapon) if services else 0
                        weapon = self.cheats._entity_from_handle(handle)
                        if weapon:
                            item = weapon + self.cheats.attribute_manager + self.cheats.econ_item
                            definition = self.cheats.pm.read_short(item + self.cheats.item_definition) & 0xFFFF
                            weapon_name = WEAPON_NAMES_BY_ID.get(definition, "Weapon")
                    distance = (math.sqrt((px-lx)**2 + (py-ly)**2 + (pz-lz)**2) / 52.49
                                if settings.esp_distance else 0.0)
                    if settings.esp_skeleton:
                        bones = self.cheats._bone_positions(
                            node, (px, py, pz), SKELETON_BONES)
                    else:
                        bones = ()
                    entities.append((px, py, pz, hp, armor, name[:24], weapon_name,
                                     distance, bones, node))

                now = time.monotonic()
                update_world = now >= next_world_update
                with self.snapshot_lock:
                    world_entities = list(self.world_snapshot)
                    bomb_info = self.bomb_snapshot
                if update_world:
                    next_world_update = now + 1.0 / max(1, min(120, int(settings.world_rate)))
                    world_entities = []
                    bomb_info = None
                if update_world and settings.world_weapon_esp:
                    entity_list = self.cheats.pm.read_longlong(
                        self.cheats.client + self.cheats.dw_entity_list)
                    highest = self.cheats.pm.read_int(
                        self.cheats.client + self.cheats.dw_highest_entity_index)
                    for index in range(65, max(65, min(highest, 2048)) + 1):
                        try:
                            entry = self.cheats.pm.read_longlong(
                                entity_list + 8 * (index >> 9) + 16)
                            entity = (self.cheats.pm.read_longlong(
                                entry + 112 * (index & 0x1FF)) if entry else 0)
                            if not entity:
                                continue
                            owner = self.cheats.pm.read_int(entity + self.cheats.owner_entity)
                            if owner not in (0, -1):
                                continue
                            item = entity + self.cheats.attribute_manager + self.cheats.econ_item
                            definition = self.cheats.pm.read_short(
                                item + self.cheats.item_definition) & 0xFFFF
                            label = WEAPON_NAMES_BY_ID.get(definition)
                            if not label:
                                continue
                            node = self.cheats.pm.read_longlong(entity + self.cheats.scene_node)
                            if not node:
                                continue
                            point = (
                                self.cheats.pm.read_float(node + self.cheats.abs_origin),
                                self.cheats.pm.read_float(node + self.cheats.abs_origin + 4),
                                self.cheats.pm.read_float(node + self.cheats.abs_origin + 8),
                            )
                            if all(math.isfinite(value) and abs(value) < 100000.0 for value in point):
                                world_entities.append((*point, label))
                        except Exception:
                            continue

                if update_world and (settings.world_bomb_esp or settings.world_bomb_info):
                    bomb = self.cheats.pm.read_longlong(
                        self.cheats.client + self.cheats.dw_planted_c4)
                    if bomb and bomb > 0x10000:
                        ticking = self.cheats.pm.read_bool(bomb + self.cheats.c4_ticking)
                        defused = self.cheats.pm.read_bool(bomb + self.cheats.c4_defused)
                        exploded = self.cheats.pm.read_bool(bomb + self.cheats.c4_exploded)
                        if ticking and not defused and not exploded:
                            node = self.cheats.pm.read_longlong(bomb + self.cheats.scene_node)
                            game_time = self.cheats._game_time()
                            if node and game_time is not None:
                                bx = self.cheats.pm.read_float(node + self.cheats.abs_origin)
                                by = self.cheats.pm.read_float(node + self.cheats.abs_origin + 4)
                                bz = self.cheats.pm.read_float(node + self.cheats.abs_origin + 8)
                                timer_length = self.cheats.pm.read_float(
                                    bomb + self.cheats.c4_timer_length)
                                remaining = self.cheats.pm.read_float(
                                    bomb + self.cheats.c4_blow_time) - game_time
                                maximum = (timer_length + 0.25 if math.isfinite(timer_length)
                                           and 5.0 <= timer_length <= 90.0 else 90.0)
                                if math.isfinite(remaining) and 0.0 <= remaining <= maximum:
                                    defusing = self.cheats.pm.read_bool(
                                        bomb + self.cheats.c4_defusing)
                                    defuse_remaining = (max(0.0, self.cheats.pm.read_float(
                                        bomb + self.cheats.c4_defuse_end) - game_time)
                                        if defusing else 0.0)
                                    site = "B" if self.cheats.pm.read_int(
                                        bomb + self.cheats.c4_site) else "A"
                                    bomb_info = (bx, by, bz, remaining, site,
                                                 defusing, defuse_remaining)
                matrix_address = self.cheats.client + self.cheats.dw_view_matrix
                matrix = list(struct.unpack(
                    "<16f", self.cheats.pm.read_bytes(matrix_address, 64)))
                with self.snapshot_lock:
                    self.snapshot = entities
                    self.world_snapshot = world_entities
                    self.bomb_snapshot = bomb_info
                    self.snapshot_matrix = matrix
                    self.snapshot_time = time.monotonic()
                    self.entities_processed = len(entities) + len(world_entities)
                    self.read_time_ms = (time.perf_counter() - started) * 1000.0
            except Exception:
                # A single failed RPM must not produce an empty ESP frame.
                # The next successful collector pass atomically replaces this
                # last-known-good snapshot; normal filters still publish [].
                pass
            rate = max(1, min(360, int(self.state.get().esp_rate)))
            self.cheats.stop.wait(max(0.001, 1.0 / rate - (time.perf_counter() - started)))

    def _rect(self) -> tuple[int, int, int, int] | None:
        if not self.game_hwnd or not ctypes.windll.user32.IsWindow(self.game_hwnd):
            windows: list[int] = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def callback(hwnd: int, _data: int) -> bool:
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == self.cheats.pm.process_id and ctypes.windll.user32.IsWindowVisible(hwnd):
                    windows.append(hwnd)
                    return False
                return True
            ctypes.windll.user32.EnumWindows(callback_type(callback), 0)
            if not windows:
                return None
            self.game_hwnd = windows[0]
        rect, point = ctypes.wintypes.RECT(), ctypes.wintypes.POINT(0, 0)
        ctypes.windll.user32.GetClientRect(self.game_hwnd, ctypes.byref(rect))
        ctypes.windll.user32.ClientToScreen(self.game_hwnd, ctypes.byref(point))
        return point.x, point.y, rect.right, rect.bottom

    @staticmethod
    def _project(position: tuple[float, float, float], matrix: list[float],
                 width: int, height: int) -> tuple[float, float] | None:
        x, y, z = position
        clip_x = x * matrix[0] + y * matrix[1] + z * matrix[2] + matrix[3]
        clip_y = x * matrix[4] + y * matrix[5] + z * matrix[6] + matrix[7]
        clip_w = x * matrix[12] + y * matrix[13] + z * matrix[14] + matrix[15]
        if clip_w <= 0.01:
            return None
        return width * 0.5 * (1 + clip_x / clip_w), height * 0.5 * (1 - clip_y / clip_w)

    @staticmethod
    def _screen_skeleton(head: tuple[float, float], feet: tuple[float, float],
                         box_width: float) -> tuple[tuple[float, float], ...]:
        cx, top, bottom = head[0], head[1], feet[1]
        height = max(1.0, bottom - top)
        y = lambda ratio: top + height * ratio
        shoulder, elbow = box_width * 0.30, box_width * 0.40
        hip, knee, foot = box_width * 0.20, box_width * 0.22, box_width * 0.20
        return (
            (cx, y(0.10)), (cx, y(0.20)), (cx, y(0.32)), (cx, y(0.45)), (cx, y(0.50)),
            (cx-shoulder, y(0.25)), (cx-elbow, y(0.40)), (cx-elbow, y(0.55)),
            (cx+shoulder, y(0.25)), (cx+elbow, y(0.40)), (cx+elbow, y(0.55)),
            (cx-hip, y(0.50)), (cx-knee, y(0.75)), (cx-foot, bottom),
            (cx+hip, y(0.50)), (cx+knee, y(0.75)), (cx+foot, bottom),
        )

    def _drag_overlay_elements(self, settings: Settings, width: int, height: int, menu_open: bool) -> None:
        down = bool(ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000)
        target = getattr(self, "drag_target", None)
        if not menu_open:
            self.drag_target, self.drag_button_down = None, down
            return
        rect = self._rect()
        if not rect: return
        point = ctypes.wintypes.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        mx, my = point.x-rect[0], point.y-rect[1]
        boxes = [("watermark", settings.watermark_x, settings.watermark_y, 152, 26),
                 ("hud", settings.hud_x, settings.hud_y, 360, 28),
                 ("bomb_hud", settings.bomb_hud_x, settings.bomb_hud_y, 300, 48)]
        previous = getattr(self, "drag_button_down", False)
        if down and not previous:
            for name,x,y,w,h in reversed(boxes):
                if x<=mx<=x+w and y<=my<=y+h:
                    self.drag_target=name; self.drag_offset=(mx-x,my-y); break
        elif down and target:
            w,h={"watermark":(152,26),"hud":(360,28),"bomb_hud":(300,48)}[target]
            ox,oy=self.drag_offset
            self.state.set(**{target+"_x":max(0,min(width-w,mx-ox)),target+"_y":max(0,min(height-h,my-oy))})
        elif not down: self.drag_target=None
        self.drag_button_down=down

    def update(self) -> None:
        next_delay = 100
        try:
            settings = self.state.get()
            if settings.screenshot_cleanup and (ctypes.windll.user32.GetAsyncKeyState(0x2C) & 1):
                self._screenshot_hidden_until = time.monotonic() + 0.45
            foreground = ctypes.windll.user32.GetForegroundWindow()
            menu_hwnd = self.menu_hwnd_getter()
            game_active = bool(self.game_hwnd and foreground in (self.game_hwnd, menu_hwnd, self.overlay_hwnd))
            if not self.game_hwnd:
                self._rect()  # Resolve it once before checking the foreground window.
                foreground = ctypes.windll.user32.GetForegroundWindow()
                menu_hwnd = self.menu_hwnd_getter()
                game_active = bool(self.game_hwnd and foreground in (self.game_hwnd, menu_hwnd, self.overlay_hwnd))
            draw_fov = (settings.aim_enabled or settings.auto_shoot) and settings.show_fov
            menu_open = self.menu_visible_getter()
            splash_open, splash_opacity, text_level = self.splash_state_getter()
            extras = (settings.crosshair_enabled or settings.watermark or settings.overlay_fps
                      or settings.overlay_clock or settings.aim_indicator
                      or settings.hud_enabled or settings.world_bomb_esp
                      or settings.world_bomb_info or settings.world_weapon_esp
                      or menu_open or splash_open)
            screenshot_hidden = time.monotonic() < self._screenshot_hidden_until
            rect = (self._rect() if settings.enabled and not screenshot_hidden
                    and (draw_fov or settings.box_esp or settings.esp_skeleton or extras)
                    and game_active else None)
            if not rect:
                if self.is_visible:
                    self.window.withdraw()
                    self.is_visible = False
            else:
                # ESP needs smooth updates; a menu/splash can run slower without
                # wasting CPU on an otherwise static background.
                next_delay = 33 if (menu_open or splash_open) else 25
                x, y, width, height = rect
                self._drag_overlay_elements(settings, width, height, menu_open)
                geometry = f"{width}x{height}+{x}+{y}"
                if geometry != self.last_geometry:
                    self.window.geometry(geometry)
                    self.last_geometry = geometry
                if not self.is_visible:
                    self.window.deiconify()
                    self.is_visible = True
                self.canvas.delete("all")
                desired_alpha = max(0.01, min(1.0, splash_opacity)) if splash_open else 1.0
                if abs(desired_alpha - self.last_window_alpha) > 0.015:
                    self.window.attributes("-alpha", desired_alpha)
                    self.last_window_alpha = desired_alpha
                if splash_open:
                    self.canvas.create_rectangle(0, 0, width, height, fill="#000000", outline="")
                elif menu_open:
                    # Stipple keeps the window layered/click-through while
                    # producing a lightweight translucent dimming effect.
                    self.canvas.create_rectangle(0, 0, width, height, fill="#050505",
                                                 outline="", stipple="gray12")
                if splash_open:
                    cx, cy = width/2, height/2
                    shade = max(20, min(255, int(255 * text_level)))
                    main = f"#{shade:02x}{shade:02x}{shade:02x}"
                    sub_value = max(18, min(170, int(170 * text_level)))
                    sub = f"#{sub_value:02x}{sub_value:02x}{sub_value:02x}"
                    self.canvas.create_text(cx, cy-18, text="LUNA",
                                            fill=main, font=(design.FONT_UI, 23, "bold"))
                    self.canvas.create_line(cx-112, cy+18, cx+112, cy+18, fill=sub, width=1)
                    self.canvas.create_text(cx, cy+38, text="DESKTOP CONTROL UTILITY",
                                            fill=sub, font=(design.FONT_MONO, 8))
                self.frame_counter += 1
                now = time.monotonic()
                if now - self.fps_timer >= 1.0:
                    self.fps_value = round(self.frame_counter / (now - self.fps_timer))
                    self.frame_counter = 0
                    self.fps_timer = now
                if settings.watermark:
                    self.canvas.create_rectangle(settings.watermark_x, settings.watermark_y, settings.watermark_x+152, settings.watermark_y+26, fill=design.SURFACE, outline=design.BORDER_STRONG)
                    self.canvas.create_rectangle(settings.watermark_x, settings.watermark_y, settings.watermark_x+3, settings.watermark_y+26, fill=design.ACCENT, outline=design.ACCENT)
                    self.canvas.create_text(settings.watermark_x+11, settings.watermark_y+13, anchor="w", text="LUNA  /  CS2",
                                            fill=design.TEXT, font=(design.FONT_UI, 8, "bold"))
                if settings.overlay_fps:
                    self.canvas.create_text(width-12, 16, anchor="ne", text=f"ESP {self.fps_value} FPS",
                                            fill=settings.name_color, font=("Consolas", 8, "bold"))
                if settings.overlay_clock:
                    self.canvas.create_text(width-12, 32, anchor="ne", text=time.strftime("%H:%M:%S"),
                                            fill=settings.name_color, font=("Consolas", 8))
                if settings.aim_indicator and (settings.aim_enabled or settings.auto_shoot):
                    indicator = "AIM  ACTIVE"
                    self.canvas.create_text(width/2, height-18, text=indicator,
                                            fill="#ffffff" if aim_active else "#777777",
                                            font=("Consolas", 8, "bold"))
                if settings.crosshair_enabled:
                    cx, cy, size = width/2, height/2, settings.crosshair_size
                    self.canvas.create_line(cx-size, cy, cx-2, cy, fill=settings.crosshair_color, width=1)
                    self.canvas.create_line(cx+2, cy, cx+size, cy, fill=settings.crosshair_color, width=1)
                    self.canvas.create_line(cx, cy-size, cx, cy-2, fill=settings.crosshair_color, width=1)
                    self.canvas.create_line(cx, cy+2, cx, cy+size, fill=settings.crosshair_color, width=1)
                if draw_fov:
                    radius = math.tan(math.radians(settings.aim_fov)) / math.tan(math.radians(45.0)) * width / 2
                    cx, cy = width / 2, height / 2
                    self.canvas.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, outline=settings.fov_color, width=1)
                if (settings.world_bomb_esp or settings.world_bomb_info
                        or settings.world_weapon_esp or settings.hud_enabled):
                    with self.snapshot_lock:
                        world_entities = list(self.world_snapshot)
                        bomb_info = self.bomb_snapshot
                        world_matrix = list(self.snapshot_matrix)
                    if len(world_matrix) == 16:
                        if settings.world_weapon_esp:
                            for wx, wy, wz, label in world_entities:
                                screen = self._project((wx, wy, wz), world_matrix, width, height)
                                if screen:
                                    self.canvas.create_text(
                                        screen[0], screen[1], text=f"? {label}",
                                        fill=settings.world_color, font=(design.FONT_UI, 8, "bold"),
                                    )
                        if settings.world_bomb_esp and bomb_info:
                            bx, by, bz, remaining, site, _defusing, _defuse_left = bomb_info
                            screen = self._project((bx, by, bz), world_matrix, width, height)
                            if screen:
                                self.canvas.create_rectangle(screen[0]-8, screen[1]-7,
                                                             screen[0]+5, screen[1]+7,
                                                             outline=settings.world_color, width=2)
                                self.canvas.create_line(screen[0]-4, screen[1]-7,
                                                        screen[0]+8, screen[1]-13,
                                                        fill=settings.world_color, width=1)
                                self.canvas.create_text(
                                    screen[0]+12, screen[1], anchor="w", text=f"{remaining:04.1f}s",
                                    fill="#ff4d4d" if remaining <= 10.0 else settings.world_color,
                                    font=(design.FONT_MONO, 10, "bold"),
                                )
                    if settings.hud_enabled:
                        hud_text = (
                            f"FPS {self.fps_value:>3}   AIM {'ON' if settings.aim_enabled else 'OFF'}"
                            f"   RCS {'ON' if settings.no_recoil else 'OFF'}"
                            f"   TRG {'ON' if settings.triggerbot else 'OFF'}"
                        )
                        self.canvas.create_rectangle(
                            settings.hud_x, settings.hud_y, settings.hud_x+360, settings.hud_y+28,
                            fill=design.SURFACE, outline=design.BORDER_STRONG,
                        )
                        self.canvas.create_text(
                            settings.hud_x+180, settings.hud_y+14, text=hud_text, fill=design.TEXT,
                            font=(design.FONT_MONO, 9, "bold"),
                        )
                    if settings.world_bomb_info and bomb_info:
                        _bx, _by, _bz, remaining, site, defusing, defuse_left = bomb_info
                        critical = remaining <= 10.0
                        status = (f"DEFUSING  {defuse_left:04.1f}s"
                                  if defusing else "PLANTED")
                        outcome = ("  SAFE" if defusing and defuse_left < remaining
                                   else "  TOO LATE" if defusing else "")
                        color = "#ff4d4d" if critical else settings.world_color
                        left, top = settings.bomb_hud_x, settings.bomb_hud_y
                        self.canvas.create_rectangle(
                            left, top, left+300, top+48,
                            fill=design.SURFACE, outline=color, width=2,
                        )
                        self.canvas.create_text(
                            left+150, top+15,
                            text=f"BOMB {site}   {remaining:04.1f}s",
                            fill=color, font=(design.FONT_MONO, 12, "bold"),
                        )
                        self.canvas.create_text(
                            left+150, top+34, text=status + outcome,
                            fill=design.TEXT, font=(design.FONT_MONO, 8, "bold"),
                        )

                if settings.box_esp or settings.esp_skeleton:
                    with self.snapshot_lock:
                        entities = list(self.snapshot)
                        matrix = list(self.snapshot_matrix)
                        snapshot_fresh = time.monotonic() - self.snapshot_time < 0.15
                    if snapshot_fresh and len(matrix) == 16:
                      for px, py, pz, hp, armor, name, weapon_name, distance, bones, _node in entities:
                        feet = self._project((px, py, pz), matrix, width, height)
                        head = self._project((px, py, pz + 64.0), matrix, width, height)
                        if not feet or not head:
                            continue
                        box_h = abs(feet[1] - head[1])
                        if box_h < 5 or box_h > height:
                            continue
                        box_w = box_h * 0.46
                        color = settings.box_color
                        left, right = head[0]-box_w/2, head[0]+box_w/2
                        if settings.box_esp and settings.esp_fill:
                            self.canvas.create_rectangle(left, head[1], right, feet[1], fill=settings.box_color,
                                                         outline="", stipple="gray50" if settings.box_fill_alpha >= 35 else "gray25")
                        if settings.box_esp:
                            if settings.box_style == "corner":
                                ratio = settings.corner_length / 100.0
                                x_len, y_len = max(6, box_w*ratio), max(6, box_h*ratio*.5)
                                for x1, y1, x2, y2 in (
                                    (left, head[1], left+x_len, head[1]), (left, head[1], left, head[1]+y_len),
                                    (right, head[1], right-x_len, head[1]), (right, head[1], right, head[1]+y_len),
                                    (left, feet[1], left+x_len, feet[1]), (left, feet[1], left, feet[1]-y_len),
                                    (right, feet[1], right-x_len, feet[1]), (right, feet[1], right, feet[1]-y_len),
                                ):
                                    self.canvas.create_line(x1, y1, x2, y2, fill=color, width=2)
                            else:
                                self.canvas.create_rectangle(left, head[1], right, feet[1], outline=color, width=2)
                        if settings.esp_skeleton and bones:
                            projected = [self._project(point, matrix, width, height) if point else None
                                         for point in bones]
                            for first, second in SKELETON_CONNECTIONS:
                                start_point, end_point = projected[first], projected[second]
                                if start_point and end_point:
                                    self.canvas.create_line(*start_point, *end_point,
                                                            fill="#090B10", width=4)
                                    self.canvas.create_line(*start_point, *end_point,
                                                            fill=settings.skeleton_color, width=2)
                        if settings.esp_name:
                            self.canvas.create_text(head[0], head[1]-9, text=name, fill=settings.name_color,
                                                    font=("Segoe UI", 8, "bold"))
                        if settings.esp_health:
                            bar_x = left - 6
                            self.canvas.create_rectangle(bar_x-2, head[1], bar_x+1, feet[1], fill="#17171b", outline="")
                            hp_top = feet[1] - box_h * hp / 100
                            hp_color = settings.hp_color if not settings.health_color else f"#{255-hp*255//100:02x}{hp*255//100:02x}30"
                            self.canvas.create_rectangle(bar_x-1, hp_top, bar_x, feet[1], fill=hp_color, outline="")
                            if hp < 100:
                                self.canvas.create_text(bar_x-5, hp_top, text=str(hp), anchor="e", fill="#ffffff",
                                                        font=("Segoe UI", 7, "bold"))
                        if settings.esp_armor and armor > 0:
                            armor_y = feet[1] + 4
                            self.canvas.create_rectangle(left, armor_y, right, armor_y+2, fill="#181a20", outline="")
                            self.canvas.create_rectangle(left, armor_y, left + box_w * armor / 100,
                                                         armor_y+2, fill=settings.armor_color, outline="")
                        if settings.esp_weapon:
                            cy = feet[1] + 12
                            self.canvas.create_rectangle(head[0]-8, cy-3, head[0]+7, cy+2,
                                                         outline=settings.weapon_color, width=1)
                            self.canvas.create_line(head[0]+7, cy-1, head[0]+16, cy-1,
                                                    fill=settings.weapon_color, width=2)
                            self.canvas.create_line(head[0]-8, cy, head[0]-14, cy+4,
                                                    fill=settings.weapon_color, width=2)
                            self.canvas.create_line(head[0]-2, cy+2, head[0]+1, cy+7,
                                                    fill=settings.weapon_color, width=2)
                        if settings.esp_distance:
                            self.canvas.create_text(head[0], feet[1]+24, text=f"{distance:.0f} m", fill=settings.name_color,
                                                    font=("Segoe UI", 7))
                        if settings.esp_snapline:
                            self.canvas.create_line(width/2, height-2, head[0], feet[1], fill=settings.line_color, width=1)
                        if settings.esp_head_dot:
                            dot = max(2.0, box_w * 0.08)
                            self.canvas.create_oval(head[0]-dot, head[1]-dot, head[0]+dot, head[1]+dot,
                                                    fill=settings.box_color, outline="")
        except Exception:
            if self.is_visible:
                self.window.withdraw()
                self.is_visible = False
        if not self.cheats.stop.is_set():
            self.window.after(next_delay, self.update)


class InterfaceStateView:
    """Settings view that keeps player ESP out of the Tkinter layer."""

    def __init__(self, source: StateStore):
        self.source = source

    def get(self) -> Settings:
        # Player/world visuals and the live FPS counter belong to Dear PyGui.
        # Keeping them out of the GDI layer prevents duplicate fullscreen work.
        return replace(self.source.get(), box_esp=False, overlay_fps=False)


class DearFovOverlay(FovOverlay):
    """GPU-backed Dear PyGui overlay used by the performance-test build."""

    TITLE = "Luna GPU Overlay"
    HUD_BG = (15, 17, 22, 232)
    HUD_BORDER = (105, 110, 122, 220)
    HUD_ACCENT = (230, 84, 63, 255)
    HUD_TEXT = (242, 240, 234, 255)
    HUD_MUTED = (170, 174, 184, 255)

    def __init__(self, root: tk.Tk, cheats: Cheats, state: StateStore):
        self.root, self.cheats, self.state = root, cheats, state
        self.game_hwnd = 0
        self.overlay_hwnd = 0
        self.snapshot_lock = threading.Lock()
        self.snapshot: list[tuple[
            float, float, float, int, int, str, str, float,
            tuple[tuple[float, float, float] | None, ...], int,
        ]] = []
        self.snapshot_matrix: list[float] = []
        self.world_snapshot: list[tuple[float, float, float, str]] = []
        self.bomb_snapshot: tuple[float, float, float, float, str, bool, float] | None = None
        self.snapshot_time = 0.0
        self.read_time_ms = 0.0
        self.entities_processed = 0
        self._screenshot_hidden_until = 0.0
        self.frame_counter = 0
        self.fps_value = 0
        self.fps_timer = time.monotonic()
        self.is_visible = False
        self.weapon_textures: dict[str, str] = {}
        self.last_geometry: tuple[int, int, int, int] | None = None
        self.menu_visible_getter: Callable[[], bool] = lambda: False
        self.menu_hwnd_getter: Callable[[], int] = lambda: 0
        self.splash_state_getter: Callable[[], tuple[bool, float, float]] = lambda: (False, 1.0, 0.0)
        self.menu_particles = [
            [random.random(), random.random(), random.uniform(0.00015, 0.00055), random.choice((1, 1, 1, 2))]
            for _ in range(28)
        ]
        threading.Thread(target=self._collect_loop, name="esp-snapshot-gpu", daemon=True).start()
        threading.Thread(target=self._render_loop, name="dearpygui-overlay", daemon=True).start()

    def _read_view_matrix(self) -> list[float]:
        """Read one coherent camera matrix immediately before frame projection."""
        address = self.cheats.client + self.cheats.dw_view_matrix
        try:
            values = struct.unpack("<16f", self.cheats.pm.read_bytes(address, 64))
            if all(math.isfinite(value) for value in values):
                return list(values)
        except Exception:
            pass
        with self.snapshot_lock:
            return list(self.snapshot_matrix)

    @staticmethod
    def _rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
        if not valid_hex_color(value):
            value = "#ffffff"
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16), alpha

    @staticmethod
    def _gpu_text(position: tuple[float, float], value: str,
                  color: tuple[int, int, int, int], size: int) -> None:
        """FluxWare-style outlined text for reliable readability in DPG."""
        x, y = position
        dpg.draw_text((x+1, y+1), value, parent="gpu_draw",
                      color=(0, 0, 0, 235), size=size)
        dpg.draw_text((x, y), value, parent="gpu_draw", color=color, size=size)

    @staticmethod
    def _gpu_corners(left: float, top: float, right: float, bottom: float,
                     color: tuple[int, int, int, int], length: float,
                     thickness: float = 1.5) -> None:
        ratio = length / 100.0
        x_len = max(6.0, (right-left) * ratio)
        y_len = max(6.0, (bottom-top) * ratio * .5)
        for start, end in (
            ((left, top), (left+x_len, top)), ((left, top), (left, top+y_len)),
            ((right, top), (right-x_len, top)), ((right, top), (right, top+y_len)),
            ((left, bottom), (left+x_len, bottom)), ((left, bottom), (left, bottom-y_len)),
            ((right, bottom), (right-x_len, bottom)), ((right, bottom), (right, bottom-y_len)),
        ):
            dpg.draw_line(start, end, parent="gpu_draw", color=color, thickness=thickness)

    def _draw_weapon_icon(self, weapon_name: str, center: tuple[float, float],
                          color: tuple[int, int, int, int], width: float = 34.0) -> bool:
        tag = self.weapon_textures.get(weapon_name)
        if not tag:
            return False
        x, y = center
        try:
            dpg.draw_image(tag, (x-width/2, y-6), (x+width/2, y+6), parent="gpu_draw",
                           color=color)
        except Exception:
            self.weapon_textures.pop(weapon_name, None)
            return False
        return True

    def _configure_native_window(self) -> None:
        find_window = ctypes.windll.user32.FindWindowW
        find_window.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
        find_window.restype = ctypes.c_void_p
        for _ in range(100):
            self.overlay_hwnd = find_window(None, self.TITLE) or 0
            if self.overlay_hwnd:
                break
            time.sleep(0.01)
        if not self.overlay_hwnd:
            raise RuntimeError("Dear PyGui viewport HWND was not found")
        get_style = ctypes.windll.user32.GetWindowLongPtrW
        set_style = ctypes.windll.user32.SetWindowLongPtrW
        get_style.argtypes = (ctypes.c_void_p, ctypes.c_int)
        set_style.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
        get_style.restype = set_style.restype = ctypes.c_ssize_t
        style = get_style(self.overlay_hwnd, -20)
        # Layered, click-through, tool window, and never activate on focus.
        set_style(self.overlay_hwnd, -20, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
        layered = ctypes.windll.user32.SetLayeredWindowAttributes
        layered.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_ubyte, ctypes.c_uint)
        layered(self.overlay_hwnd, 0x000000, 255, 0x1)
        set_window_pos = ctypes.windll.user32.SetWindowPos
        set_window_pos.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_uint)
        # Apply the extended styles immediately without activating the overlay.
        set_window_pos(self.overlay_hwnd, -1, 0, 0, 0, 0,
                       0x0001 | 0x0002 | 0x0010 | 0x0020 | 0x0040)

    def _set_visible(self, visible: bool) -> None:
        if visible == self.is_visible or not self.overlay_hwnd:
            return
        show_window = ctypes.windll.user32.ShowWindow
        show_window.argtypes = (ctypes.c_void_p, ctypes.c_int)
        show_window(self.overlay_hwnd, 4 if visible else 0)
        self.is_visible = visible

    def _draw_esp(self, settings: Settings, width: int, height: int,
                  matrix: list[float] | None = None) -> None:
        with self.snapshot_lock:
            entities = list(self.snapshot)
            fresh = time.monotonic() - self.snapshot_time < 0.50
            if matrix is None:
                matrix = list(self.snapshot_matrix)
        if not fresh or len(matrix) != 16:
            return
        for px, py, pz, hp, armor, name, weapon_name, distance, bones, node in entities:
            # Entity metadata is cached, but movement must be sampled in the
            # render frame or boxes trail behind moving pawns by one snapshot.
            try:
                live_position = struct.unpack(
                    "<3f", self.cheats.pm.read_bytes(node + self.cheats.abs_origin, 12))
                if all(math.isfinite(value) and abs(value) < 100000.0
                       for value in live_position):
                    px, py, pz = live_position
                    if settings.esp_skeleton:
                        live_bones = self.cheats._bone_positions(
                            node, live_position, SKELETON_BONES)
                        # CS2 can swap model-state buffers between our two RPM
                        # calls. Keep the previous complete pose for that frame.
                        if sum(point is not None for point in live_bones) >= 6:
                            bones = live_bones
            except Exception:
                pass
            feet = self._project((px, py, pz), matrix, width, height)
            head = self._project((px, py, pz + 64.0), matrix, width, height)
            if not feet or not head:
                continue
            box_h = abs(feet[1] - head[1])
            if box_h < 5 or box_h > height:
                continue
            box_w = box_h * 0.46
            left, right = head[0] - box_w / 2, head[0] + box_w / 2
            if settings.box_esp and settings.esp_fill:
                dpg.draw_rectangle((left, head[1]), (right, feet[1]), parent="gpu_draw",
                                   fill=self._rgba(settings.box_color, round(settings.box_fill_alpha * 2.55)),
                                   color=(0, 0, 0, 0))
            if settings.box_esp:
                if settings.box_style == "corner":
                    self._gpu_corners(left, head[1], right, feet[1], self._rgba(settings.box_color),
                                      settings.corner_length)
                else:
                    dpg.draw_rectangle((left, head[1]), (right, feet[1]), parent="gpu_draw",
                                       color=self._rgba(settings.box_color), thickness=settings.box_thickness)
            if settings.esp_skeleton and bones:
                projected = [self._project(point, matrix, width, height) if point else None
                             for point in bones]
                for first, second in SKELETON_CONNECTIONS:
                    start_point, end_point = projected[first], projected[second]
                    if start_point and end_point:
                        dpg.draw_line(start_point, end_point, parent="gpu_draw",
                                      color=(7, 9, 13, 230), thickness=4.0)
                        dpg.draw_line(start_point, end_point, parent="gpu_draw",
                                      color=self._rgba(settings.skeleton_color), thickness=1.7)
            if settings.esp_name:
                self._gpu_text((head[0] - len(name) * 3.4, head[1] - 16), name,
                               self._rgba(settings.name_color), 13)
            if settings.esp_health:
                bar_x = left - 6
                hp_top = feet[1] - box_h * hp / 100
                hp_color = settings.hp_color if not settings.health_color else f"#{255-hp*255//100:02x}{hp*255//100:02x}30"
                dpg.draw_rectangle((bar_x - 2, head[1]), (bar_x + 1, feet[1]), parent="gpu_draw",
                                   fill=(18, 18, 18, 230), color=(18, 18, 18, 230))
                dpg.draw_rectangle((bar_x - 1, hp_top), (bar_x, feet[1]), parent="gpu_draw",
                                   fill=self._rgba(hp_color), color=self._rgba(hp_color))
                if hp < 100:
                    self._gpu_text((bar_x - 24, hp_top - 6), str(hp), (255, 255, 255, 255), 11)
            if settings.esp_armor and armor > 0:
                armor_y = feet[1] + 4
                dpg.draw_line((left, armor_y), (left + box_w * armor / 100, armor_y), parent="gpu_draw",
                              color=self._rgba(settings.armor_color), thickness=2)
            if settings.esp_weapon:
                cy, color = feet[1] + 10, self._rgba(settings.weapon_color)
                self._draw_weapon_icon(weapon_name, (head[0], cy), color)
            if settings.esp_distance:
                self._gpu_text((head[0] - 15, feet[1] + 20), f"{distance:.0f} m",
                               self._rgba(settings.name_color), 11)
            if settings.esp_snapline:
                dpg.draw_line((width / 2, height - 2), (head[0], feet[1]), parent="gpu_draw",
                              color=self._rgba(settings.line_color), thickness=1)
            if settings.esp_head_dot:
                dpg.draw_circle((head[0], head[1]), max(2.0, box_w * 0.08), parent="gpu_draw",
                                color=self._rgba(settings.box_color), fill=self._rgba(settings.box_color))

    def _draw_world_hud(self, settings: Settings, width: int, height: int,
                        matrix: list[float] | None = None) -> None:
        """Draw world entities and interface HUD owned by the GPU overlay."""
        with self.snapshot_lock:
            world_entities = list(self.world_snapshot)
            bomb_info = self.bomb_snapshot
            if matrix is None:
                matrix = list(self.snapshot_matrix)

        if settings.cinema_bars:
            bar = int(height * max(2.0, min(20.0, settings.cinema_bar_size)) / 100.0)
            dpg.draw_rectangle((0, 0), (width, bar), parent="gpu_draw",
                               fill=(0, 0, 0, 255), color=(0, 0, 0, 255))
            dpg.draw_rectangle((0, height-bar), (width, height), parent="gpu_draw",
                               fill=(0, 0, 0, 255), color=(0, 0, 0, 255))

        if settings.performance_panel:
            perf = f"OVR {self.fps_value} FPS  READ {self.read_time_ms:.2f} ms  ENT {self.entities_processed}"
            self._gpu_text((width-310, 32), perf, self._rgba(settings.name_color), 11)

        if settings.overlay_fps:
            self._gpu_text((width - 105, 10), f"ESP {self.fps_value} FPS",
                           self._rgba(settings.name_color), 12)

        if len(matrix) == 16:
            if settings.world_weapon_esp:
                for wx, wy, wz, label in world_entities:
                    low = label.lower()
                    grenade = any(x in low for x in ("grenade", "flash", "molotov", "decoy"))
                    knife = "knife" in low or "bayonet" in low
                    c4 = label == "C4"
                    if ((grenade and not settings.weapon_filter_grenades)
                            or (knife and not settings.weapon_filter_knives)
                            or (c4 and not settings.weapon_filter_c4)
                            or (not grenade and not knife and not c4 and not settings.weapon_filter_active)):
                        continue
                    screen = self._project((wx, wy, wz), matrix, width, height)
                    if screen:
                        self._gpu_text(screen, label, self._rgba(settings.world_color), 12)
            if settings.world_bomb_esp and bomb_info:
                bx, by, bz, remaining, _site, _defusing, _defuse_left = bomb_info
                screen = self._project((bx, by, bz), matrix, width, height)
                if screen:
                    color = "#ff4d4d" if remaining <= 10.0 else settings.world_color
                    rgba = self._rgba(color)
                    dpg.draw_rectangle((screen[0]-8, screen[1]-7), (screen[0]+5, screen[1]+7),
                                       parent="gpu_draw", color=rgba, thickness=2)
                    dpg.draw_line((screen[0]-4, screen[1]-7), (screen[0]+8, screen[1]-13),
                                  parent="gpu_draw", color=rgba, thickness=1)
                    self._gpu_text((screen[0]+12, screen[1]-8), f"{remaining:04.1f}s", rgba, 14)

        if settings.hud_enabled:
            text = (f"FPS {self.fps_value:>3}   AIM {'ON' if settings.aim_enabled else 'OFF'}"
                    f"   RCS {'ON' if settings.no_recoil else 'OFF'}"
                    f"   TRG {'ON' if settings.triggerbot else 'OFF'}")
            dpg.draw_rectangle((settings.hud_x, settings.hud_y),
                               (settings.hud_x + 360, settings.hud_y + 28),
                               parent="gpu_draw", fill=self.HUD_BG, color=self.HUD_BORDER)
            dpg.draw_line((settings.hud_x, settings.hud_y),
                          (settings.hud_x + 360, settings.hud_y), parent="gpu_draw",
                          color=self.HUD_ACCENT, thickness=2)
            self._gpu_text((settings.hud_x + 20, settings.hud_y + 7), text,
                           self.HUD_TEXT, 13)
            active_binds = []
            if settings.aim_enabled:
                active_binds.append(("AIM", settings.aim_key.upper()))
            if settings.triggerbot:
                active_binds.append(("TRIGGER", "ON"))
            if settings.no_recoil:
                active_binds.append(("RCS", "ON"))
            panel_h = 28 + max(1, len(active_binds)) * 18
            kx, ky = settings.keybind_hud_x, settings.keybind_hud_y
            if settings.keybind_list:
                dpg.draw_rectangle((kx, ky), (kx+190, ky+panel_h), parent="gpu_draw",
                               fill=self.HUD_BG, color=self.HUD_BORDER)
                dpg.draw_line((kx, ky), (kx+190, ky), parent="gpu_draw",
                          color=self.HUD_ACCENT, thickness=2)
                self._gpu_text((kx+10, ky+7), "KEYBIND LIST", self.HUD_TEXT, 12)
                if active_binds:
                    for index, (label, key) in enumerate(active_binds):
                        row_y = ky + 27 + index*18
                        self._gpu_text((kx+10, row_y), label, self.HUD_MUTED, 11)
                        self._gpu_text((kx+143, row_y), key, self.HUD_TEXT, 11)
                else:
                    self._gpu_text((kx+10, ky+28), "No active binds", self.HUD_MUTED, 11)

        if settings.world_bomb_info and bomb_info:
            _bx, _by, _bz, remaining, site, defusing, defuse_left = bomb_info
            color_hex = "#ff4d4d" if remaining <= 10.0 else settings.world_color
            status = f"DEFUSING {defuse_left:04.1f}s" if defusing else "PLANTED"
            outcome = ("  SAFE" if defusing and defuse_left < remaining
                       else "  TOO LATE" if defusing else "")
            left, top = settings.bomb_hud_x, settings.bomb_hud_y
            dpg.draw_rectangle((left, top), (left + 300, top + 48), parent="gpu_draw",
                               fill=self.HUD_BG, color=self.HUD_BORDER)
            dpg.draw_line((left, top), (left+300, top), parent="gpu_draw",
                          color=self._rgba(color_hex), thickness=2)
            bomb_color = self._rgba(color_hex)
            tag = self.weapon_textures.get("C4")
            if tag:
                try:
                    dpg.draw_image(tag, (left+12, top+8), (left+44, top+40), parent="gpu_draw",
                                   color=bomb_color)
                except Exception:
                    self.weapon_textures.pop("C4", None)
            self._gpu_text((left+55, top+6), f"SITE {site}   {remaining:04.1f}s", bomb_color, 16)
            self._gpu_text((left+55, top+27), status + outcome,
                           (245, 245, 247, 255), 12)

    def _draw_frame(self, settings: Settings, width: int, height: int,
                    menu_open: bool, splash_open: bool, text_level: float) -> None:
        dpg.delete_item("gpu_draw", children_only=True)
        self._drag_overlay_elements(settings, width, height, menu_open)
        if splash_open:
            dpg.draw_rectangle((0, 0), (width, height), parent="gpu_draw", fill=(1, 1, 1, 245), color=(1, 1, 1, 245))
        # Unlike Tk stipple, alpha-filled fullscreen rectangles on a Win32
        # color-key viewport become opaque. Keep the menu background completely
        # transparent and draw only particles around it.
        if splash_open:
            shade = max(20, min(255, int(255 * text_level)))
            dpg.draw_text((width / 2 - 92, height / 2 - 35), "LUNA", parent="gpu_draw",
                          color=(shade, shade, shade, 255), size=28)
            dpg.draw_line((width / 2 - 110, height / 2 + 18), (width / 2 + 110, height / 2 + 18),
                          parent="gpu_draw", color=(120, 120, 120, shade), thickness=1)
            dpg.draw_text((width / 2 - 82, height / 2 + 32), "DESKTOP CONTROL UTILITY", parent="gpu_draw",
                          color=(150, 150, 150, shade), size=11)
        if settings.watermark:
            dpg.draw_rectangle((settings.watermark_x, settings.watermark_y), (settings.watermark_x+152, settings.watermark_y+26), parent="gpu_draw", fill=(250, 249, 246, 245),
                               color=(145, 141, 133, 255))
            dpg.draw_rectangle((settings.watermark_x, settings.watermark_y), (settings.watermark_x+3, settings.watermark_y+26), parent="gpu_draw", fill=(230, 84, 63, 255), color=(230, 84, 63, 255))
            dpg.draw_text((settings.watermark_x+11, settings.watermark_y+7), "LUNA  /  GPU", parent="gpu_draw", color=(23, 23, 22, 255), size=12)
        if settings.overlay_fps:
            dpg.draw_text((width - 95, 10), f"ESP {self.fps_value} FPS", parent="gpu_draw",
                          color=self._rgba(settings.name_color), size=11)
        if settings.overlay_clock:
            dpg.draw_text((width - 65, 27), time.strftime("%H:%M:%S"), parent="gpu_draw",
                          color=self._rgba(settings.name_color), size=11)
        if settings.aim_indicator and (settings.aim_enabled or settings.auto_shoot):
            label = "AIM ACTIVE"
            dpg.draw_text((width / 2 - len(label) * 3.2, height - 24), label, parent="gpu_draw",
                          color=(255, 255, 255, 255), size=11)
        if settings.crosshair_enabled:
            cx, cy, size = width / 2, height / 2, settings.crosshair_size
            color = self._rgba(settings.crosshair_color)
            for p1, p2 in (((cx-size, cy), (cx-2, cy)), ((cx+2, cy), (cx+size, cy)),
                           ((cx, cy-size), (cx, cy-2)), ((cx, cy+2), (cx, cy+size))):
                dpg.draw_line(p1, p2, parent="gpu_draw", color=color, thickness=1)
        if (settings.aim_enabled or settings.auto_shoot) and settings.show_fov:
            radius = math.tan(math.radians(settings.aim_fov)) / math.tan(math.radians(45.0)) * width / 2
            dpg.draw_circle((width / 2, height / 2), radius, parent="gpu_draw",
                            color=self._rgba(settings.fov_color), thickness=1)
        if (settings.world_bomb_esp or settings.world_bomb_info
                or settings.world_weapon_esp or settings.hud_enabled):
            with self.snapshot_lock:
                world_entities = list(self.world_snapshot)
                bomb_info = self.bomb_snapshot
                matrix = list(self.snapshot_matrix)
            if len(matrix) == 16:
                if settings.world_weapon_esp:
                    for wx, wy, wz, label in world_entities:
                        screen = self._project((wx, wy, wz), matrix, width, height)
                        if screen:
                            dpg.draw_text(screen, f"? {label}", parent="gpu_draw",
                                          color=self._rgba(settings.world_color), size=12)
                if settings.world_bomb_esp and bomb_info:
                    bx, by, bz, remaining, _site, _defusing, _defuse_left = bomb_info
                    screen = self._project((bx, by, bz), matrix, width, height)
                    if screen:
                        color = "#ff4d4d" if remaining <= 10.0 else settings.world_color
                        rgba = self._rgba(color)
                        dpg.draw_rectangle((screen[0]-8, screen[1]-7), (screen[0]+5, screen[1]+7),
                                           parent="gpu_draw", color=rgba, thickness=2)
                        dpg.draw_line((screen[0]-4, screen[1]-7), (screen[0]+8, screen[1]-13),
                                      parent="gpu_draw", color=rgba, thickness=1)
                        dpg.draw_text((screen[0]+12, screen[1]-7), f"{remaining:04.1f}s",
                                      parent="gpu_draw", color=rgba, size=14)
            if settings.hud_enabled:
                text = (f"FPS {self.fps_value:>3}   AIM {'ON' if settings.aim_enabled else 'OFF'}"
                        f"   RCS {'ON' if settings.no_recoil else 'OFF'}"
                        f"   TRG {'ON' if settings.triggerbot else 'OFF'}")
                dpg.draw_rectangle((settings.hud_x, settings.hud_y), (settings.hud_x+360, settings.hud_y+28),
                                   parent="gpu_draw", fill=(18, 18, 20, 225),
                                   color=(90, 90, 96, 255))
                dpg.draw_text((settings.hud_x+20, settings.hud_y+8), text, parent="gpu_draw",
                              color=(245, 245, 247, 255), size=12)
            if settings.world_bomb_info and bomb_info:
                _bx, _by, _bz, remaining, site, defusing, defuse_left = bomb_info
                color_hex = "#ff4d4d" if remaining <= 10.0 else settings.world_color
                status = (f"DEFUSING {defuse_left:04.1f}s"
                          if defusing else "PLANTED")
                outcome = ("  SAFE" if defusing and defuse_left < remaining
                           else "  TOO LATE" if defusing else "")
                left, top = settings.bomb_hud_x, settings.bomb_hud_y
                dpg.draw_rectangle((left, top), (left+300, top+48),
                                   parent="gpu_draw", fill=(18, 18, 20, 235),
                                   color=self._rgba(color_hex), thickness=2)
                dpg.draw_text((left+75, top+7),
                              f"BOMB {site}   {remaining:04.1f}s", parent="gpu_draw",
                              color=self._rgba(color_hex), size=16)
                dpg.draw_text((left+85, top+28), status + outcome,
                              parent="gpu_draw", color=(245, 245, 247, 255), size=11)
        if settings.box_esp or settings.esp_skeleton:
            self._draw_esp(settings, width, height)

    def _render_loop(self) -> None:
        try:
            dpg.create_context()
            dpg.create_viewport(title=self.TITLE, width=640, height=480, decorated=False,
                                always_on_top=True, resizable=False, disable_close=True,
                                clear_color=(0, 0, 0, 0), vsync=False)
            dpg.add_viewport_drawlist(tag="gpu_draw", front=True)
            icon_dir = ASSET_DIR / "cs2_icons"
            with dpg.texture_registry(show=False):
                for weapon_name, icon_name in (*CS2_ICON_BY_WEAPON.items(), ("C4", "c4")):
                    icon_path = icon_dir / f"{icon_name}.png"
                    if not icon_path.exists():
                        continue
                    texture_width, texture_height, _channels, pixels = dpg.load_image(str(icon_path))
                    tag = f"cs2_icon_{icon_name}"
                    if not dpg.does_item_exist(tag):
                        dpg.add_static_texture(texture_width, texture_height, pixels, tag=tag)
                    self.weapon_textures[weapon_name] = tag
            font_path = (Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive") /
                         "game/csgo/panorama/fonts/notosans-regular.ttf")
            if not font_path.exists():
                font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "verdana.ttf"
            if font_path.exists():
                with dpg.font_registry():
                    with dpg.font(str(font_path), 14, tag="overlay_font"):
                        dpg.add_font_range_hint(dpg.mvFontRangeHint_Cyrillic)
            dpg.setup_dearpygui()
            if dpg.does_item_exist("overlay_font"):
                dpg.bind_font("overlay_font")
            dpg.show_viewport()
            dpg.set_viewport_vsync(False)
            self._configure_native_window()
            self.is_visible = True
            self._set_visible(False)
            while not self.cheats.stop.is_set() and dpg.is_dearpygui_running():
                frame_started = time.perf_counter()
                settings = self.state.get()
                if settings.screenshot_cleanup and (ctypes.windll.user32.GetAsyncKeyState(0x2C) & 1):
                    self._screenshot_hidden_until = time.monotonic() + 0.45
                rect = self._rect()
                foreground = ctypes.windll.user32.GetForegroundWindow()
                menu_hwnd = self.menu_hwnd_getter()
                game_active = bool(self.game_hwnd and foreground in (self.game_hwnd, menu_hwnd, self.overlay_hwnd))
                menu_open = self.menu_visible_getter()
                splash_open, _splash_opacity, text_level = self.splash_state_getter()
                # Native overlay owns static interface extras; the GPU overlay
                # owns player/world ESP and HUD elements backed by snapshots.
                player_needed = settings.box_esp or settings.esp_skeleton
                world_needed = (settings.world_bomb_esp or settings.world_bomb_info
                                or settings.world_weapon_esp or settings.hud_enabled
                                or settings.overlay_fps or settings.performance_panel or settings.cinema_bars)
                needed = (settings.enabled and time.monotonic() >= getattr(
                              self, "_screenshot_hidden_until", 0.0)
                          and (player_needed or world_needed) and not menu_open and not splash_open)
                if not rect or not game_active or not needed:
                    self._set_visible(False)
                    dpg.render_dearpygui_frame()
                    self.cheats.stop.wait(0.025)
                    continue
                x, y, width, height = rect
                geometry = (x, y, width, height)
                if geometry != self.last_geometry:
                    dpg.set_viewport_pos((x, y))
                    dpg.set_viewport_width(width)
                    dpg.set_viewport_height(height)
                    self.last_geometry = geometry
                self._set_visible(True)
                dpg.delete_item("gpu_draw", children_only=True)
                # Camera rotation changes far more often than entity world positions.
                # Sampling it here removes a full collector/render interval of lag.
                frame_matrix = self._read_view_matrix()
                if world_needed:
                    self._draw_world_hud(settings, width, height, frame_matrix)
                if player_needed:
                    self._draw_esp(settings, width, height, frame_matrix)
                dpg.render_dearpygui_frame()
                self.frame_counter += 1
                now = time.monotonic()
                if now - self.fps_timer >= 1.0:
                    self.fps_value = round(self.frame_counter / (now - self.fps_timer))
                    self.frame_counter = 0
                    self.fps_timer = now
                render_rate = max(60, min(360, int(settings.esp_rate)))
                remaining = 1.0 / render_rate - (time.perf_counter() - frame_started)
                if remaining > 0:
                    self.cheats.stop.wait(remaining)
        except Exception:
            logging.exception("Dear PyGui overlay stopped")
        finally:
            try:
                dpg.destroy_context()
            except Exception:
                pass


try:
    from .native_overlay import NativeFovOverlay as FovOverlay
except Exception:
    logging.exception("Native FOV overlay backend is unavailable")


class Menu:
    WIDTH = 900
    HEIGHT = 740
    BG = "#080808"
    PANEL = "#111111"
    PANEL_2 = "#181818"
    TEXT = "#f5f5f5"
    MUTED = "#858585"
    ACCENT = "#ffffff"
    RED = "#ffffff"

    def __init__(self, cheats: Cheats, state: StateStore, stop: threading.Event, status: str):
        enable_dpi_awareness()
        self.cheats = cheats
        self.state = state
        self.stop = stop
        current = state.set(world_filter=False, bunny_hop=False)
        self._select_theme(current.menu_theme if current.menu_theme in ("Editorial", "Nightware") else "Nightware")
        initial_scale = current.menu_scale if current.menu_scale in (75, 100, 125) else 100
        self.WIDTH = round(900 * initial_scale / 100)
        self.HEIGHT = round(740 * initial_scale / 100) + (35 if initial_scale == 75 else 0)
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.root.minsize(round(760 * initial_scale / 100), round(620 * initial_scale / 100))
        self.root.resizable(True, True)
        self.root.overrideredirect(True)
        self.root.configure(bg=self.BG)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.0)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.visible = False
        # Startup is intentionally single-stage. The old ten-second fullscreen
        # splash raced two layered windows and produced a black flicker.
        self.splash_active = False
        self.splash_opacity = 1.0
        self.splash_text_level = 0.0
        self.splash_started = time.monotonic()
        self.events: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._last_toggle_request = 0.0
        self.config_manager = ConfigManager()
        self.config_name_var = tk.StringVar(value="default")
        self._save_after_id: str | None = None

        self.enabled_var = tk.BooleanVar(value=current.enabled)
        self.glow_var = tk.BooleanVar(value=current.glow)
        self.flash_var = tk.BooleanVar(value=current.anti_flash)
        self.bhop_var = tk.BooleanVar(value=current.bunny_hop)
        self.bhop_key_var = tk.StringVar(value=current.bhop_key)
        self.bhop_key_mode_var = tk.StringVar(value=current.bhop_key_mode.title())
        self.recoil_var = tk.BooleanVar(value=current.no_recoil)
        self.recoil_strength_var = tk.DoubleVar(value=current.recoil_strength)
        self.recoil_smooth_var = tk.DoubleVar(value=current.recoil_smooth)
        self.rcs_mode_var = tk.StringVar(value=current.rcs_mode)
        self.rcs_start_bullet_var = tk.DoubleVar(value=current.rcs_start_bullet)
        self.rcs_x_var = tk.DoubleVar(value=current.rcs_x)
        self.rcs_y_var = tk.DoubleVar(value=current.rcs_y)
        self.shake_var = tk.BooleanVar(value=current.no_shake)
        self.aim_var = tk.BooleanVar(value=current.aim_enabled)
        self.aim_key_var = tk.StringVar(value=current.aim_key)
        self.aim_key_mode_var = tk.StringVar(value=current.aim_key_mode.title())
        self.smooth_var = tk.DoubleVar(value=current.aim_smooth)
        self.fov_var = tk.DoubleVar(value=current.aim_fov)
        self.target_var = tk.StringVar(value=current.aim_target)
        self.aim_lock_var = tk.BooleanVar(value=current.aim_lock)
        self.dynamic_fov_var = tk.BooleanVar(value=current.dynamic_fov)
        self.aim_fov_pistol_var = tk.DoubleVar(value=current.aim_fov_pistol)
        self.aim_fov_rifle_var = tk.DoubleVar(value=current.aim_fov_rifle)
        self.aim_fov_sniper_var = tk.DoubleVar(value=current.aim_fov_sniper)
        self.aim_fov_smg_var = tk.DoubleVar(value=current.aim_fov_smg)
        self.aim_smooth_pistol_var = tk.DoubleVar(value=current.aim_smooth_pistol)
        self.aim_smooth_rifle_var = tk.DoubleVar(value=current.aim_smooth_rifle)
        self.aim_smooth_sniper_var = tk.DoubleVar(value=current.aim_smooth_sniper)
        self.aim_smooth_smg_var = tk.DoubleVar(value=current.aim_smooth_smg)
        self.rcs_profile_vars = {
            weapon: {
                "enabled": tk.BooleanVar(value=getattr(current, f"rcs_enabled_{weapon}")),
                "amount": tk.DoubleVar(value=getattr(current, f"rcs_amount_{weapon}")),
                "smooth": tk.DoubleVar(value=getattr(current, f"rcs_smooth_{weapon}")),
                "start": tk.DoubleVar(value=getattr(current, f"rcs_start_{weapon}")),
                "x": tk.DoubleVar(value=getattr(current, f"rcs_x_{weapon}")),
                "y": tk.DoubleVar(value=getattr(current, f"rcs_y_{weapon}")),
            }
            for weapon in ("pistol", "rifle", "sniper", "smg")
        }
        self.first_shot_delay_var = tk.DoubleVar(value=current.first_shot_delay)
        self.target_switch_delay_var = tk.DoubleVar(value=current.target_switch_delay)
        self.lock_timeout_var = tk.DoubleVar(value=current.lock_timeout)
        self.aim_dead_zone_var = tk.DoubleVar(value=current.aim_dead_zone)
        self.aim_max_step_var = tk.DoubleVar(value=current.aim_max_step)
        self.target_priority_var = tk.StringVar(value=current.target_priority)
        self.hitbox_fallback_var = tk.BooleanVar(value=current.hitbox_fallback)
        self.ignore_teammates_var = tk.BooleanVar(value=current.ignore_teammates)
        self.visibility_check_var = tk.BooleanVar(value=current.visibility_check)
        self.triggerbot_var = tk.BooleanVar(value=current.triggerbot)
        self.trigger_delay_var = tk.DoubleVar(value=current.trigger_delay)
        self.shoot_in_smoke_var = tk.BooleanVar(value=current.shoot_in_smoke)
        self.auto_shoot_var = tk.BooleanVar(value=current.auto_shoot)
        self.auto_stop_var = tk.BooleanVar(value=current.auto_stop)
        self.show_fov_var = tk.BooleanVar(value=current.show_fov)
        self.box_var = tk.BooleanVar(value=current.box_esp)
        self.box_style_var = tk.StringVar(value=current.box_style)
        self.esp_preset_var = tk.StringVar(value=current.esp_preset)
        self.box_thickness_var = tk.DoubleVar(value=current.box_thickness)
        self.box_fill_alpha_var = tk.DoubleVar(value=current.box_fill_alpha)
        self.corner_length_var = tk.DoubleVar(value=current.corner_length)
        self.esp_name_var = tk.BooleanVar(value=current.esp_name)
        self.esp_health_var = tk.BooleanVar(value=current.esp_health)
        self.esp_weapon_var = tk.BooleanVar(value=current.esp_weapon)
        self.esp_armor_var = tk.BooleanVar(value=current.esp_armor)
        self.esp_distance_var = tk.BooleanVar(value=current.esp_distance)
        self.esp_snapline_var = tk.BooleanVar(value=current.esp_snapline)
        self.esp_head_dot_var = tk.BooleanVar(value=current.esp_head_dot)
        self.esp_skeleton_var = tk.BooleanVar(value=current.esp_skeleton)
        self.world_bomb_esp_var = tk.BooleanVar(value=current.world_bomb_esp)
        self.world_bomb_info_var = tk.BooleanVar(value=current.world_bomb_info)
        self.world_weapon_esp_var = tk.BooleanVar(value=current.world_weapon_esp)
        self.weapon_filter_active_var = tk.BooleanVar(value=current.weapon_filter_active)
        self.weapon_filter_grenades_var = tk.BooleanVar(value=current.weapon_filter_grenades)
        self.weapon_filter_c4_var = tk.BooleanVar(value=current.weapon_filter_c4)
        self.weapon_filter_knives_var = tk.BooleanVar(value=current.weapon_filter_knives)
        self.esp_enemies_var = tk.BooleanVar(value=current.esp_enemies)
        self.esp_allies_var = tk.BooleanVar(value=current.esp_allies)
        self.esp_bots_var = tk.BooleanVar(value=current.esp_bots)
        self.esp_state_indicators_var = tk.BooleanVar(value=current.esp_state_indicators)
        self.hud_enabled_var = tk.BooleanVar(value=current.hud_enabled)
        self.keybind_list_var = tk.BooleanVar(value=current.keybind_list)
        self.performance_panel_var = tk.BooleanVar(value=current.performance_panel)
        self.esp_rate_var = tk.DoubleVar(value=current.esp_rate)
        self.world_rate_var = tk.DoubleVar(value=current.world_rate)
        self.hud_rate_var = tk.DoubleVar(value=current.hud_rate)
        self.cinema_bars_var = tk.BooleanVar(value=current.cinema_bars)
        self.cinema_bar_size_var = tk.DoubleVar(value=current.cinema_bar_size)
        self.screenshot_cleanup_var = tk.BooleanVar(value=current.screenshot_cleanup)
        self.disable_cosmetics_in_menu_var = tk.BooleanVar(value=current.disable_cosmetics_in_menu)
        self.element_colors = {
            "Box": tk.StringVar(value=current.box_color), "Name": tk.StringVar(value=current.name_color),
            "HP": tk.StringVar(value=current.hp_color), "Armor": tk.StringVar(value=current.armor_color),
            "Weapon": tk.StringVar(value=current.weapon_color), "FOV": tk.StringVar(value=current.fov_color),
            "Crosshair": tk.StringVar(value=current.crosshair_color),
            "Line": tk.StringVar(value=current.line_color),
            "Skeleton": tk.StringVar(value=current.skeleton_color),
            "World": tk.StringVar(value=current.world_color),
            "WorldTint": tk.StringVar(value=current.world_filter_color),
            "LowHP": tk.StringVar(value=current.profile_low_hp_color),
            "Bomb": tk.StringVar(value=current.profile_bomb_color),
        }
        self.world_filter_var = tk.BooleanVar(value=current.world_filter)
        self.world_filter_strength_var = tk.DoubleVar(value=current.world_filter_strength)
        self.world_night_var = tk.BooleanVar(value=current.world_night_mode)
        self.skybox_var = tk.StringVar(value=current.skybox_name)
        self.radar_var = tk.BooleanVar(value=current.radar_hack)
        self.skin_changer_var = tk.BooleanVar(value=current.skin_changer)
        self.skin_weapon_var = tk.StringVar(value=current.skin_weapon)
        self.skin_name_var = tk.StringVar(value=current.skin_name)
        self.skin_wear_var = tk.DoubleVar(value=current.skin_wear)
        self.skin_seed_var = tk.DoubleVar(value=current.skin_seed)
        self.skin_stattrak_var = tk.BooleanVar(value=current.skin_stattrak)
        self.crosshair_var = tk.BooleanVar(value=current.crosshair_enabled)
        self.crosshair_size_var = tk.DoubleVar(value=current.crosshair_size)
        self.watermark_var = tk.BooleanVar(value=current.watermark)
        self.overlay_fps_var = tk.BooleanVar(value=current.overlay_fps)
        self.overlay_clock_var = tk.BooleanVar(value=current.overlay_clock)
        self.aim_indicator_var = tk.BooleanVar(value=current.aim_indicator)
        self.esp_fill_var = tk.BooleanVar(value=current.esp_fill)
        self.color_mode = tk.StringVar(value="health" if current.health_color else "custom")
        self.custom_color = current.custom_color
        self.menu_scale_var = tk.IntVar(value=current.menu_scale if current.menu_scale in (75, 100, 125) else 100)
        self.menu_theme_var = tk.StringVar(value=current.menu_theme if current.menu_theme in ("Editorial", "Nightware") else "Nightware")
        self.esp_preview_enabled_var = tk.BooleanVar(value=current.esp_preview_enabled)
        self._menu_status = status
        self.esp_preview_window: tk.Toplevel | None = None
        self.rcs_mode_popup: tk.Toplevel | None = None
        self.capture_feature: str | None = None
        self.capture_hook = None
        self.bind_buttons: dict[str, tk.Button] = {}

        self._styles()
        self._build(status)
        self.root.bind("<Configure>", lambda _event: self.root.after_idle(self._position_esp_preview), add="+")
        # Hybrid renderer: all interface visuals remain pixel-identical to the
        # original Tkinter build, while player ESP is drawn on the GPU layer.
        self.fov_overlay = FovOverlay(self.root, cheats, InterfaceStateView(state))
        self.esp_overlay = DearFovOverlay(self.root, cheats, state)
        self.fov_overlay.menu_visible_getter = lambda: self.visible
        self.fov_overlay.menu_hwnd_getter = lambda: getattr(self, "menu_hwnd", 0)
        self.fov_overlay.splash_state_getter = lambda: (
            self.splash_active, self.splash_opacity, self.splash_text_level
        )
        self.esp_overlay.menu_visible_getter = lambda: self.visible
        self.esp_overlay.menu_hwnd_getter = lambda: getattr(self, "menu_hwnd", 0)
        self.esp_overlay.splash_state_getter = lambda: (
            self.splash_active, self.splash_opacity, self.splash_text_level
        )
        self._configure_overlay_menu()
        self._set_menu_input_transparent(True)
        self._bind_menu_toggle()
        self.root.after(16, self._poll_events)
        self.root.after(150, self._position_overlay_menu)
        self.root.after_idle(self.toggle)

    def _select_theme(self, theme: str) -> None:
        palettes = {
            "Editorial": {
                "BACKGROUND": "#F2F0EA", "SURFACE": "#F8F7F3", "SURFACE_ALT": "#EAE7DF",
                "SURFACE_HOVER": "#E2DED5", "BORDER": "#C9C5BB", "BORDER_STRONG": "#8C887F",
                "TEXT": "#181817", "TEXT_SECONDARY": "#4F4D48", "TEXT_DISABLED": "#817D75",
                "ACCENT": "#E6543F", "ACCENT_HOVER": "#C94734", "ACCENT_SOFT": "#F2D3CC",
            },
            "Nightware": {
                "BACKGROUND": "#080909", "SURFACE": "#101112", "SURFACE_ALT": "#0B0C0D",
                "SURFACE_HOVER": "#17191A", "BORDER": "#232526", "BORDER_STRONG": "#343638",
                "TEXT": "#E8E8E8", "TEXT_SECONDARY": "#8A8D90", "TEXT_DISABLED": "#5E6163",
                "ACCENT": "#E8E8E8", "ACCENT_HOVER": "#FFFFFF", "ACCENT_SOFT": "#202122",
                "SUCCESS": "#D7D7D7", "ERROR": "#E8E8E8",
            },
        }
        palette = palettes.get(theme, palettes["Nightware"])
        for key, value in palette.items():
            setattr(design, key, value)
        self.BG = design.BACKGROUND
        self.PANEL = design.SURFACE
        self.PANEL_2 = design.SURFACE_ALT
        self.TEXT = design.TEXT
        self.MUTED = design.TEXT_SECONDARY
        self.ACCENT = design.ACCENT
        self.RED = self.ACCENT

    def _t(self, text: str) -> str:
        return text
        translations = {
            "Aim": "Аим", "Vision": "Визуалы", "Misc": "Разное", "Settings": "Настройки",
            "Weapon and target control": "Управление стрельбой и целями",
            "Players and local view": "Отображение игроков и интерфейса",
            "Movement and effects": "Движение и игровые эффекты",
            "Interface preferences": "Оформление и параметры интерфейса",
            "VECTOR AIM": "ВЕКТОРНЫЙ АИМ", "Hold selected key to activate": "Удерживайте выбранную клавишу",
            "RECOIL": "ОТДАЧА", "Weapon handling": "Управление оружием",
            "Enable Vector Aim": "Включить Vector Aim", "Show FOV circle": "Показывать круг FOV",
            "Aim point": "Точка наведения", "Smooth": "Плавность", "No Recoil": "Без отдачи",
            "Strength": "Сила", "Recoil smooth": "Плавность отдачи", "Remove screen shake": "Убрать тряску",
            "Aim key": "Клавиша Aim", "Target lock": "Фиксация цели",
            "PLAYERS": "ИГРОКИ", "Enemy visualization": "Отображение противников",
            "STYLE / EXTRAS": "СТИЛЬ / ДОПОЛНИТЕЛЬНО", "ESP palette and overlay extras": "Цвета ESP и элементы overlay",
            "Glow ESP": "Подсветка", "Box ESP": "Рамка", "Name": "Имя", "Health bar": "Полоса здоровья",
            "Weapon": "Оружие", "Armor": "Броня", "Distance": "Расстояние", "Snapline": "Линии",
            "Head dot": "Точка головы", "Filled box": "Заливка рамки", "Custom crosshair": "Свой прицел",
            "Crosshair": "Размер прицела", "Watermark": "Водяной знак", "Overlay FPS": "FPS оверлея",
            "MOVEMENT": "ДВИЖЕНИЕ", "Player movement": "Управление движением", "Bunny Hop": "Распрыжка",
            "EFFECTS": "ЭФФЕКТЫ", "Screen effects": "Экранные эффекты", "Anti-Flash": "Без ослепления",
            "Radar Hack": "Радар", "INTERFACE": "ИНТЕРФЕЙС", "Theme, size and language": "Тема, размер и язык",
            "Theme": "Тема", "Menu size": "Размер меню", "Language": "Язык",
        }
        return translations.get(text, text)

    def _styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCheckbutton", background=self.PANEL, foreground=self.TEXT, font=(design.FONT_UI, 8),
                        indicatorbackground=design.SURFACE, indicatorforeground=self.ACCENT,
                        indicatorcolor=design.SURFACE, bordercolor=design.BORDER_STRONG, padding=(0, 1))
        style.map("TCheckbutton", background=[("active", self.PANEL)], foreground=[("active", self.TEXT), ("disabled", design.TEXT_DISABLED)], indicatorbackground=[("selected", self.ACCENT), ("disabled", design.SURFACE_ALT)])
        style.configure("TRadiobutton", background=self.PANEL, foreground=self.TEXT, font=(design.FONT_UI, 8), indicatorcolor=design.SURFACE, bordercolor=design.BORDER_STRONG)
        style.map("TRadiobutton", background=[("active", self.PANEL)], foreground=[("active", self.TEXT)], indicatorcolor=[("selected", self.ACCENT)])
        style.configure("Aim.TCombobox", fieldbackground=design.SURFACE, background=design.SURFACE,
                        foreground=self.TEXT, arrowcolor=self.TEXT, bordercolor=design.BORDER_STRONG,
                        lightcolor=design.BORDER, darkcolor=design.BORDER, padding=3)
        style.map("Aim.TCombobox", fieldbackground=[("readonly", design.SURFACE), ("disabled", design.SURFACE_ALT)],
                  foreground=[("readonly", self.TEXT), ("disabled", design.TEXT_DISABLED)],
                  selectbackground=[("readonly", design.ACCENT_SOFT)], selectforeground=[("readonly", self.TEXT)])
        style.configure("Luna.Horizontal.TScale", background=self.PANEL, troughcolor=design.BORDER,
                        bordercolor=design.BORDER, lightcolor=design.ACCENT,
                        darkcolor=design.ACCENT, sliderthickness=6, gripcount=0)

    def _compact(self) -> bool:
        return self.menu_scale_var.get() == 75

    def _metric(self, regular: int, compact: int) -> int:
        return compact if self._compact() else regular

    def _configure_overlay_menu(self) -> None:
        self.root.update_idletasks()
        get_ancestor = ctypes.windll.user32.GetAncestor
        get_ancestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        get_ancestor.restype = ctypes.c_void_p
        self.menu_hwnd = get_ancestor(self.root.winfo_id(), 2) or self.root.winfo_id()
        get_style = ctypes.windll.user32.GetWindowLongPtrW
        set_style = ctypes.windll.user32.SetWindowLongPtrW
        get_style.argtypes = (ctypes.c_void_p, ctypes.c_int)
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
        set_style.restype = ctypes.c_ssize_t
        style = get_style(self.menu_hwnd, -20)
        set_style(self.menu_hwnd, -20, (style | 0x80) & ~0x40000)  # TOOLWINDOW, no taskbar button
        create_region = ctypes.windll.gdi32.CreateRoundRectRgn
        create_region.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int)
        create_region.restype = ctypes.c_void_p
        set_region = ctypes.windll.user32.SetWindowRgn
        set_region.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)
        set_region.restype = ctypes.c_int
        rounded = create_region(0, 0, self.WIDTH + 1, self.HEIGHT + 1, 18, 18)
        if rounded:
            set_region(self.menu_hwnd, rounded, True)

    def _position_overlay_menu(self) -> None:
        if self.visible:
            rect = self.fov_overlay._rect()
            if rect:
                left, top, width, height = rect
                x = left + max(0, (width - self.WIDTH) // 2)
                y = top + max(0, (height - self.HEIGHT) // 2)
                self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self._position_esp_preview()

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_menu(self, event: tk.Event) -> None:
        dx, dy = getattr(self, "_drag_origin", (0, 0))
        self.root.geometry(f"+{event.x_root-dx}+{event.y_root-dy}")
        self.root.after_idle(self._position_esp_preview)

    def _build(self, status: str) -> None:
        body = tk.Frame(self.root, bg=self.BG)
        body.pack(fill="both", expand=True)
        sidebar = tk.Frame(body, bg=design.SURFACE_ALT, width=self._metric(225, 180), highlightbackground=design.BORDER, highlightthickness=1)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        side_header = tk.Frame(sidebar, bg=design.SURFACE_ALT, height=self._metric(82, 66))
        side_header.pack(fill="x")
        side_header.pack_propagate(False)
        tk.Label(side_header, text="LUNA", fg=self.TEXT, bg=design.SURFACE_ALT,
                 font=(design.FONT_UI, self._metric(20, 16), "bold")).pack(anchor="w", padx=18, pady=(15, 0))
        tk.Label(side_header, text=f"CONTROL PANEL  /  {APP_VERSION}", fg=self.MUTED, bg=design.SURFACE_ALT,
                 font=(design.FONT_MONO, 6)).pack(anchor="w", padx=18)
        tk.Frame(sidebar, bg=design.BORDER, height=1).pack(fill="x", padx=14)
        nav_host = tk.Frame(sidebar, bg=design.SURFACE_ALT)
        nav_host.pack(fill="both", expand=True)
        nav = tk.Frame(nav_host, bg=design.SURFACE_ALT)
        nav.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.92)
        for widget in (body, sidebar, side_header):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag_menu)
        holder_shell = tk.Frame(body, bg=self.BG)
        holder_shell.pack(side="left", fill="both", expand=True, padx=self._metric(16, 10), pady=self._metric(14, 10))
        self.page_canvas = tk.Canvas(
            holder_shell,
            bg=self.BG,
            highlightthickness=0,
            bd=0,
        )
        self.page_canvas.pack(fill="both", expand=True)
        holder = tk.Frame(self.page_canvas, bg=self.BG)
        page_window = self.page_canvas.create_window((0, 0), window=holder, anchor="nw")
        holder.bind("<Configure>", lambda _event: self.page_canvas.configure(scrollregion=self.page_canvas.bbox("all")))
        self.page_canvas.bind("<Configure>", lambda event: self.page_canvas.itemconfigure(page_window, width=event.width))
        self.page_canvas.bind("<MouseWheel>", lambda event: self.page_canvas.yview_scroll(-max(1, event.delta // 120), "units"))
        self.pages: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.nav_rows: dict[str, tk.Frame] = {}
        self.nav_marks: dict[str, tk.Frame] = {}
        self.nav_icon_canvases: dict[str, tk.Canvas] = {}
        nav_fallback = {"Aim": "◎", "Vision": "◉", "Inventory": "▣", "Misc": "⌁"}
        for name in ("Aim", "Vision", "Misc", "Settings"):
            row = tk.Frame(nav, bg=design.SURFACE_ALT)
            row.pack(fill="x", padx=4, pady=2)
            mark = tk.Frame(row, bg=design.SURFACE_ALT, width=2)
            mark.pack(side="left", fill="y")
            icon = self._nav_icon(row, name)
            icon.pack(side="left", padx=(10, 2))
            self.nav_icon_canvases[name] = icon
            nav_label = "ESP" if name == "Vision" else self._t(name).upper()
            button = tk.Button(row, text=nav_label,
                               command=lambda page=name: self._show_page(page),
                               anchor="w", relief="flat", bd=0, padx=6, pady=self._metric(10, 6), cursor="hand2",
                               font=(design.FONT_UI, 9, "bold"), bg=design.SURFACE_ALT, fg=self.MUTED,
                               activebackground=design.SURFACE_HOVER, activeforeground=self.TEXT,
                               highlightbackground=design.BORDER, highlightthickness=0)
            button.pack(side="left", fill="x", expand=True)
            self.nav_buttons[name] = button
            self.nav_rows[name] = row
            self.nav_marks[name] = mark
            page = tk.Frame(holder, bg=self.BG)
            self.pages[name] = page

        tk.Button(sidebar, text="×", command=self.close, bg=design.SURFACE_ALT, fg=self.MUTED,
                  activebackground=design.SURFACE_ALT, activeforeground=self.TEXT, relief="flat", bd=0,
                  font=(design.FONT_UI, 11), cursor="hand2").pack(side="bottom", anchor="e", padx=10, pady=(0, 8))
        tk.Checkbutton(sidebar, text="MASTER", variable=self.enabled_var, command=self._sync, bg=design.SURFACE_ALT,
                       fg=self.TEXT, activebackground=design.SURFACE_ALT, activeforeground=self.ACCENT,
                       selectcolor=self.ACCENT, font=(design.FONT_UI, 9, "bold")).pack(side="bottom", anchor="w", padx=18, pady=(4, 18))
        tk.Label(sidebar, text="F1  OPEN / CLOSE", justify="left",
                 fg=self.MUTED, bg=design.SURFACE_ALT, font=(design.FONT_MONO, 8)).pack(side="bottom", pady=4)
        tk.Label(sidebar, text="LUNA  /  DESKTOP", fg=design.TEXT_DISABLED, bg=design.SURFACE_ALT,
                 font=(design.FONT_MONO, 7)).pack(side="bottom", pady=(4, 8))

        aim = self.pages["Aim"]
        aim_subnav = tk.Frame(aim, bg=self.BG)
        aim_subnav.pack(fill="x", pady=(0, 7))
        aim_subnav_center = tk.Frame(aim_subnav, bg=self.BG)
        aim_subnav_center.pack(anchor="center")
        self.aim_subpages = {name: tk.Frame(aim, bg=self.BG)
                             for name in ("AIMBOT", "PISTOL", "RIFLE", "SNIPER", "SMG")}
        self.aim_subnav_buttons = {}
        self.aim_weapon_icons: dict[str, tuple[tk.PhotoImage, tk.PhotoImage]] = {}
        category_icons = {
            "PISTOL": "deagle.png", "RIFLE": "ak47.png",
            "SNIPER": "awp.png", "SMG": "mp9.png",
        }
        for label in self.aim_subpages:
            icon = None
            icon_path = ASSET_DIR / "cs2_icons" / category_icons.get(label, "")
            if label != "AIMBOT" and icon_path.exists():
                try:
                    source = tk.PhotoImage(file=str(icon_path))
                    scale = max(1, math.ceil(max(source.width() / 34, source.height() / 18)))
                    sampled = source.subsample(scale, scale)
                    inactive_icon = self._tint_icon(sampled, self.TEXT if self.menu_theme_var.get() == "Nightware" else "#000000")
                    active_icon = self._tint_icon(sampled, self.TEXT)
                    self.aim_weapon_icons[label] = (inactive_icon, active_icon)
                    icon = inactive_icon
                except tk.TclError:
                    icon = None
            button = tk.Button(aim_subnav_center, text=label, image=icon, compound="left",
                               command=lambda value=label: self._show_aim_subpage(value),
                               bg=design.SURFACE_ALT, fg=self.TEXT if self.menu_theme_var.get() == "Nightware" else self.MUTED,
                               activebackground=design.SURFACE_HOVER, activeforeground=self.TEXT,
                               relief="solid", bd=1, padx=self._metric(18, 10), pady=self._metric(7, 4), cursor="hand2",
                               font=(design.FONT_UI, 8, "bold"))
            button.pack(side="left", padx=(0, 6))
            self.aim_subnav_buttons[label] = button
        self._page_title(aim, "Aim", "Weapon and target control")
        aim_general = self.aim_subpages["AIMBOT"]
        aim_left = self._group(aim_general, "AIMBOT", "Target acquisition and aim assist")
        aim_left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        aim_right = self._group(aim_general, "TARGETING", "Selection, timing and automation")
        aim_right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self._check(aim_left, "Enable Aimbot", self.aim_var)
        self._check_color(aim_left, "Draw FOV", self.show_fov_var, "FOV")
        self._check(aim_left, "Target Lock", self.aim_lock_var)
        self._check(aim_left, "Visible Check", self.visibility_check_var)
        self._check(aim_left, "Ignore Teammates", self.ignore_teammates_var)
        self._bind_control(aim_left, "Aim Hotkey", "aim", self.aim_key_var, self.aim_key_mode_var)
        self._combo(aim_left, "Hitbox", self.target_var, (
            "Nearest part", "head", "neck", "chest", "stomach", "pelvis",
            "left shoulder", "left arm", "right shoulder", "right arm",
        ))
        self._check(aim_left, "Dynamic FOV", self.dynamic_fov_var)
        self._combo(aim_left, "Priority", self.target_priority_var, ("Crosshair", "Distance", "Lowest HP"))
        self._check(aim_left, "Hitbox fallback", self.hitbox_fallback_var)
        self._slider(aim_left, "First delay ms", self.first_shot_delay_var, 0.0, 300.0, 5.0)
        self._slider(aim_left, "Switch delay", self.target_switch_delay_var, 0.0, 500.0, 10.0)
        self._slider(aim_left, "Lock timeout", self.lock_timeout_var, 0.0, 5000.0, 100.0)
        self._slider(aim_left, "Dead-zone", self.aim_dead_zone_var, 0.0, 2.0, 0.05)
        self._slider(aim_left, "Maximum step", self.aim_max_step_var, 0.1, 8.0, 0.1)
        self._check(aim_right, "No Visual Recoil", self.shake_var)
        self._check(aim_right, "Triggerbot", self.triggerbot_var)
        self._check(aim_right, "Shoot In Smoke", self.shoot_in_smoke_var)
        self._check(aim_right, "Auto Fire", self.auto_shoot_var)
        self._check(aim_right, "Auto Stop", self.auto_stop_var)
        self._slider(aim_right, "Trigger Delay", self.trigger_delay_var, 0.0, 150.0, 5.0)

        for name, weapon, fov_variable, smooth_variable in (
            ("PISTOL", "pistol", self.aim_fov_pistol_var, self.aim_smooth_pistol_var),
            ("RIFLE", "rifle", self.aim_fov_rifle_var, self.aim_smooth_rifle_var),
            ("SNIPER", "sniper", self.aim_fov_sniper_var, self.aim_smooth_sniper_var),
            ("SMG", "smg", self.aim_fov_smg_var, self.aim_smooth_smg_var),
        ):
            profile = self.aim_subpages[name]
            values = self._group(profile, f"{name} PROFILE", "Automatically selected by active weapon")
            values.pack(side="left", fill="both", expand=True, padx=(0, 6))
            behavior = self._group(profile, "RECOIL CONTROL", "Class-specific Memory/Pattern RCS")
            behavior.pack(side="left", fill="both", expand=True, padx=(6, 0))
            self._slider(values, "FOV", fov_variable, 1.0, 30.0, 0.5)
            self._slider(values, "Smoothing", smooth_variable, 1.0, 20.0, 0.5)
            rcs = self.rcs_profile_vars[weapon]
            self._check_rcs_mode(behavior, rcs["enabled"])
            self._slider(behavior, "RCS Amount", rcs["amount"], 0.0, 200.0, 5.0)
            self._slider(behavior, "RCS Smoothing", rcs["smooth"], 1.0, 5.0, 0.25)
            self._slider(behavior, "RCS start bullet", rcs["start"], 1.0, 8.0, 1.0)
            self._slider(behavior, "RCS X", rcs["x"], 0.0, 200.0, 5.0)
            self._slider(behavior, "RCS Y", rcs["y"], 0.0, 200.0, 5.0)
        self._show_aim_subpage("AIMBOT")

        vision = self.pages["Vision"]
        subnav = tk.Frame(vision, bg=self.BG)
        subnav.pack(fill="x", pady=(0, 7))
        vision_subnav_left = tk.Frame(subnav, bg=self.BG)
        vision_subnav_left.pack(anchor="w")
        self.vision_subpages = {
            "ESP": tk.Frame(vision, bg=self.BG),
            "WORLD": tk.Frame(vision, bg=self.BG),
        }
        self.vision_subnav_buttons = {}
        for label in ("ESP", "WORLD"):
            button = tk.Button(vision_subnav_left, text=label, command=lambda value=label: self._show_vision_subpage(value),
                               bg=design.SURFACE_ALT, fg=self.MUTED, activebackground=design.SURFACE_HOVER,
                               activeforeground=self.TEXT, relief="solid", bd=1, highlightthickness=0,
                               padx=self._metric(20, 12), pady=self._metric(5, 3), cursor="hand2",
                               font=(design.FONT_UI, self._metric(8, 7), "bold"))
            button.pack(side="left", padx=(0, 6))
            self.vision_subnav_buttons[label] = button
        self._page_title(vision, "ESP", "Players, world and overlay interface")

        esp_page = self.vision_subpages["ESP"]
        player_main = self._group(esp_page, "PLAYER ESP", "Targets and information")
        player_main.pack(side="left", fill="both", expand=True, padx=(0, 6))
        player_style = self._group(esp_page, "BOX / STYLE", "Shape, colors and details")
        player_style.pack(side="left", fill="both", expand=True, padx=6)

        world_page = self.vision_subpages["WORLD"]
        world_page.grid_columnconfigure(0, weight=1, uniform="world")
        world_page.grid_columnconfigure(1, weight=1, uniform="world")
        local = self._group(world_page, "WORLD ESP", "Bomb and dropped items")
        local.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        hud_group = self._group(world_page, "HUD", "Interface panels and editor")
        hud_group.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 6))
        world_tools = self._group(world_page, "WORLD / PERFORMANCE", "Atmosphere and update rates")
        world_tools.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self._check(player_main, "Glow", self.glow_var)
        self._combo(player_main, "ESP Preset", self.esp_preset_var, ("Legit", "Minimal", "Full", "Custom"))
        self.esp_preset_var.trace_add("write", lambda *_: self._apply_esp_preset())
        self._check(player_main, "Enemies", self.esp_enemies_var)
        self._check(player_main, "Allies", self.esp_allies_var)
        self._check(player_main, "Bots", self.esp_bots_var)
        self._check(player_main, "Ignore Teammates", self.ignore_teammates_var)
        self._check_color(player_main, "Player Name", self.esp_name_var, "Name")
        self._check_color(player_main, "Health Bar", self.esp_health_var, "HP")
        self._check_color(player_main, "Weapon ESP", self.esp_weapon_var, "Weapon")
        self._check_color(player_main, "Armor Bar", self.esp_armor_var, "Armor")
        self._check(player_main, "Distance", self.esp_distance_var)
        self._check_box_style(player_style)
        self._check(player_style, "Box Fill", self.esp_fill_var)
        self._check_color(player_style, "Snaplines", self.esp_snapline_var, "Line")
        self._check_color(player_style, "Skeleton", self.esp_skeleton_var, "Skeleton")
        self._check(player_style, "Head Marker", self.esp_head_dot_var)
        self._slider(player_style, "Fill opacity", self.box_fill_alpha_var, 0.0, 100.0, 1.0)
        self._slider(player_style, "Box thickness", self.box_thickness_var, 0.5, 5.0, 0.25)
        self._slider(player_style, "Corner length", self.corner_length_var, 10.0, 50.0, 1.0)
        modes = tk.Frame(player_style, bg=self.PANEL)
        modes.pack(fill="x", padx=16, pady=5)
        ttk.Radiobutton(modes, text="Health", variable=self.color_mode, value="health", command=self._sync).pack(side="left")
        ttk.Radiobutton(modes, text="Custom", variable=self.color_mode, value="custom", command=self._sync).pack(side="left", padx=6)
        self.color_button = tk.Button(modes, text=" ", bg=self.custom_color, width=3, relief="flat", command=self.choose_color)
        self.color_button.pack(side="right")
        self._check_color(local, "Bomb ESP", self.world_bomb_esp_var, "World")
        self._check(local, "Bomb Info HUD", self.world_bomb_info_var)
        self._check_color(local, "Dropped Weapons", self.world_weapon_esp_var, "World")
        self._check(local, "Active weapons", self.weapon_filter_active_var)
        self._check(local, "Grenades", self.weapon_filter_grenades_var)
        self._check(local, "C4", self.weapon_filter_c4_var)
        self._check(local, "Knives", self.weapon_filter_knives_var)
        self._check(hud_group, "Game HUD", self.hud_enabled_var)
        self._check(hud_group, "Keybind List", self.keybind_list_var)
        self._check(hud_group, "Performance panel", self.performance_panel_var)
        self._check(hud_group, "State indicators", self.esp_state_indicators_var)
        self._check_color(hud_group, "Custom crosshair", self.crosshair_var, "Crosshair")
        self._slider(hud_group, "Crosshair", self.crosshair_size_var, 3.0, 18.0, 1.0)
        self._check(hud_group, "Watermark", self.watermark_var)
        self._check(hud_group, "Overlay FPS", self.overlay_fps_var)
        self._check(world_tools, "Cinema bars", self.cinema_bars_var)
        self._slider(world_tools, "Cinema size", self.cinema_bar_size_var, 2.0, 20.0, 1.0)
        self._check(world_tools, "Hide on screenshot", self.screenshot_cleanup_var)
        self._check(world_tools, "Disable cosmetics in menu", self.disable_cosmetics_in_menu_var)
        self._slider(world_tools, "ESP rate", self.esp_rate_var, 30.0, 240.0, 1.0)
        self._slider(world_tools, "World rate", self.world_rate_var, 5.0, 60.0, 1.0)
        self._slider(world_tools, "HUD rate", self.hud_rate_var, 1.0, 30.0, 1.0)
        self._check(world_tools, "Night Mode", self.world_night_var)
        tk.Label(world_tools, text="Night Mode is rendered as a click-through color layer.",
                 fg=self.MUTED, bg=self.PANEL, wraplength=210, justify="left",
                 font=(design.FONT_UI, 8)).pack(anchor="w", padx=16, pady=(8, 12))
        self._show_vision_subpage("ESP")

        misc = self.pages["Misc"]
        self._page_title(misc, "Misc", "Movement and effects")
        movement = self._group(misc, "MOVEMENT", "Player movement")
        movement.pack(side="left", fill="both", expand=True, padx=(0, 6))
        effects = self._group(misc, "EFFECTS", "Screen effects")
        effects.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self._config_panel(movement)
        self._check(effects, "No Flash", self.flash_var)
        self._check(effects, "Radar Reveal", self.radar_var)
        self._check(effects, "Overlay clock", self.overlay_clock_var)
        self._check(effects, "Aim indicator", self.aim_indicator_var)
        tk.Label(effects, text="Settings are saved automatically.", fg=self.MUTED, bg=self.PANEL, wraplength=180,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=12)

        settings_page = self.pages["Settings"]
        self._page_title(settings_page, "Settings", "Interface preferences")
        appearance = self._group(settings_page, "APPEARANCE", "Theme and layout")
        appearance.pack(side="left", fill="both", expand=True, padx=(0, 6))
        preview_settings = self._group(settings_page, "ESP PREVIEW", "Separate window next to the menu")
        preview_settings.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self._combo(appearance, "Theme", self.menu_theme_var, ("Nightware", "Editorial"), command=self._apply_interface_settings)
        self._combo(appearance, "Menu size", self.menu_scale_var, (75, 100, 125), command=self._apply_interface_settings)
        tk.Label(appearance, text="100% is the default size. Changes apply immediately.", fg=self.MUTED,
                 bg=self.PANEL, wraplength=260, justify="left", font=(design.FONT_UI, 8)).pack(anchor="w", padx=16, pady=(10, 0))
        self._check(preview_settings, "Show ESP Preview", self.esp_preview_enabled_var)
        tk.Label(preview_settings, text="The preview is a separate companion window. It follows the menu and hides with F1.",
                 fg=self.MUTED, bg=self.PANEL, wraplength=260, justify="left", font=(design.FONT_UI, 8)).pack(anchor="w", padx=16, pady=(8, 0))

        self._show_page("Aim")
        self._sync_esp_preview_window()

    def _sync_esp_preview_window(self) -> None:
        enabled = self.esp_preview_enabled_var.get()
        window = self.esp_preview_window
        if not enabled:
            if window is not None and window.winfo_exists():
                window.withdraw()
            return
        if window is None or not window.winfo_exists():
            window = tk.Toplevel(self.root)
            self.esp_preview_window = window
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.configure(bg=design.BORDER_STRONG)
            body = tk.Frame(window, bg=self.PANEL)
            body.pack(fill="both", expand=True, padx=1, pady=1)
            header = tk.Frame(body, bg=self.PANEL_2, height=36)
            header.pack(fill="x")
            header.pack_propagate(False)
            tk.Label(header, text="ESP PREVIEW", bg=self.PANEL_2, fg=self.TEXT,
                     font=(design.FONT_UI, 8, "bold")).pack(side="left", padx=12, pady=10)
            tk.Label(header, text="LIVE", bg=self.PANEL_2, fg=self.ACCENT,
                     font=(design.FONT_MONO, 7, "bold")).pack(side="right", padx=12)
            self.esp_preview = tk.Canvas(body, width=358, height=326, bg=self.PANEL,
                                         highlightthickness=0, bd=0)
            self.esp_preview.pack(fill="both", expand=True)
            try:
                source_image = tk.PhotoImage(file=str(ASSET_DIR / "cs2-ct-player-transparent.png"))
                sample = 4
                self.esp_preview_image = source_image.subsample(sample, sample)
            except tk.TclError:
                self.esp_preview_image = None
            window.protocol("WM_DELETE_WINDOW", lambda: self.esp_preview_enabled_var.set(False) or self._sync())
        if self._should_show_esp_preview():
            window.deiconify()
            self._position_esp_preview()
        else:
            window.withdraw()
        self._draw_esp_preview()

    def _should_show_esp_preview(self) -> bool:
        return (self.visible and self.esp_preview_enabled_var.get()
                and getattr(self, "current_page", "") == "Vision"
                and getattr(self, "current_vision_subpage", "") == "ESP")

    def _position_esp_preview(self) -> None:
        window = self.esp_preview_window
        if window is None or not window.winfo_exists() or not self._should_show_esp_preview():
            return
        self.root.update_idletasks()
        preview_width = 250 if self._compact() else 290
        preview_height = round(self.root.winfo_height() * 0.70)
        preview_x = self.root.winfo_x() + self.root.winfo_width() + 8
        preview_y = self.root.winfo_y() + (self.root.winfo_height() - preview_height) // 2
        window.geometry(f"{preview_width}x{preview_height}+{preview_x}+{preview_y}")

    @staticmethod
    def _rounded_preview_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
                              radius: float, fill: str, outline: str) -> None:
        points = (
            x1 + radius, y1, x2 - radius, y1, x2, y1 + radius, x2, y2 - radius,
            x2 - radius, y2, x1 + radius, y2, x1, y2 - radius, x1, y1 + radius,
        )
        canvas.create_polygon(points, smooth=True, splinesteps=16, fill=fill, outline=outline, width=1)

    def _apply_interface_settings(self) -> None:
        scale = self.menu_scale_var.get()
        if scale not in (75, 100, 125):
            scale = 100
            self.menu_scale_var.set(scale)
        self.WIDTH = round(900 * scale / 100)
        self.HEIGHT = round(740 * scale / 100) + (35 if scale == 75 else 0)
        self.root.minsize(round(760 * scale / 100), round(620 * scale / 100))
        self._select_theme(self.menu_theme_var.get())
        self._styles()
        if self.esp_preview_window is not None and self.esp_preview_window.winfo_exists():
            self.esp_preview_window.destroy()
        self.esp_preview_window = None
        for child in self.root.winfo_children():
            child.destroy()
        self._build(self._menu_status)
        self._configure_overlay_menu()
        self._position_overlay_menu()
        self._sync()

    def _draw_esp_preview(self) -> None:
        if not hasattr(self, "esp_preview") or not self.esp_preview.winfo_exists():
            return
        canvas = self.esp_preview
        canvas.delete("esp_preview")
        canvas.update_idletasks()
        canvas_width = max(268, canvas.winfo_width())
        canvas_height = max(326, canvas.winfo_height())
        box_width = 140 if canvas_width >= 330 else 120
        box_height = 340 if canvas_height >= 460 else 262
        left, right = canvas_width / 2 - box_width / 2, canvas_width / 2 + box_width / 2
        top, bottom = max(28, (canvas_height - box_height) / 2), max(28, (canvas_height - box_height) / 2) + box_height
        center_x, head_y = (left + right) / 2, 43
        head_y = top + 15
        if getattr(self, "esp_preview_image", None) is not None:
            canvas.create_image(center_x, (top + bottom) / 2 + 4, image=self.esp_preview_image,
                                tags=("esp_preview",))
        box_color = self.element_colors["Box"].get()
        if self.esp_fill_var.get() and self.box_var.get():
            canvas.create_rectangle(left, top, right, bottom, fill=box_color, outline="",
                                    stipple="gray50" if self.box_fill_alpha_var.get() >= 35 else "gray25",
                                    tags=("esp_preview",))
        if self.box_var.get():
            if self.box_style_var.get() == "corner":
                ratio = self.corner_length_var.get()/100.0
                x_len, y_len = (right-left)*ratio, (bottom-top)*ratio*.5
                for x1, y1, x2, y2 in (
                    (left,top,left+x_len,top),(left,top,left,top+y_len),
                    (right,top,right-x_len,top),(right,top,right,top+y_len),
                    (left,bottom,left+x_len,bottom),(left,bottom,left,bottom-y_len),
                    (right,bottom,right-x_len,bottom),(right,bottom,right,bottom-y_len),
                ):
                    canvas.create_line(x1,y1,x2,y2,fill=box_color,width=2,tags=("esp_preview",))
            else:
                canvas.create_rectangle(left, top, right, bottom, outline=box_color, width=2,
                                        tags=("esp_preview",))
        if self.esp_name_var.get():
            canvas.create_text(center_x, top - 10, text="LUNA PLAYER", fill=self.element_colors["Name"].get(),
                               font=("Segoe UI", 7, "bold"), tags=("esp_preview",))
        if self.esp_health_var.get():
            hp, bar_x = 72, left - 7
            hp_top = bottom - (bottom - top) * hp / 100
            hp_color = "#47c95a" if self.color_mode.get() == "health" else self.element_colors["HP"].get()
            canvas.create_rectangle(bar_x - 2, top, bar_x + 1, bottom, fill="#191919", outline="",
                                    tags=("esp_preview",))
            canvas.create_rectangle(bar_x - 1, hp_top, bar_x, bottom, fill=hp_color, outline="",
                                    tags=("esp_preview",))
            canvas.create_text(bar_x - 5, hp_top, text=str(hp), anchor="e", fill="#ffffff",
                               font=("Segoe UI", 6, "bold"), tags=("esp_preview",))
        if self.esp_armor_var.get():
            armor = 84
            canvas.create_rectangle(left, bottom + 4, right, bottom + 6, fill="#191919", outline="",
                                    tags=("esp_preview",))
            canvas.create_rectangle(left, bottom + 4, left + (right-left) * armor / 100, bottom + 6,
                                    fill=self.element_colors["Armor"].get(), outline="", tags=("esp_preview",))
        if self.esp_weapon_var.get():
            canvas.create_text(center_x, bottom + 16, text="▸ M4A1-S", fill=self.element_colors["Weapon"].get(),
                               font=("Segoe UI Symbol", 7), tags=("esp_preview",))
        if self.esp_distance_var.get():
            canvas.create_text(center_x, bottom + 29, text="18 m", fill=self.element_colors["Name"].get(),
                               font=("Segoe UI", 6), tags=("esp_preview",))
        if self.esp_snapline_var.get():
            canvas.create_line(canvas_width / 2, canvas_height - 16, center_x, bottom, fill=self.element_colors["Line"].get(),
                               width=1, tags=("esp_preview",))
        if self.esp_skeleton_var.get():
            color = self.element_colors["Skeleton"].get()
            points = {
                "head": (center_x, top + 28), "neck": (center_x, top + 51), "chest": (center_x, top + 88),
                "pelvis": (center_x, top + 148), "ls": (center_x - 30, top + 74), "le": (center_x - 43, top + 120), "lh": (center_x - 50, top + 164),
                "rs": (center_x + 30, top + 74), "re": (center_x + 43, top + 120), "rh": (center_x + 50, top + 164),
                "lk": (center_x - 23, top + 202), "lf": (center_x - 29, top + 254), "rk": (center_x + 23, top + 202), "rf": (center_x + 29, top + 254),
            }
            for first, second in (
                ("head", "neck"), ("neck", "chest"), ("chest", "pelvis"),
                ("chest", "ls"), ("ls", "le"), ("le", "lh"),
                ("chest", "rs"), ("rs", "re"), ("re", "rh"),
                ("pelvis", "lk"), ("lk", "lf"), ("pelvis", "rk"), ("rk", "rf"),
            ):
                canvas.create_line(*points[first], *points[second], fill=color, width=2,
                                   tags=("esp_preview",))
        if self.esp_head_dot_var.get():
            canvas.create_oval(center_x-3, head_y-3, center_x+3, head_y+3, fill=box_color, outline="",
                               tags=("esp_preview",))

    def _profile_palette(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=self.PANEL)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        for key, label in (("LowHP", "LOW HP"), ("Bomb", "C4")):
            button = tk.Button(bar, text=label, bg=self.element_colors[key].get(), fg="#ffffff",
                               activeforeground="#ffffff", relief="flat", cursor="hand2",
                               font=(design.FONT_UI, 7, "bold"),
                               command=lambda name=key: self._choose_element_color(name))
            button.pack(side="left", expand=True, fill="x", padx=1)
            self.element_color_buttons[key] = button

    def _skin_weapon_changed(self) -> None:
        if not hasattr(self, "skin_name_combo"):
            return
        names = tuple(SKIN_CATALOG.get(self.skin_weapon_var.get(), {}))
        self.skin_name_combo.configure(values=names)
        if names and self.skin_name_var.get() not in names:
            self.skin_name_var.set(names[0])
        self._sync()

    def _apply_inventory_selection(self) -> None:
        self.skin_changer_var.set(True)
        self._sync()
        settings = self.state.get()
        loadout = {
            name: dict(entry) for name, entry in settings.skin_loadout.items()
            if isinstance(entry, dict)
        }
        weapon_name = self.skin_weapon_var.get()
        if weapon_name in SKIN_CATALOG and any(
                finish.target_definition in KNIFE_DEFINITIONS
                for finish in SKIN_CATALOG[weapon_name].values()):
            knife_names = {
                name for name, finishes in SKIN_CATALOG.items()
                if any(finish.target_definition in KNIFE_DEFINITIONS for finish in finishes.values())
            }
            for knife_name in knife_names:
                loadout.pop(knife_name, None)
        loadout[weapon_name] = {
            "skin": self.skin_name_var.get(),
            "wear": float(self.skin_wear_var.get()),
            "seed": int(self.skin_seed_var.get()),
            "stattrak": self.skin_stattrak_var.get(),
        }
        self.state.set(skin_loadout=loadout)
        self.cheats.request_skin_refresh()
        self.inventory_apply_button.configure(text="SAVED — APPLIES ON NEXT SPAWN", bg=design.SUCCESS)
        self.root.after(1400, lambda: self.inventory_apply_button.configure(
            text="SAVE TO LOADOUT", bg=self.ACCENT
        ) if self.inventory_apply_button.winfo_exists() else None)

    def _init_stars(self) -> None:
        self.stars: list[tuple[int, int]] = []
        width = max(260, self.WIDTH - 520)
        for _ in range(max(18, self.WIDTH // 35)):
            x, y = random.randint(2, width), random.randint(5, 52)
            radius = random.choice((1, 1, 1, 2))
            item = self.star_canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                                                fill=random.choice(("#303030", "#555555", "#888888")), outline="")
            self.stars.append((item, radius))
        self.root.after(200, self._animate_stars)

    def _animate_stars(self) -> None:
        if self.visible and self.root.winfo_exists():
            shades = ("#292929", "#444444", "#707070", self.ACCENT)
            for item, _radius in random.sample(self.stars, k=max(1, len(self.stars)//5)):
                self.star_canvas.itemconfigure(item, fill=random.choice(shades))
        if not self.stop.is_set():
            self.root.after(200, self._animate_stars)

    @staticmethod
    def _ease(value: float) -> float:
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    def _animate_splash(self) -> None:
        if not self.splash_active or self.stop.is_set():
            return
        elapsed = time.monotonic() - self.splash_started
        if elapsed < 2.50:
            self.splash_opacity = 0.78 * self._ease(elapsed / 2.50)
            self.splash_text_level = 0.0
        elif elapsed < 4.30:
            self.splash_opacity = 0.78
            self.splash_text_level = self._ease((elapsed - 2.50) / 1.80)
        elif elapsed < 7.50:
            self.splash_opacity = 0.78
            self.splash_text_level = 1.0
        elif elapsed < 10.0:
            fade = self._ease((elapsed - 7.50) / 2.50)
            self.splash_opacity = max(0.01, 0.78 * (1.0 - fade))
            self.splash_text_level = 1.0 - fade
        else:
            self.splash_active = False
            self.splash_opacity = 1.0
            self.splash_text_level = 0.0
            if not self.visible:
                self.toggle()
            return
        self.root.after(16, self._animate_splash)

    @staticmethod
    def _tint_icon(source: tk.PhotoImage, color: str) -> tk.PhotoImage:
        """Preserve PNG transparency while replacing visible pixels."""
        result = tk.PhotoImage(width=source.width(), height=source.height())
        for y in range(source.height()):
            for x in range(source.width()):
                try:
                    transparent = source.transparency_get(x, y)
                except tk.TclError:
                    transparent = False
                if transparent:
                    result.transparency_set(x, y, True)
                else:
                    result.put(color, (x, y))
        return result

    def _nav_icon(self, parent: tk.Widget, name: str) -> tk.Canvas:
        canvas = tk.Canvas(parent, width=28, height=28, bg=design.SURFACE_ALT,
                           highlightthickness=0, bd=0)
        self._paint_nav_icon(canvas, name, False)
        return canvas

    def _paint_nav_icon(self, canvas: tk.Canvas, name: str, active: bool) -> None:
        canvas.delete("all")
        color = self.TEXT if active else self.MUTED
        if name == "Aim":
            canvas.create_oval(7, 7, 21, 21, outline=color, width=1)
            canvas.create_line(14, 3, 14, 8, fill=color)
            canvas.create_line(14, 20, 14, 25, fill=color)
            canvas.create_line(3, 14, 8, 14, fill=color)
            canvas.create_line(20, 14, 25, 14, fill=color)
            canvas.create_oval(12.5, 12.5, 15.5, 15.5, outline=color, width=1)
        elif name == "Vision":
            canvas.create_arc(4, 8, 24, 20, start=15, extent=150, style="arc", outline=color, width=1)
            canvas.create_arc(4, 8, 24, 20, start=195, extent=150, style="arc", outline=color, width=1)
            canvas.create_oval(11, 11, 17, 17, outline=color, width=1)
        elif name == "Misc":
            for y, x in ((8, 10), (14, 18), (20, 12)):
                canvas.create_line(5, y, 23, y, fill=color, width=1)
                canvas.create_oval(x - 2, y - 2, x + 2, y + 2, outline=color, width=1)
        else:  # Settings
            canvas.create_oval(8, 8, 20, 20, outline=color, width=1)
            canvas.create_oval(12, 12, 16, 16, outline=color, width=1)
            for x1, y1, x2, y2 in ((14, 4, 14, 8), (14, 20, 14, 24), (4, 14, 8, 14), (20, 14, 24, 14),
                                   (7, 7, 9, 9), (19, 7, 21, 9), (7, 19, 9, 21), (19, 19, 21, 21)):
                canvas.create_line(x1, y1, x2, y2, fill=color, width=1)

    def _page_title(self, parent: tk.Frame, title: str, subtitle: str) -> None:
        header = tk.Frame(parent, bg=self.BG)
        header.pack(fill="x", pady=(0, 16))
        tk.Label(header, text=f"LUNA   /   {self._t(title).upper()}", fg=self.MUTED, bg=self.BG,
                 font=(design.FONT_MONO, 7)).pack(anchor="w", pady=(0, 10))
        tk.Label(header, text=self._t(title), fg=self.TEXT, bg=self.BG, font=(design.FONT_UI, 16, "bold")).pack(anchor="w")
        tk.Label(header, text=self._t(subtitle), fg=self.MUTED, bg=self.BG, font=(design.FONT_UI, 8)).pack(anchor="w", pady=(2, 0))
        tk.Frame(header, bg=design.BORDER_STRONG, height=1).pack(fill="x", pady=(12, 0))

    def _show_vision_subpage(self, name: str) -> None:
        if not hasattr(self, "vision_subpages"):
            return
        for page_name, page in self.vision_subpages.items():
            page.pack_forget()
            active = page_name == name
            self.vision_subnav_buttons[page_name].configure(
                bg=design.SURFACE_HOVER if active else design.SURFACE_ALT,
                fg=self.TEXT if active else self.MUTED,
                highlightbackground=self.TEXT if active else design.BORDER,
            )
        self.vision_subpages[name].pack(fill="both", expand=True)
        self.current_vision_subpage = name
        self._sync_esp_preview_window()

    def _show_aim_subpage(self, name: str) -> None:
        if not hasattr(self, "aim_subpages"):
            return
        for page_name, page in self.aim_subpages.items():
            page.pack_forget()
            active = page_name == name
            button_options = {
                "bg": design.SURFACE if active else design.SURFACE_ALT,
                "fg": self.TEXT if self.menu_theme_var.get() == "Nightware" else (self.ACCENT if active else "#000000"),
                "activeforeground": self.TEXT if self.menu_theme_var.get() == "Nightware" else self.ACCENT,
                "highlightbackground": self.ACCENT if active else design.BORDER,
            }
            icons = self.aim_weapon_icons.get(page_name)
            if icons:
                button_options["image"] = icons[1] if active else icons[0]
            self.aim_subnav_buttons[page_name].configure(
                **button_options,
            )
        self.aim_subpages[name].pack(fill="both", expand=True)

    def _show_page(self, name: str) -> None:
        editor = getattr(self, "inline_color_editor", None)
        if editor is not None and editor.winfo_exists():
            editor.destroy()
        box_popup = getattr(self, "box_style_popup", None)
        if box_popup is not None and box_popup.winfo_exists():
            box_popup.destroy()
        for page_name, page in self.pages.items():
            page.pack_forget()
            active = page_name == name
            self.nav_buttons[page_name].configure(bg=design.SURFACE if active else design.SURFACE_ALT,
                                                  fg=self.TEXT if active else self.MUTED,
                                                  highlightthickness=0)
            self.nav_rows[page_name].configure(bg=design.SURFACE if active else design.SURFACE_ALT)
            self.nav_icon_canvases[page_name].configure(
                bg=design.SURFACE if active else design.SURFACE_ALT)
            self._paint_nav_icon(self.nav_icon_canvases[page_name], page_name, active)
            self.nav_marks[page_name].configure(bg=self.ACCENT if active else design.SURFACE_ALT)
        self.pages[name].pack(fill="both", expand=True)
        if hasattr(self, "page_canvas"):
            self.page_canvas.yview_moveto(0.0)
        self.current_page = name
        self._sync_esp_preview_window()
    def _group(self, parent: tk.Frame, title: str, subtitle: str) -> tk.Frame:
        group = tk.Frame(parent, bg=self.PANEL, highlightbackground=design.BORDER, highlightthickness=1)
        padding = self._metric(16, 10)
        tk.Label(group, text=self._t(title), fg=self.TEXT, bg=self.PANEL, font=(design.FONT_UI, self._metric(9, 8), "bold")).pack(anchor="w", padx=padding, pady=(self._metric(13, 8), 1))
        tk.Label(group, text=self._t(subtitle), fg=self.MUTED, bg=self.PANEL, font=(design.FONT_UI, self._metric(8, 7))).pack(anchor="w", padx=padding, pady=(0, self._metric(9, 5)))
        tk.Frame(group, bg=design.BORDER, height=1).pack(fill="x", padx=padding, pady=(0, self._metric(7, 4)))
        return group
    def _check(self, parent: tk.Frame, text: str, variable: tk.BooleanVar) -> None:
        row = tk.Frame(parent, bg=self.PANEL)
        row.pack(fill="x", padx=self._metric(16, 10), pady=self._metric(4, 2))
        ttk.Checkbutton(row, text=self._t(text), variable=variable, command=self._sync).pack(side="left")

    def _check_color(self, parent: tk.Frame, text: str, variable: tk.BooleanVar, color_key: str) -> None:
        row = tk.Frame(parent, bg=self.PANEL)
        row.pack(fill="x", padx=self._metric(16, 10), pady=self._metric(3, 2))
        ttk.Checkbutton(row, text=self._t(text), variable=variable, command=self._sync).pack(side="left")
        color = self.element_colors[color_key].get()
        button = tk.Button(row, text="●", width=2, bg=design.SURFACE_ALT, fg=color,
                           activebackground=design.SURFACE_HOVER, activeforeground=color, relief="solid", bd=1,
                           highlightbackground=design.BORDER, command=lambda key=color_key: self._choose_element_color(key), cursor="hand2")
        button.pack(side="right", padx=2)
        if not hasattr(self, "element_color_buttons"):
            self.element_color_buttons = {}
        self.element_color_buttons[color_key] = button

    def _check_box_style(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, bg=self.PANEL)
        row.pack(fill="x", padx=16, pady=3)
        ttk.Checkbutton(row, text=self._t("Bounding Box"), variable=self.box_var,
                        command=self._sync).pack(side="left")
        color = self.element_colors["Box"].get()
        color_button = tk.Button(row, text="", width=3, bg=color, activebackground=color,
                                 relief="flat", command=lambda: self._choose_element_color("Box"),
                                 cursor="hand2")
        color_button.pack(side="right", padx=(4, 2))
        if not hasattr(self, "element_color_buttons"):
            self.element_color_buttons = {}
        self.element_color_buttons["Box"] = color_button
        gear = tk.Canvas(row, width=22, height=22, bg=self.PANEL, highlightthickness=0,
                         cursor="hand2")
        gear.pack(side="right")
        cx, cy = 11, 11
        gear.create_oval(5, 5, 17, 17, outline=self.MUTED, width=2)
        gear.create_oval(9, 9, 13, 13, outline=self.MUTED, width=1)
        for x1, y1, x2, y2 in ((11,2,11,6),(11,16,11,20),(2,11,6,11),(16,11,20,11),
                               (4,4,7,7),(15,15,18,18),(4,18,7,15),(15,7,18,4)):
            gear.create_line(x1,y1,x2,y2,fill=self.MUTED,width=2)
        gear.bind("<Button-1>", lambda _event, widget=gear: self._open_box_style_popup(widget))

    def _check_rcs_mode(self, parent: tk.Frame,
                        enabled_variable: tk.BooleanVar | None = None) -> None:
        row = tk.Frame(parent, bg=self.PANEL)
        row.pack(fill="x", padx=16, pady=3)
        ttk.Checkbutton(row, text="Enable RCS", variable=enabled_variable or self.recoil_var,
                        command=self._sync).pack(side="left")
        gear = tk.Canvas(row, width=22, height=22, bg=self.PANEL,
                         highlightthickness=0, cursor="hand2")
        gear.pack(side="right")
        gear.create_oval(5, 5, 17, 17, outline=self.MUTED, width=2)
        gear.create_oval(9, 9, 13, 13, outline=self.MUTED, width=1)
        for x1, y1, x2, y2 in ((11,2,11,6),(11,16,11,20),(2,11,6,11),(16,11,20,11),
                               (4,4,7,7),(15,15,18,18),(4,18,7,15),(15,7,18,4)):
            gear.create_line(x1, y1, x2, y2, fill=self.MUTED, width=2)
        gear.bind("<Button-1>", lambda _event, widget=gear: self._open_rcs_mode_popup(widget))

    def _open_rcs_mode_popup(self, anchor: tk.Widget) -> None:
        old = getattr(self, "rcs_mode_popup", None)
        if old is not None and old.winfo_exists():
            old.destroy()
        popup = tk.Toplevel(self.root)
        self.rcs_mode_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=design.BORDER_STRONG)
        x, y = anchor.winfo_rootx()-230, anchor.winfo_rooty()+anchor.winfo_height()+5
        popup.geometry(f"270x304+{x}+{y}")
        body = tk.Frame(popup, bg=self.PANEL)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(body, text="RCS MODE", bg=self.PANEL, fg=self.MUTED,
                 font=(design.FONT_UI, 8, "bold")).pack(anchor="w", padx=12, pady=(9, 4))
        modes = tk.Frame(body, bg=self.PANEL)
        modes.pack(fill="x", padx=10)
        for label in ("Pattern RCS", "Memory RCS"):
            ttk.Radiobutton(body, text=label, variable=self.rcs_mode_var, value=label,
                            command=self._sync).pack(anchor="w", padx=10, pady=3)
        tk.Frame(body, bg=design.BORDER, height=1).pack(fill="x", padx=12, pady=(5, 3))
        tk.Label(body, text="BASE PROFILE", bg=self.PANEL, fg=self.MUTED,
                 font=(design.FONT_UI, 8, "bold")).pack(anchor="w", padx=12, pady=(2, 0))
        for label, variable, low, high, step in (
            ("Strength", self.recoil_strength_var, 0.0, 200.0, 5.0),
            ("Smoothing", self.recoil_smooth_var, 1.0, 5.0, 0.25),
            ("Start bullet", self.rcs_start_bullet_var, 1.0, 8.0, 1.0),
            ("Vertical", self.rcs_y_var, 0.0, 200.0, 5.0),
        ):
            row = tk.Frame(body, bg=self.PANEL)
            row.pack(fill="x", padx=12, pady=1)
            tk.Label(row, text=label, bg=self.PANEL, fg=self.MUTED, width=12, anchor="w",
                     font=(design.FONT_UI, 8)).pack(side="left")
            scale = tk.Scale(row, variable=variable, from_=low, to=high, resolution=step,
                             command=lambda _value: self._sync(), showvalue=False, orient="horizontal",
                             bg=self.PANEL, fg=self.TEXT, troughcolor=design.BORDER, highlightthickness=0,
                             activebackground=self.ACCENT, length=126, sliderlength=12)
            scale.pack(side="right")
        popup.focus_force()
        popup.bind("<FocusOut>", lambda _event: popup.after(
            80, lambda: popup.destroy() if popup.winfo_exists() and popup.focus_get() is None else None))

    def _open_box_style_popup(self, anchor: tk.Widget) -> None:
        old = getattr(self, "box_style_popup", None)
        if old is not None and old.winfo_exists():
            old.destroy()
        popup = tk.Toplevel(self.root)
        self.box_style_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=design.BORDER_STRONG)
        x = anchor.winfo_rootx() - 175
        y = anchor.winfo_rooty() + anchor.winfo_height() + 5
        popup.geometry(f"205x108+{x}+{y}")
        body = tk.Frame(popup, bg=self.PANEL)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(body, text="BOX STYLE", bg=self.PANEL, fg=self.MUTED,
                 font=(design.FONT_UI, 8, "bold")).pack(anchor="w", padx=12, pady=(9, 4))
        for label, value in (("Box Classic", "classic"), ("Corner Box", "corner")):
            ttk.Radiobutton(body, text=label, variable=self.box_style_var, value=value,
                            command=self._sync).pack(anchor="w", padx=10, pady=3)
        popup.bind("<FocusOut>", lambda _event: popup.after(80, lambda: popup.destroy()
                   if popup.winfo_exists() and popup.focus_get() is None else None))
        popup.focus_force()

    def _config_panel(self, parent: tk.Frame) -> None:
        tk.Frame(parent, bg=design.BORDER, height=1).pack(fill="x", padx=16, pady=12)
        tk.Label(parent, text="CONFIGS", fg=self.TEXT, bg=self.PANEL,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(0, 5))
        self.config_combo = ttk.Combobox(parent, textvariable=self.config_name_var, width=20,
                                         values=self.config_manager.names(), style="Aim.TCombobox")
        self.config_combo.pack(fill="x", padx=16, pady=4)
        buttons = tk.Frame(parent, bg=self.PANEL)
        buttons.pack(fill="x", padx=14, pady=4)
        for label, command in (("New", self._new_config), ("Save", self._save_config), ("Load", self._load_config),
                               ("Update", self._save_config), ("Delete", self._delete_config)):
            tk.Button(buttons, text=label, command=command, bg=design.SURFACE, fg=self.TEXT,
                      activebackground=design.SURFACE_HOVER, activeforeground=self.ACCENT, relief="solid", bd=1,
                      highlightbackground=design.BORDER, font=(design.FONT_UI, 8), cursor="hand2").pack(side="left", expand=True, fill="x", padx=2)

    def _refresh_configs(self) -> None:
        self.config_combo.configure(values=self.config_manager.names())

    def _apply_esp_preset(self) -> None:
        if getattr(self, "_loading_config", False):
            return
        preset = self.esp_preset_var.get()
        values = {
            "Legit": (True, True, True, False, True, False, False, False, 0.0),
            "Minimal": (True, True, False, False, False, False, False, False, 0.0),
            "Full": (True, True, True, True, True, True, True, True, 18.0),
        }.get(preset)
        if not values:
            self._sync()
            return
        variables = (self.box_var, self.esp_name_var, self.esp_health_var,
                     self.esp_armor_var, self.esp_weapon_var, self.esp_skeleton_var,
                     self.esp_snapline_var, self.esp_head_dot_var, self.box_fill_alpha_var)
        for variable, value in zip(variables, values):
            variable.set(value)
        self._sync()

    def _save_config(self) -> None:
        self._sync()
        name = self.config_manager.save(self.config_name_var.get(), self.state.get())
        self.config_name_var.set(name)
        self._refresh_configs()

    def _new_config(self) -> None:
        requested = self.config_name_var.get().strip()
        name = requested if requested and requested != "default" else "new_config"
        base = name
        index = 2
        existing = set(self.config_manager.names())
        while name in existing:
            name = f"{base}_{index}"
            index += 1
        self._sync()
        self.config_manager.save(name, self.state.get())
        self.config_name_var.set(name)
        self._refresh_configs()
        self._load_config()

    def _load_config(self) -> None:
        try:
            loaded = self.config_manager.load(self.config_name_var.get())
        except (OSError, ValueError, TypeError):
            messagebox.showerror(APP_NAME, "Не удалось загрузить CFG", parent=self.root)
            return
        self.state.set(**loaded.__dict__)
        mapping = {
            "enabled_var": "enabled", "glow_var": "glow", "flash_var": "anti_flash",
            "bhop_var": "bunny_hop", "recoil_var": "no_recoil", "recoil_strength_var": "recoil_strength",
            "bhop_key_var": "bhop_key", "bhop_key_mode_var": "bhop_key_mode",
            "recoil_smooth_var": "recoil_smooth",
            "rcs_mode_var": "rcs_mode",
            "rcs_start_bullet_var": "rcs_start_bullet", "rcs_x_var": "rcs_x", "rcs_y_var": "rcs_y",
            "shake_var": "no_shake", "aim_var": "aim_enabled", "smooth_var": "aim_smooth",
            "aim_key_var": "aim_key", "aim_key_mode_var": "aim_key_mode",
            "fov_var": "aim_fov", "target_var": "aim_target", "show_fov_var": "show_fov",
            "aim_lock_var": "aim_lock", "ignore_teammates_var": "ignore_teammates",
            "dynamic_fov_var": "dynamic_fov", "aim_fov_pistol_var": "aim_fov_pistol",
            "aim_fov_rifle_var": "aim_fov_rifle", "aim_fov_sniper_var": "aim_fov_sniper",
            "aim_fov_smg_var": "aim_fov_smg", "aim_smooth_pistol_var": "aim_smooth_pistol",
            "aim_smooth_rifle_var": "aim_smooth_rifle", "aim_smooth_sniper_var": "aim_smooth_sniper",
            "aim_smooth_smg_var": "aim_smooth_smg", "first_shot_delay_var": "first_shot_delay",
            "target_switch_delay_var": "target_switch_delay", "lock_timeout_var": "lock_timeout",
            "aim_dead_zone_var": "aim_dead_zone", "aim_max_step_var": "aim_max_step",
            "target_priority_var": "target_priority", "hitbox_fallback_var": "hitbox_fallback",
            "visibility_check_var": "visibility_check",
            "triggerbot_var": "triggerbot", "trigger_delay_var": "trigger_delay",
            "shoot_in_smoke_var": "shoot_in_smoke",
            "auto_shoot_var": "auto_shoot", "auto_stop_var": "auto_stop",
            "box_var": "box_esp", "box_style_var": "box_style", "esp_preset_var": "esp_preset",
            "box_thickness_var": "box_thickness",
            "box_fill_alpha_var": "box_fill_alpha", "corner_length_var": "corner_length",
            "esp_name_var": "esp_name", "esp_health_var": "esp_health",
            "esp_weapon_var": "esp_weapon", "esp_armor_var": "esp_armor", "esp_distance_var": "esp_distance",
            "esp_snapline_var": "esp_snapline", "esp_head_dot_var": "esp_head_dot",
            "esp_skeleton_var": "esp_skeleton",
            "world_bomb_esp_var": "world_bomb_esp", "world_bomb_info_var": "world_bomb_info",
            "world_weapon_esp_var": "world_weapon_esp", "hud_enabled_var": "hud_enabled",
            "weapon_filter_active_var": "weapon_filter_active", "weapon_filter_grenades_var": "weapon_filter_grenades",
            "weapon_filter_c4_var": "weapon_filter_c4", "weapon_filter_knives_var": "weapon_filter_knives",
            "esp_enemies_var": "esp_enemies", "esp_allies_var": "esp_allies", "esp_bots_var": "esp_bots",
            "esp_state_indicators_var": "esp_state_indicators", "keybind_list_var": "keybind_list",
            "performance_panel_var": "performance_panel",
            "esp_rate_var": "esp_rate", "world_rate_var": "world_rate", "hud_rate_var": "hud_rate",
            "cinema_bars_var": "cinema_bars", "cinema_bar_size_var": "cinema_bar_size",
            "screenshot_cleanup_var": "screenshot_cleanup",
            "disable_cosmetics_in_menu_var": "disable_cosmetics_in_menu",
            "world_filter_var": "world_filter",
            "world_filter_strength_var": "world_filter_strength",
            "world_night_var": "world_night_mode",
            "skybox_var": "skybox_name",
            "radar_var": "radar_hack", "crosshair_var": "crosshair_enabled",
            "crosshair_size_var": "crosshair_size", "watermark_var": "watermark",
            "overlay_fps_var": "overlay_fps", "esp_fill_var": "esp_fill",
            "overlay_clock_var": "overlay_clock",
            "aim_indicator_var": "aim_indicator",
            "skin_changer_var": "skin_changer", "skin_weapon_var": "skin_weapon",
            "skin_name_var": "skin_name", "skin_wear_var": "skin_wear",
            "skin_seed_var": "skin_seed", "skin_stattrak_var": "skin_stattrak",
            "menu_scale_var": "menu_scale", "menu_theme_var": "menu_theme",
            "esp_preview_enabled_var": "esp_preview_enabled",
        }
        self._loading_config = True
        try:
            for variable_name, setting_name in mapping.items():
                getattr(self, variable_name).set(getattr(loaded, setting_name))
        finally:
            self._loading_config = False
        # A traced Tk variable may have fired while applying the profile in
        # older builds. Make the loaded snapshot authoritative once more.
        self.state.set(**loaded.__dict__)
        for weapon, variables in self.rcs_profile_vars.items():
            for key, variable in variables.items():
                variable.set(getattr(loaded, f"rcs_{key}_{weapon}"))
        self.bind_buttons["aim"].configure(text=loaded.aim_key.upper())
        if "bhop" in self.bind_buttons:
            self.bind_buttons["bhop"].configure(text=loaded.bhop_key.upper())
        colors = {"Box": "box_color", "Name": "name_color", "HP": "hp_color", "Armor": "armor_color",
                  "Weapon": "weapon_color", "FOV": "fov_color", "Crosshair": "crosshair_color",
                  "Line": "line_color", "Skeleton": "skeleton_color", "World": "world_color",
                  "WorldTint": "world_filter_color", "LowHP": "profile_low_hp_color",
                  "Bomb": "profile_bomb_color"}
        for key, setting_name in colors.items():
            value = getattr(loaded, setting_name)
            self.element_colors[key].set(value)
            self.element_color_buttons[key].configure(fg=value, activeforeground=value)
        self.color_mode.set("health" if loaded.health_color else "custom")
        self.custom_color = loaded.custom_color
        self.color_button.configure(bg=loaded.custom_color, activebackground=loaded.custom_color)
        self._apply_interface_settings()

    def _delete_config(self) -> None:
        selected = self.config_name_var.get()
        if self.config_manager._safe_name(selected).casefold() == "default":
            messagebox.showinfo(APP_NAME, "CFG default нельзя удалить", parent=self.root)
            return
        self.config_manager.delete(selected)
        self.config_name_var.set("default")
        self._refresh_configs()
        self._load_config()

    def _slider(self, parent: tk.Frame, text: str, variable: tk.DoubleVar,
                minimum: float, maximum: float, resolution: float) -> None:
        row = tk.Frame(parent, bg=self.PANEL)
        row.pack(fill="x", padx=self._metric(16, 10), pady=self._metric(3, 2))
        tk.Label(row, text=self._t(text), fg=self.MUTED, bg=self.PANEL, font=(design.FONT_UI, self._metric(9, 8)), width=self._metric(14, 12), anchor="w").pack(side="left")
        value_label = tk.Label(row, textvariable=variable, fg=self.TEXT, bg=self.PANEL,
                               font=(design.FONT_MONO, self._metric(8, 7)), width=5, anchor="e")
        value_label.pack(side="right")
        def changed(raw_value: str) -> None:
            value = float(raw_value)
            snapped = round((value - minimum) / resolution) * resolution + minimum
            variable.set(max(minimum, min(maximum, snapped)))
            self._sync()

        ttk.Scale(row, variable=variable, from_=minimum, to=maximum, orient="horizontal",
                  command=changed, style="Luna.Horizontal.TScale", length=self._metric(105, 78)).pack(side="right", padx=(4, 2))

    def _combo(self, parent: tk.Frame, text: str, variable: tk.Variable, values: tuple, readonly: bool = True,
               command=None) -> None:
        row = tk.Frame(parent, bg=self.PANEL)
        row.pack(fill="x", padx=self._metric(16, 10), pady=self._metric(5, 3))
        tk.Label(row, text=self._t(text), fg=self.MUTED, bg=self.PANEL, font=("Segoe UI", self._metric(9, 8))).pack(side="left")
        combo = ttk.Combobox(row, textvariable=variable, state="readonly" if readonly else "normal", width=self._metric(14, 11),
                             values=values, style="Aim.TCombobox")
        combo.pack(side="right")
        def selected(_event=None) -> None:
            self._sync()
            if command is not None:
                command()
        combo.bind("<<ComboboxSelected>>", selected)

    def _bind_control(self, parent: tk.Frame, label: str, feature: str,
                      key_variable: tk.StringVar, mode_variable: tk.StringVar) -> None:
        row = tk.Frame(parent, bg=self.PANEL)
        row.pack(fill="x", padx=16, pady=4)
        tk.Label(row, text=label, fg=self.MUTED, bg=self.PANEL,
                 font=(design.FONT_UI, 8)).pack(side="left")
        mode = ttk.Combobox(row, textvariable=mode_variable, state="readonly", width=7,
                            values=("Hold", "Toggle"), style="Aim.TCombobox")
        mode.pack(side="right")
        mode.bind("<<ComboboxSelected>>", lambda _event: self._sync())
        button = tk.Button(row, text=key_variable.get().upper(), command=lambda: self._capture_bind(feature),
                           bg=design.SURFACE, fg=self.TEXT, activebackground=design.SURFACE_HOVER,
                           relief="solid", bd=1, width=9, pady=4, cursor="hand2",
                           font=(design.FONT_MONO, 8, "bold"))
        button.pack(side="right", padx=(0, 4))
        self.bind_buttons[feature] = button

    def _capture_bind(self, feature: str) -> None:
        if self.capture_feature is not None:
            return
        self.capture_feature = feature
        self.bind_buttons[feature].configure(text="PRESS…", fg=self.ACCENT)
        def capture(event) -> None:
            if self.capture_feature == feature and event.event_type == "down" and event.name != "f1":
                self.events.put(f"bind:{feature}:{event.name}")
        self.capture_hook = keyboard.hook(capture, suppress=False)
        mouse_names = {1: "mouse1", 2: "mouse3", 3: "mouse2", 4: "mouse4", 5: "mouse5"}
        self.root.after(120, lambda: self.root.bind_all("<ButtonPress>", lambda event: self.events.put(
            f"bind:{feature}:{mouse_names[event.num]}") if self.capture_feature == feature and event.num in mouse_names else "", add="+"))

    def _color_palette(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="ESP COLORS", fg=self.MUTED, bg=self.PANEL,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16, pady=(8, 3))
        grid = tk.Frame(parent, bg=self.PANEL)
        grid.pack(fill="x", padx=14, pady=(0, 6))
        self.element_color_buttons: dict[str, tk.Button] = {}
        for index, (name, variable) in enumerate(self.element_colors.items()):
            button = tk.Button(grid, text=name, command=lambda key=name: self._choose_element_color(key),
                               bg=design.SURFACE_ALT, fg=self.TEXT, activebackground=design.SURFACE_HOVER,
                               activeforeground=self.TEXT, relief="solid", bd=1, highlightbackground=design.BORDER,
                               font=("Segoe UI", 7, "bold"),
                               cursor="hand2", width=8)
            button.grid(row=index // 3, column=index % 3, padx=2, pady=2, sticky="ew")
            grid.grid_columnconfigure(index % 3, weight=1)
            self.element_color_buttons[name] = button

    def _choose_element_color(self, name: str) -> None:
        variable = self.element_colors[name]
        def apply(selected: str) -> None:
            variable.set(selected.lower())
            self.element_color_buttons[name].configure(fg=selected, activeforeground=selected)
            self._sync()
        self._open_color_editor(variable.get(), f"{name.upper()} COLOR", apply,
                                self.element_color_buttons[name])

    def _open_color_editor_legacy(self, initial: str, title: str, callback: Callable[[str], None],
                                  anchor: tk.Widget) -> None:
        """Open the built-in HSV/RGB color editor used by all color controls."""
        if not valid_hex_color(initial):
            initial = "#ffffff"
        previous = getattr(self, "inline_color_editor", None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()
        editor = tk.Frame(self.root, bg=design.SURFACE, highlightbackground=design.BORDER_STRONG, highlightthickness=1)
        self.inline_color_editor = editor
        self.root.update_idletasks()
        editor_width, editor_height = 460, 430
        x = anchor.winfo_rootx() - self.root.winfo_rootx() + anchor.winfo_width() - editor_width
        y = anchor.winfo_rooty() - self.root.winfo_rooty() + anchor.winfo_height() + 6
        x = max(8, min(self.WIDTH - editor_width - 8, x))
        y = max(70, min(self.HEIGHT - editor_height - 8, y))
        editor.place(x=x, y=y, width=editor_width, height=editor_height)
        editor.lift()

        top = tk.Frame(editor, bg="#0b0b0b", height=46, highlightbackground="#292929", highlightthickness=1)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text=title, bg="#0b0b0b", fg=self.TEXT,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=16)
        tk.Label(top, text="CUSTOM EDITOR", bg="#0b0b0b", fg="#555555",
                 font=("Consolas", 7)).pack(side="right", padx=16)

        body = tk.Frame(editor, bg="#090909")
        body.pack(fill="both", expand=True, padx=14, pady=12)
        picker = tk.Frame(body, bg="#090909")
        picker.pack(fill="x")
        sv_canvas = tk.Canvas(picker, width=300, height=190, bg="#111111", highlightthickness=1,
                              highlightbackground="#343434", cursor="crosshair")
        sv_canvas.pack(side="left")
        hue_canvas = tk.Canvas(picker, width=24, height=190, bg="#111111", highlightthickness=1,
                               highlightbackground="#343434", cursor="sb_v_double_arrow")
        hue_canvas.pack(side="left", padx=(8, 0))
        preview = tk.Canvas(picker, width=88, height=190, bg="#111111", highlightthickness=1,
                            highlightbackground="#343434")
        preview.pack(side="right")

        red = int(initial[1:3], 16)
        green = int(initial[3:5], 16)
        blue = int(initial[5:7], 16)
        hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        hsv = [hue, saturation, value]
        rgb_vars = [tk.IntVar(value=red), tk.IntVar(value=green), tk.IntVar(value=blue)]
        hex_var = tk.StringVar(value=initial.upper())
        busy = False
        redraw_id: str | None = None

        for y in range(190):
            color = colorsys.hsv_to_rgb(y / 189, 1.0, 1.0)
            value_hex = "#%02x%02x%02x" % tuple(round(channel * 255) for channel in color)
            hue_canvas.create_line(0, y, 24, y, fill=value_hex)

        def current_hex() -> str:
            return "#%02x%02x%02x" % tuple(max(0, min(255, variable.get())) for variable in rgb_vars)

        def draw_sv() -> None:
            nonlocal redraw_id
            redraw_id = None
            sv_canvas.delete("gradient")
            columns, rows = 60, 38
            cell_w, cell_h = 300 / columns, 190 / rows
            for row in range(rows):
                val = 1.0 - row / (rows - 1)
                for column in range(columns):
                    sat = column / (columns - 1)
                    color = colorsys.hsv_to_rgb(hsv[0], sat, val)
                    color_hex = "#%02x%02x%02x" % tuple(round(channel * 255) for channel in color)
                    sv_canvas.create_rectangle(column*cell_w, row*cell_h,
                                               (column+1)*cell_w+1, (row+1)*cell_h+1,
                                               fill=color_hex, outline="", tags=("gradient",))
            sv_canvas.tag_lower("gradient")
            draw_markers()

        def draw_markers() -> None:
            color_hex = current_hex()
            hex_var.set(color_hex.upper())
            preview.delete("all")
            preview.create_rectangle(8, 8, 80, 126, fill=color_hex, outline="#555555")
            preview.create_text(44, 145, text=color_hex.upper(), fill=self.TEXT, font=("Consolas", 8, "bold"))
            preview.create_text(44, 166, text=f"{rgb_vars[0].get()}  {rgb_vars[1].get()}  {rgb_vars[2].get()}",
                                fill=self.MUTED, font=("Consolas", 7))
            sv_canvas.delete("marker")
            x, y = hsv[1] * 300, (1.0 - hsv[2]) * 190
            sv_canvas.create_oval(x-5, y-5, x+5, y+5, outline="#000000", width=3, tags=("marker",))
            sv_canvas.create_oval(x-4, y-4, x+4, y+4, outline="#ffffff", width=1, tags=("marker",))
            hue_canvas.delete("marker")
            hy = hsv[0] * 189
            hue_canvas.create_line(0, hy, 24, hy, fill="#ffffff", width=3, tags=("marker",))

        def hsv_to_controls() -> None:
            nonlocal busy
            busy = True
            converted = colorsys.hsv_to_rgb(*hsv)
            for variable, channel in zip(rgb_vars, converted):
                variable.set(round(channel * 255))
            busy = False
            draw_markers()

        def schedule_gradient() -> None:
            nonlocal redraw_id
            if redraw_id is not None:
                editor.after_cancel(redraw_id)
            redraw_id = editor.after(20, draw_sv)

        def rgb_changed(_value: str = "") -> None:
            if busy:
                return
            channels = [variable.get() / 255 for variable in rgb_vars]
            new_h, new_s, new_v = colorsys.rgb_to_hsv(*channels)
            hue_changed = abs(new_h - hsv[0]) > 0.002
            hsv[:] = [new_h, new_s, new_v]
            draw_markers()
            if hue_changed:
                schedule_gradient()

        def pick_sv(event: tk.Event) -> None:
            hsv[1] = max(0.0, min(1.0, event.x / 300))
            hsv[2] = 1.0 - max(0.0, min(1.0, event.y / 190))
            hsv_to_controls()

        def pick_hue(event: tk.Event) -> None:
            hsv[0] = max(0.0, min(1.0, event.y / 189))
            hsv_to_controls()
            schedule_gradient()

        sv_canvas.bind("<Button-1>", pick_sv)
        sv_canvas.bind("<B1-Motion>", pick_sv)
        hue_canvas.bind("<Button-1>", pick_hue)
        hue_canvas.bind("<B1-Motion>", pick_hue)

        controls = tk.Frame(body, bg="#090909")
        controls.pack(fill="x", pady=(10, 0))
        for row, (label, variable, color) in enumerate(zip(("R", "G", "B"), rgb_vars,
                                                           ("#e25a5a", "#56c66f", "#5d83df"))):
            tk.Label(controls, text=label, bg="#090909", fg=color, width=2,
                     font=("Consolas", 9, "bold")).grid(row=row, column=0)
            tk.Scale(controls, variable=variable, from_=0, to=255, orient="horizontal", showvalue=False,
                     command=rgb_changed, length=245, bg="#090909", troughcolor="#292929",
                     activebackground=color, highlightthickness=0, bd=0).grid(row=row, column=1, sticky="ew")
            tk.Label(controls, textvariable=variable, bg="#090909", fg=self.TEXT, width=4,
                     font=("Consolas", 8)).grid(row=row, column=2, padx=(5, 8))
        hex_entry = tk.Entry(controls, textvariable=hex_var, bg="#171717", fg=self.TEXT,
                             insertbackground=self.TEXT, relief="flat", width=10, justify="center",
                             font=("Consolas", 9, "bold"))
        hex_entry.grid(row=0, column=3, rowspan=2, padx=(4, 0), ipady=6)

        def apply_hex(_event: tk.Event | None = None) -> None:
            nonlocal busy
            text = hex_var.get().strip()
            if not text.startswith("#"):
                text = "#" + text
            if not valid_hex_color(text):
                hex_entry.configure(fg="#e15b64")
                return
            hex_entry.configure(fg=self.TEXT)
            busy = True
            for variable, offset in zip(rgb_vars, (1, 3, 5)):
                variable.set(int(text[offset:offset+2], 16))
            busy = False
            hsv[:] = list(colorsys.rgb_to_hsv(*(variable.get()/255 for variable in rgb_vars)))
            schedule_gradient()
            draw_markers()

        hex_entry.bind("<Return>", apply_hex)

        actions = tk.Frame(editor, bg="#0b0b0b", height=48, highlightbackground="#292929", highlightthickness=1)
        actions.pack(fill="x", side="bottom")
        for preset in ("#ffffff", "#e34848", "#a970d6", "#54a7ff", "#55d77b"):
            tk.Button(actions, bg=preset, activebackground=preset, width=2, relief="flat", bd=0,
                      command=lambda value=preset: (hex_var.set(value), apply_hex())).pack(side="left", padx=(10, 0), pady=11)
        tk.Button(actions, text="CANCEL", command=editor.destroy, bg="#171717", fg=self.MUTED,
                  activebackground="#252525", activeforeground=self.TEXT, relief="flat",
                  font=("Segoe UI", 8, "bold"), padx=12, pady=6).pack(side="right", padx=(4, 10), pady=8)
        tk.Button(actions, text="APPLY", command=lambda: (callback(current_hex()), editor.destroy()),
                  bg=self.ACCENT, fg="#090909", activebackground="#d8d8d8", activeforeground="#090909",
                  relief="flat", font=("Segoe UI", 8, "bold"), padx=16, pady=6).pack(side="right", pady=8)
        draw_sv()

    def _open_color_editor(self, initial: str, title: str, callback: Callable[[str], None],
                           anchor: tk.Widget) -> None:
        """Compact inline palette with reliable clipboard-aware HEX input."""
        if not valid_hex_color(initial):
            initial = "#ffffff"
        previous = getattr(self, "inline_color_editor", None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()
        editor = tk.Frame(self.root, bg="#090909", highlightbackground="#4a4a4a", highlightthickness=1)
        self.inline_color_editor = editor
        self.root.update_idletasks()
        editor_width, editor_height = 350, 300
        x = anchor.winfo_rootx() - self.root.winfo_rootx() + anchor.winfo_width() - editor_width
        y = anchor.winfo_rooty() - self.root.winfo_rooty() + anchor.winfo_height() + 6
        x = max(8, min(self.WIDTH - editor_width - 8, x))
        y = max(70, min(self.HEIGHT - editor_height - 8, y))
        editor.place(x=x, y=y, width=editor_width, height=editor_height)
        editor.lift()

        header = tk.Frame(editor, bg=design.SURFACE_ALT, height=38, highlightbackground=design.BORDER, highlightthickness=1)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=title, bg=design.SURFACE_ALT, fg=self.TEXT,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=12)
        tk.Button(header, text="×", command=editor.destroy, bg=design.SURFACE_ALT, fg=self.MUTED,
                  activebackground=design.SURFACE_HOVER, activeforeground=self.ACCENT, relief="flat", bd=0,
                  font=("Segoe UI", 12), width=3).pack(side="right", fill="y")

        initial_rgb = tuple(int(initial[index:index+2], 16) / 255 for index in (1, 3, 5))
        hsv = list(colorsys.rgb_to_hsv(*initial_rgb))
        hex_var = tk.StringVar(value=initial.upper())
        picker = tk.Frame(editor, bg=design.SURFACE)
        picker.pack(padx=12, pady=(10, 6))
        sv_width, sv_height = 292, 180
        sv_canvas = tk.Canvas(picker, width=sv_width, height=sv_height, bg="#111111",
                              highlightthickness=1, highlightbackground="#343434", cursor="crosshair")
        sv_canvas.pack(side="left")
        hue_canvas = tk.Canvas(picker, width=20, height=sv_height, bg="#111111",
                               highlightthickness=1, highlightbackground="#343434", cursor="sb_v_double_arrow")
        hue_canvas.pack(side="left", padx=(8, 0))
        redraw_id: str | None = None

        for row in range(sv_height):
            color = colorsys.hsv_to_rgb(row / (sv_height - 1), 1.0, 1.0)
            color_hex = "#%02x%02x%02x" % tuple(round(channel * 255) for channel in color)
            hue_canvas.create_line(0, row, 20, row, fill=color_hex)

        def hsv_hex() -> str:
            rgb = colorsys.hsv_to_rgb(*hsv)
            return "#%02X%02X%02X" % tuple(round(channel * 255) for channel in rgb)

        def draw_markers(update_hex: bool = True) -> None:
            if update_hex:
                hex_var.set(hsv_hex())
            sv_canvas.delete("marker")
            marker_x, marker_y = hsv[1] * sv_width, (1.0 - hsv[2]) * sv_height
            sv_canvas.create_oval(marker_x-5, marker_y-5, marker_x+5, marker_y+5,
                                  outline="#000000", width=3, tags=("marker",))
            sv_canvas.create_oval(marker_x-4, marker_y-4, marker_x+4, marker_y+4,
                                  outline="#ffffff", width=1, tags=("marker",))
            hue_canvas.delete("marker")
            hue_y = hsv[0] * (sv_height - 1)
            hue_canvas.create_line(0, hue_y, 20, hue_y, fill="#ffffff", width=3, tags=("marker",))

        def draw_gradient() -> None:
            nonlocal redraw_id
            redraw_id = None
            sv_canvas.delete("gradient")
            columns, rows = 58, 36
            cell_w, cell_h = sv_width / columns, sv_height / rows
            for row in range(rows):
                value = 1.0 - row / (rows - 1)
                for column in range(columns):
                    saturation = column / (columns - 1)
                    rgb = colorsys.hsv_to_rgb(hsv[0], saturation, value)
                    color_hex = "#%02x%02x%02x" % tuple(round(channel * 255) for channel in rgb)
                    sv_canvas.create_rectangle(column*cell_w, row*cell_h,
                                               (column+1)*cell_w+1, (row+1)*cell_h+1,
                                               fill=color_hex, outline="", tags=("gradient",))
            sv_canvas.tag_lower("gradient")
            draw_markers()

        def schedule_gradient() -> None:
            nonlocal redraw_id
            if redraw_id is not None:
                editor.after_cancel(redraw_id)
            redraw_id = editor.after(18, draw_gradient)

        def choose_sv(event: tk.Event) -> None:
            hsv[1] = max(0.0, min(1.0, event.x / sv_width))
            hsv[2] = 1.0 - max(0.0, min(1.0, event.y / sv_height))
            draw_markers()

        def choose_hue(event: tk.Event) -> None:
            hsv[0] = max(0.0, min(1.0, event.y / (sv_height - 1)))
            draw_markers()
            schedule_gradient()

        sv_canvas.bind("<Button-1>", choose_sv)
        sv_canvas.bind("<B1-Motion>", choose_sv)
        hue_canvas.bind("<Button-1>", choose_hue)
        hue_canvas.bind("<B1-Motion>", choose_hue)

        footer = tk.Frame(editor, bg=design.SURFACE_ALT, highlightbackground=design.BORDER, highlightthickness=1)
        footer.pack(fill="x", side="bottom", ipady=8)
        tk.Label(footer, text="HEX", bg=design.SURFACE_ALT, fg=self.MUTED,
                 font=("Consolas", 8, "bold")).pack(side="left", padx=(12, 7))
        hex_entry = tk.Entry(footer, textvariable=hex_var, bg=design.SURFACE, fg=self.TEXT,
                             insertbackground=self.TEXT, selectbackground=design.ACCENT_SOFT, selectforeground=self.TEXT,
                             relief="solid", bd=1, width=12, justify="center", font=(design.FONT_MONO, 10, "bold"))
        hex_entry.pack(side="left", ipady=6)

        def parse_hex() -> str | None:
            text = hex_var.get().strip()
            if not text.startswith("#"):
                text = "#" + text
            if not valid_hex_color(text):
                hex_entry.configure(fg="#e15b64")
                return None
            hex_entry.configure(fg=self.TEXT)
            normalized = text.upper()
            hex_var.set(normalized)
            rgb = tuple(int(normalized[index:index+2], 16) / 255 for index in (1, 3, 5))
            hsv[:] = list(colorsys.rgb_to_hsv(*rgb))
            schedule_gradient()
            draw_markers(update_hex=False)
            return normalized

        def paste_hex(_event: tk.Event) -> str:
            try:
                pasted = self.root.clipboard_get().strip()
            except tk.TclError:
                return "break"
            hex_entry.delete(0, "end")
            hex_entry.insert(0, pasted)
            parse_hex()
            return "break"

        def copy_hex(_event: tk.Event) -> str:
            selected = hex_entry.selection_get() if hex_entry.selection_present() else hex_entry.get()
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)
            return "break"

        def select_all(_event: tk.Event) -> str:
            hex_entry.selection_range(0, "end")
            hex_entry.icursor("end")
            return "break"

        for sequence in ("<Control-v>", "<Control-V>", "<Shift-Insert>"):
            hex_entry.bind(sequence, paste_hex)
        hex_entry.bind("<<Paste>>", paste_hex)
        for sequence in ("<Control-c>", "<Control-C>"):
            hex_entry.bind(sequence, copy_hex)
        hex_entry.bind("<<Copy>>", copy_hex)
        for sequence in ("<Control-a>", "<Control-A>"):
            hex_entry.bind(sequence, select_all)
        hex_entry.bind("<<SelectAll>>", select_all)
        hex_entry.bind("<Return>", lambda _event: parse_hex())

        hex_menu = tk.Menu(hex_entry, tearoff=False, bg=design.SURFACE, fg=self.TEXT,
                           activebackground=design.ACCENT_SOFT, activeforeground=self.TEXT,
                           relief="flat", bd=1, font=("Segoe UI", 8))
        hex_menu.add_command(label="Paste", command=lambda: paste_hex(tk.Event()))
        hex_menu.add_command(label="Copy", command=lambda: copy_hex(tk.Event()))
        hex_menu.add_command(label="Select all", command=lambda: select_all(tk.Event()))
        hex_entry.bind("<Button-3>", lambda event: hex_menu.tk_popup(event.x_root, event.y_root))

        def apply_color() -> None:
            selected = parse_hex()
            if selected is not None:
                callback(selected)
                editor.destroy()

        tk.Button(footer, text="APPLY", command=apply_color, bg=self.ACCENT, fg="#FFFFFF",
                  activebackground=design.ACCENT_HOVER, activeforeground="#FFFFFF", relief="flat",
                  font=("Segoe UI", 8, "bold"), padx=18, pady=6).pack(side="right", padx=12)
        draw_gradient()
        hex_entry.focus_set()
        hex_entry.selection_range(0, "end")

    def _sync(self) -> None:
        current_positions = self.state.get()
        settings = self.state.set(
            watermark_x=current_positions.watermark_x,
            watermark_y=current_positions.watermark_y,
            hud_x=current_positions.hud_x,
            hud_y=current_positions.hud_y,
            bomb_hud_x=current_positions.bomb_hud_x,
            bomb_hud_y=current_positions.bomb_hud_y,
            keybind_hud_x=current_positions.keybind_hud_x,
            keybind_hud_y=current_positions.keybind_hud_y,
            enabled=self.enabled_var.get(),
            glow=self.glow_var.get(),
            anti_flash=self.flash_var.get(),
            bunny_hop=False,
            bhop_key=self.bhop_key_var.get().strip().lower() or "space",
            bhop_key_mode=self.bhop_key_mode_var.get().strip().lower() or "hold",
            no_recoil=any(profile["enabled"].get()
                          for profile in self.rcs_profile_vars.values()),
            recoil_strength=float(self.recoil_strength_var.get()),
            recoil_smooth=float(self.recoil_smooth_var.get()),
            rcs_mode=self.rcs_mode_var.get(),
            rcs_start_bullet=int(self.rcs_start_bullet_var.get()),
            rcs_x=float(self.rcs_x_var.get()), rcs_y=float(self.rcs_y_var.get()),
            rcs_enabled_pistol=self.rcs_profile_vars["pistol"]["enabled"].get(),
            rcs_enabled_rifle=self.rcs_profile_vars["rifle"]["enabled"].get(),
            rcs_enabled_sniper=self.rcs_profile_vars["sniper"]["enabled"].get(),
            rcs_enabled_smg=self.rcs_profile_vars["smg"]["enabled"].get(),
            rcs_amount_pistol=float(self.rcs_profile_vars["pistol"]["amount"].get()),
            rcs_amount_rifle=float(self.rcs_profile_vars["rifle"]["amount"].get()),
            rcs_amount_sniper=float(self.rcs_profile_vars["sniper"]["amount"].get()),
            rcs_amount_smg=float(self.rcs_profile_vars["smg"]["amount"].get()),
            rcs_smooth_pistol=float(self.rcs_profile_vars["pistol"]["smooth"].get()),
            rcs_smooth_rifle=float(self.rcs_profile_vars["rifle"]["smooth"].get()),
            rcs_smooth_sniper=float(self.rcs_profile_vars["sniper"]["smooth"].get()),
            rcs_smooth_smg=float(self.rcs_profile_vars["smg"]["smooth"].get()),
            rcs_start_pistol=int(self.rcs_profile_vars["pistol"]["start"].get()),
            rcs_start_rifle=int(self.rcs_profile_vars["rifle"]["start"].get()),
            rcs_start_sniper=int(self.rcs_profile_vars["sniper"]["start"].get()),
            rcs_start_smg=int(self.rcs_profile_vars["smg"]["start"].get()),
            rcs_x_pistol=float(self.rcs_profile_vars["pistol"]["x"].get()),
            rcs_x_rifle=float(self.rcs_profile_vars["rifle"]["x"].get()),
            rcs_x_sniper=float(self.rcs_profile_vars["sniper"]["x"].get()),
            rcs_x_smg=float(self.rcs_profile_vars["smg"]["x"].get()),
            rcs_y_pistol=float(self.rcs_profile_vars["pistol"]["y"].get()),
            rcs_y_rifle=float(self.rcs_profile_vars["rifle"]["y"].get()),
            rcs_y_sniper=float(self.rcs_profile_vars["sniper"]["y"].get()),
            rcs_y_smg=float(self.rcs_profile_vars["smg"]["y"].get()),
            no_shake=self.shake_var.get(),
            aim_enabled=self.aim_var.get(),
            aim_key=self.aim_key_var.get().strip().lower() or "alt",
            aim_key_mode=self.aim_key_mode_var.get().strip().lower() or "hold",
            aim_smooth=float(self.smooth_var.get()),
            aim_fov=float(self.fov_var.get()),
            aim_target=self.target_var.get(),
            aim_lock=self.aim_lock_var.get(),
            dynamic_fov=self.dynamic_fov_var.get(),
            aim_fov_pistol=float(self.aim_fov_pistol_var.get()),
            aim_fov_rifle=float(self.aim_fov_rifle_var.get()),
            aim_fov_sniper=float(self.aim_fov_sniper_var.get()),
            aim_fov_smg=float(self.aim_fov_smg_var.get()),
            aim_smooth_pistol=float(self.aim_smooth_pistol_var.get()),
            aim_smooth_rifle=float(self.aim_smooth_rifle_var.get()),
            aim_smooth_sniper=float(self.aim_smooth_sniper_var.get()),
            aim_smooth_smg=float(self.aim_smooth_smg_var.get()),
            first_shot_delay=float(self.first_shot_delay_var.get()),
            target_switch_delay=float(self.target_switch_delay_var.get()),
            lock_timeout=float(self.lock_timeout_var.get()),
            aim_dead_zone=float(self.aim_dead_zone_var.get()),
            aim_max_step=float(self.aim_max_step_var.get()),
            target_priority=self.target_priority_var.get(),
            hitbox_fallback=self.hitbox_fallback_var.get(),
            ignore_teammates=self.ignore_teammates_var.get(),
            visibility_check=self.visibility_check_var.get(),
            triggerbot=self.triggerbot_var.get(),
            trigger_delay=float(self.trigger_delay_var.get()),
            shoot_in_smoke=self.shoot_in_smoke_var.get(),
            auto_shoot=self.auto_shoot_var.get(),
            auto_stop=self.auto_stop_var.get(),
            show_fov=self.show_fov_var.get(),
            box_esp=self.box_var.get(),
            box_style=self.box_style_var.get(),
            esp_preset=self.esp_preset_var.get(),
            box_thickness=float(self.box_thickness_var.get()),
            box_fill_alpha=float(self.box_fill_alpha_var.get()),
            corner_length=float(self.corner_length_var.get()),
            esp_name=self.esp_name_var.get(),
            esp_health=self.esp_health_var.get(),
            esp_weapon=self.esp_weapon_var.get(),
            esp_armor=self.esp_armor_var.get(),
            esp_distance=self.esp_distance_var.get(),
            esp_snapline=self.esp_snapline_var.get(),
            esp_head_dot=self.esp_head_dot_var.get(),
            esp_skeleton=self.esp_skeleton_var.get(),
            world_bomb_esp=self.world_bomb_esp_var.get(),
            world_bomb_info=self.world_bomb_info_var.get(),
            world_weapon_esp=self.world_weapon_esp_var.get(),
            weapon_filter_active=self.weapon_filter_active_var.get(),
            weapon_filter_grenades=self.weapon_filter_grenades_var.get(),
            weapon_filter_c4=self.weapon_filter_c4_var.get(),
            weapon_filter_knives=self.weapon_filter_knives_var.get(),
            esp_enemies=self.esp_enemies_var.get(), esp_allies=self.esp_allies_var.get(),
            esp_bots=self.esp_bots_var.get(), esp_state_indicators=self.esp_state_indicators_var.get(),
            hud_enabled=self.hud_enabled_var.get(),
            keybind_list=self.keybind_list_var.get(),
            performance_panel=self.performance_panel_var.get(),
            esp_rate=int(self.esp_rate_var.get()), world_rate=int(self.world_rate_var.get()),
            hud_rate=int(self.hud_rate_var.get()), cinema_bars=self.cinema_bars_var.get(),
            cinema_bar_size=float(self.cinema_bar_size_var.get()),
            screenshot_cleanup=self.screenshot_cleanup_var.get(),
            disable_cosmetics_in_menu=self.disable_cosmetics_in_menu_var.get(),
            box_color=self.element_colors["Box"].get(),
            name_color=self.element_colors["Name"].get(),
            hp_color=self.element_colors["HP"].get(),
            armor_color=self.element_colors["Armor"].get(),
            weapon_color=self.element_colors["Weapon"].get(),
            fov_color=self.element_colors["FOV"].get(),
            line_color=self.element_colors["Line"].get(),
            skeleton_color=self.element_colors["Skeleton"].get(),
            world_color=self.element_colors["World"].get(),
            profile_low_hp_color=self.element_colors["LowHP"].get(),
            profile_bomb_color=self.element_colors["Bomb"].get(),
            world_filter=False,
            world_filter_color=self.element_colors["WorldTint"].get(),
            world_filter_strength=float(self.world_filter_strength_var.get()),
            world_night_mode=self.world_night_var.get(),
            skybox_name=self.skybox_var.get(),
            crosshair_enabled=self.crosshair_var.get(),
            crosshair_color=self.element_colors["Crosshair"].get(),
            crosshair_size=float(self.crosshair_size_var.get()),
            watermark=self.watermark_var.get(),
            overlay_fps=self.overlay_fps_var.get(),
            overlay_clock=self.overlay_clock_var.get(),
            aim_indicator=self.aim_indicator_var.get(),
            esp_fill=self.esp_fill_var.get(),
            radar_hack=self.radar_var.get(),
            skin_changer=False,
            skin_weapon=self.skin_weapon_var.get(),
            skin_name=self.skin_name_var.get(),
            skin_wear=float(self.skin_wear_var.get()),
            skin_seed=int(self.skin_seed_var.get()),
            skin_stattrak=self.skin_stattrak_var.get(),
            health_color=self.color_mode.get() == "health",
            custom_color=self.custom_color,
            menu_scale=self.menu_scale_var.get(),
            menu_theme=self.menu_theme_var.get(),
            esp_preview_enabled=self.esp_preview_enabled_var.get(),
        )
        if self._save_after_id is not None:
            self.root.after_cancel(self._save_after_id)
        self._save_after_id = self.root.after(300, self._save_settings_now)
        self._sync_esp_preview_window()
        self._draw_esp_preview()

    def _save_settings_now(self) -> None:
        self._save_after_id = None
        try:
            self.state.get().save()
        except OSError:
            logging.exception("Не удалось сохранить настройки")

    def choose_color(self) -> None:
        def apply(selected: str) -> None:
            self.custom_color = selected.lower()
            self.color_button.configure(bg=selected, activebackground=selected)
            self.color_mode.set("custom")
            self._sync()
        self._open_color_editor(self.custom_color, "GLOW COLOR", apply, self.color_button)

    def _bind_menu_toggle(self) -> None:
        try:
            keyboard.add_hotkey("f1", self._queue_toggle, suppress=False)
        except Exception:
            logging.exception("Глобальная клавиша F1 недоступна")
        self.root.bind("<Escape>", lambda _event: self._queue_toggle())

    def _queue_toggle(self) -> None:
        now = time.monotonic()
        if now - self._last_toggle_request < 0.18:
            return
        self._last_toggle_request = now
        self.events.put("toggle")

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event.startswith("bind:"):
                    _prefix, feature, key = event.split(":", 2)
                    variable = self.aim_key_var if feature == "aim" else self.bhop_key_var
                    variable.set(key.strip().lower())
                    self.bind_buttons[feature].configure(text=key.upper(), fg=self.TEXT)
                    self.capture_feature = None
                    self.root.unbind_all("<ButtonPress>")
                    if self.capture_hook is not None:
                        keyboard.unhook(self.capture_hook)
                        self.capture_hook = None
                    self._sync()
                elif event == "toggle" and self.capture_feature is None:
                    self.toggle()
        except queue.Empty:
            pass
        if not self.stop.is_set():
            self.root.after(16, self._poll_events)

    def toggle(self) -> None:
        self.visible = not self.visible
        popup = self.rcs_mode_popup
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        if not self.visible:
            self.root.attributes("-alpha", 0.0)
            self._set_menu_input_transparent(True)
            if self.esp_preview_window is not None and self.esp_preview_window.winfo_exists():
                self.esp_preview_window.withdraw()
        else:
            self._set_menu_input_transparent(False)
            self.root.attributes("-alpha", 1.0)
            self.root.attributes("-topmost", True)
            self._position_overlay_menu()
            self._sync_esp_preview_window()
            self.root.lift()
            self.root.focus_force()

    def _set_menu_input_transparent(self, transparent: bool) -> None:
        get_style = ctypes.windll.user32.GetWindowLongPtrW
        set_style = ctypes.windll.user32.SetWindowLongPtrW
        get_style.argtypes = (ctypes.c_void_p, ctypes.c_int)
        get_style.restype = ctypes.c_ssize_t
        set_style.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
        set_style.restype = ctypes.c_ssize_t
        style = get_style(self.menu_hwnd, -20)
        if transparent:
            style |= 0x20 | 0x08000000
        else:
            style &= ~(0x20 | 0x08000000)
            style |= 0x80
        set_style(self.menu_hwnd, -20, style)

    def close(self) -> None:
        if self.stop.is_set():
            return

        # Set stop first so repeated callbacks cannot spam the same exception.
        self.stop.set()

        if self.esp_preview_window is not None and self.esp_preview_window.winfo_exists():
            self.esp_preview_window.destroy()

        try:
            close_overlay = getattr(self.fov_overlay, "close", None)
            if close_overlay is not None:
                close_overlay()
        except Exception:
            logging.exception("Failed to close native overlay")

        # Do NOT call self._sync() here.
        # _sync() reads Tk variables and is the source of the traceback.
        try:
            if self._save_after_id is not None:
                self.root.after_cancel(self._save_after_id)
                self._save_after_id = None
        except (RuntimeError, tk.TclError):
            self._save_after_id = None

        try:
            self._save_settings_now()
        except Exception:
            logging.exception("Failed to save settings during shutdown")

        try:
            if self.capture_hook is not None:
                keyboard.unhook(self.capture_hook)
                self.capture_hook = None
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

        try:
            self.root.after_idle(self.root.destroy)
        except (RuntimeError, tk.TclError):
            try:
                self.root.destroy()
            except Exception:
                pass

    def run(self) -> None:
        self.root.mainloop()


def connect() -> tuple[pymem.Pymem, int]:
    pm = pymem.Pymem(PROCESS_NAME)
    module = pymem.process.module_from_name(pm.process_handle, "client.dll")
    if module is None:
        raise RuntimeError("Модуль client.dll не найден")
    return pm, module.lpBaseOfDll


def show_startup_error(message: str) -> None:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(APP_NAME, message, parent=root)
    root.destroy()


def main() -> int:
    configure_logging()
    logging.info("Запуск %s %s", APP_NAME, APP_VERSION)
    try:
        pm, client = connect()
        state = StateStore(Settings.load())
        stop = threading.Event()
        cheats = Cheats(pm, client, state, stop)
    except requests.RequestException as exc:
        logging.exception("Ошибка загрузки смещений")
        show_startup_error(f"Не удалось загрузить актуальные смещения.\n\n{exc}\n\nПодробности: {LOG_PATH}")
        return 2
    except (pymem.exception.PymemError, ProcessLookupError, RuntimeError) as exc:
        logging.exception("Ошибка подключения")
        show_startup_error(f"Не удалось подключиться к {PROCESS_NAME}.\nСначала запустите игру.\n\n{exc}")
        return 3
    except (OffsetError, KeyError, TypeError) as exc:
        logging.exception("Некорректные смещения")
        show_startup_error(f"Формат смещений изменился.\n\n{exc}\n\nПодробности: {LOG_PATH}")
        return 4

    workers = (
        threading.Thread(target=cheats.glow_loop, name="glow", daemon=True),
        threading.Thread(target=cheats.anti_flash_loop, name="anti-flash", daemon=True),
        threading.Thread(target=cheats.no_recoil_loop, name="no-recoil", daemon=True),
        threading.Thread(target=cheats.no_shake_loop, name="no-shake", daemon=True),
        threading.Thread(target=cheats.vector_aim_loop, name="vector-aim", daemon=True),
        threading.Thread(target=cheats.radar_loop, name="radar", daemon=True),
        threading.Thread(target=cheats.triggerbot_loop, name="triggerbot", daemon=True),
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
            logging.exception("Ошибка закрытия процесса")
        logging.info("Завершение программы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
