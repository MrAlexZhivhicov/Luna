import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import threading
import time
from pathlib import Path


class NativeFovOverlay:
    def __init__(self, root, cheats, state):
        self.root = root
        self.cheats = cheats
        self.state = state
        self.game_hwnd = 0
        self.is_visible = False
        self.menu_visible_getter = lambda: False
        self.menu_hwnd_getter = lambda: 0
        self.splash_state_getter = lambda: (False, 1.0, 0.0)
        self._proc = None
        self._last_payload = ""
        self._overlay_dir = Path(__file__).resolve().parent.parent / "native_overlay"
        self._exe_path = self._overlay_dir / "bin" / "NativeOverlay.exe"
        self._state_path = self._overlay_dir / "runtime_state.txt"
        self._launch_failed = False
        self._screenshot_hidden_until = 0.0
        self._start_process()
        threading.Thread(target=self._watch_stop, name="native-overlay-stop", daemon=True).start()
        self.root.after(25, self.update)

    def _start_process(self) -> None:
        if self._launch_failed or self._proc is not None:
            return
        if not self._exe_path.exists():
            logging.warning("Native overlay executable is missing: %s", self._exe_path)
            self._launch_failed = True
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text("", encoding="utf-8")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(
                [str(self._exe_path), str(self.cheats.pm.process_id), str(self._state_path), str(os.getpid())],
                creationflags=creation_flags,
            )
        except Exception:
            logging.exception("Native overlay launch failed")
            self._launch_failed = True

    def _watch_stop(self) -> None:
        self.cheats.stop.wait()
        self._terminate_process()

    def _terminate_process(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass

    def close(self) -> None:
        """Synchronously stop the native child before the Python host exits."""
        self._terminate_process()

    def _rect(self):
        if not self.game_hwnd or not ctypes.windll.user32.IsWindow(self.game_hwnd):
            windows = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def callback(hwnd, _data):
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
        rect = ctypes.wintypes.RECT()
        point = ctypes.wintypes.POINT(0, 0)
        ctypes.windll.user32.GetClientRect(self.game_hwnd, ctypes.byref(rect))
        ctypes.windll.user32.ClientToScreen(self.game_hwnd, ctypes.byref(point))
        return point.x, point.y, rect.right, rect.bottom

    @staticmethod
    def _flag(value) -> str:
        return "1" if value else "0"

    def _build_payload(self) -> str:
        settings = self.state.get()
        menu_open = bool(self.menu_visible_getter())
        if settings.screenshot_cleanup and (ctypes.windll.user32.GetAsyncKeyState(0x2C) & 1):
            self._screenshot_hidden_until = time.monotonic() + 0.45
        screenshot_hidden = time.monotonic() < self._screenshot_hidden_until
        menu_hwnd = int(self.menu_hwnd_getter() or 0)
        splash_open, splash_opacity, text_level = self.splash_state_getter()
        rect = self._rect()
        x = y = width = height = 0
        if rect:
            x, y, width, height = rect
        lines = [
            f"enabled={self._flag(settings.enabled and not screenshot_hidden)}",
            f"game_hwnd={int(self.game_hwnd or 0)}",
            f"menu_hwnd={menu_hwnd}",
            f"x={x}",
            f"y={y}",
            f"width={width}",
            f"height={height}",
            f"aim_enabled={self._flag(settings.aim_enabled)}",
            f"auto_shoot={self._flag(settings.auto_shoot)}",
            f"show_fov={self._flag(settings.show_fov)}",
            f"aim_fov={float(settings.aim_fov):.4f}",
            f"crosshair_enabled={self._flag(settings.crosshair_enabled)}",
            f"crosshair_size={float(settings.crosshair_size):.4f}",
            f"watermark={self._flag(settings.watermark)}",
            f"watermark_x={float(settings.watermark_x):.2f}",
            f"watermark_y={float(settings.watermark_y):.2f}",
            f"overlay_fps={self._flag(settings.overlay_fps)}",
            f"overlay_clock={self._flag(settings.overlay_clock)}",
            f"aim_indicator={self._flag(settings.aim_indicator)}",
            f"world_filter={self._flag(settings.world_filter and not (menu_open and settings.disable_cosmetics_in_menu))}",
            f"world_filter_color={settings.world_filter_color}",
            f"world_filter_strength={max(0.0, min(35.0, float(settings.world_filter_strength))):.2f}",
            f"world_night_mode={self._flag(settings.world_night_mode and not (menu_open and settings.disable_cosmetics_in_menu))}",
            f"menu_open={self._flag(menu_open)}",
            f"splash_open={self._flag(splash_open)}",
            f"splash_opacity={max(0.0, min(1.0, float(splash_opacity))):.4f}",
            f"text_level={max(0.0, min(1.0, float(text_level))):.4f}",
            f"fov_color={settings.fov_color}",
            f"crosshair_color={settings.crosshair_color}",
            f"name_color={settings.name_color}",
        ]
        return "\n".join(lines) + "\n"

    def update(self) -> None:
        try:
            if self._proc is not None and self._proc.poll() is not None:
                logging.warning("Native overlay exited with code %s", self._proc.returncode)
                self._proc = None
            if self._proc is None and not self._launch_failed:
                self._start_process()
            payload = self._build_payload()
            if payload != self._last_payload:
                self._state_path.write_text(payload, encoding="utf-8")
                self._last_payload = payload
        except Exception:
            logging.exception("Native overlay update failed")
        if not self.cheats.stop.is_set():
            self.root.after(25, self.update)
