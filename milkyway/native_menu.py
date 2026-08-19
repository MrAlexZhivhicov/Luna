"""Thin lifecycle/IPC bridge for the native Win32 settings menu."""

from __future__ import annotations

import logging
import subprocess
import tkinter as tk
from pathlib import Path

from .engine import InterfaceStateView
from .native_overlay import NativeFovOverlay


class NativeMenu:
    def __init__(self, cheats, state, stop, status: str):
        self.cheats = cheats
        self.state = state
        self.stop = stop
        self.root = tk.Tk()
        self.root.withdraw()
        self.visible = True
        self.menu_hwnd = 0
        self.splash_active = False
        self.splash_opacity = 1.0
        self.splash_text_level = 1.0
        base = Path(__file__).resolve().parent.parent
        self._exe = base / "native_menu" / "bin" / "NativeMenu.exe"
        self._ipc = base / "native_menu" / "menu_state.txt"
        self._proc = None
        self._last = {}
        self._write_initial()
        self._launch()
        self.fov_overlay = NativeFovOverlay(self.root, cheats, InterfaceStateView(state))
        self.fov_overlay.menu_visible_getter = lambda: self.visible
        self.fov_overlay.menu_hwnd_getter = lambda: self.menu_hwnd
        self.root.after(40, self._poll)

    def _write_initial(self):
        value = self.state.get()
        self._ipc.parent.mkdir(parents=True, exist_ok=True)
        self._ipc.write_text(
            "\n".join((
                f"watermark={int(value.watermark)}",
                f"overlay_fps={int(value.overlay_fps)}",
                f"overlay_clock={int(value.overlay_clock)}",
                f"crosshair_enabled={int(value.crosshair_enabled)}",
                f"show_fov={int(value.show_fov)}",
                f"crosshair_size={int(value.crosshair_size)}",
                f"aim_fov={int(value.aim_fov)}",
            )) + "\n", encoding="utf-8")

    def _launch(self):
        if not self._exe.exists():
            raise RuntimeError(f"Native menu executable is missing: {self._exe}")
        self._proc = subprocess.Popen([str(self._exe), str(self._ipc)])

    def _read(self):
        values = {}
        for line in self._ipc.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        return values

    def _poll(self):
        if self.stop.is_set():
            self.close()
            return
        try:
            values = self._read()
            self.visible = values.get("visible", "0") == "1"
            self.menu_hwnd = int(values.get("hwnd", "0"))
            if values.get("closed") == "1" or (self._proc and self._proc.poll() is not None):
                self.close()
                return
            changes = {
                "watermark": values.get("watermark", "0") == "1",
                "overlay_fps": values.get("overlay_fps", "0") == "1",
                "overlay_clock": values.get("overlay_clock", "0") == "1",
                "crosshair_enabled": values.get("crosshair_enabled", "0") == "1",
                "show_fov": values.get("show_fov", "0") == "1",
                "crosshair_size": float(values.get("crosshair_size", "6")),
                "aim_fov": float(values.get("aim_fov", "6")),
            }
            if changes != self._last:
                self.state.set(**changes)
                self._last = changes
        except (OSError, ValueError):
            logging.exception("Native menu state read failed")
        self.root.after(40, self._poll)

    def close(self):
        if not self.stop.is_set():
            self.stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        try:
            self.state.get().save()
        except OSError:
            logging.exception("Settings save failed")
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()
