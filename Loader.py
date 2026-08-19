"""
Luna Loader
Pixel-matched interactive UI based on the supplied Figma reference.

The gray Figma canvas is NOT part of the app.
Actual app size: 392 x 677 px.

Dependency:
    pip install psutil
"""

import ctypes
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser

import psutil


# ----------------------------------------------------------------------
# Window / style
# ----------------------------------------------------------------------

WINDOW_W = 392
WINDOW_H = 677

TITLEBAR_BG = "#ECE9E2"
BODY_BG = "#F3F1EC"

WHITE = "#171716"
LINE = "#CBC7BE"
HOVER = "#E6E2DA"
ACTIVE_PRESS = "#D9D4CB"
DIM = "#6E6B65"
ACCENT = "#E6543F"

SUCCESS = "#2F7955"
WARNING = "#A56820"
ERROR = "#B63E31"


def enable_dpi_awareness():
    """Prevent Windows display scaling from changing the pixel geometry."""
    if not sys.platform.startswith("win"):
        return

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class MilkyWayLoader(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Luna Loader")
        self.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.minsize(WINDOW_W, WINDOW_H)
        self.maxsize(WINDOW_W, WINDOW_H)
        self.resizable(False, False)
        self.overrideredirect(True)
        self.configure(bg=BODY_BG)

        self.cs2_process = None
        self.app_process = None
        self.is_loaded = False
        self.is_loading = False
        self.active_tab = "cs2"  # единственная вкладка
        self._launched_cs2_by_loader = False
        self._cs2_launch_time = None

        self._drag_offset_x = 0
        self._drag_offset_y = 0

        self._font_family = self._choose_font()
        self.font_normal = tkfont.Font(
            family=self._font_family,
            size=11,
            weight="normal",
        )
        self.font_small = tkfont.Font(
            family=self._font_family,
            size=10,
            weight="normal",
        )
        self.font_controls = tkfont.Font(
            family="Arial",
            size=16,
            weight="normal",
        )

        self.canvas = tk.Canvas(
            self,
            width=WINDOW_W,
            height=WINDOW_H,
            bg=BODY_BG,
            bd=0,
            highlightthickness=0,
            relief="flat",
            cursor="arrow",
        )
        self.canvas.pack(fill="both", expand=True)

        self._buttons = {}
        self._tabs = {}

        self._build_ui()
        self._bind_window_events()
        self.after_idle(self.center_window)

    # ------------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------------

    def _choose_font(self):
        available = set(tkfont.families(self))
        for family in (
            "Inter",
            "Segoe UI",
            "Intel One Mono",
            "Consolas",
            "Courier New",
            "DejaVu Sans Mono",
        ):
            if family in available:
                return family
        return "TkFixedFont"

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        c = self.canvas

        # Nocturnal editorial canvas shared with the Luna control panel.
        c.create_rectangle(
            0, 0, WINDOW_W, WINDOW_H,
            fill=BODY_BG,
            outline=BODY_BG,
        )

        # ---------------- title bar: original screenshot x20..412 / y14..49 ----------------
        c.create_rectangle(
            0, 0, WINDOW_W, 35,
            fill=TITLEBAR_BG,
            outline=TITLEBAR_BG,
            tags=("titlebar",),
        )

        c.create_text(
            12, 19,
            text="◐  LUNA  /  LOADER",
            font=self.font_normal,
            fill=WHITE,
            anchor="w",
        )

        # Minimize and close are real interactive hit zones.
        self._create_title_control(
            "minimize",
            333, 0, 365, 35,
            "—",
            self.minimize_window,
        )
        self._create_title_control(
            "close",
            365, 0, 392, 35,
            "×",
            self.close_window,
        )

        # Any empty titlebar area is draggable.
        c.tag_bind("titlebar", "<ButtonPress-1>", self._start_drag)
        c.tag_bind("titlebar", "<B1-Motion>", self._drag_window)

        # ---------------- tabs ----------------
        self._create_tab(
            "cs2",
            0, 35, 392, 62,
            "01   LUNA CS2",
        )
        self._refresh_tabs()

        # ---------------- path ----------------
        self.path_text = c.create_text(
            1, 101,
            text="LUNA  /  CS2",
            font=self.font_small,
            fill=WHITE,
            anchor="w",
        )
        c.create_line(
            0, 111, 392, 111,
            fill=LINE,
            width=1,
        )

        # ---------------- info block ----------------
        self.info_title_1 = c.create_text(
            12, 149,
            text="An open-source cheat project",
            font=self.font_normal,
            fill=WHITE,
            anchor="nw",
        )
        self.info_title_2 = c.create_text(
            12, 169,
            text="written in Python.",
            font=self.font_normal,
            fill=WHITE,
            anchor="nw",
        )

        self.info_quote_1 = c.create_text(
            12, 211,
            text='"cannot be used for commercial purposes"',
            font=self.font_normal,
            fill=WHITE,
            anchor="nw",
        )
        self.info_quote_2 = c.create_text(
            12, 232,
            text='"the creator is not responsible',
            font=self.font_normal,
            fill=WHITE,
            anchor="nw",
        )
        self.info_quote_3 = c.create_text(
            12, 253,
            text='for your account when playing with soft"',
            font=self.font_normal,
            fill=WHITE,
            anchor="nw",
        )

        # ---------------- main controls ----------------
        self._create_button(
            "load",
            31, 330, 361, 368,
            "LOAD",
            self.load_application,
        )

        self._create_button(
            "logs",
            31, 378, 196, 418,
            "LOGS",
            self.open_logs,
        )

        self._create_button(
            "configs",
            196, 378, 361, 418,
            "CONFIGS",
            self.open_configs,
        )

    def _create_title_control(self, name, x1, y1, x2, y2, text, command):
        tag = f"title_{name}"

        bg_id = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            fill=TITLEBAR_BG,
            outline=TITLEBAR_BG,
            tags=(tag,),
        )
        text_id = self.canvas.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2 + (1 if name == "close" else 0),
            text=text,
            font=self.font_controls,
            fill=WHITE,
            anchor="center",
            tags=(tag,),
        )

        self.canvas.tag_bind(tag, "<Button-1>", lambda _e: command())
        self.canvas.tag_bind(
            tag,
            "<Enter>",
            lambda _e, i=bg_id, n=name: self._title_hover(i, n, True),
        )
        self.canvas.tag_bind(
            tag,
            "<Leave>",
            lambda _e, i=bg_id, n=name: self._title_hover(i, n, False),
        )

        return bg_id, text_id

    def _title_hover(self, item_id, name, entered):
        if entered:
            color = ERROR if name == "close" else HOVER
        else:
            color = TITLEBAR_BG
        self.canvas.itemconfigure(item_id, fill=color)

    def _create_tab(self, name, x1, y1, x2, y2, text):
        tag = f"tab_{name}"

        rect = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            fill=BODY_BG,
            outline=LINE,
            width=1,
            tags=(tag,),
        )
        label = self.canvas.create_text(
            x1 + 17,
            (y1 + y2) / 2 + 1,
            text=text,
            font=self.font_normal,
            fill=WHITE,
            anchor="w",
            tags=(tag,),
        )

        self._tabs[name] = {
            "rect": rect,
            "label": label,
            "tag": tag,
        }

        self.canvas.tag_bind(
            tag,
            "<Button-1>",
            lambda _e, tab=name: self.switch_tab(tab),
        )
        self.canvas.tag_bind(
            tag,
            "<Enter>",
            lambda _e, tab=name: self._tab_hover(tab, True),
        )
        self.canvas.tag_bind(
            tag,
            "<Leave>",
            lambda _e, tab=name: self._tab_hover(tab, False),
        )

    def _tab_hover(self, name, entered):
        tab = self._tabs[name]
        if entered:
            self.canvas.itemconfigure(tab["rect"], fill=HOVER)
        else:
            self.canvas.itemconfigure(tab["rect"], fill=BODY_BG)

    def _refresh_tabs(self):
        for name, tab in self._tabs.items():
            active = name == self.active_tab
            self.canvas.itemconfigure(
                tab["rect"],
                outline=WHITE if active else LINE,
                width=1,
            )
            self.canvas.itemconfigure(
                tab["label"],
                fill=WHITE if active else "#DDDDDD",
            )

    def _create_button(self, name, x1, y1, x2, y2, text, command):
        tag = f"button_{name}"

        rect = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            fill=ACCENT if name == "load" else BODY_BG,
            outline=ACCENT if name == "load" else LINE,
            width=1,
            tags=(tag,),
        )

        label = self.canvas.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2 + 1,
            text=text,
            font=self.font_normal,
            fill="#FFFFFF" if name == "load" else WHITE,
            anchor="center",
            tags=(tag,),
        )

        self._buttons[name] = {
            "rect": rect,
            "label": label,
            "tag": tag,
            "command": command,
        }

        self.canvas.tag_bind(
            tag,
            "<ButtonPress-1>",
            lambda _e, n=name: self._button_press(n),
        )
        self.canvas.tag_bind(
            tag,
            "<ButtonRelease-1>",
            lambda _e, n=name: self._button_release(n),
        )
        self.canvas.tag_bind(
            tag,
            "<Enter>",
            lambda _e, n=name: self._button_hover(n, True),
        )
        self.canvas.tag_bind(
            tag,
            "<Leave>",
            lambda _e, n=name: self._button_hover(n, False),
        )

    def _button_hover(self, name, entered):
        button = self._buttons[name]
        normal = ACCENT if name == "load" else BODY_BG
        hover = "#CB4634" if name == "load" else HOVER
        self.canvas.itemconfigure(
            button["rect"],
            fill=hover if entered else normal,
        )
        self.canvas.configure(cursor="hand2" if entered else "arrow")

    def _button_press(self, name):
        button = self._buttons[name]
        self.canvas.itemconfigure(button["rect"], fill="#B93F30" if name == "load" else ACTIVE_PRESS)

    def _button_release(self, name):
        button = self._buttons[name]
        self.canvas.itemconfigure(button["rect"], fill="#CB4634" if name == "load" else HOVER)

        # Pointer may have been released outside of the original object.
        x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
        y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
        bbox = self.canvas.bbox(button["tag"])

        if bbox:
            x1, y1, x2, y2 = bbox
            if x1 <= x <= x2 and y1 <= y <= y2:
                button["command"]()

    # ------------------------------------------------------------------
    # Window handling
    # ------------------------------------------------------------------

    def _bind_window_events(self):
        self.bind("<Escape>", lambda _e: self.close_window())
        self.bind("<Map>", self._on_map)

        # Drag via title text too.
        self.canvas.bind("<ButtonPress-1>", self._canvas_drag_fallback_start, add="+")
        self.canvas.bind("<B1-Motion>", self._canvas_drag_fallback_move, add="+")

    def _canvas_drag_fallback_start(self, event):
        # Only the empty/title text part of y=0..35 should drag.
        if 0 <= event.y <= 35 and event.x < 333:
            self._start_drag(event)

    def _canvas_drag_fallback_move(self, event):
        if 0 <= event.y <= 80:
            self._drag_window(event)

    def _start_drag(self, event):
        self._drag_offset_x = event.x_root - self.winfo_x()
        self._drag_offset_y = event.y_root - self.winfo_y()

    def _drag_window(self, event):
        x = event.x_root - self._drag_offset_x
        y = event.y_root - self._drag_offset_y
        self.geometry(f"+{x}+{y}")

    def center_window(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() - WINDOW_W) // 2
        y = (self.winfo_screenheight() - WINDOW_H) // 2
        self.geometry(f"{WINDOW_W}x{WINDOW_H}+{x}+{y}")

    def minimize_window(self):
        try:
            self.overrideredirect(False)
            self.iconify()
        except tk.TclError:
            pass

    def _on_map(self, _event=None):
        self.after(20, self._restore_borderless)

    def _restore_borderless(self):
        try:
            if self.state() == "normal":
                self.overrideredirect(True)
        except tk.TclError:
            pass

    def close_window(self):
        proc = self.app_process
        self.app_process = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self.destroy()

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------

    def switch_tab(self, tab_name):
        # В проекте оставлена только CS2-вкладка.
        if tab_name != "cs2":
            return

        self.active_tab = "cs2"
        self._refresh_tabs()
        self.canvas.itemconfigure(
            self.path_text,
            text="luna/cs2",
        )

    def _set_info_text(self, line1, line2, quote1, quote2, quote3):
        self.canvas.itemconfigure(self.info_title_1, text=line1)
        self.canvas.itemconfigure(self.info_title_2, text=line2)
        self.canvas.itemconfigure(self.info_quote_1, text=quote1)
        self.canvas.itemconfigure(self.info_quote_2, text=quote2)
        self.canvas.itemconfigure(self.info_quote_3, text=quote3)

    # ------------------------------------------------------------------
    # Load button status
    # ------------------------------------------------------------------

    def _set_load_text(self, text, color=WHITE):
        self.canvas.itemconfigure(
            self._buttons["load"]["label"],
            text=text,
            fill=color,
        )
        self.update_idletasks()

    def reset_load_button(self):
        self.is_loaded = False
        self.is_loading = False
        self._launched_cs2_by_loader = False
        self._cs2_launch_time = None
        self._set_load_text("Load", WHITE)

    # ------------------------------------------------------------------
    # Existing loader behavior
    # ------------------------------------------------------------------

    def check_cs2_running(self):
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name")
                if name and name.lower() == "cs2.exe":
                    self.cs2_process = proc
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        self.cs2_process = None
        return False

    def launch_cs2(self):
        try:
            if sys.platform.startswith("win"):
                os.startfile("steam://rungameid/730")
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "steam://rungameid/730"])
            else:
                subprocess.Popen(["xdg-open", "steam://rungameid/730"])
            return True
        except Exception as exc:
            print(f"Ошибка запуска CS2: {exc}")
            return False

    def wait_for_cs2(self, timeout=60):
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.check_cs2_running():
                return True
            time.sleep(1)

        return False

    def load_application(self):
        """
        If CS2 is already running, start MilkyWay immediately.

        If the loader has to start CS2 itself, do not start the remaining
        MilkyWay scripts until at least 30 seconds have passed from the Steam
        launch request.
        """
        if self.is_loaded or self.is_loading:
            return

        self.is_loading = True
        self._launched_cs2_by_loader = False
        self._cs2_launch_time = None
        self._set_load_text("Loading...", WARNING)

        # CS2 was already running before Load was pressed.
        if self.check_cs2_running():
            self._set_load_text("CS2 Found! Starting...", SUCCESS)
            self.after(800, self.execute_main_function)
            return

        # CS2 is closed, so this loader launches it.
        self._set_load_text("CS2 not found. Launching...", WARNING)

        if not self.launch_cs2():
            self._show_load_error("Failed to launch CS2")
            return

        self._launched_cs2_by_loader = True
        self._cs2_launch_time = time.monotonic()
        self._set_load_text("Waiting for CS2...", WARNING)
        self.after(500, self._poll_cs2_start)

    def _poll_cs2_start(self):
        if not self.is_loading:
            return

        elapsed = (
            time.monotonic() - self._cs2_launch_time
            if self._cs2_launch_time is not None
            else 0.0
        )

        running = self.check_cs2_running()

        # Give Steam/game startup more room than before.
        if not running and elapsed >= 90.0:
            self._show_load_error("Timeout! CS2 not found")
            return

        if running:
            if self._launched_cs2_by_loader and elapsed < 30.0:
                remaining = max(1, int(30.0 - elapsed + 0.999))
                self._set_load_text(
                    f"CS2 starting... {remaining}s",
                    WARNING,
                )
                self.after(500, self._poll_cs2_start)
                return

            self._set_load_text("CS2 Ready! Starting...", SUCCESS)
            self.after(800, self.execute_main_function)
            return

        self._set_load_text("Waiting for CS2...", WARNING)
        self.after(500, self._poll_cs2_start)

    def execute_main_function(self):
        """
        Start milkyway.app in a separate Python process.

        milkyway.app / milkyway.engine use Tkinter. Tkinter widgets and
        Tk variables must live on the main thread of the process that owns
        their Tcl interpreter. Starting main() with threading.Thread caused:
            RuntimeError: main thread is not in main loop

        A separate process gives the engine its own real main thread while
        keeping this loader responsive.
        """
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))

            # Do not start a second copy if the previous one is still alive.
            if self.app_process is not None and self.app_process.poll() is None:
                self.is_loaded = True
                self.is_loading = False
                self._set_load_text("Loaded", SUCCESS)
                return

            self._set_load_text("Running...", SUCCESS)

            launcher_code = (
                "import os, sys; "
                f"os.chdir({base_dir!r}); "
                f"sys.path.insert(0, {base_dir!r}); "
                "from milkyway.app import main; "
                "main()"
            )

            creationflags = 0
            if sys.platform.startswith("win"):
                # Keep the GUI child process independent from Tkinter's thread.
                creationflags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                 | getattr(subprocess, "CREATE_NO_WINDOW", 0))

            self.app_process = subprocess.Popen(
                [sys.executable, "-c", launcher_code],
                cwd=base_dir,
                creationflags=creationflags,
            )

            self.is_loaded = True
            self.is_loading = False
            self._set_load_text("Loaded", SUCCESS)
            # The control panel owns the foreground from this point. Keeping
            # the loader mapped underneath caused its old MilkyWay/Luna frame
            # to flash through the transparent startup overlay.
            self.withdraw()

            # Watch the child without blocking the loader.
            self.after(1000, self._check_app_process)

        except Exception as exc:
            self._show_load_error(f"Error: {str(exc)[:28]}")

    def _check_app_process(self):
        """Update loader state when the separate MilkyWay process exits."""
        if self.app_process is None:
            return

        return_code = self.app_process.poll()

        if return_code is None:
            self.after(1000, self._check_app_process)
            return

        self.app_process = None
        self.is_loaded = False
        self.is_loading = False
        self._set_load_text("Load", WHITE)
        self.deiconify()
        self.lift()
        self.after_idle(self.center_window)

    def _show_load_error(self, message):
        self.is_loading = False
        self.is_loaded = False
        self._set_load_text(message, ERROR)
        self.after(2200, self.reset_load_button)

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    def _open_directory(self, path):
        os.makedirs(path, exist_ok=True)

        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            print(f"Cannot open directory: {exc}")

    def open_logs(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self._open_directory(
            os.path.join(base_dir, "logs")
        )

    def open_configs(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self._open_directory(
            os.path.join(base_dir, "configs")
        )

if __name__ == "__main__":
    enable_dpi_awareness()
    app = MilkyWayLoader()
    app.mainloop()
