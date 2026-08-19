"""Small synthetic Tkinter vs Dear PyGui overlay renderer benchmark."""

from __future__ import annotations

import statistics
import time
import tkinter as tk

import dearpygui.dearpygui as dpg


WIDTH, HEIGHT = 960, 540
FRAMES = 240
BOXES = tuple((45 + (i % 8) * 112, 55 + (i // 8) * 220, 54, 145) for i in range(16))


def result(name: str, samples: list[float]) -> None:
    mean = statistics.fmean(samples) * 1000
    p95 = sorted(samples)[int(len(samples) * 0.95)] * 1000
    print(f"{name:12} mean={mean:7.3f} ms   p95={p95:7.3f} ms   theoretical={1000/mean:7.1f} FPS")


def bench_tk() -> list[float]:
    root = tk.Tk()
    root.title("Tkinter benchmark")
    root.geometry(f"{WIDTH}x{HEIGHT}+20+20")
    canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg="#010101", highlightthickness=0)
    canvas.pack()
    root.update()
    samples: list[float] = []
    for frame in range(FRAMES):
        started = time.perf_counter()
        canvas.delete("all")
        shift = frame % 30
        for index, (x, y, w, h) in enumerate(BOXES):
            x += shift
            canvas.create_rectangle(x, y, x+w, y+h, outline="#ffffff", width=2)
            canvas.create_text(x+w/2, y-9, text=f"Player {index+1}", fill="#ffffff")
            canvas.create_rectangle(x-6, y+h*0.25, x-4, y+h, fill="#60df70", outline="")
            canvas.create_line(WIDTH/2, HEIGHT-2, x+w/2, y+h, fill="#8a8a8a")
        root.update_idletasks()
        root.update()
        samples.append(time.perf_counter() - started)
    root.destroy()
    return samples


def bench_dpg() -> list[float]:
    dpg.create_context()
    dpg.create_viewport(title="Dear PyGui benchmark", width=WIDTH, height=HEIGHT,
                        decorated=True, resizable=False, vsync=False)
    dpg.add_viewport_drawlist(tag="bench_draw", front=True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_viewport_vsync(False)
    samples: list[float] = []
    for frame in range(FRAMES):
        started = time.perf_counter()
        dpg.delete_item("bench_draw", children_only=True)
        shift = frame % 30
        for index, (x, y, w, h) in enumerate(BOXES):
            x += shift
            dpg.draw_rectangle((x, y), (x+w, y+h), parent="bench_draw", color=(255, 255, 255, 255), thickness=2)
            dpg.draw_text((x+3, y-14), f"Player {index+1}", parent="bench_draw", color=(255, 255, 255, 255), size=11)
            dpg.draw_rectangle((x-6, y+h*0.25), (x-4, y+h), parent="bench_draw",
                               color=(96, 223, 112, 255), fill=(96, 223, 112, 255))
            dpg.draw_line((WIDTH/2, HEIGHT-2), (x+w/2, y+h), parent="bench_draw", color=(138, 138, 138, 255))
        dpg.render_dearpygui_frame()
        samples.append(time.perf_counter() - started)
    dpg.destroy_context()
    return samples


if __name__ == "__main__":
    print(f"Synthetic overlay test: {BOXES.__len__()} entities, {FRAMES} frames")
    result("Tkinter", bench_tk())
    result("Dear PyGui", bench_dpg())
