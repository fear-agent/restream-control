#!/usr/bin/env python3
"""
Crosskeys Stream Syncer GUI

Small Windows GUI for delaying VLC runner streams by slot.
Designed for VLC windows titled RUNNER 1, RUNNER 2, RUNNER 3, RUNNER 4.

The delay controls use the direct VLC window-message method that worked in testing.
Relaunch closes/reopens a runner from race_setup_last.txt so the stream returns to current live playback.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import app_state

try:
    from PIL import Image, ImageDraw, ImageGrab, ImageTk
except Exception:
    Image = None
    ImageDraw = None
    ImageGrab = None
    ImageTk = None

ROOT = app_state.APP_DIR
LAST_SETUP = ROOT / "race_setup_last.txt"
SYNC_SCREENSHOT_DIR = ROOT / "sync_screenshots"
QUALITY = "720p60,720p,480p,360p,1080p60,1080p,best"
VLC_PLAYER_ARGS = "--no-video-title-show --no-osd --no-qt-privacy-ask --play-and-pause {playerinput}"

BG = "#101113"
PANEL = "#202327"
PANEL_2 = "#2a2f35"
INPUT_BG = "#111315"
TEXT = "#f9fafb"
MUTED = "#9ca3af"
ACCENT = "#0f766e"
BORDER = "#3f454b"

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
IsWindowVisible = user32.IsWindowVisible
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
PostMessageW = user32.PostMessageW
GetWindowRect = user32.GetWindowRect
ShowWindow = user32.ShowWindow
SetForegroundWindow = user32.SetForegroundWindow
BringWindowToTop = user32.BringWindowToTop

VK_SPACE = 0x20
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_CLOSE = 0x0010
SW_RESTORE = 9


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@dataclass
class RunnerWindow:
    slot: int
    hwnd: int
    title: str


@dataclass
class RunnerInfo:
    slot: int
    display_name: str
    twitch_name: str


def clean(value: str) -> str:
    return (value or "").strip()


def get_window_title(hwnd: int) -> str:
    length = GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def list_runner_windows() -> Dict[int, RunnerWindow]:
    found: Dict[int, RunnerWindow] = {}

    def callback(hwnd: int, _lparam: int) -> bool:
        if not IsWindowVisible(hwnd):
            return True
        title = get_window_title(hwnd)
        match = re.search(r"\bRUNNER\s+([1-4])\b.*VLC media player", title, re.I)
        if match:
            slot = int(match.group(1))
            if slot not in found:
                found[slot] = RunnerWindow(slot=slot, hwnd=hwnd, title=title)
        return True

    EnumWindows(EnumWindowsProc(callback), 0)
    return found


def list_child_windows(hwnd: int) -> List[int]:
    children: List[int] = []

    def callback(child_hwnd: int, _lparam: int) -> bool:
        children.append(child_hwnd)
        return True

    EnumChildWindows(hwnd, EnumWindowsProc(callback), 0)
    return children


def post_space_to(hwnd: int) -> None:
    PostMessageW(hwnd, WM_KEYDOWN, VK_SPACE, 0)
    PostMessageW(hwnd, WM_CHAR, ord(" "), 0)
    time.sleep(0.03)
    PostMessageW(hwnd, WM_KEYUP, VK_SPACE, 0)


def toggle_runner(window: RunnerWindow) -> None:
    post_space_to(window.hwnd)
    for child in list_child_windows(window.hwnd):
        post_space_to(child)


def close_window(window: RunnerWindow) -> None:
    PostMessageW(window.hwnd, WM_CLOSE, 0, 0)


def find_vlc() -> str:
    candidates = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return "vlc"


def normalize_twitch(value: str) -> str:
    value = clean(value)
    value = value.lstrip("@").strip()
    value = re.sub(r"^https?://", "", value, flags=re.I)
    value = re.sub(r"^www\.", "", value, flags=re.I)
    if value.lower().startswith("twitch.tv/"):
        value = value.split("/", 1)[1]
    value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return value.strip()


def launch_stream(slot: int, twitch_name: str) -> None:
    twitch_name = normalize_twitch(twitch_name)
    if not twitch_name:
        raise ValueError("Missing Twitch name")
    title = f"RUNNER {slot}"
    player = find_vlc()
    cmd = [
        "streamlink",
        "--twitch-low-latency",
        "--player-no-close",
        "--player", player,
        "--player-args", VLC_PLAYER_ARGS,
        "--title", title,
        f"https://twitch.tv/{twitch_name}",
        QUALITY,
    ]
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(cmd, cwd=str(ROOT))


def parse_last_setup() -> Dict[int, RunnerInfo]:
    info: Dict[int, RunnerInfo] = {}
    if not LAST_SETUP.exists():
        return info
    text = LAST_SETUP.read_text(encoding="utf-8", errors="ignore")
    separator = r"(?:\u2014|\u00e2\u20ac\u201d|->|-)"
    patterns = [
        re.compile(
            rf"(?:RUNNER|Runner)\s+([1-4])\s*:\s*(.*?)\s*{separator}\s*(?:https?://)?twitch\.tv/([A-Za-z0-9_]+)",
            re.I,
        ),
        re.compile(
            rf"Slot\s+([1-4])\s+relaunched.*?:\s*(.*?)\s*{separator}\s*(?:https?://)?twitch\.tv/([A-Za-z0-9_]+)",
            re.I,
        ),
    ]
    for line in text.splitlines():
        for pattern in patterns:
            m = pattern.search(line)
            if m:
                slot = int(m.group(1))
                display = clean(m.group(2)) or m.group(3)
                twitch = normalize_twitch(m.group(3))
                info[slot] = RunnerInfo(slot, display, twitch)
    return info


def load_current_race_info() -> Dict[int, RunnerInfo]:
    info: Dict[int, RunnerInfo] = {}
    data = app_state.load_current_race()
    runners = data.get("runners", {})
    if not isinstance(runners, dict):
        return info
    for slot_raw, runner in runners.items():
        if not isinstance(runner, dict):
            continue
        try:
            slot = int(slot_raw)
        except ValueError:
            continue
        if slot not in {1, 2, 3, 4}:
            continue
        twitch = normalize_twitch(runner.get("twitch_name", ""))
        if twitch:
            display = clean(runner.get("display_name", "")) or twitch
            info[slot] = RunnerInfo(slot, display, twitch)
    return info


class SyncPanel(tk.Frame):
    def __init__(self, parent: tk.Widget, standalone: bool = False) -> None:
        super().__init__(parent, bg=BG)
        self.root = self.winfo_toplevel()
        if standalone:
            self.root.title("Restream Sync Tool")
            self.root.geometry("1280x760")
            self.root.minsize(1100, 680)
            self.root.configure(bg=BG)

        self.windows: Dict[int, RunnerWindow] = {}
        self.runner_info: Dict[int, RunnerInfo] = {}
        self.busy_slots: set[int] = set()
        self.seconds_vars: Dict[int, tk.StringVar] = {}
        self.runner_vars: Dict[int, tk.StringVar] = {}
        self.status_vars: Dict[int, tk.StringVar] = {}
        self.delay_buttons: Dict[int, ttk.Button] = {}
        self.toggle_buttons: Dict[int, ttk.Button] = {}
        self.reload_buttons: Dict[int, ttk.Button] = {}
        self.calc_time_a_var = tk.StringVar()
        self.calc_time_b_var = tk.StringVar()
        self.calc_result_var = tk.StringVar(value="Delay: -")
        self.calc_slot_var = tk.StringVar(value="1")
        self.last_calculated_seconds: Optional[float] = None
        self.last_timer_image_path: Optional[Path] = None
        self.timer_preview_image = None
        self.timer_preview_source = None
        self.timer_preview_resize_after = None
        self.timer_preview_zoom = 1.0
        self.timer_preview_offset = [0, 0]
        self.timer_preview_drag_start = None

        self._setup_style()
        self._build_ui()
        self.refresh_all()

    def _setup_style(self) -> None:
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("TFrame", background=BG)
        self.style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        self.style.configure("TLabelframe", background=BG, foreground=TEXT, bordercolor=BORDER)
        self.style.configure("TLabelframe.Label", background=BG, foreground=TEXT, font=("Segoe UI", 10, "bold"))
        self.style.configure("TButton", background=PANEL_2, foreground=TEXT, padding=(12, 8), borderwidth=0, relief="flat")
        self.style.map("TButton", background=[("active", ACCENT)])
        self.style.configure("TEntry", fieldbackground=INPUT_BG, foreground=TEXT, bordercolor=BORDER, padding=(6, 5))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 12))
        ttk.Button(top, text="Refresh Status", command=self.refresh_all).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="Clear Seconds", command=self.clear_seconds).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="Apply All Delays", command=self.delay_all_entered).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="Clear Timer Images", command=self.clear_timer_screenshots).pack(side="right", padx=(8, 0))

        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True)

        left = ttk.Frame(content)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))

        right = ttk.Frame(content)
        right.pack(side="left", fill="both")
        right.configure(width=340)
        right.pack_propagate(False)

        preview_frame = ttk.Frame(left)
        preview_frame.pack(fill="both", expand=True, pady=(0, 10))
        preview_actions = ttk.Frame(preview_frame)
        preview_actions.pack(fill="x", pady=(0, 4))
        ttk.Label(preview_actions, text="Timer Screenshot", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 12))
        ttk.Button(preview_actions, text="Screenshot", command=self.create_timer_sync_screenshot).pack(side="left", padx=(0, 8))
        ttk.Button(preview_actions, text="Open Image", command=self.open_last_timer_screenshot).pack(side="left", padx=(0, 8))
        ttk.Button(preview_actions, text="Reset View", command=self.reset_timer_preview_view).pack(side="left", padx=(0, 8))
        self.timer_preview_status_var = tk.StringVar(value="No timer screenshot loaded.")
        ttk.Label(preview_actions, textvariable=self.timer_preview_status_var).pack(side="left", padx=(8, 0))
        ttk.Label(
            preview_frame,
            text="Take a screenshot, compare the timer values, then use the calculator below. Mouse wheel zooms; drag to pan.",
            foreground=MUTED,
        ).pack(fill="x", pady=(0, 6))
        self.timer_preview_canvas = tk.Canvas(
            preview_frame,
            bg=INPUT_BG,
            highlightthickness=0,
        )
        self.timer_preview_canvas.pack(fill="both", expand=True, pady=(0, 6))
        self.timer_preview_canvas.bind("<Configure>", self.on_timer_preview_resize)
        self.timer_preview_canvas.bind("<MouseWheel>", self.on_timer_preview_wheel)
        self.timer_preview_canvas.bind("<ButtonPress-1>", self.on_timer_preview_press)
        self.timer_preview_canvas.bind("<B1-Motion>", self.on_timer_preview_drag)

        calc = ttk.LabelFrame(left, text="Delay Calculator")
        calc.pack(fill="x", pady=(0, 10))
        ttk.Label(calc, text="Base timer").grid(row=0, column=0, sticky="w", padx=(8, 6), pady=(8, 4))
        ttk.Entry(calc, textvariable=self.calc_time_a_var, width=12).grid(row=0, column=1, sticky="w", padx=(0, 10), pady=(8, 4))
        ttk.Label(calc, text="Runner timer").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=(8, 4))
        ttk.Entry(calc, textvariable=self.calc_time_b_var, width=12).grid(row=0, column=3, sticky="w", padx=(0, 10), pady=(8, 4))
        ttk.Button(calc, text="Calculate", command=self.calculate_time_difference).grid(row=0, column=4, sticky="w", padx=(0, 10), pady=(8, 4))
        ttk.Label(calc, textvariable=self.calc_result_var).grid(row=0, column=5, sticky="w", padx=(0, 8), pady=(8, 4))

        ttk.Label(calc, text="Base is the timer everyone should match. Runner is the stream you are delaying.", foreground=MUTED).grid(
            row=1, column=0, columnspan=6, sticky="w", padx=(8, 8), pady=(2, 4)
        )
        ttk.Label(calc, text="Send result to runner").grid(row=2, column=0, columnspan=2, sticky="w", padx=(8, 6), pady=(4, 8))
        ttk.Combobox(calc, textvariable=self.calc_slot_var, values=["1", "2", "3", "4"], width=8, state="readonly").grid(row=2, column=2, sticky="w", padx=(0, 10), pady=(4, 8))
        ttk.Button(calc, text="Use as Delay", command=self.use_calculated_delay).grid(row=2, column=3, columnspan=2, sticky="w", padx=(0, 8), pady=(4, 8))
        ttk.Button(calc, text="Delay Now", command=self.delay_calculated_now).grid(row=2, column=5, sticky="w", padx=(0, 8), pady=(4, 8))
        calc.columnconfigure(5, weight=1)

        runner_frame = ttk.Frame(right)
        runner_frame.pack(fill="x")
        for slot in range(1, 5):
            card = tk.Frame(runner_frame, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", pady=(0, 8))
            top_row = tk.Frame(card, bg=PANEL)
            top_row.pack(fill="x", padx=8, pady=(7, 4))
            ttk.Label(top_row, text=f"R{slot}", width=4, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))

            runner_var = tk.StringVar(value="")
            self.runner_vars[slot] = runner_var
            ttk.Label(top_row, textvariable=runner_var).pack(side="left", fill="x", expand=True)
            ttk.Label(top_row, text="Delay").pack(side="left", padx=(6, 4))

            status_var = tk.StringVar(value="Not found")
            self.status_vars[slot] = status_var

            seconds_var = tk.StringVar(value="")
            self.seconds_vars[slot] = seconds_var
            ttk.Entry(top_row, textvariable=seconds_var, width=9).pack(side="left")

            actions = ttk.Frame(card)
            actions.pack(fill="x", padx=8, pady=(0, 7))
            delay_button = ttk.Button(actions, text="Delay", command=lambda s=slot: self.delay_one(s), width=7)
            delay_button.pack(side="left", padx=(0, 5))
            self.delay_buttons[slot] = delay_button

            toggle_button = ttk.Button(actions, text="Pause", command=lambda s=slot: self.toggle_one(s), width=7)
            toggle_button.pack(side="left", padx=(0, 5))
            self.toggle_buttons[slot] = toggle_button

            reload_button = ttk.Button(actions, text="Relaunch", command=lambda s=slot: self.reload_live(s), width=8)
            reload_button.pack(side="left")
            self.reload_buttons[slot] = reload_button

        controls = ttk.Frame(right)
        controls.pack(fill="x", pady=(14, 8))
        ttk.Button(controls, text="Refresh", command=self.refresh_windows).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Reload Race Info", command=self.refresh_race_info).pack(side="left", padx=(0, 8))

        self.summary_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.summary_var, wraplength=330).pack(anchor="w", pady=(2, 6))

        log_frame = ttk.LabelFrame(right, text="Log")
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log.configure(bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

    def log_message(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{timestamp}] {message}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int]:
        rect = RECT()
        if not GetWindowRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("Could not read VLC window position.")
        return (rect.left, rect.top, rect.right, rect.bottom)

    def capture_window_image(self, window: RunnerWindow):
        if ImageGrab is None:
            raise RuntimeError("Pillow ImageGrab is not available. Install Pillow from requirements.txt.")
        ShowWindow(window.hwnd, SW_RESTORE)
        BringWindowToTop(window.hwnd)
        SetForegroundWindow(window.hwnd)
        time.sleep(0.08)
        left, top, right, bottom = self.get_window_rect(window.hwnd)
        if right <= left or bottom <= top:
            raise RuntimeError(f"RUNNER {window.slot} window has an invalid size.")
        return ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB")

    def create_timer_sync_screenshot(self) -> None:
        self.refresh_windows(log=False)
        if not self.windows:
            messagebox.showwarning("Timer screenshot", "No RUNNER VLC windows were found.")
            return
        self.log_message("Creating timer sync screenshot...")
        threading.Thread(target=self.timer_sync_screenshot_worker, daemon=True).start()

    def timer_sync_screenshot_worker(self) -> None:
        try:
            path = self.build_timer_sync_screenshot()
        except Exception as exc:
            self.root.after(0, self.log_message, f"ERROR creating timer screenshot: {exc}")
            self.root.after(0, messagebox.showerror, "Timer screenshot failed", str(exc))
            return
        self.root.after(0, self.display_timer_screenshot, path)

    def display_timer_screenshot(self, path: Path) -> None:
        self.last_timer_image_path = path
        self.log_message(f"Timer screenshot saved: {path}")
        self.timer_preview_status_var.set(path.name)
        self.timer_preview_zoom = 1.0
        self.timer_preview_offset = [0, 0]
        self.render_timer_preview(path, self.last_timer_preview_slots())
        self.refocus_tool()

    def last_timer_preview_slots(self) -> list[int]:
        return sorted(self.windows) or [1, 2, 3, 4]

    def refocus_tool(self) -> None:
        try:
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def render_timer_preview(self, path: Path, slots: list[int] | None = None) -> None:
        if Image is None or ImageTk is None:
            self.timer_preview_canvas.delete("all")
            self.timer_preview_canvas.create_text(12, 12, text=f"Saved: {path}", fill=MUTED, anchor="nw")
            return
        try:
            self.root.update_idletasks()
            image = Image.open(path).convert("RGB")
            self.timer_preview_source = self.crop_timer_preview_image(image, slots or [1, 2, 3, 4])
            self.draw_timer_preview()
        except Exception as exc:
            self.timer_preview_canvas.delete("all")
            self.timer_preview_canvas.create_text(12, 12, text=f"Saved, but preview failed: {exc}", fill=MUTED, anchor="nw")

    def draw_timer_preview(self) -> None:
        if Image is None or ImageTk is None or self.timer_preview_source is None:
            return
        canvas_w = max(self.timer_preview_canvas.winfo_width(), 1)
        canvas_h = max(self.timer_preview_canvas.winfo_height(), 1)
        source_w, source_h = self.timer_preview_source.size
        fit_scale = min(canvas_w / source_w, canvas_h / source_h)
        scale = max(0.05, fit_scale * self.timer_preview_zoom)
        draw_w = max(1, int(source_w * scale))
        draw_h = max(1, int(source_h * scale))
        image = self.timer_preview_source.resize((draw_w, draw_h), Image.LANCZOS)
        self.timer_preview_image = ImageTk.PhotoImage(image)
        x = (canvas_w - draw_w) // 2 + int(self.timer_preview_offset[0])
        y = (canvas_h - draw_h) // 2 + int(self.timer_preview_offset[1])
        self.timer_preview_canvas.delete("all")
        self.timer_preview_canvas.create_image(x, y, image=self.timer_preview_image, anchor="nw")
        self.timer_preview_canvas.config(scrollregion=(x, y, x + draw_w, y + draw_h))

    def reset_timer_preview_view(self) -> None:
        self.timer_preview_zoom = 1.0
        self.timer_preview_offset = [0, 0]
        self.draw_timer_preview()

    def on_timer_preview_wheel(self, event) -> None:
        if self.timer_preview_source is None:
            return
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self.timer_preview_zoom = max(0.5, min(6.0, self.timer_preview_zoom * factor))
        self.draw_timer_preview()

    def on_timer_preview_press(self, event) -> None:
        self.timer_preview_drag_start = (event.x, event.y, self.timer_preview_offset[0], self.timer_preview_offset[1])

    def on_timer_preview_drag(self, event) -> None:
        if not self.timer_preview_drag_start:
            return
        start_x, start_y, offset_x, offset_y = self.timer_preview_drag_start
        self.timer_preview_offset = [offset_x + event.x - start_x, offset_y + event.y - start_y]
        self.draw_timer_preview()

    def crop_timer_preview_image(self, image, slots: list[int]):
        slots = sorted(set(slots))
        if not slots:
            return image
        gap = 8
        label_height = 28
        cell_width = (image.width - gap) // 2
        cell_height = (image.height - gap) // 2 - label_height
        positions = {
            1: (0, 0),
            2: (0, cell_height + label_height + gap),
            3: (cell_width + gap, 0),
            4: (cell_width + gap, cell_height + label_height + gap),
        }
        if len(slots) <= 2:
            cells = []
            for slot in slots:
                x, y = positions.get(slot, (0, 0))
                cells.append(image.crop((x, y, x + cell_width, y + label_height + cell_height)))
            if len(cells) == 1:
                return cells[0]
            preview = Image.new("RGB", (cell_width * len(cells) + gap * (len(cells) - 1), label_height + cell_height), (12, 14, 16))
            x = 0
            for cell in cells:
                preview.paste(cell, (x, 0))
                x += cell_width + gap
            return preview
        boxes = []
        for slot in slots:
            x, y = positions.get(slot, (0, 0))
            boxes.append((x, y, x + cell_width, y + label_height + cell_height))
        left = min(box[0] for box in boxes)
        top = min(box[1] for box in boxes)
        right = max(box[2] for box in boxes)
        bottom = max(box[3] for box in boxes)
        return image.crop((left, top, right, bottom))

    def on_timer_preview_resize(self, _event=None) -> None:
        if not self.last_timer_image_path or not self.last_timer_image_path.exists():
            return
        if self.timer_preview_resize_after:
            try:
                self.root.after_cancel(self.timer_preview_resize_after)
            except tk.TclError:
                pass
        self.timer_preview_resize_after = self.root.after(120, self.render_timer_preview_after_resize)

    def render_timer_preview_after_resize(self) -> None:
        self.timer_preview_resize_after = None
        self.draw_timer_preview()

    def open_last_timer_screenshot(self) -> None:
        if not self.last_timer_image_path or not self.last_timer_image_path.exists():
            messagebox.showinfo("Timer screenshot", "No timer screenshot has been created yet.")
            return
        if os.name == "nt":
            os.startfile(str(self.last_timer_image_path))  # type: ignore[attr-defined]

    def build_timer_sync_screenshot(self) -> Path:
        if Image is None or ImageDraw is None:
            raise RuntimeError("Pillow is not available. Install Pillow from requirements.txt.")

        captures = {}
        for slot in [1, 2, 3, 4]:
            window = self.windows.get(slot)
            if not window:
                continue
            captures[slot] = self.capture_window_image(window)

        if not captures:
            raise RuntimeError("No runner windows could be captured.")

        cell_width = max(image.width for image in captures.values())
        cell_height = max(image.height for image in captures.values())
        label_height = 28
        gap = 8
        canvas = Image.new("RGB", (cell_width * 2 + gap, (cell_height + label_height) * 2 + gap), (12, 14, 16))
        draw = ImageDraw.Draw(canvas)
        positions = {
            1: (0, 0),
            2: (0, cell_height + label_height + gap),
            3: (cell_width + gap, 0),
            4: (cell_width + gap, cell_height + label_height + gap),
        }
        for slot, (x, y) in positions.items():
            label = f"RUNNER {slot}"
            draw.rectangle((x, y, x + cell_width, y + label_height), fill=(16, 17, 19))
            draw.text((x + 8, y + 7), label, fill=(249, 250, 251))
            image = captures.get(slot)
            if image:
                canvas.paste(image, (x, y + label_height))
            else:
                draw.rectangle((x, y + label_height, x + cell_width, y + label_height + cell_height), outline=(63, 69, 75), width=2)
                draw.text((x + 8, y + label_height + 8), "Not captured", fill=(156, 163, 175))

        SYNC_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SYNC_SCREENSHOT_DIR / f"timer_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        canvas.save(path)
        return path

    def clear_timer_screenshots(self) -> None:
        SYNC_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        files = [p for p in SYNC_SCREENSHOT_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}]
        if not files:
            self.log_message("No timer screenshot images to delete.")
            messagebox.showinfo("Clear timer images", "No timer screenshot images found.")
            return
        if not messagebox.askyesno("Clear timer images", f"Delete {len(files)} timer screenshot image(s)?"):
            return
        deleted = 0
        for path in files:
            try:
                path.unlink()
                deleted += 1
            except Exception as exc:
                self.log_message(f"Could not delete {path.name}: {exc}")
        self.log_message(f"Deleted {deleted} timer screenshot image(s).")

    def refresh_all(self) -> None:
        self.refresh_race_info(log=False)
        self.refresh_windows(log=False)
        self.log_message("Ready.")

    def refresh_race_info(self, log: bool = True) -> None:
        self.runner_info = parse_last_setup()
        self.runner_info.update(load_current_race_info())
        for slot in range(1, 5):
            info = self.runner_info.get(slot)
            if info:
                self.runner_vars[slot].set(info.display_name)
                self.reload_buttons[slot].configure(state="normal")
            else:
                self.runner_vars[slot].set("No last setup")
                self.reload_buttons[slot].configure(state="normal")
        if log:
            self.log_message(f"Reloaded race info. Found {len(self.runner_info)} runner(s).")

    def refresh_windows(self, log: bool = True) -> None:
        self.windows = list_runner_windows()
        for slot in range(1, 5):
            if slot in self.windows:
                self.status_vars[slot].set(self.windows[slot].title)
                state = "normal" if slot not in self.busy_slots else "disabled"
                self.delay_buttons[slot].configure(state=state)
                self.toggle_buttons[slot].configure(state=state)
            else:
                self.status_vars[slot].set("Not found")
                self.delay_buttons[slot].configure(state="disabled")
                self.toggle_buttons[slot].configure(state="disabled")
        self.summary_var.set(f"Detected {len(self.windows)} runner VLC window(s). Refresh after relaunching or replacing a runner.")
        if log:
            self.log_message(f"Refreshed VLC windows. Found {len(self.windows)} runner VLC window(s).")

    def clear_seconds(self) -> None:
        for var in self.seconds_vars.values():
            var.set("")

    def parse_timecode(self, value: str) -> float:
        raw = value.strip()
        if not raw:
            raise ValueError("Enter both times.")
        parts = raw.split(":")
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) > 3:
            raise ValueError(f"Too many ':' separators in {raw!r}.")
        total = 0.0
        multiplier = 1.0
        for part in reversed(parts):
            part = part.strip()
            if not part:
                raise ValueError(f"Invalid time value {raw!r}.")
            total += float(part) * multiplier
            multiplier *= 60.0
        return total

    def format_seconds(self, seconds: float) -> str:
        if seconds == int(seconds):
            return str(int(seconds))
        return f"{seconds:.3f}".rstrip("0").rstrip(".")

    def calculate_time_difference(self) -> None:
        try:
            time_a = self.parse_timecode(self.calc_time_a_var.get())
            time_b = self.parse_timecode(self.calc_time_b_var.get())
        except ValueError as exc:
            self.last_calculated_seconds = None
            self.calc_result_var.set("Delay: -")
            messagebox.showwarning("Time calculator", str(exc))
            return
        difference = abs(time_b - time_a)
        self.last_calculated_seconds = difference
        display = self.format_seconds(difference)
        self.calc_result_var.set(f"Delay: {display}s")
        self.log_message(f"Delay calculated: {display}s")

    def use_calculated_delay(self) -> None:
        if self.last_calculated_seconds is None:
            self.calculate_time_difference()
        if self.last_calculated_seconds is None:
            return
        try:
            slot = int(self.calc_slot_var.get())
        except ValueError:
            messagebox.showwarning("Time calculator", "Choose a runner slot.")
            return
        self.seconds_vars[slot].set(self.format_seconds(self.last_calculated_seconds))
        self.log_message(f"Set RUNNER {slot} delay to {self.format_seconds(self.last_calculated_seconds)}s.")

    def delay_calculated_now(self) -> None:
        self.use_calculated_delay()
        if self.last_calculated_seconds is None:
            return
        try:
            slot = int(self.calc_slot_var.get())
        except ValueError:
            messagebox.showwarning("Time calculator", "Choose a runner slot.")
            return
        self.delay_one(slot)

    def _get_seconds(self, slot: int) -> Optional[float]:
        raw = self.seconds_vars[slot].get().strip()
        if not raw:
            messagebox.showwarning("Missing seconds", f"Enter seconds for RUNNER {slot}.")
            return None
        try:
            seconds = float(raw)
        except ValueError:
            messagebox.showwarning("Invalid seconds", f"'{raw}' is not valid for RUNNER {slot}.")
            return None
        if seconds <= 0:
            messagebox.showwarning("Invalid seconds", "Seconds must be greater than 0.")
            return None
        return seconds

    def _set_slot_busy(self, slot: int, busy: bool) -> None:
        if busy:
            self.busy_slots.add(slot)
            self.delay_buttons[slot].configure(state="disabled")
            self.toggle_buttons[slot].configure(state="disabled")
            self.reload_buttons[slot].configure(state="disabled")
        else:
            self.busy_slots.discard(slot)
            if slot in self.windows:
                self.delay_buttons[slot].configure(state="normal")
                self.toggle_buttons[slot].configure(state="normal")
            self.reload_buttons[slot].configure(state="normal")

    def toggle_one(self, slot: int) -> None:
        window = self.windows.get(slot)
        if not window:
            messagebox.showwarning("Window not found", f"RUNNER {slot} VLC window was not found. Click Refresh.")
            return
        try:
            toggle_runner(window)
            self.log_message(f"Pause/Resume sent to RUNNER {slot}.")
        except Exception as exc:
            self.log_message(f"ERROR toggling RUNNER {slot}: {exc}")
            messagebox.showerror("Pause/Resume failed", str(exc))

    def delay_one(self, slot: int) -> None:
        seconds = self._get_seconds(slot)
        if seconds is None:
            return
        window = self.windows.get(slot)
        if not window:
            messagebox.showwarning("Window not found", f"RUNNER {slot} VLC window was not found. Click Refresh.")
            return
        self._start_delay_thread(slot, window, seconds)

    def delay_all_entered(self) -> None:
        jobs: List[tuple[int, RunnerWindow, float]] = []
        for slot in range(1, 5):
            raw = self.seconds_vars[slot].get().strip()
            if not raw:
                continue
            try:
                seconds = float(raw)
            except ValueError:
                messagebox.showwarning("Invalid seconds", f"'{raw}' is not valid for RUNNER {slot}.")
                return
            if seconds <= 0:
                messagebox.showwarning("Invalid seconds", f"RUNNER {slot} seconds must be greater than 0.")
                return
            window = self.windows.get(slot)
            if not window:
                messagebox.showwarning("Window not found", f"RUNNER {slot} VLC window was not found. Click Refresh.")
                return
            jobs.append((slot, window, seconds))

        if not jobs:
            messagebox.showinfo("No delays", "Enter seconds for one or more runners first.")
            return

        self.log_message("Delay All: " + ", ".join(f"R{s}={sec:g}s" for s, _w, sec in jobs))
        for slot, _window, _seconds in jobs:
            self._set_slot_busy(slot, True)

        def worker() -> None:
            start_times: Dict[int, float] = {}
            try:
                for slot, window, _seconds in jobs:
                    self.root.after(0, self.log_message, f"Pause RUNNER {slot}")
                    toggle_runner(window)
                    start_times[slot] = time.perf_counter()
                    time.sleep(0.08)

                remaining = {slot for slot, _window, _seconds in jobs}
                delays = {slot: seconds for slot, _window, seconds in jobs}
                windows = {slot: window for slot, window, _seconds in jobs}
                while remaining:
                    now = time.perf_counter()
                    due = [slot for slot in remaining if now - start_times[slot] >= delays[slot]]
                    if not due:
                        time.sleep(0.02)
                        continue
                    for slot in sorted(due):
                        toggle_runner(windows[slot])
                        remaining.remove(slot)
                        self.root.after(0, self.log_message, f"Resume RUNNER {slot} after {delays[slot]:g}s")
            except Exception as exc:
                self.root.after(0, self.log_message, f"ERROR during Delay All: {exc}")
                self.root.after(0, messagebox.showerror, "Delay All failed", str(exc))
            finally:
                for slot, _window, _seconds in jobs:
                    self.root.after(0, self._set_slot_busy, slot, False)

        threading.Thread(target=worker, daemon=True).start()

    def _start_delay_thread(self, slot: int, window: RunnerWindow, seconds: float) -> None:
        self._set_slot_busy(slot, True)
        self.log_message(f"Pausing RUNNER {slot} for {seconds:g}s.")

        def worker() -> None:
            try:
                toggle_runner(window)
                time.sleep(seconds)
                toggle_runner(window)
                self.root.after(0, self.log_message, f"Resumed RUNNER {slot} after {seconds:g}s.")
            except Exception as exc:
                self.root.after(0, self.log_message, f"ERROR delaying RUNNER {slot}: {exc}")
                self.root.after(0, messagebox.showerror, "Delay failed", str(exc))
            finally:
                self.root.after(0, self._set_slot_busy, slot, False)

        threading.Thread(target=worker, daemon=True).start()

    def reload_live(self, slot: int) -> None:
        info = self.runner_info.get(slot)
        twitch = info.twitch_name if info else ""
        if not twitch:
            twitch = simpledialog.askstring("Relaunch Runner", f"Twitch name for RUNNER {slot}:", parent=self.root) or ""
            twitch = normalize_twitch(twitch)
            if not twitch:
                return

        confirm = messagebox.askyesno(
            "Relaunch Runner",
            f"Close/relaunch RUNNER {slot} from twitch.tv/{twitch}?\n\nThis is the way to return that slot to current live playback.",
        )
        if not confirm:
            return

        self._set_slot_busy(slot, True)
        self.log_message(f"Relaunch RUNNER {slot}: twitch.tv/{twitch}")

        def worker() -> None:
            try:
                window = self.windows.get(slot)
                if window:
                    close_window(window)
                    time.sleep(1.0)
                launch_stream(slot, twitch)
                time.sleep(3.0)
                self.root.after(0, self.refresh_windows)
            except Exception as exc:
                self.root.after(0, self.log_message, f"ERROR reloading RUNNER {slot}: {exc}")
                self.root.after(0, messagebox.showerror, "Reload failed", str(exc))
            finally:
                self.root.after(0, self._set_slot_busy, slot, False)

        threading.Thread(target=worker, daemon=True).start()


class SyncerApp(SyncPanel):
    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root, standalone=True)
        self.pack(fill="both", expand=True)


def main() -> None:
    root = tk.Tk()
    SyncerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
