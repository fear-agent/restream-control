#!/usr/bin/env python3
"""
Restream Control App v3.1
Main control surface for setup, embedded sync, cropping launcher, and event tools.
"""
from __future__ import annotations

import importlib.util
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

from PIL import Image, ImageTk

import app_state
import cropping_tool
import obs_crop_service
import stream_syncer

APP_TITLE = "Restream Control"
BASE_DIR = app_state.APP_DIR
REPO_ROOT = app_state.REPO_ROOT
PYTHON = sys.executable
PYTHONW_PATH = Path(sys.executable).with_name("pythonw.exe")
GUI_PYTHON = str(PYTHONW_PATH if os.name == "nt" and PYTHONW_PATH.exists() else sys.executable)

CONTROL_SCRIPT = BASE_DIR / "launch_crosskeys.py"
CROPPING_TOOL = BASE_DIR / "cropping_tool.py"
LEGACY_CROPPING_TOOL = BASE_DIR / "obs_crop_helper_ws.py"
SYNC_TOOL = BASE_DIR / "stream_syncer.py"
SCREENSHOT_SCRIPT = BASE_DIR / "capture_runner_screenshots.ps1"
OBS_TEXT_DIR = app_state.config_path("obs_text_dir")
SCREENSHOT_DIR = app_state.config_path("screenshot_dir")
SYNC_SCREENSHOT_DIR = BASE_DIR / "sync_screenshots"
LAST_SETUP = BASE_DIR / "race_setup_last.txt"
RUNNERS_CSV = app_state.config_path("runner_csv")
LOGO_FILE = BASE_DIR / "assets" / "logo-w.png"
OBS_TEMPLATE_FILE = REPO_ROOT / "obs-template" / "Restream_Control_Template.json"
DEFAULT_LAYOUT_IMAGES = {
    "2P": REPO_ROOT / "obs-template" / "assets" / "overlay-bg-default.png",
    "4P": REPO_ROOT / "obs-template" / "assets" / "overlay-bg-default-4p.png",
}
LAYOUT_DESIGN_FILE = app_state.STATE_DIR / "layout_designer.json"

DISCORD_PTB_PATHS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "DiscordPTB" / "Update.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "DiscordPTB" / "DiscordPTB.exe",
]

BG = "#101113"
SIDEBAR = "#171717"
PANEL = "#202327"
PANEL_2 = "#2a2f35"
INPUT_BG = "#111315"
TEXT = "#f9fafb"
MUTED = "#9ca3af"
ACCENT = "#0f766e"
ACCENT_HOVER = "#115e59"
DANGER = "#7f1d1d"
DANGER_HOVER = "#991b1b"
BORDER = "#3f454b"
GOOD = "#22c55e"
WARN = "#f59e0b"
DESIGN_WIDTH = 1920
DESIGN_HEIGHT = 1080
LAYOUT_REGION_COLORS = {
    "Game": "#14b8a6",
    "Tracker": "#f59e0b",
    "Timer": "#60a5fa",
    "Runner Name": "#e879f9",
    "Comms": "#f43f5e",
    "Facecam": "#a78bfa",
    "Image": "#22c55e",
    "Text": "#e5e7eb",
    "Browser": "#38bdf8",
}
LAYOUT_REGION_TYPES = ["Game", "Tracker", "Timer", "Facecam", "Runner Name", "Comms", "Text", "Image"]
MAX_EXTRA_TEXT_REGIONS = 3


def bundled_or_exists(path: Path) -> bool:
    return app_state.IS_FROZEN or path.exists()


def load_launch_module() -> Optional[Any]:
    if app_state.IS_FROZEN:
        try:
            import launch_crosskeys
            return launch_crosskeys
        except Exception:
            return None
    if not CONTROL_SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location("launch_crosskeys", CONTROL_SCRIPT)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["launch_crosskeys"] = module
    spec.loader.exec_module(module)
    return module


def run_console(args: list[str]) -> None:
    try:
        subprocess.Popen(
            args,
            cwd=str(BASE_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
    except Exception as exc:
        messagebox.showerror("Launch failed", str(exc))


def hidden_creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def run_hidden(args: list[str]) -> None:
    try:
        subprocess.Popen(args, cwd=str(BASE_DIR), creationflags=hidden_creationflags())
    except Exception as exc:
        messagebox.showerror("Launch failed", str(exc))


def run_detached(args: list[str]) -> None:
    try:
        subprocess.Popen(args, cwd=str(BASE_DIR))
    except Exception as exc:
        messagebox.showerror("Launch failed", str(exc))


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_path(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        if os.name == "nt" and path.suffix.lower() == ".md":
            subprocess.Popen(["notepad.exe", str(path)])
            return
        raise


def open_windows_volume_mixer() -> None:
    if os.name == "nt":
        try:
            subprocess.Popen(["explorer.exe", "ms-settings:apps-volume"])
            return
        except Exception:
            subprocess.Popen(["sndvol.exe"])
            return
    messagebox.showinfo("Volume mixer", "Windows Volume Mixer is only available on Windows.")


class ScrollablePage(tk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)
        self._update_scrollbar()

    def _update_scrollbar(self) -> None:
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        content_height = bbox[3] - bbox[1]
        needs_scroll = content_height > max(1, self.canvas.winfo_height())
        if needs_scroll and not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y")
        elif not needs_scroll and self.scrollbar.winfo_ismapped():
            self.scrollbar.pack_forget()

    def _bind_mousewheel(self, _event=None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event=None) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class RunnerRow:
    def __init__(self, app: "RestreamApp", parent: tk.Frame, slot: int) -> None:
        self.app = app
        self.slot = slot
        self.enabled_var = tk.BooleanVar(value=True)
        self.selected_var = tk.StringVar()
        self.display_var = tk.StringVar()
        self.twitch_var = tk.StringVar()

        self.frame = tk.Frame(parent, bg=PANEL)
        self.frame.pack(fill="x", padx=14, pady=2)

        self.label = tk.Label(
            self.frame,
            text=f"Runner {slot}",
            bg=PANEL,
            fg=TEXT,
            width=8,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        self.label.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.suggestions: list[str] = []
        self.popup: Optional[tk.Toplevel] = None
        self.listbox: Optional[tk.Listbox] = None
        self.combo = tk.Entry(
            self.frame,
            textvariable=self.selected_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Segoe UI", 10),
        )
        self.combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), ipady=6)
        self.combo.bind("<Return>", self.on_enter)
        self.combo.bind("<Tab>", self.on_enter)
        self.combo.bind("<KeyRelease>", self.on_keyrelease)
        self.combo.bind("<Down>", self.focus_suggestions)
        self.combo.bind("<FocusOut>", self.hide_popup_later)

        self.display_entry = tk.Entry(
            self.frame,
            textvariable=self.display_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=20,
            font=("Segoe UI", 10),
        )
        self.display_entry.grid(row=0, column=2, sticky="ew", padx=(0, 8), ipady=5)

        self.twitch_entry = tk.Entry(
            self.frame,
            textvariable=self.twitch_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=20,
            font=("Segoe UI", 10),
        )
        self.twitch_entry.grid(row=0, column=3, sticky="ew", padx=(0, 8), ipady=5)

        self.clear_btn = app.button(self.frame, "Clear", self.clear, compact=True)
        self.clear_btn.grid(row=0, column=4, sticky="e")

        self.frame.columnconfigure(1, weight=2)
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(3, weight=1)

    def set_values(self, values: list[str]) -> None:
        self.suggestions = values

    def set_enabled(self, enabled: bool) -> None:
        self.enabled_var.set(enabled)
        state = "normal" if enabled else "disabled"
        self.combo.configure(state=state)
        self.display_entry.configure(state=state)
        self.twitch_entry.configure(state=state)
        self.clear_btn.configure(state=state)
        self.label.configure(fg=TEXT if enabled else MUTED)
        if not enabled:
            self.clear()

    def clear(self) -> None:
        self.selected_var.set("")
        self.display_var.set("")
        self.twitch_var.set("")

    def on_select(self, _event=None) -> None:
        self.apply_selection(self.selected_var.get())

    def on_enter(self, _event=None) -> None:
        value = self.selected_var.get()
        match = self.app.best_runner_value(value)
        if match:
            self.selected_var.set(match)
            self.apply_selection(match)
            self.hide_popup()
            return "break"
        self.apply_selection(value)
        self.hide_popup()
        return "break"

    def on_keyrelease(self, event=None) -> None:
        # Lightweight filtering without hijacking navigation keys.
        if event and event.keysym in {"Up", "Down", "Return", "Escape", "Tab", "Left", "Right"}:
            return
        typed = self.selected_var.get().strip().lower()
        if not typed:
            self.hide_popup()
            return
        filtered = self.app.match_runner_values(typed)
        self.set_values(filtered[:40] if filtered else self.app.runner_combo_values)
        self.show_popup(filtered[:12])

    def show_popup(self, values: list[str]) -> None:
        if not values:
            self.hide_popup()
            return
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = tk.Toplevel(self.combo)
            self.popup.overrideredirect(True)
            self.popup.configure(bg=BORDER)
            self.listbox = tk.Listbox(
                self.popup,
                bg=INPUT_BG,
                fg=TEXT,
                selectbackground=ACCENT,
                selectforeground="white",
                activestyle="none",
                relief="flat",
                height=min(8, len(values)),
                font=("Segoe UI", 10),
            )
            self.listbox.pack(fill="both", expand=True, padx=1, pady=1)
            self.listbox.bind("<ButtonRelease-1>", self.pick_suggestion)
            self.listbox.bind("<Return>", self.pick_suggestion)
            self.listbox.bind("<Escape>", lambda _event: self.hide_popup())
        if self.listbox is None:
            return
        self.listbox.delete(0, "end")
        for value in values:
            self.listbox.insert("end", value)
        self.listbox.configure(height=min(8, len(values)))
        x = self.combo.winfo_rootx()
        y = self.combo.winfo_rooty() + self.combo.winfo_height()
        width = max(self.combo.winfo_width(), 320)
        height = min(8, len(values)) * 24 + 4
        self.popup.geometry(f"{width}x{height}+{x}+{y}")
        self.popup.deiconify()
        self.popup.lift()

    def hide_popup_later(self, _event=None) -> None:
        self.combo.after(150, self.hide_popup)

    def hide_popup(self) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.withdraw()

    def focus_suggestions(self, _event=None):
        if self.listbox is not None and self.popup is not None and self.popup.winfo_viewable():
            self.listbox.focus_set()
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            return "break"
        return None

    def pick_suggestion(self, _event=None):
        if self.listbox is None:
            return "break"
        selection = self.listbox.curselection()
        if not selection:
            return "break"
        value = self.listbox.get(selection[0])
        self.selected_var.set(value)
        self.apply_selection(value)
        self.hide_popup()
        self.combo.focus_set()
        return "break"

    def apply_selection(self, value: str) -> None:
        value = value.strip()
        if not value:
            return
        runner = self.app.runner_by_combo.get(value)
        if runner:
            self.display_var.set(self.app.runner_display_by_combo.get(value, runner.display_name))
            self.twitch_var.set(runner.twitch_name)
            return

        # Accept plain twitch, @twitch, twitch.tv/name, or URL.
        mod = self.app.launch_mod
        twitch = mod.normalize_twitch_input(value) if mod else value.strip().lstrip("@")
        if twitch:
            self.twitch_var.set(twitch)
            if not self.display_var.get().strip():
                self.display_var.set(twitch)

    def to_runner(self) -> Any:
        if not self.enabled_var.get():
            return None
        mod = self.app.launch_mod
        if mod is None:
            raise RuntimeError("launch_crosskeys.py could not be loaded.")
        twitch = mod.normalize_twitch_input(self.twitch_var.get().strip() or self.selected_var.get().strip())
        if not mod.is_probable_twitch_name(twitch):
            raise ValueError(f"Runner {self.slot} needs a valid Twitch name.")
        display = self.display_var.get().strip() or twitch
        return mod.Runner(display, twitch)


class RestreamApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1480x900")
        self.minsize(1280, 760)
        self.configure(bg=BG)

        self.launch_mod = load_launch_module()
        self.runners = []
        self.runner_combo_values: list[str] = []
        self.runner_search_text: dict[str, str] = {}
        self.runner_by_combo: dict[str, Any] = {}
        self.runner_display_by_combo: dict[str, str] = {}
        self.runner_rows: dict[int, RunnerRow] = {}
        self.name_vars: dict[str, tk.StringVar] = {}
        self.current_page = "Setup"
        self.nav_buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.page_bodies: dict[str, tk.Frame] = {}
        self.status_var = tk.StringVar(value="Ready")
        self.log_var = tk.StringVar(value="")
        self.dashboard_layout_var = tk.StringVar(value="Layout: -")
        self.dashboard_runners_var = tk.StringVar(value="Runners: -")
        self.dashboard_obs_var = tk.StringVar(value="OBS: not checked")
        self.mode_var = tk.StringVar(value="2")
        self.comms_var = tk.StringVar()
        self.replace_slot_var = tk.StringVar(value="1")
        obs_config = app_state.load_config().get("obs_websocket", {})
        self.obs_host_var = tk.StringVar(value=str(obs_config.get("host", "localhost")))
        self.obs_port_var = tk.StringVar(value=str(obs_config.get("port", 4455)))
        self.obs_password_var = tk.StringVar(value=str(obs_config.get("password", "")))
        self.vlc_audio_var = tk.StringVar()
        self.vlc_audio_status_var = tk.StringVar(value="Choose an optional VLC output device.")
        self.vlc_audio_devices: dict[str, str] = {}
        self.vlc_audio_combo: Optional[ttk.Combobox] = None
        self.edit_runner_var = tk.StringVar()
        self.edit_display_var = tk.StringVar()
        self.edit_twitch_var = tk.StringVar()
        self.edit_aliases_var = tk.StringVar()
        self.source_map_text: Optional[tk.Text] = None
        self.audio_status_var = tk.StringVar(value="Click Refresh Audio to read OBS audio inputs.")
        self.audio_rows_frame: Optional[tk.Frame] = None
        self.audio_rows: dict[str, dict[str, Any]] = {}
        self.audio_mapper_layout_var = tk.StringVar(value="Current")
        self.audio_mapper_status_var = tk.StringVar(value="Load OBS audio sources to map runner windows.")
        self.audio_mapper_frame: Optional[tk.Frame] = None
        self.audio_mapper_rows: dict[str, dict[str, Any]] = {}
        self.builder_layout_var = tk.StringVar(value="Both")
        self.builder_status_var = tk.StringVar(value="Scan OBS before creating missing default template sources.")
        self.builder_text: Optional[tk.Text] = None
        self.wizard_status_var = tk.StringVar(value="Start here on a new machine, or use this later to re-check setup.")
        self.wizard_checks_frame: Optional[tk.Frame] = None
        self.layout_mode_var = tk.StringVar(value="4P")
        self.layout_slot_var = tk.StringVar(value="R1")
        self.layout_region_type_var = tk.StringVar(value="Game")
        self.layout_copy_from_var = tk.StringVar(value="R1")
        self.layout_copy_to_var = tk.StringVar(value="R2")
        self.layout_copy_part_var = tk.StringVar(value="All")
        self.layout_status_var = tk.StringVar(value="Draw a region on the canvas, then save the layout.")
        self.layout_regions: list[dict[str, Any]] = []
        self.layout_selected_id: Optional[str] = None
        self.layout_selected_ids: set[str] = set()
        self.layout_drag: Optional[dict[str, Any]] = None
        self.layout_undo_stack: list[dict[str, Any]] = []
        self.layout_canvas: Optional[tk.Canvas] = None
        self.layout_bg_path = ""
        self.layout_bg_source: Optional[Image.Image] = None
        self.layout_bg_photo: Optional[ImageTk.PhotoImage] = None
        self.layout_image_label_var = tk.StringVar(value="No layout image loaded")
        self.layout_image_layer_var = tk.StringVar(value="Overlay above feeds")
        self.layout_image_region_layer_var = tk.StringVar(value="Above feeds")
        self.layout_source_name_var = tk.StringVar()
        self.layout_image_path_var = tk.StringVar()
        self.layout_text_var = tk.StringVar()
        self.layout_region_details_var = tk.StringVar(value="Select a region to edit settings.")
        self.sync_panel: Optional[stream_syncer.SyncPanel] = None
        self.crop_panel: Optional[cropping_tool.CropPanel] = None
        self.logo_image = None

        self._setup_style()
        self._build()
        self.load_runners_into_setup()
        self.show_page("Setup Wizard" if self.should_show_setup_wizard() else "Setup")
        self.after(150, self.refresh_status)

    def log_status(self, message: str) -> None:
        self.status_var.set(message)
        self.log_var.set(message)
        app_state.append_log(message)
        self.update_dashboard(include_obs=False)

    def refocus_app(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def should_show_setup_wizard(self) -> bool:
        if app_state.CONFIG_FILE.exists():
            return False
        return app_state.IS_FROZEN or not app_state.CURRENT_RACE_FILE.exists()

    def _setup_style(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("TFrame", background=BG)
        self.style.configure("Panel.TFrame", background=PANEL)
        self.style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        self.style.configure("TButton", font=("Segoe UI", 10), padding=(14, 9))
        self.style.configure(
            "TCombobox",
            fieldbackground=INPUT_BG,
            background=PANEL_2,
            foreground=TEXT,
            selectbackground=INPUT_BG,
            selectforeground=TEXT,
            selectionbackground=INPUT_BG,
            selectionforeground=TEXT,
            arrowcolor=TEXT,
            arrowsize=18,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(8, 6, 8, 6),
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", INPUT_BG), ("focus", INPUT_BG), ("!disabled", INPUT_BG)],
            foreground=[("readonly", TEXT), ("focus", TEXT), ("!disabled", TEXT)],
            selectbackground=[("readonly", INPUT_BG), ("focus", INPUT_BG), ("!disabled", INPUT_BG)],
            selectforeground=[("readonly", TEXT), ("focus", TEXT), ("!disabled", TEXT)],
            background=[("readonly", PANEL_2), ("active", ACCENT), ("!disabled", PANEL_2)],
            arrowcolor=[("disabled", MUTED), ("readonly", TEXT), ("active", "white"), ("!disabled", TEXT)],
        )
        self.option_add("*TCombobox*selectBackground", INPUT_BG)
        self.option_add("*TCombobox*selectForeground", TEXT)
        self.option_add("*TCombobox*Listbox.background", INPUT_BG)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

    def _build(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True)

        sidebar = tk.Frame(root, bg=SIDEBAR, width=150)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        if LOGO_FILE.exists():
            try:
                logo = Image.open(LOGO_FILE).convert("RGBA")
                logo.thumbnail((96, 64), Image.LANCZOS)
                self.logo_image = ImageTk.PhotoImage(logo)
                tk.Label(sidebar, image=self.logo_image, bg=SIDEBAR).pack(anchor="center", pady=(16, 4))
            except Exception:
                pass
        title = tk.Label(sidebar, text="Restream Control", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 10, "bold"), justify="center", wraplength=120)
        title.pack(anchor="center", padx=12, pady=(0, 16))

        nav_labels = {
            "Custom OBS Layout": "Custom Layout",
        }
        for name in ["Setup", "Cropping", "Sync", "Audio", "Custom OBS Layout", "Template Setup", "Checklist", "Setup Wizard", "Settings"]:
            btn = tk.Button(
                sidebar,
                text=nav_labels.get(name, name),
                anchor="w",
                relief="flat",
                bd=0,
                bg=PANEL_2,
                fg=TEXT,
                activebackground=ACCENT,
                activeforeground="white",
                font=("Segoe UI", 11),
                padx=14,
                pady=10,
                highlightthickness=1,
                highlightbackground=BORDER,
                command=lambda n=name: self.show_page(n),
            )
            btn.pack(fill="x", padx=10, pady=4)
            self.nav_buttons[name] = btn

        content = tk.Frame(root, bg=BG)
        content.pack(side="left", fill="both", expand=True)

        header = tk.Frame(content, bg=BG)
        header.pack(fill="x", padx=20, pady=(14, 8))
        self.page_title = tk.Label(header, text="Setup", bg=BG, fg=TEXT, font=("Segoe UI", 18, "bold"))
        self.page_title.pack(side="left")
        self.button(header, "Refresh Status", self.refresh_status, compact=True).pack(side="right")

        tk.Label(content, textvariable=self.status_var, bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=22, pady=(0, 8))

        dashboard = tk.Frame(content, bg=BG)
        dashboard.pack(fill="x", padx=20, pady=(0, 8))
        for var in [
            self.dashboard_layout_var,
            self.dashboard_runners_var,
            self.dashboard_obs_var,
        ]:
            tk.Label(
                dashboard,
                textvariable=var,
                bg=PANEL,
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
                relief="solid",
                bd=1,
                padx=10,
                pady=6,
            ).pack(side="left", padx=(0, 6))

        self.page_container = tk.Frame(content, bg=BG)
        self.page_container.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        for name in ["Setup", "Cropping", "Sync", "Audio", "Custom OBS Layout", "Template Setup", "Checklist", "Setup Wizard", "Settings"]:
            page = tk.Frame(self.page_container, bg=BG) if name in {"Cropping", "Sync", "Custom OBS Layout"} else ScrollablePage(self.page_container)
            self.pages[name] = page
            self.page_bodies[name] = page if name in {"Cropping", "Sync", "Custom OBS Layout"} else page.inner

        self._build_setup(self.page_bodies["Setup"])
        self._build_wizard(self.page_bodies["Setup Wizard"])
        self._build_audio_panel(self.page_bodies["Audio"])
        self._build_layout_designer(self.page_bodies["Custom OBS Layout"])
        self._build_obs_builder(self.page_bodies["Template Setup"])
        self._build_checklist(self.page_bodies["Checklist"])
        self._build_settings(self.page_bodies["Settings"])

    def show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.page_title.config(text=name)
        self.current_page = name
        for key, btn in self.nav_buttons.items():
            if key == name:
                btn.config(bg=ACCENT, fg="white", font=("Segoe UI", 11, "bold"), relief="flat")
            else:
                btn.config(bg=PANEL_2, fg=TEXT, font=("Segoe UI", 11), relief="flat")
        if name == "Sync" and self.sync_panel is not None:
            self.sync_panel.refresh_all()
        elif name == "Sync" and self.sync_panel is None:
            self._build_sync(self.page_bodies["Sync"])
        if name == "Cropping" and self.crop_panel is not None:
            self.crop_panel.refresh_current_race()
        elif name == "Cropping" and self.crop_panel is None:
            self._build_cropping(self.page_bodies["Cropping"])

    def panel(self, parent: tk.Frame, title: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill="x", padx=4, pady=6)
        tk.Label(frame, text=title, bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 7))
        return frame

    def button(self, parent: tk.Widget, text: str, command, primary: bool=False, danger: bool=False, compact: bool=False) -> tk.Button:
        bg = ACCENT if primary else (DANGER if danger else PANEL_2)
        active = ACCENT_HOVER if primary else (DANGER_HOVER if danger else "#243047")
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg="white",
            activebackground=active,
            activeforeground="white",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            highlightcolor=ACCENT,
            font=("Segoe UI", 10, "bold" if primary else "normal"),
            padx=12 if compact else 16,
            pady=7 if compact else 11,
        )

    def _build_setup(self, parent: tk.Frame) -> None:
        p = self.panel(parent, "Race Setup")

        top = tk.Frame(p, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(top, text="Race type", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        for label, value in [("2P", "2"), ("4P", "4")]:
            rb = tk.Radiobutton(
                top,
                text=label,
                value=value,
                variable=self.mode_var,
                command=self.update_mode,
                bg=PANEL,
                fg=TEXT,
                selectcolor=ACCENT,
                activebackground=ACCENT_HOVER,
                activeforeground="white",
                indicatoron=False,
                relief="solid",
                bd=1,
                width=6,
                font=("Segoe UI", 11, "bold"),
                padx=8,
                pady=7,
            )
            rb.pack(side="left", padx=(0, 8))
        self.button(top, "Load Last Race", self.load_saved_race_into_fields, compact=True).pack(side="right", padx=(8, 0))
        self.button(top, "Reload Runner List", self.load_runners_into_setup, compact=True).pack(side="right")

        header = tk.Frame(p, bg=PANEL)
        header.pack(fill="x", padx=16, pady=(0, 2))
        tk.Label(header, text="", bg=PANEL, width=9).grid(row=0, column=0, padx=(0, 8))
        tk.Label(header, text="Search / select runner", bg=PANEL, fg=MUTED, anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(header, text="Display name", bg=PANEL, fg=MUTED, anchor="w").grid(row=0, column=2, sticky="w")
        tk.Label(header, text="Twitch name", bg=PANEL, fg=MUTED, anchor="w").grid(row=0, column=3, sticky="w")
        header.columnconfigure(1, weight=2)
        header.columnconfigure(2, weight=1)
        header.columnconfigure(3, weight=1)

        for slot in range(1, 5):
            self.runner_rows[slot] = RunnerRow(self, p, slot)

        comm_row = tk.Frame(p, bg=PANEL)
        comm_row.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(comm_row, text="Comms", bg=PANEL, fg=TEXT, width=9, anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        comm_entry = tk.Entry(comm_row, textvariable=self.comms_var, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", font=("Segoe UI", 10))
        comm_entry.pack(side="left", fill="x", expand=True, ipady=7)
        tk.Label(comm_row, text="  comma or & separated", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")

        actions = tk.Frame(p, bg=PANEL)
        actions.pack(fill="x", padx=16, pady=(6, 12))
        self.button(actions, "Launch Streams", self.launch_from_gui, primary=True).pack(side="left", padx=(0, 8))
        self.button(actions, "Update OBS Text", self.write_names_only).pack(side="left", padx=8)
        self.button(actions, "Clear Fields", self.clear_runner_fields).pack(side="left", padx=8)
        replace = tk.Frame(actions, bg=PANEL)
        replace.pack(side="right")
        tk.Label(replace, text="Replace A Runner", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        tk.Label(replace, text="Slot", bg=PANEL, fg=TEXT, font=("Segoe UI", 10)).pack(side="left", padx=(0, 6))
        slot_combo = ttk.Combobox(replace, textvariable=self.replace_slot_var, values=["1", "2", "3", "4"], width=8, state="readonly")
        slot_combo.pack(side="left", padx=(0, 8), ipady=5)
        self.button(replace, "Relaunch Slot", self.relaunch_slot_from_gui, compact=True).pack(side="left", padx=(0, 8))
        self.button(replace, "Replace Runner", self.replace_from_gui, primary=True, compact=True).pack(side="left")

        self.update_mode()

    def _build_wizard(self, parent: tk.Frame) -> None:
        intro = self.panel(parent, "Setup Wizard")
        tk.Label(
            intro,
            text="Use this page to set up a new machine or re-check the app before sharing it with someone else.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            wraplength=980,
        ).pack(fill="x", padx=16, pady=(0, 8))
        top = tk.Frame(intro, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(0, 14))
        self.button(top, "Refresh Checks", self.refresh_wizard_checks, primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(top, "Open Setup Guide", self.open_setup_guide, compact=True).pack(side="left", padx=8)
        self.button(top, "Copy Diagnostics", self.copy_diagnostics, compact=True).pack(side="left", padx=8)
        tk.Label(top, textvariable=self.wizard_status_var, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(12, 0))

        checks = self.panel(parent, "1. Install Check")
        self.wizard_checks_frame = tk.Frame(checks, bg=PANEL)
        self.wizard_checks_frame.pack(fill="x", padx=16, pady=(0, 14))

        obs_panel = self.panel(parent, "2. OBS WebSocket")
        tk.Label(
            obs_panel,
            text="Enter host, port, and password in Settings, then test the connection.",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 8))
        obs_actions = tk.Frame(obs_panel, bg=PANEL)
        obs_actions.pack(fill="x", padx=16, pady=(0, 14))
        self.button(obs_actions, "Go to Settings", lambda: self.show_page("Settings"), compact=True).pack(side="left", padx=(0, 8))
        self.button(obs_actions, "Test OBS", self.test_obs_connection, primary=True, compact=True).pack(side="left", padx=8)

        layout_panel = self.panel(parent, "3. OBS Layout")
        tk.Label(
            layout_panel,
            text="Choose the fast included template path, or draw your own custom layout.",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 8))
        layout_actions = tk.Frame(layout_panel, bg=PANEL)
        layout_actions.pack(fill="x", padx=16, pady=(0, 14))
        self.button(layout_actions, "Template Setup", lambda: self.show_page("Template Setup"), primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(layout_actions, "Custom OBS Layout", lambda: self.show_page("Custom OBS Layout"), compact=True).pack(side="left", padx=8)
        self.button(layout_actions, "Scan OBS", self.scan_obs_builder, compact=True).pack(side="left", padx=8)

        audio_panel = self.panel(parent, "4. Audio")
        tk.Label(
            audio_panel,
            text="Launch runner VLC windows first, then map runner audio. Do not mute VLC. If you do not want to hear VLC locally, route VLC to an unused output device in Windows Volume Mixer.",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            wraplength=980,
        ).pack(fill="x", padx=16, pady=(0, 8))
        audio_actions = tk.Frame(audio_panel, bg=PANEL)
        audio_actions.pack(fill="x", padx=16, pady=(0, 14))
        self.button(audio_actions, "Go to Audio", lambda: self.show_page("Audio"), primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(audio_actions, "Open Volume Mixer", open_windows_volume_mixer, compact=True).pack(side="left", padx=8)

        race_panel = self.panel(parent, "5. First Race Test")
        tk.Label(
            race_panel,
            text="Pick a 2P or 4P race, launch streams, take screenshots, crop one runner, then use the Checklist before going live.",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            wraplength=980,
        ).pack(fill="x", padx=16, pady=(0, 8))
        race_actions = tk.Frame(race_panel, bg=PANEL)
        race_actions.pack(fill="x", padx=16, pady=(0, 14))
        self.button(race_actions, "Go to Setup", lambda: self.show_page("Setup"), primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(race_actions, "Take Screenshots", self.take_screenshots, compact=True).pack(side="left", padx=8)
        self.button(race_actions, "Go to Cropping", lambda: self.show_page("Cropping"), compact=True).pack(side="left", padx=8)
        self.button(race_actions, "Go to Sync", lambda: self.show_page("Sync"), compact=True).pack(side="left", padx=8)
        self.button(race_actions, "Open Checklist", lambda: self.show_page("Checklist"), compact=True).pack(side="left", padx=8)

        finish_panel = self.panel(parent, "6. Finish")
        tk.Label(
            finish_panel,
            text="When checks are clean, create a Start Menu shortcut and use Checklist as your event-day home base.",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 8))
        finish_actions = tk.Frame(finish_panel, bg=PANEL)
        finish_actions.pack(fill="x", padx=16, pady=(0, 14))
        self.button(finish_actions, "Create Start Menu Shortcut", self.create_start_menu_shortcut, compact=True).pack(side="left", padx=(0, 8))
        self.button(finish_actions, "Refresh Checklist", self.wizard_refresh_checklist, compact=True).pack(side="left", padx=8)

        self.refresh_wizard_checks(include_obs=False)

    def _build_cropping(self, parent: tk.Frame) -> None:
        self.crop_panel = cropping_tool.CropPanel(parent)
        self.crop_panel.pack(fill="both", expand=True)

    def _build_sync(self, parent: tk.Frame) -> None:
        self.sync_panel = stream_syncer.SyncPanel(parent)
        self.sync_panel.pack(fill="both", expand=True)

    def _build_audio_panel(self, parent: tk.Frame) -> None:
        help_panel = self.panel(parent, "VLC Listening Setup")
        tk.Label(
            help_panel,
            text="Leave VLC unmuted so OBS can capture it. To stop hearing runner audio in your speakers/headphones, open Windows Volume Mixer and set VLC media player to an unused output device such as a monitor, unused headset, or virtual cable.",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=1100,
        ).pack(fill="x", padx=16, pady=(4, 8))
        help_actions = tk.Frame(help_panel, bg=PANEL)
        help_actions.pack(fill="x", padx=16, pady=(0, 14))
        self.button(help_actions, "Open Volume Mixer", open_windows_volume_mixer, primary=True, compact=True).pack(side="left", padx=(0, 8))

        p = self.panel(parent, "OBS Audio")
        top = tk.Frame(p, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(4, 8))
        self.button(top, "Refresh Audio", self.refresh_audio_controls, primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(top, "Mute All", lambda: self.set_all_audio_mute(True), compact=True).pack(side="left", padx=8)
        self.button(top, "Unmute All", lambda: self.set_all_audio_mute(False), compact=True).pack(side="left", padx=8)
        tk.Label(top, textvariable=self.audio_status_var, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(12, 0))

        header = tk.Frame(p, bg=PANEL)
        header.pack(fill="x", padx=16, pady=(0, 2))
        tk.Label(header, text="OBS input", bg=PANEL, fg=MUTED, anchor="w", width=36).grid(row=0, column=0, sticky="w", padx=(0, 8))
        tk.Label(header, text="Mute", bg=PANEL, fg=MUTED, anchor="w", width=10).grid(row=0, column=1, sticky="w", padx=(0, 8))
        tk.Label(header, text="Volume", bg=PANEL, fg=MUTED, anchor="w").grid(row=0, column=2, sticky="w")
        header.columnconfigure(2, weight=1)

        self.audio_rows_frame = tk.Frame(p, bg=PANEL)
        self.audio_rows_frame.pack(fill="x", padx=16, pady=(0, 14))

        mapper = self.panel(parent, "Audio Source Mapper")
        mapper_top = tk.Frame(mapper, bg=PANEL)
        mapper_top.pack(fill="x", padx=16, pady=(4, 8))
        tk.Label(mapper_top, text="Layout", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        audio_layout_combo = ttk.Combobox(mapper_top, textvariable=self.audio_mapper_layout_var, values=["Current", "2P", "4P", "Both"], state="readonly", width=10)
        audio_layout_combo.pack(side="left", padx=(0, 8), ipady=5)
        self.button(mapper_top, "Load Audio Windows", self.load_audio_mapper, primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(mapper_top, "Apply Audio Mapping", self.apply_audio_mapper, compact=True).pack(side="left", padx=8)
        tk.Label(mapper_top, textvariable=self.audio_mapper_status_var, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(12, 0))

        tk.Label(
            mapper,
            text="Map each runner audio source to the matching VLC window. Created audio sources stay muted until you unmute them.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(0, 8))

        mapper_header = tk.Frame(mapper, bg=PANEL)
        mapper_header.pack(fill="x", padx=16, pady=(0, 2))
        tk.Label(mapper_header, text="Source", bg=PANEL, fg=MUTED, anchor="w", width=18).grid(row=0, column=0, sticky="w", padx=(0, 8))
        tk.Label(mapper_header, text="Window / device", bg=PANEL, fg=MUTED, anchor="w").grid(row=0, column=1, sticky="w", padx=(0, 8))
        tk.Label(mapper_header, text="Priority", bg=PANEL, fg=MUTED, anchor="w", width=28).grid(row=0, column=2, sticky="w", padx=(0, 8))
        mapper_header.columnconfigure(1, weight=1)

        self.audio_mapper_frame = tk.Frame(mapper, bg=PANEL)
        self.audio_mapper_frame.pack(fill="x", padx=16, pady=(0, 14))

    def _build_obs_builder(self, parent: tk.Frame) -> None:
        p = self.panel(parent, "Template Setup")

        top = tk.Frame(p, bg=PANEL)
        top.pack(fill="x", padx=16, pady=(4, 8))
        tk.Label(top, text="Layout", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        layout_combo = ttk.Combobox(top, textvariable=self.builder_layout_var, values=["Both", "2P", "4P"], state="readonly", width=10)
        layout_combo.pack(side="left", padx=(0, 10), ipady=5)
        self.button(top, "Scan OBS", self.scan_obs_builder, primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(top, "Create Missing Defaults", self.create_missing_obs_sources, compact=True).pack(side="left", padx=8)
        self.button(top, "Reset To Default Template", self.reset_to_default_template, compact=True, danger=True).pack(side="left", padx=8)
        tk.Label(top, textvariable=self.builder_status_var, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(12, 0))

        tk.Label(
            p,
            text="Quick setup for the included Restream Control template. Create Missing Defaults adds only what is missing; Reset intentionally moves template items back to the default layout.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=16, pady=(0, 8))

        result_frame = tk.Frame(p, bg=INPUT_BG)
        result_frame.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        result_scroll = ttk.Scrollbar(result_frame, orient="vertical")
        result_scroll.pack(side="right", fill="y")
        self.builder_text = tk.Text(
            result_frame,
            height=28,
            bg=INPUT_BG,
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
            wrap="word",
            yscrollcommand=result_scroll.set,
        )
        self.builder_text.pack(side="left", fill="both", expand=True)
        result_scroll.configure(command=self.builder_text.yview)
        self.set_builder_text(
            "Template Setup\n\n"
            "1. Open OBS and enable WebSocket.\n"
            "2. Click Scan OBS.\n"
            "3. Create Missing Defaults if you want the included Restream Control scenes and source names.\n\n"
            "Create Missing Defaults is safe for existing scenes. Reset To Default Template is for rebuilding the included template positions."
        )

    def _build_layout_designer(self, parent: tk.Frame) -> None:
        top = tk.Frame(parent, bg=BG)
        top.pack(fill="x", pady=(2, 6))

        core_tools = tk.Frame(top, bg=BG)
        core_tools.pack(side="left")

        tk.Label(core_tools, text="Layout", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        ttk.Combobox(core_tools, textvariable=self.layout_mode_var, values=["2P", "4P"], state="readonly", width=8).pack(side="left", padx=(0, 10), ipady=5)
        tk.Label(core_tools, text="Runner", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(4, 8))
        layout_slot_combo = ttk.Combobox(core_tools, textvariable=self.layout_slot_var, values=["R1", "R2", "R3", "R4"], state="readonly", width=8)
        layout_slot_combo.pack(side="left", padx=(0, 10), ipady=5)
        layout_slot_combo.bind("<<ComboboxSelected>>", self.on_layout_slot_changed)
        tk.Label(core_tools, text="Region", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(4, 8))
        ttk.Combobox(
            core_tools,
            textvariable=self.layout_region_type_var,
            values=LAYOUT_REGION_TYPES,
            state="readonly",
            width=16,
        ).pack(side="left", padx=(0, 12), ipady=5)

        image_tools = tk.Frame(top, bg=BG)
        image_tools.pack(side="right")
        tk.Label(image_tools, text="Layout Image", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        self.button(image_tools, "Load", self.load_layout_background, compact=True).pack(side="left", padx=(0, 8))
        self.button(image_tools, "Clear", self.clear_layout_background, compact=True).pack(side="left", padx=(0, 8))
        tk.Label(image_tools, text="Overlay layer", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        ttk.Combobox(
            image_tools,
            textvariable=self.layout_image_layer_var,
            values=["Overlay above feeds", "Behind feeds"],
            state="readonly",
            width=18,
        ).pack(side="left", padx=(0, 8), ipady=5)

        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill="x", pady=(0, 8))
        self.button(actions, "Apply to OBS", self.apply_current_designer_layout_to_obs, primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(actions, "Undo", self.undo_layout_change, compact=True).pack(side="left", padx=(0, 8))

        copy_tools = tk.Frame(actions, bg=BG)
        copy_tools.pack(side="right")
        tk.Label(copy_tools, text="Copy", bg=BG, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        ttk.Combobox(copy_tools, textvariable=self.layout_copy_from_var, values=["R1", "R2", "R3", "R4"], state="readonly", width=7).pack(side="left", padx=(0, 8), ipady=5)
        tk.Label(copy_tools, text="to", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left", padx=(0, 8))
        ttk.Combobox(copy_tools, textvariable=self.layout_copy_to_var, values=["R1", "R2", "R3", "R4"], state="readonly", width=7).pack(side="left", padx=(0, 8), ipady=5)
        tk.Label(copy_tools, text="Part", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(side="left", padx=(0, 8))
        ttk.Combobox(
            copy_tools,
            textvariable=self.layout_copy_part_var,
            values=["All", "Game", "Tracker", "Timer", "Facecam", "Runner Name"],
            state="readonly",
            width=14,
        ).pack(side="left", padx=(0, 8), ipady=5)
        self.button(copy_tools, "Copy Boxes", self.copy_runner_layout_regions, compact=True).pack(side="left", padx=(0, 8))

        tk.Label(
            parent,
            text="Draw one box for each runner part, text, or image area. Hold Shift and click boxes to select multiple; use arrow keys to nudge selected boxes. Click empty space to clear selection.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        self.layout_canvas = tk.Canvas(parent, bg=INPUT_BG, highlightbackground=BORDER, highlightthickness=1, bd=0)
        self.layout_canvas.pack(fill="both", expand=True)
        self.layout_canvas.bind("<Configure>", lambda _event: self.redraw_layout_designer())
        self.layout_canvas.bind("<ButtonPress-1>", self.layout_canvas_mouse_down)
        self.layout_canvas.bind("<B1-Motion>", self.layout_canvas_mouse_drag)
        self.layout_canvas.bind("<ButtonRelease-1>", self.layout_canvas_mouse_up)
        self.layout_canvas.bind("<Delete>", lambda _event: self.delete_selected_layout_region())
        self.layout_canvas.bind("<BackSpace>", lambda _event: self.delete_selected_layout_region())
        self.layout_canvas.bind("<Control-z>", lambda _event: self.undo_layout_change())
        self.layout_canvas.bind("<Left>", self.nudge_selected_layout_regions)
        self.layout_canvas.bind("<Right>", self.nudge_selected_layout_regions)
        self.layout_canvas.bind("<Up>", self.nudge_selected_layout_regions)
        self.layout_canvas.bind("<Down>", self.nudge_selected_layout_regions)

        bottom = tk.Frame(parent, bg=BG)
        bottom.pack(fill="x", pady=(8, 0))
        tk.Label(bottom, textvariable=self.layout_status_var, bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True)
        self.button(bottom, "Save Layout", self.save_layout_designer, compact=True).pack(side="right", padx=(8, 0))
        self.button(bottom, "Reload Saved Layout", self.load_layout_designer, compact=True).pack(side="right", padx=(8, 0))
        self.button(bottom, "Remove Unused Sources", self.remove_unused_layout_sources, compact=True, danger=True).pack(side="right", padx=(8, 0))
        self.button(bottom, "Clear Boxes", self.clear_layout_regions, compact=True, danger=True).pack(side="right", padx=(8, 0))
        self.button(bottom, "Delete", self.delete_selected_layout_region, compact=True, danger=True).pack(side="right", padx=(8, 0))
        selected = tk.Frame(parent, bg=BG)
        selected.pack(fill="x", pady=(4, 0))
        tk.Label(selected, text="Selected:", bg=BG, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(selected, textvariable=self.layout_region_details_var, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(6, 0))

        text_tools = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        text_tools.pack(fill="x", pady=(6, 0))
        tk.Label(text_tools, text="Text Box", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(10, 8), pady=8)
        tk.Entry(text_tools, textvariable=self.layout_text_var, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat").pack(side="left", fill="x", expand=True, padx=(0, 8), pady=8, ipady=5)
        self.button(text_tools, "Update Text", self.update_selected_layout_text, compact=True).pack(side="left", padx=(0, 10), pady=8)
        self.button(text_tools, "Clear Text Boxes", self.clear_layout_text_regions, compact=True, danger=True).pack(side="left", padx=(0, 10), pady=8)

        image_tools = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        image_tools.pack(fill="x", pady=(6, 0))
        tk.Label(image_tools, text="Image", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(10, 8), pady=8)
        tk.Label(image_tools, text="Layer", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6), pady=8)
        image_layer_combo = ttk.Combobox(
            image_tools,
            textvariable=self.layout_image_region_layer_var,
            values=["Behind feeds", "Above feeds", "Above overlay"],
            state="readonly",
            width=14,
        )
        image_layer_combo.pack(side="left", padx=(0, 8), pady=8, ipady=5)
        image_layer_combo.bind("<<ComboboxSelected>>", self.update_selected_layout_image_layer)
        tk.Entry(image_tools, textvariable=self.layout_image_path_var, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat").pack(side="left", fill="x", expand=True, padx=(0, 8), pady=8, ipady=5)
        self.button(image_tools, "Choose Image", self.choose_layout_region_image, compact=True).pack(side="left", padx=(0, 8), pady=8)
        self.button(image_tools, "Update Image", self.update_selected_layout_image, compact=True).pack(side="left", padx=(0, 10), pady=8)

        self.load_layout_designer(show_status=False)

    def layout_canvas_bounds(self) -> tuple[float, float, float, float, float]:
        canvas = self.layout_canvas
        if canvas is None:
            return (0.0, 0.0, 1.0, 1.0, 1.0)
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        scale = min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT)
        draw_w = DESIGN_WIDTH * scale
        draw_h = DESIGN_HEIGHT * scale
        x0 = (width - draw_w) / 2
        y0 = (height - draw_h) / 2
        return x0, y0, draw_w, draw_h, scale

    def design_to_screen(self, x: float, y: float) -> tuple[float, float]:
        x0, y0, _draw_w, _draw_h, scale = self.layout_canvas_bounds()
        return x0 + x * scale, y0 + y * scale

    def screen_to_design(self, x: float, y: float) -> tuple[float, float]:
        x0, y0, _draw_w, _draw_h, scale = self.layout_canvas_bounds()
        dx = (x - x0) / scale
        dy = (y - y0) / scale
        return max(0.0, min(DESIGN_WIDTH, dx)), max(0.0, min(DESIGN_HEIGHT, dy))

    def on_layout_slot_changed(self, _event=None) -> None:
        self.layout_region_type_var.set("Game")
        self.layout_status_var.set(f"Runner {self.layout_slot_var.get()} selected. Region reset to Game.")

    def layout_region_hit(self, x: float, y: float) -> tuple[Optional[dict[str, Any]], str]:
        for region in reversed(self.layout_regions):
            rx = float(region.get("x", 0))
            ry = float(region.get("y", 0))
            rw = float(region.get("w", 0))
            rh = float(region.get("h", 0))
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                near_right = abs(x - (rx + rw)) <= 18
                near_bottom = abs(y - (ry + rh)) <= 18
                return region, "resize" if near_right and near_bottom else "move"
        return None, "draw"

    def push_layout_undo(self) -> None:
        snapshot = {
            "regions": copy.deepcopy(self.layout_regions),
            "selected_id": self.layout_selected_id,
            "selected_ids": sorted(self.layout_selected_ids),
            "background": self.layout_bg_path,
            "layout_image_layer": self.layout_image_layer_var.get(),
            "mode": self.layout_mode_var.get(),
        }
        self.layout_undo_stack.append(snapshot)
        if len(self.layout_undo_stack) > 30:
            self.layout_undo_stack.pop(0)

    def undo_layout_change(self) -> None:
        if not self.layout_undo_stack:
            self.layout_status_var.set("Nothing to undo.")
            return
        snapshot = self.layout_undo_stack.pop()
        self.layout_regions = [self.normalize_layout_region(region) for region in snapshot.get("regions", []) if isinstance(region, dict)]
        self.layout_selected_id = snapshot.get("selected_id")
        self.layout_selected_ids = {str(value) for value in snapshot.get("selected_ids", []) if value}
        if self.layout_selected_id:
            self.layout_selected_ids.add(str(self.layout_selected_id))
        self.layout_mode_var.set(str(snapshot.get("mode") or self.layout_mode_var.get()))
        self.layout_image_layer_var.set(str(snapshot.get("layout_image_layer") or "Overlay above feeds"))
        self.set_layout_image_path(str(snapshot.get("background", "") or ""))
        self.load_layout_region_settings(None)
        self.layout_status_var.set("Undid last custom layout change.")
        self.redraw_layout_designer()

    def set_layout_image_path(self, path: str) -> None:
        self.layout_bg_path = path
        self.layout_bg_source = None
        self.layout_bg_photo = None
        if path and Path(path).exists():
            try:
                self.layout_bg_source = Image.open(path).convert("RGBA")
                self.layout_image_label_var.set(Path(path).name)
                return
            except Exception:
                self.layout_image_label_var.set("Layout image missing")
                return
        self.layout_image_label_var.set("No layout image loaded")

    def next_layout_text_index(self, layout: str) -> Optional[int]:
        layout = app_state.normalize_layout(layout)
        used: set[int] = set()
        for region in self.layout_regions:
            if app_state.normalize_layout(region.get("layout", layout)) != layout:
                continue
            if str(region.get("type", "")) != "Text":
                continue
            try:
                used.add(int(region.get("text_index", 0)))
            except Exception:
                pass
        for index in range(1, MAX_EXTRA_TEXT_REGIONS + 1):
            if index not in used:
                return index
        return None

    def next_layout_image_index(self, layout: str) -> int:
        layout = app_state.normalize_layout(layout)
        used: set[int] = set()
        for region in self.layout_regions:
            if app_state.normalize_layout(region.get("layout", layout)) != layout:
                continue
            if str(region.get("type", "")) != "Image":
                continue
            try:
                used.add(int(region.get("image_index", 0)))
            except Exception:
                match = re.search(r"\bImage\s+([0-9]+)$", str(region.get("source", "")))
                if match:
                    used.add(int(match.group(1)))
        index = 1
        while index in used:
            index += 1
        return index

    def make_layout_region(self, x: float, y: float) -> dict[str, Any]:
        region_type = self.layout_region_type_var.get().strip() or "Game"
        if region_type == "Camera":
            region_type = "Facecam"
        slot = "" if region_type == "Comms" else self.layout_slot_var.get().strip()
        text_index = self.next_layout_text_index(self.layout_mode_var.get()) if region_type == "Text" else None
        image_index = self.next_layout_image_index(self.layout_mode_var.get()) if region_type == "Image" else None
        region = {
            "type": region_type,
            "slot": slot,
            "layout": self.layout_mode_var.get(),
            "text_index": text_index,
            "image_index": image_index,
        }
        return {
            "id": f"region_{len(self.layout_regions) + 1}_{int(x)}_{int(y)}",
            "layout": self.layout_mode_var.get(),
            "slot": slot,
            "type": region_type,
            "x": x,
            "y": y,
            "w": 1.0,
            "h": 1.0,
            "source": self.default_designer_source_name(self.layout_mode_var.get(), region),
            "image_path": "",
            "text": f"Text {text_index}" if region_type == "Text" and text_index else "",
            "text_index": text_index,
            "image_index": image_index,
            "layer": self.layout_image_region_layer_var.get() if region_type == "Image" else "",
        }

    def unique_layout_region_key(self, region: dict[str, Any]) -> Optional[str]:
        region_type = str(region.get("type", "") or "").strip()
        if region_type == "Camera":
            region_type = "Facecam"
        layout = app_state.normalize_layout(region.get("layout", self.layout_mode_var.get()))
        slot = str(region.get("slot", "") or "").strip().upper()
        if region_type in {"Game", "Tracker", "Timer", "Facecam", "Runner Name"} and slot:
            return f"{layout}::{slot}::{region_type}"
        if region_type == "Comms":
            return f"{layout}::comms"
        return None

    def normalize_layout_region(self, region: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(region)
        if str(normalized.get("type", "")) == "Camera":
            normalized["type"] = "Facecam"
        source = str(normalized.get("source", "") or "")
        source = re.sub(r"\bCamera$", "Facecam", source)
        normalized["source"] = source
        if str(normalized.get("type", "")) == "Text" and not normalized.get("text_index"):
            match = re.search(r"\bText\s+([1-3])$", source)
            if match:
                normalized["text_index"] = int(match.group(1))
        if str(normalized.get("type", "")) == "Text":
            try:
                index = int(normalized.get("text_index", 0))
            except Exception:
                index = 0
            if index < 1 or index > MAX_EXTRA_TEXT_REGIONS:
                normalized["text_index"] = 1
        if str(normalized.get("type", "")) == "Image" and not normalized.get("image_index"):
            match = re.search(r"\bImage\s+([0-9]+)$", source)
            if match:
                normalized["image_index"] = int(match.group(1))
        if str(normalized.get("type", "")) == "Image":
            layer = str(normalized.get("layer", "") or "").strip()
            if layer not in {"Behind feeds", "Above feeds", "Above overlay"}:
                normalized["layer"] = "Above feeds"
        return normalized

    def existing_layout_region_for_key(self, key: Optional[str]) -> Optional[dict[str, Any]]:
        if not key:
            return None
        for region in self.layout_regions:
            if self.unique_layout_region_key(region) == key:
                return region
        return None

    def layout_region_by_id(self, region_id: str | None) -> Optional[dict[str, Any]]:
        if not region_id:
            return None
        for region in self.layout_regions:
            if str(region.get("id", "")) == region_id:
                return region
        return None

    def sync_layout_selected_ids(self) -> None:
        existing_ids = {str(region.get("id", "")) for region in self.layout_regions}
        self.layout_selected_ids = {region_id for region_id in self.layout_selected_ids if region_id in existing_ids}
        if self.layout_selected_id and self.layout_selected_id not in existing_ids:
            self.layout_selected_id = next(iter(self.layout_selected_ids), None)
        elif self.layout_selected_id:
            self.layout_selected_ids.add(self.layout_selected_id)

    def copy_runner_layout_regions(self) -> None:
        layout = app_state.normalize_layout(self.layout_mode_var.get())
        source_slot = self.layout_copy_from_var.get().strip().upper()
        target_slot = self.layout_copy_to_var.get().strip().upper()
        if source_slot == target_slot:
            self.layout_status_var.set("Choose two different runner slots.")
            return
        max_slot = 2 if layout == "2P" else 4
        try:
            source_num = int(source_slot.replace("R", ""))
            target_num = int(target_slot.replace("R", ""))
        except ValueError:
            self.layout_status_var.set("Choose valid runner slots.")
            return
        if source_num < 1 or source_num > max_slot or target_num < 1 or target_num > max_slot:
            self.layout_status_var.set(f"{layout} only uses R1 through R{max_slot}.")
            return

        allowed_copy_types = {"Game", "Tracker", "Timer", "Facecam", "Runner Name"}
        requested_part = self.layout_copy_part_var.get().strip() or "All"
        copy_types = allowed_copy_types if requested_part == "All" else {requested_part}
        copy_types = copy_types & allowed_copy_types
        if not copy_types:
            self.layout_status_var.set("Choose a valid runner part to copy.")
            return
        source_regions = [
            self.normalize_layout_region(region)
            for region in self.layout_regions
            if app_state.normalize_layout(region.get("layout", layout)) == layout
            and str(region.get("slot", "")).strip().upper() == source_slot
            and str(region.get("type", "")) in copy_types
        ]
        if not source_regions:
            self.layout_status_var.set(f"No {source_slot} runner boxes to copy.")
            return

        min_x = min(float(region.get("x", 0)) for region in source_regions)
        min_y = min(float(region.get("y", 0)) for region in source_regions)
        max_x = max(float(region.get("x", 0)) + float(region.get("w", 0)) for region in source_regions)
        max_y = max(float(region.get("y", 0)) + float(region.get("h", 0)) for region in source_regions)
        dx = 80.0
        dy = 80.0
        if max_x + dx > DESIGN_WIDTH:
            dx = max(0.0, DESIGN_WIDTH - max_x)
        if max_y + dy > DESIGN_HEIGHT:
            dy = max(0.0, DESIGN_HEIGHT - max_y)
        if dx == 0.0 and dy == 0.0:
            dx = -min(80.0, min_x)
            dy = -min(80.0, min_y)

        self.push_layout_undo()
        self.layout_regions = [
            region for region in self.layout_regions
            if not (
                app_state.normalize_layout(region.get("layout", layout)) == layout
                and str(region.get("slot", "")).strip().upper() == target_slot
                and str(region.get("type", "")) in copy_types
            )
        ]

        copied: list[dict[str, Any]] = []
        for index, region in enumerate(source_regions, start=1):
            new_region = copy.deepcopy(region)
            new_region["id"] = f"region_copy_{target_slot}_{int(time.time())}_{index}"
            new_region["layout"] = layout
            new_region["slot"] = target_slot
            new_region["x"] = max(0.0, min(float(region.get("x", 0)) + dx, DESIGN_WIDTH - float(region.get("w", 1))))
            new_region["y"] = max(0.0, min(float(region.get("y", 0)) + dy, DESIGN_HEIGHT - float(region.get("h", 1))))
            new_region["source"] = self.default_designer_source_name(layout, new_region)
            copied.append(new_region)

        self.layout_regions.extend(copied)
        self.layout_selected_id = copied[0]["id"] if copied else None
        self.layout_selected_ids = {str(region.get("id", "")) for region in copied}
        self.load_layout_region_settings(None)
        part_label = "all runner" if requested_part == "All" else requested_part
        self.layout_status_var.set(f"Copied {len(copied)} {part_label} box(es) from {source_slot} to {target_slot}. Drag them into place.")
        self.redraw_layout_designer()

    def layout_canvas_mouse_down(self, event) -> None:
        if self.layout_canvas is None:
            return
        self.layout_canvas.focus_set()
        x, y = self.screen_to_design(event.x, event.y)
        region, mode = self.layout_region_hit(x, y)
        shift_pressed = bool(event.state & 0x0001)

        if region is None and (shift_pressed or self.layout_selected_ids or self.layout_selected_id):
            self.layout_selected_id = None
            self.layout_selected_ids.clear()
            self.load_layout_region_settings(None)
            self.layout_status_var.set("Selection cleared.")
            self.redraw_layout_designer()
            return

        if region is None:
            region = self.make_layout_region(x, y)
            if str(region.get("type", "")) == "Text" and not region.get("text_index"):
                self.layout_status_var.set(f"Only {MAX_EXTRA_TEXT_REGIONS} extra text boxes are allowed.")
                return
            existing = self.existing_layout_region_for_key(self.unique_layout_region_key(region))
            if existing is not None:
                region = existing
                mode = "move"
                self.layout_status_var.set(f"{self.layout_region_label(region)} already exists. Selected it instead.")
            else:
                self.push_layout_undo()
                self.layout_regions.append(region)
                mode = "draw"
        elif mode in {"move", "resize"}:
            region_id = str(region.get("id", ""))
            if shift_pressed:
                if region_id in self.layout_selected_ids:
                    self.layout_selected_ids.remove(region_id)
                    if self.layout_selected_id == region_id:
                        self.layout_selected_id = next(iter(self.layout_selected_ids), None)
                else:
                    self.layout_selected_ids.add(region_id)
                    self.layout_selected_id = region_id
                self.load_layout_region_settings(self.layout_region_by_id(self.layout_selected_id))
                self.layout_status_var.set(f"Selected {len(self.layout_selected_ids)} box(es).")
                self.redraw_layout_designer()
                return
            self.push_layout_undo()
            if region_id not in self.layout_selected_ids or len(self.layout_selected_ids) <= 1 or mode == "resize":
                self.layout_selected_ids = {region_id}
        self.layout_selected_id = str(region.get("id", ""))
        self.layout_selected_ids.add(self.layout_selected_id)
        self.load_layout_region_settings(region)
        selected_regions = [
            selected for selected in (self.layout_region_by_id(region_id) for region_id in self.layout_selected_ids)
            if selected is not None
        ]
        group_bounds = None
        if selected_regions and mode == "move" and str(region.get("id", "")) in self.layout_selected_ids:
            min_x = min(float(selected.get("x", 0)) for selected in selected_regions)
            min_y = min(float(selected.get("y", 0)) for selected in selected_regions)
            max_x = max(float(selected.get("x", 0)) + float(selected.get("w", 0)) for selected in selected_regions)
            max_y = max(float(selected.get("y", 0)) + float(selected.get("h", 0)) for selected in selected_regions)
            group_bounds = {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y}
        self.layout_drag = {
            "mode": mode,
            "region": region,
            "start_x": x,
            "start_y": y,
            "orig_x": float(region.get("x", 0)),
            "orig_y": float(region.get("y", 0)),
            "orig_w": float(region.get("w", 0)),
            "orig_h": float(region.get("h", 0)),
            "selected_originals": {
                str(selected.get("id", "")): {"x": float(selected.get("x", 0)), "y": float(selected.get("y", 0))}
                for selected in selected_regions
            },
            "group_bounds": group_bounds,
        }
        self.redraw_layout_designer()

    def selected_layout_region(self) -> Optional[dict[str, Any]]:
        if not self.layout_selected_id:
            return None
        for region in self.layout_regions:
            if str(region.get("id", "")) == self.layout_selected_id:
                return region
        return None

    def load_layout_region_settings(self, region: Optional[dict[str, Any]] = None) -> None:
        region = region or self.selected_layout_region()
        if region is None:
            self.layout_source_name_var.set("")
            self.layout_image_path_var.set("")
            self.layout_image_region_layer_var.set("Above feeds")
            self.layout_text_var.set("")
            self.layout_region_details_var.set("Select a region.")
            return
        self.layout_source_name_var.set(str(region.get("source", "") or ""))
        self.layout_image_path_var.set(str(region.get("image_path", "") or ""))
        image_layer = str(region.get("layer", "") or "").strip()
        self.layout_image_region_layer_var.set(image_layer if image_layer in {"Behind feeds", "Above feeds", "Above overlay"} else "Above feeds")
        self.layout_text_var.set(str(region.get("text", "") or ""))
        self.layout_region_details_var.set(self.layout_region_label(region))

    def choose_layout_region_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose region image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.layout_image_path_var.set(path)
        self.update_selected_layout_region_settings()

    def update_selected_layout_region_settings(self) -> None:
        region = self.selected_layout_region()
        if region is None:
            self.layout_status_var.set("Select a region before updating settings.")
            return
        region["source"] = self.layout_source_name_var.get().strip()
        region["image_path"] = self.layout_image_path_var.get().strip()
        if str(region.get("type", "")) == "Image":
            region["layer"] = self.layout_image_region_layer_var.get().strip() or "Above feeds"
        region["text"] = self.layout_text_var.get().strip()
        if not region["source"]:
            region["source"] = self.default_designer_source_name(app_state.normalize_layout(region.get("layout", self.layout_mode_var.get())), region)
            self.layout_source_name_var.set(str(region["source"]))
        self.layout_status_var.set(f"Updated {self.layout_region_label(region)} settings.")
        self.redraw_layout_designer()

    def update_selected_layout_text(self) -> None:
        region = self.selected_layout_region()
        if region is None or str(region.get("type", "")) != "Text":
            self.layout_status_var.set("Select an extra text box before updating text.")
            return
        self.push_layout_undo()
        region["text"] = self.layout_text_var.get().strip()
        self.layout_status_var.set(f"Updated {self.layout_region_label(region)} text.")
        self.redraw_layout_designer()

    def update_selected_layout_image(self) -> None:
        region = self.selected_layout_region()
        if region is None or str(region.get("type", "")) != "Image":
            self.layout_status_var.set("Select an image box before updating the image.")
            return
        self.push_layout_undo()
        region["image_path"] = self.layout_image_path_var.get().strip()
        region["layer"] = self.layout_image_region_layer_var.get().strip() or "Above feeds"
        if not region.get("source"):
            region["source"] = self.default_designer_source_name(app_state.normalize_layout(region.get("layout", self.layout_mode_var.get())), region)
        self.layout_status_var.set(f"Updated {self.layout_region_label(region)} image.")
        self.redraw_layout_designer()

    def update_selected_layout_image_layer(self, _event=None) -> None:
        region = self.selected_layout_region()
        if region is None or str(region.get("type", "")) != "Image":
            return
        self.push_layout_undo()
        region["layer"] = self.layout_image_region_layer_var.get().strip() or "Above feeds"
        self.layout_status_var.set(f"{self.layout_region_label(region)} layer set to {region['layer']}.")
        self.redraw_layout_designer()

    def nudge_selected_layout_regions(self, event) -> str:
        self.sync_layout_selected_ids()
        if not self.layout_selected_ids:
            return "break"
        key = str(getattr(event, "keysym", ""))
        dx = -1.0 if key == "Left" else 1.0 if key == "Right" else 0.0
        dy = -1.0 if key == "Up" else 1.0 if key == "Down" else 0.0
        if dx == 0.0 and dy == 0.0:
            return "break"
        if getattr(event, "state", 0) & 0x0001:
            dx *= 10.0
            dy *= 10.0
        selected = [
            region for region in self.layout_regions
            if str(region.get("id", "")) in self.layout_selected_ids
        ]
        if not selected:
            return "break"
        self.push_layout_undo()
        for region in selected:
            width = float(region.get("w", 1))
            height = float(region.get("h", 1))
            region["x"] = max(0.0, min(float(region.get("x", 0)) + dx, DESIGN_WIDTH - width))
            region["y"] = max(0.0, min(float(region.get("y", 0)) + dy, DESIGN_HEIGHT - height))
        self.layout_status_var.set(f"Nudged {len(selected)} box(es). Hold Shift for 10 px.")
        self.redraw_layout_designer()
        return "break"

    def layout_canvas_mouse_drag(self, event) -> None:
        if not self.layout_drag:
            return
        x, y = self.screen_to_design(event.x, event.y)
        region = self.layout_drag["region"]
        mode = self.layout_drag["mode"]
        start_x = float(self.layout_drag["start_x"])
        start_y = float(self.layout_drag["start_y"])
        orig_x = float(self.layout_drag["orig_x"])
        orig_y = float(self.layout_drag["orig_y"])
        orig_w = float(self.layout_drag["orig_w"])
        orig_h = float(self.layout_drag["orig_h"])
        if mode == "draw":
            region["x"] = min(start_x, x)
            region["y"] = min(start_y, y)
            region["w"] = abs(x - start_x)
            region["h"] = abs(y - start_y)
        elif mode == "move":
            dx = x - start_x
            dy = y - start_y
            selected_originals = self.layout_drag.get("selected_originals", {})
            group_bounds = self.layout_drag.get("group_bounds")
            if selected_originals and group_bounds and len(selected_originals) > 1:
                dx = max(-float(group_bounds["min_x"]), min(DESIGN_WIDTH - float(group_bounds["max_x"]), dx))
                dy = max(-float(group_bounds["min_y"]), min(DESIGN_HEIGHT - float(group_bounds["max_y"]), dy))
                for region_id, original in selected_originals.items():
                    selected = self.layout_region_by_id(region_id)
                    if selected is None:
                        continue
                    selected["x"] = float(original["x"]) + dx
                    selected["y"] = float(original["y"]) + dy
            else:
                region["x"] = max(0.0, min(DESIGN_WIDTH - orig_w, orig_x + dx))
                region["y"] = max(0.0, min(DESIGN_HEIGHT - orig_h, orig_y + dy))
        elif mode == "resize":
            region["w"] = max(12.0, min(DESIGN_WIDTH - orig_x, orig_w + x - start_x))
            region["h"] = max(12.0, min(DESIGN_HEIGHT - orig_y, orig_h + y - start_y))
        self.redraw_layout_designer()

    def layout_canvas_mouse_up(self, _event) -> None:
        if self.layout_drag:
            region = self.layout_drag["region"]
            if float(region.get("w", 0)) < 12 or float(region.get("h", 0)) < 12:
                self.layout_regions = [r for r in self.layout_regions if r is not region]
                self.layout_selected_id = None
                self.layout_selected_ids.clear()
                self.load_layout_region_settings(None)
            else:
                label = self.layout_region_label(region)
                selected_count = len(self.layout_selected_ids)
                suffix = f" ({selected_count} selected)" if selected_count > 1 else ""
                self.layout_status_var.set(f"Selected {label}: {int(region['w'])}x{int(region['h'])} at {int(region['x'])},{int(region['y'])}.{suffix}")
        self.layout_drag = None
        self.redraw_layout_designer()

    def layout_region_label(self, region: dict[str, Any]) -> str:
        region_type = str(region.get("type", "Region"))
        if region_type == "Text":
            index = region.get("text_index")
            return f"Text {index}" if index else "Text"
        slot = str(region.get("slot", "")).strip()
        return f"{slot} {region_type}".strip()

    def default_designer_source_name(self, layout: str, region: dict[str, Any]) -> str:
        layout = app_state.normalize_layout(layout)
        region_type = str(region.get("type", "") or "").strip()
        slot = str(region.get("slot", "") or "").strip().upper()
        slot_match = re.match(r"^R([1-4])$", slot)
        slot_num = slot_match.group(1) if slot_match else ""
        if region_type == "Game" and slot_num:
            return f"{layout} R{slot_num} Stream"
        if region_type in {"Tracker", "Timer"} and slot_num:
            return f"{layout} R{slot_num} {region_type}"
        if region_type in {"Facecam", "Camera"} and slot_num:
            return f"{layout} R{slot_num} Facecam"
        if region_type == "Runner Name" and slot_num:
            return f"Runner {slot_num} Name"
        if region_type == "Comms":
            return "Comms Name"
        if region_type == "Image":
            index = region.get("image_index") or 1
            return f"{layout} Image {index}".strip()
        if region_type == "Text":
            index = region.get("text_index") or 1
            return f"{layout} Text {index}".strip()
        if region_type == "Camera":
            return f"{layout} {slot} Facecam".strip()
        if region_type == "Browser":
            return f"{layout} {slot} Browser".strip()
        return f"{layout} {region_type}".strip()

    def redraw_layout_designer(self) -> None:
        canvas = self.layout_canvas
        if canvas is None:
            return
        canvas.delete("all")
        x0, y0, draw_w, draw_h, scale = self.layout_canvas_bounds()
        canvas.create_rectangle(x0, y0, x0 + draw_w, y0 + draw_h, outline=BORDER, width=2, fill="#0d1012")

        if self.layout_bg_source is not None:
            bg = self.layout_bg_source.resize((max(1, int(draw_w)), max(1, int(draw_h))), Image.LANCZOS)
            self.layout_bg_photo = ImageTk.PhotoImage(bg)
            canvas.create_image(x0, y0, image=self.layout_bg_photo, anchor="nw")

        minor_grid = "#1a232d"
        major_grid = "#32404d"
        for col in range(1, 25):
            gx = x0 + (draw_w / 24) * col
            canvas.create_line(gx, y0, gx, y0 + draw_h, fill=major_grid if col % 4 == 0 else minor_grid)
        for row in range(1, 13):
            gy = y0 + (draw_h / 12) * row
            canvas.create_line(x0, gy, x0 + draw_w, gy, fill=major_grid if row % 3 == 0 else minor_grid)

        for region in self.layout_regions:
            sx, sy = self.design_to_screen(float(region.get("x", 0)), float(region.get("y", 0)))
            ex, ey = self.design_to_screen(float(region.get("x", 0)) + float(region.get("w", 0)), float(region.get("y", 0)) + float(region.get("h", 0)))
            color = LAYOUT_REGION_COLORS.get(str(region.get("type", "")), "#e5e7eb")
            region_id = str(region.get("id", ""))
            selected = region_id == self.layout_selected_id or region_id in self.layout_selected_ids
            canvas.create_rectangle(sx, sy, ex, ey, outline="white" if selected else color, width=3 if selected else 2)
            canvas.create_rectangle(sx, sy, ex, ey, fill=color, stipple="gray25", outline="")
            label = self.layout_region_label(region)
            canvas.create_text(sx + 8, sy + 8, text=label, fill="white", anchor="nw", font=("Segoe UI", max(9, int(12 * scale)), "bold"))
            if selected:
                canvas.create_rectangle(ex - 10, ey - 10, ex + 3, ey + 3, outline="white", fill=color)

    def load_layout_background(self) -> None:
        layout = app_state.normalize_layout(self.layout_mode_var.get())
        default_image = DEFAULT_LAYOUT_IMAGES.get(layout) or DEFAULT_LAYOUT_IMAGES["2P"]
        initial_dir = default_image.parent if default_image.exists() else REPO_ROOT
        initial_file = default_image.name if default_image.exists() else ""
        path = filedialog.askopenfilename(
            title="Choose layout image",
            initialdir=str(initial_dir),
            initialfile=initial_file,
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            self.push_layout_undo()
            self.set_layout_image_path(path)
            self.layout_image_label_var.set(Path(path).name)
            self.layout_status_var.set(f"Loaded layout image: {Path(path).name}")
            self.redraw_layout_designer()
        except Exception as exc:
            messagebox.showerror("Layout image failed", str(exc))

    def clear_layout_background(self) -> None:
        self.push_layout_undo()
        self.set_layout_image_path("")
        self.layout_status_var.set("Layout image cleared.")
        self.redraw_layout_designer()

    def delete_selected_layout_region(self) -> None:
        self.sync_layout_selected_ids()
        delete_ids = set(self.layout_selected_ids)
        if not delete_ids and self.layout_selected_id:
            delete_ids.add(self.layout_selected_id)
        if not delete_ids:
            self.layout_status_var.set("No region selected.")
            return
        self.push_layout_undo()
        before = len(self.layout_regions)
        self.layout_regions = [r for r in self.layout_regions if str(r.get("id", "")) not in delete_ids]
        self.layout_selected_id = None
        self.layout_selected_ids.clear()
        self.load_layout_region_settings(None)
        self.layout_status_var.set(f"Deleted {before - len(self.layout_regions)} region(s).")
        self.redraw_layout_designer()

    def clear_layout_regions(self) -> None:
        if not self.layout_regions:
            self.layout_status_var.set("No regions to clear.")
            return
        if not messagebox.askyesno("Clear regions", "Clear every drawn layout region?"):
            return
        self.push_layout_undo()
        self.layout_regions = []
        self.layout_selected_id = None
        self.layout_selected_ids.clear()
        self.load_layout_region_settings(None)
        self.layout_status_var.set("Cleared all regions.")
        self.redraw_layout_designer()

    def clear_layout_text_regions(self) -> None:
        layout = app_state.normalize_layout(self.layout_mode_var.get())
        text_regions = [
            region for region in self.layout_regions
            if app_state.normalize_layout(region.get("layout", layout)) == layout
            and str(region.get("type", "")) == "Text"
        ]
        if not text_regions:
            self.layout_status_var.set(f"No extra text boxes found for {layout}.")
            return
        if not messagebox.askyesno("Clear text boxes", f"Clear {len(text_regions)} extra text box(es) from the {layout} layout?"):
            return
        self.push_layout_undo()
        text_ids = {str(region.get("id", "")) for region in text_regions}
        self.layout_regions = [region for region in self.layout_regions if str(region.get("id", "")) not in text_ids]
        if self.layout_selected_id in text_ids:
            self.layout_selected_id = None
            self.layout_selected_ids.difference_update(text_ids)
            self.load_layout_region_settings(None)
        self.layout_status_var.set(f"Cleared {len(text_regions)} extra text box(es). Use Remove Unused Sources to remove them from OBS.")
        self.redraw_layout_designer()

    def save_layout_designer(self) -> None:
        data = self.current_layout_designer_data()
        app_state.save_json(LAYOUT_DESIGN_FILE, data)
        self.layout_status_var.set(f"Saved {len(self.layout_regions)} region(s) to {LAYOUT_DESIGN_FILE.name}.")

    def current_layout_designer_data(self) -> dict[str, Any]:
        return {
            "version": 1,
            "layout": self.layout_mode_var.get(),
            "background": self.layout_bg_path,
            "layout_image_layer": self.layout_image_layer_var.get(),
            "canvas": {"width": DESIGN_WIDTH, "height": DESIGN_HEIGHT},
            "regions": [self.normalize_layout_region(region) for region in self.layout_regions],
        }

    def load_layout_designer(self, show_status: bool = True) -> None:
        data = app_state.load_json(LAYOUT_DESIGN_FILE, {})
        if not isinstance(data, dict):
            data = {}
        if show_status:
            self.push_layout_undo()
        self.layout_mode_var.set(str(data.get("layout", self.layout_mode_var.get() or "4P")))
        self.layout_image_layer_var.set(str(data.get("layout_image_layer", "Overlay above feeds") or "Overlay above feeds"))
        regions = data.get("regions", [])
        self.layout_regions = [self.normalize_layout_region(r) for r in regions if isinstance(r, dict)]
        self.set_layout_image_path(str(data.get("background", "") or ""))
        self.layout_selected_id = None
        self.layout_selected_ids.clear()
        self.load_layout_region_settings(None)
        if show_status:
            self.layout_status_var.set(f"Loaded {len(self.layout_regions)} region(s).")
        self.redraw_layout_designer()

    def apply_current_designer_layout_to_obs(self) -> None:
        self.apply_designer_layout_to_obs(self.current_layout_designer_data(), [app_state.normalize_layout(self.layout_mode_var.get())], save_first=True)

    def desired_designer_scene_sources(self, data: dict[str, Any], layout: str) -> set[str]:
        layout = app_state.normalize_layout(layout)
        source_map = app_state.load_config().get("obs_source_map", {})
        if not isinstance(source_map, dict):
            source_map = {}
        data_layout = app_state.normalize_layout(data.get("layout", layout))
        regions = data.get("regions", [])
        if not isinstance(regions, list):
            regions = []
        desired: set[str] = set()
        for raw_region in regions:
            if not isinstance(raw_region, dict):
                continue
            region = self.normalize_layout_region(raw_region)
            if app_state.normalize_layout(region.get("layout", data_layout)) != layout:
                continue
            source = self.designer_source_name_for_region(layout, region)
            if source:
                desired.add(str(source_map.get(source, source)))
        background_path = str(data.get("background", "") or "")
        if background_path:
            image_layer = str(data.get("layout_image_layer", "Overlay above feeds") or "Overlay above feeds")
            desired.add("Background Image [placeholder]" if image_layer.lower().startswith("behind") else f"Background {layout}")
        return desired

    def cleanup_candidate_layout_sources(self, layout: str) -> set[str]:
        layout = app_state.normalize_layout(layout)
        slots = [1, 2] if layout == "2P" else [1, 2, 3, 4]
        candidates: set[str] = set()
        for slot in slots:
            candidates.update({
                f"{layout} R{slot} Stream",
                f"{layout} R{slot} Tracker",
                f"{layout} R{slot} Timer",
                f"{layout} R{slot} Facecam",
                f"Runner {slot} Name",
            })
        candidates.update({
            "Comms Name",
            f"Background {layout}",
            f"Background {layout} Outlines",
            "Background Image [placeholder]",
        })
        for index in range(1, MAX_EXTRA_TEXT_REGIONS + 1):
            candidates.add(f"{layout} Text {index}")
        return candidates

    def remove_unused_layout_sources(self) -> None:
        data = self.current_layout_designer_data()
        layout = app_state.normalize_layout(self.layout_mode_var.get())
        desired = self.desired_designer_scene_sources(data, layout)
        if not desired and not str(data.get("background", "") or ""):
            messagebox.showinfo("Remove unused sources", "Draw at least one layout box or load a layout image first. Cleanup compares OBS against the current layout.")
            return
        if not self.save_obs_settings():
            return
        scene_name = f"{layout} Restream"
        try:
            client = obs_crop_service.connect()
            scene_items = self.scene_item_map(client, scene_name)
        except Exception as exc:
            self.layout_status_var.set(f"Cleanup failed: {exc}")
            self.log_status(f"OBS Layout cleanup failed: {exc}")
            return
        if not scene_items:
            messagebox.showinfo("Remove unused sources", f"No scene items found in {scene_name}.")
            return

        candidates = self.cleanup_candidate_layout_sources(layout)
        removable = sorted(name for name in scene_items if name in candidates and name not in desired)
        if not removable:
            self.layout_status_var.set("No unused Restream Control scene items found.")
            messagebox.showinfo("Remove unused sources", "No unused Restream Control scene items found for the current layout.")
            return

        preview = "\n".join(f"- {name}" for name in removable[:25])
        if len(removable) > 25:
            preview += f"\n...and {len(removable) - 25} more"
        message = (
            f"Remove these unused Restream Control scene items from {scene_name}?\n\n"
            f"{preview}\n\n"
            "This removes them from this OBS scene only. It does not delete random OBS sources, and it does not delete shared inputs globally."
        )
        if not messagebox.askyesno("Remove unused sources", message):
            return

        removed = 0
        failed: list[str] = []
        for source_name in removable:
            item_id = scene_items.get(source_name)
            if item_id is None:
                continue
            try:
                client.remove_scene_item(scene_name, item_id)
                removed += 1
            except Exception as exc:
                failed.append(f"{source_name}: {exc}")
        if failed:
            messagebox.showwarning("Remove unused sources", "Some sources could not be removed:\n\n" + "\n".join(failed[:8]))
        self.layout_status_var.set(f"Removed {removed} unused scene item(s) from {scene_name}.")
        self.log_status(f"OBS Layout cleanup removed {removed} unused scene item(s) from {scene_name}.")

    def apply_saved_designer_layout_to_obs(self) -> None:
        data = app_state.load_json(LAYOUT_DESIGN_FILE, {})
        if not isinstance(data, dict) or (not data.get("regions") and not data.get("background")):
            messagebox.showinfo("Custom OBS Layout", "No saved custom layout found. Open Custom OBS Layout, draw regions or load a layout image, then save the layout.")
            return
        self.apply_designer_layout_to_obs(data, self.selected_builder_layouts(), save_first=False)

    def designer_source_name_for_region(self, layout: str, region: dict[str, Any]) -> Optional[str]:
        explicit_source = str(region.get("source", "") or "").strip()
        if explicit_source:
            return explicit_source
        return self.default_designer_source_name(layout, region) or None

    def designer_transform_from_region(self, region: dict[str, Any]) -> dict[str, Any]:
        x = max(0.0, min(float(region.get("x", 0.0)), float(DESIGN_WIDTH - 1)))
        y = max(0.0, min(float(region.get("y", 0.0)), float(DESIGN_HEIGHT - 1)))
        w = max(1.0, min(float(region.get("w", 1.0)), float(DESIGN_WIDTH) - x))
        h = max(1.0, min(float(region.get("h", 1.0)), float(DESIGN_HEIGHT) - y))
        region_type = str(region.get("type", "") or "")
        bounds_type = "OBS_BOUNDS_SCALE_INNER" if region_type in {"Runner Name", "Comms", "Text"} else "OBS_BOUNDS_STRETCH"
        return {
            "alignment": 5,
            "positionX": x,
            "positionY": y,
            "rotation": 0.0,
            "scaleX": 1.0,
            "scaleY": 1.0,
            "cropLeft": 0,
            "cropTop": 0,
            "cropRight": 0,
            "cropBottom": 0,
            "boundsType": bounds_type,
            "boundsAlignment": 0,
            "boundsWidth": w,
            "boundsHeight": h,
        }

    def create_designer_source_if_missing(
        self,
        client: Any,
        scene_name: str,
        source_name: str,
        region: dict[str, Any],
        source_names: set[str],
        scene_items: dict[str, int],
        template: dict[str, Any],
        supported_kinds: set[str] | None,
    ) -> tuple[Optional[int], str]:
        item_id = scene_items.get(source_name)
        if item_id is not None:
            self.update_designer_input_settings(client, source_name, region)
            return item_id, "EXISTING"

        if source_name not in source_names:
            try:
                source_template = self.template_source(template, source_name)
                source_kind = str(source_template.get("id", ""))
                settings = self.builder_input_settings(source_template)
                settings.update(self.designer_input_settings(region, source_name))
            except KeyError:
                custom = self.designer_custom_input(region, source_name, supported_kinds)
                if custom is None:
                    return None, "MISSING_TEMPLATE"
                source_kind, settings = custom
            if source_kind in {"scene", "group"}:
                return None, "CONTAINER"
            source_kind = self.resolve_builder_input_kind(client, source_kind, supported_kinds)
            response = client.create_input(scene_name, source_name, source_kind, settings, True)
            item_id = self.get_scene_item_id_value(response)
            source_names.add(source_name)
            scene_items[source_name] = item_id
            self.update_designer_input_settings(client, source_name, region)
            return item_id, "CREATE"

        response = client.create_scene_item(scene_name, source_name, True)
        item_id = self.get_scene_item_id_value(response)
        scene_items[source_name] = item_id
        self.update_designer_input_settings(client, source_name, region)
        return item_id, "ADD"

    def designer_custom_input(self, region: dict[str, Any], source_name: str, supported_kinds: set[str] | None) -> Optional[tuple[str, dict[str, Any]]]:
        region_type = str(region.get("type", "") or "")
        if region_type == "Image":
            path = str(region.get("image_path", "") or "").strip()
            if not path:
                return None
            return self.resolve_builder_input_kind(None, "image_source", supported_kinds), {"file": path}
        if region_type == "Text":
            text = str(region.get("text", "") or "").strip() or source_name
            return self.resolve_builder_input_kind(None, "text_gdiplus", supported_kinds), {
                "read_from_file": False,
                "text": text,
                "font": {"face": "Impact", "style": "Regular", "size": 72, "flags": 0},
                "outline": True,
                "outline_color": 4278190080,
                "outline_size": 8,
            }
        if region_type == "Browser":
            if supported_kinds and "browser_source" not in supported_kinds:
                return None
            return "browser_source", {
                "url": str(region.get("url", "") or "about:blank"),
                "width": max(1, int(float(region.get("w", 1280)))),
                "height": max(1, int(float(region.get("h", 720)))),
            }
        if region_type in {"Facecam", "Camera"}:
            slot = str(region.get("slot", "") or "").strip().upper()
            match = re.match(r"^R([1-4])$", slot)
            if not match:
                return None
            return self.resolve_builder_input_kind(None, "window_capture", supported_kinds), {
                "cursor": False,
                "method": 2,
                "client_area": False,
                "window": f"RUNNER {match.group(1)} - VLC media player:Qt5QWindowIcon:vlc.exe",
                "priority": 1,
            }
        return None

    def designer_input_settings(self, region: dict[str, Any], source_name: str) -> dict[str, Any]:
        region_type = str(region.get("type", "") or "")
        settings: dict[str, Any] = {}
        if region_type == "Image":
            path = str(region.get("image_path", "") or "").strip()
            if path:
                settings = {"file": path}
        elif region_type == "Text":
            settings = {
                "read_from_file": False,
                "text": str(region.get("text", "") or "").strip() or source_name,
            }
        elif region_type == "Browser":
            settings = {
                "width": max(1, int(float(region.get("w", 1280)))),
                "height": max(1, int(float(region.get("h", 720)))),
            }
            url = str(region.get("url", "") or "").strip()
            if url:
                settings["url"] = url
        elif region_type in {"Facecam", "Camera"}:
            slot = str(region.get("slot", "") or "").strip().upper()
            match = re.match(r"^R([1-4])$", slot)
            if match:
                settings = {
                    "cursor": False,
                    "method": 2,
                    "client_area": False,
                    "window": f"RUNNER {match.group(1)} - VLC media player:Qt5QWindowIcon:vlc.exe",
                    "priority": 1,
                }
        return settings

    def update_designer_input_settings(self, client: Any, source_name: str, region: dict[str, Any]) -> None:
        settings = self.designer_input_settings(region, source_name)
        if settings:
            try:
                client.set_input_settings(source_name, settings, True)
            except Exception:
                pass

    def apply_designer_background_to_obs(
        self,
        client: Any,
        scene_name: str,
        layout: str,
        background_path: str,
        image_layer: str,
        source_names: set[str],
        scene_items: dict[str, int],
        template: dict[str, Any],
        supported_kinds: set[str] | None,
    ) -> tuple[str, bool]:
        if not background_path:
            return "SKIP    no layout image selected", False
        if not Path(background_path).exists():
            return f"SKIP    layout image not found: {background_path}", False
        layer_is_behind = str(image_layer or "").lower().startswith("behind")
        source_name = "Background Image [placeholder]" if layer_is_behind else f"Background {app_state.normalize_layout(layout)}"
        region = {
            "type": "Image",
            "source": source_name,
            "image_path": background_path,
            "x": 0,
            "y": 0,
            "w": DESIGN_WIDTH,
            "h": DESIGN_HEIGHT,
        }
        item_id, status = self.create_designer_source_if_missing(
            client,
            scene_name,
            source_name,
            region,
            source_names,
            scene_items,
            template,
            supported_kinds,
        )
        if item_id is None:
            return f"SKIP    layout image: could not create {source_name} ({status})", False
        client.set_scene_item_transform(scene_name, item_id, self.designer_transform_from_region(region))
        try:
            client.set_scene_item_enabled(scene_name, item_id, True)
        except Exception:
            pass
        label = "layout image behind feeds" if layer_is_behind else "layout image overlay"
        return f"{status:<8} {label} -> {source_name}", status == "CREATE"

    def designer_layer_order_names(self, layout: str, regions: list[dict[str, Any]]) -> list[str]:
        layout = app_state.normalize_layout(layout)
        slots = [1, 2] if layout == "2P" else [1, 2, 3, 4]
        ordered: list[str] = ["Background Image [placeholder]"]

        def region_source_names(region_types: set[str], layer: str | None = None) -> list[str]:
            names: list[str] = []
            for raw_region in regions:
                region = self.normalize_layout_region(raw_region)
                region_type = str(region.get("type", "") or "")
                if region_type not in region_types:
                    continue
                if layer is not None and str(region.get("layer", "Above feeds") or "Above feeds") != layer:
                    continue
                source = self.designer_source_name_for_region(layout, region)
                if source:
                    names.append(source)
            return names

        ordered.extend(region_source_names({"Image", "Browser"}, "Behind feeds"))
        for slot in slots:
            for part in ["Stream", "Tracker", "Timer", "Facecam"]:
                ordered.append(f"{layout} R{slot} {part}")
        ordered.extend(region_source_names({"Image", "Browser"}, "Above feeds"))
        ordered.extend([f"Background {layout}", f"Background {layout} Outlines"])
        ordered.extend(region_source_names({"Image", "Browser"}, "Above overlay"))
        for slot in slots:
            ordered.append(f"Runner {slot} Name")
        ordered.append("Comms Name")
        ordered.extend(region_source_names({"Text"}))
        seen: set[str] = set()
        unique: list[str] = []
        for name in ordered:
            if name and name not in seen:
                unique.append(name)
                seen.add(name)
        return unique

    def mapped_designer_layer_order_names(self, ordered_names: list[str], source_map: dict[str, Any]) -> list[str]:
        return [str(source_map.get(name, name)) for name in ordered_names]

    def apply_designer_layout_to_obs(self, data: dict[str, Any], layouts: list[str], save_first: bool = False) -> None:
        if save_first:
            app_state.save_json(LAYOUT_DESIGN_FILE, data)
        regions = data.get("regions", [])
        background_path = str(data.get("background", "") or "")
        image_layer = str(data.get("layout_image_layer", "Overlay above feeds") or "Overlay above feeds")
        if not isinstance(regions, list):
            regions = []
        regions = [self.normalize_layout_region(region) for region in regions if isinstance(region, dict)]
        if not regions and not background_path:
            messagebox.showinfo("OBS Layout", "There are no layout regions or layout image to apply.")
            return
        layouts = [app_state.normalize_layout(layout) for layout in layouts]
        message = (
            "Apply the saved designer rectangles to OBS?\n\n"
            "This creates missing Restream Control scenes/sources when possible, then moves and resizes them. It does not delete sources or change audio."
        )
        if not messagebox.askyesno("Apply OBS Layout", message):
            return
        if not self.save_obs_settings():
            return

        try:
            client = obs_crop_service.connect()
            template = self.load_obs_template()
            supported_kinds = self.supported_obs_input_kinds(client)
            snapshot = self.scan_obs_snapshot(client)
        except Exception as exc:
            self.builder_status_var.set(f"OBS Layout apply failed: {exc}")
            self.layout_status_var.set(f"OBS apply failed: {exc}")
            self.log_status(f"OBS Layout apply failed: {exc}")
            return

        source_map = app_state.load_config().get("obs_source_map", {})
        if not isinstance(source_map, dict):
            source_map = {}

        lines = ["Apply OBS Layout", ""]
        applied = 0
        added = 0
        created = 0
        skipped = 0
        failed = 0
        data_layout = app_state.normalize_layout(data.get("layout"))
        scene_names = set(snapshot["scenes"])
        source_names = set(snapshot["all_sources"])

        for layout in layouts:
            scene_name = f"{layout} Restream"
            lines.append(f"{layout} layout")
            lines.append("-" * 40)
            if scene_name not in scene_names:
                try:
                    client.create_scene(scene_name)
                    scene_names.add(scene_name)
                    source_names.add(scene_name)
                    created += 1
                    lines.append(f"CREATE  {scene_name}")
                except Exception as exc:
                    failed += 1
                    lines.append(f"FAILED  {scene_name}: {exc}")
                    lines.append("")
                    continue

            scene_items = self.scene_item_map(client, scene_name)
            background_line, background_created = self.apply_designer_background_to_obs(
                client,
                scene_name,
                layout,
                str(data.get("background", "") or ""),
                image_layer,
                source_names,
                scene_items,
                template,
                supported_kinds,
            )
            lines.append(background_line)
            if background_created:
                created += 1
            layout_regions = [
                region for region in regions
                if app_state.normalize_layout(region.get("layout", data_layout)) == layout
            ]
            if not layout_regions:
                skipped += 1
                lines.append("SKIP    no designer regions saved for this layout")
                scene_items = self.scene_item_map(client, scene_name)
                ordered_names = self.mapped_designer_layer_order_names(self.designer_layer_order_names(layout, []), source_map)
                order_failures = self.apply_template_order(client, scene_name, ordered_names, scene_items)
                if order_failures:
                    failed += len(order_failures)
                    lines.extend(order_failures)
                else:
                    lines.append("APPLY   OBS Layout layer order")
                lines.append("")
                continue

            for region in layout_regions:
                logical_name = self.designer_source_name_for_region(layout, region)
                label = self.layout_region_label(region)
                if not logical_name:
                    skipped += 1
                    lines.append(f"SKIP    {label}: no OBS source mapping yet")
                    continue
                source_name = str(source_map.get(logical_name, logical_name))
                try:
                    item_id, create_status = self.create_designer_source_if_missing(
                        client,
                        scene_name,
                        source_name,
                        region,
                        source_names,
                        scene_items,
                        template,
                        supported_kinds,
                    )
                    if item_id is None:
                        skipped += 1
                        lines.append(f"SKIP    {label}: could not create mapped source ({source_name}, {create_status})")
                        continue
                    if create_status == "CREATE":
                        created += 1
                    elif create_status == "ADD":
                        added += 1
                    client.set_scene_item_transform(scene_name, item_id, self.designer_transform_from_region(region))
                    try:
                        client.set_scene_item_enabled(scene_name, item_id, True)
                    except Exception:
                        pass
                    applied += 1
                    lines.append(
                        f"APPLY   {source_name}: "
                        f"{int(float(region.get('x', 0)))},{int(float(region.get('y', 0)))} "
                        f"{int(float(region.get('w', 0)))}x{int(float(region.get('h', 0)))}"
                    )
                except Exception as exc:
                    failed += 1
                    lines.append(f"FAILED  {source_name}: {exc}")
            scene_items = self.scene_item_map(client, scene_name)
            ordered_names = self.mapped_designer_layer_order_names(self.designer_layer_order_names(layout, layout_regions), source_map)
            order_failures = self.apply_template_order(client, scene_name, ordered_names, scene_items)
            if order_failures:
                failed += len(order_failures)
                lines.extend(order_failures)
            else:
                lines.append("APPLY   OBS Layout layer order")
            lines.append("")

        lines.append("Result")
        lines.append("-" * 40)
        lines.append(f"Applied: {applied}")
        lines.append(f"Created: {created}")
        lines.append(f"Added to scene: {added}")
        lines.append(f"Skipped: {skipped}")
        lines.append(f"Failed: {failed}")

        result_text = "\n".join(lines)
        self.set_builder_text(result_text)
        self.builder_status_var.set(f"OBS Layout apply complete: {applied} applied, {created} created, {skipped} skipped, {failed} failed.")
        self.layout_status_var.set(f"OBS apply complete: {applied} applied, {created} created, {skipped} skipped, {failed} failed.")
        self.log_status(f"OBS Layout apply complete: {applied} applied, {created} created, {skipped} skipped, {failed} failed.")

    def _build_names(self, parent: tk.Frame) -> None:
        p = self.panel(parent, "OBS Text Names")
        fields = [
            ("Runner 1", "runner1.txt"),
            ("Runner 2", "runner2.txt"),
            ("Runner 3", "runner3.txt"),
            ("Runner 4", "runner4.txt"),
            ("Comms", "comm_names.txt"),
        ]
        for label, filename in fields:
            row = tk.Frame(p, bg=PANEL)
            row.pack(fill="x", padx=16, pady=5)
            tk.Label(row, text=label, bg=PANEL, fg=TEXT, width=10, anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left")
            var = tk.StringVar(value=self.read_text_file(filename))
            self.name_vars[filename] = var
            entry = tk.Entry(row, textvariable=var, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", font=("Segoe UI", 10))
            entry.pack(side="left", fill="x", expand=True, padx=(8, 8), ipady=7)
            self.button(row, "Save", lambda f=filename: self.save_one_name(f)).pack(side="left")

        bottom = tk.Frame(p, bg=PANEL)
        bottom.pack(fill="x", padx=16, pady=(10, 16))
        self.button(bottom, "Reload Names", self.reload_names).pack(side="left")
        self.button(bottom, "Save All", self.save_all_names, primary=True).pack(side="right")

    def _build_checklist(self, parent: tk.Frame) -> None:
        p = self.panel(parent, "Event Checklist")
        actions = tk.Frame(p, bg=PANEL)
        actions.pack(fill="x", padx=16, pady=(4, 10))
        self.button(actions, "Refresh Checklist", self.refresh_checklist, primary=True).pack(side="left", padx=(0, 8))
        self.button(actions, "Take Screenshots", self.take_screenshots).pack(side="left", padx=8)
        self.button(actions, "Apply Saved Crops", self.apply_saved_crops_from_main).pack(side="left", padx=8)
        self.button(actions, "Go to Cropping", lambda: self.show_page("Cropping")).pack(side="left", padx=8)

        actions2 = tk.Frame(p, bg=PANEL)
        actions2.pack(fill="x", padx=16, pady=(0, 10))
        self.button(actions2, "Go to Sync", lambda: self.show_page("Sync")).pack(side="left", padx=(0, 8))
        self.button(actions2, "Open Discord PTB", self.open_discord_ptb).pack(side="left", padx=8)
        self.button(actions2, "Open OBS Text Folder", lambda: open_folder(OBS_TEXT_DIR)).pack(side="left", padx=8)
        self.button(actions2, "OBS Settings", lambda: self.show_page("Settings")).pack(side="left", padx=8)

        checklist_frame = tk.Frame(p, bg=INPUT_BG)
        checklist_frame.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        checklist_scroll = ttk.Scrollbar(checklist_frame, orient="vertical")
        checklist_scroll.pack(side="right", fill="y")
        self.checklist_text = tk.Text(
            checklist_frame,
            height=22,
            bg=INPUT_BG,
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            relief="flat",
            wrap="word",
            yscrollcommand=checklist_scroll.set,
        )
        self.checklist_text.pack(side="left", fill="both", expand=True)
        checklist_scroll.configure(command=self.checklist_text.yview)
        self.refresh_checklist(include_obs=False)

    def _build_settings(self, parent: tk.Frame) -> None:
        p = self.panel(parent, "Settings")
        row1 = tk.Frame(p, bg=PANEL)
        row1.pack(fill="x", padx=16, pady=(4, 10))
        self.button(row1, "Open Launcher Folder", lambda: open_folder(BASE_DIR)).pack(side="left", padx=(0, 8))
        self.button(row1, "Open OBS Text Folder", lambda: open_folder(OBS_TEXT_DIR)).pack(side="left", padx=8)
        self.button(row1, "Open Screenshot Folder", lambda: open_folder(SCREENSHOT_DIR)).pack(side="left", padx=8)
        self.button(row1, "Open State Folder", lambda: open_folder(app_state.STATE_DIR)).pack(side="left", padx=8)

        row2 = tk.Frame(p, bg=PANEL)
        row2.pack(fill="x", padx=16, pady=(0, 12))
        self.button(row2, "Delete Crop Screenshots", self.delete_screenshots, danger=True).pack(side="left", padx=(0, 8))
        self.button(row2, "Delete Timer Images", self.delete_timer_screenshots, danger=True).pack(side="left", padx=8)

        row3 = tk.Frame(p, bg=PANEL)
        row3.pack(fill="x", padx=16, pady=(0, 12))
        self.button(row3, "Export Settings", self.export_settings, primary=True).pack(side="left", padx=(0, 8))
        self.button(row3, "Import Settings", self.import_settings).pack(side="left", padx=8)
        self.button(row3, "Copy Diagnostics", self.copy_diagnostics, compact=True).pack(side="left", padx=8)

        vlc_panel = self.panel(parent, "VLC Audio Output")
        tk.Label(
            vlc_panel,
            text="Optional: launch VLC through a specific Windows output device so runner audio stays out of your speakers while OBS can still capture it.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=1100,
        ).pack(fill="x", padx=16, pady=(0, 8))
        vlc_row = tk.Frame(vlc_panel, bg=PANEL)
        vlc_row.pack(fill="x", padx=16, pady=(0, 8))
        tk.Label(vlc_row, text="VLC output", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        self.vlc_audio_combo = ttk.Combobox(vlc_row, textvariable=self.vlc_audio_var, state="readonly", width=72)
        self.vlc_audio_combo.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        self.button(vlc_row, "Refresh Devices", self.refresh_vlc_audio_devices, compact=True).pack(side="left", padx=(0, 8))
        self.button(vlc_row, "Save & Relaunch", self.save_vlc_audio_device_and_relaunch, primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(vlc_row, "Use Windows Default", self.clear_vlc_audio_device, compact=True).pack(side="left", padx=(0, 8))
        self.button(vlc_row, "Open Volume Mixer", open_windows_volume_mixer, compact=True).pack(side="left")
        tk.Label(vlc_panel, textvariable=self.vlc_audio_status_var, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(0, 12))

        backup_panel = self.panel(parent, "Local Data Backups")
        backup_top = tk.Frame(backup_panel, bg=PANEL)
        backup_top.pack(fill="x", padx=16, pady=(4, 8))
        self.button(backup_top, "Backup Local Data", self.backup_local_data, primary=True, compact=True).pack(side="left", padx=(0, 8))
        self.button(backup_top, "Restore Runner List", self.restore_runner_list, compact=True).pack(side="left", padx=8)
        self.button(backup_top, "Open Runner CSV", self.open_runner_csv, compact=True).pack(side="left", padx=8)
        self.button(backup_top, "Open Backup Folder", lambda: open_folder(self.local_backup_dir()), compact=True).pack(side="left", padx=8)
        tk.Label(
            backup_panel,
            text="Backs up your runner list, crop presets, and custom OBS layout. These local files are ignored by Git.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(0, 12))

        runner_panel = self.panel(parent, "Runner List")
        edit_top = tk.Frame(runner_panel, bg=PANEL)
        edit_top.pack(fill="x", padx=16, pady=(4, 8))
        self.edit_runner_combo = ttk.Combobox(edit_top, textvariable=self.edit_runner_var, state="readonly", width=42)
        self.edit_runner_combo.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        self.edit_runner_combo.bind("<<ComboboxSelected>>", self.load_runner_editor_selection)
        self.button(edit_top, "Reload", self.refresh_runner_editor, compact=True).pack(side="left")

        edit_actions = tk.Frame(runner_panel, bg=PANEL)
        edit_actions.pack(fill="x", padx=16, pady=(0, 8))
        self.button(edit_actions, "Merge Duplicates", self.merge_duplicate_runners, compact=True).pack(side="left", padx=(0, 8))
        self.button(edit_actions, "Delete Selected Runner", self.delete_selected_runner, danger=True, compact=True).pack(side="left", padx=8)

        edit_fields = tk.Frame(runner_panel, bg=PANEL)
        edit_fields.pack(fill="x", padx=16, pady=(0, 8))
        for label, var, width in [
            ("Display", self.edit_display_var, 22),
            ("Twitch", self.edit_twitch_var, 22),
            ("Aliases", self.edit_aliases_var, 36),
        ]:
            tk.Label(edit_fields, text=label, bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 6))
            tk.Entry(edit_fields, textvariable=var, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", width=width).pack(side="left", ipady=6, padx=(0, 12))
        self.button(edit_fields, "Save Runner", self.save_runner_editor, primary=True, compact=True).pack(side="left")

        obs_panel = self.panel(parent, "OBS Websocket")
        obs_row = tk.Frame(obs_panel, bg=PANEL)
        obs_row.pack(fill="x", padx=16, pady=(4, 8))
        tk.Label(obs_row, text="Host", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 6))
        tk.Entry(obs_row, textvariable=self.obs_host_var, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", width=18).pack(side="left", ipady=6, padx=(0, 12))
        tk.Label(obs_row, text="Port", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 6))
        tk.Entry(obs_row, textvariable=self.obs_port_var, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", width=8).pack(side="left", ipady=6, padx=(0, 12))
        tk.Label(obs_row, text="Password", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 6))
        tk.Entry(obs_row, textvariable=self.obs_password_var, show="*", bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", width=22).pack(side="left", ipady=6, padx=(0, 12))
        self.button(obs_row, "Save", self.save_obs_settings, compact=True).pack(side="left", padx=(0, 8))
        self.button(obs_row, "Test", self.test_obs_connection, compact=True).pack(side="left")

        mapping_panel = self.panel(parent, "OBS Source Mapping")
        mapping_top = tk.Frame(mapping_panel, bg=PANEL)
        mapping_top.pack(fill="x", padx=16, pady=(4, 8))
        self.button(mapping_top, "Load Current", self.load_source_map_editor, compact=True).pack(side="left", padx=(0, 8))
        self.button(mapping_top, "Use Default Names", self.fill_default_source_map, compact=True).pack(side="left", padx=8)
        self.button(mapping_top, "Save Mapping", self.save_source_map_editor, primary=True, compact=True).pack(side="left", padx=8)
        tk.Label(
            mapping_panel,
            text="Edit the right side only. Left side is the app's expected name; right side is the actual OBS source or group item name.",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(0, 6))
        tk.Label(
            mapping_panel,
            text="Example: 4P R1 Stream = Player 1 Capture",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(0, 6))
        self.source_map_text = tk.Text(mapping_panel, height=12, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", wrap="none")
        self.source_map_text.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self.load_source_map_editor()

        self.refresh_runner_editor()
        self.refresh_vlc_audio_devices()

    def discover_vlc_audio_devices(self) -> list[dict[str, str]]:
        if os.name != "nt":
            return []
        script = r"""
Get-PnpDevice -Class AudioEndpoint -Status OK -ErrorAction SilentlyContinue |
  Where-Object { $_.InstanceId -like 'SWD\MMDEVAPI\{0.0.0*' } |
  Select-Object FriendlyName, InstanceId |
  ConvertTo-Json -Depth 2
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=hidden_creationflags(),
            )
        except Exception:
            return []
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            data = json.loads(result.stdout)
        except Exception:
            return []
        if isinstance(data, dict):
            data = [data]
        devices: list[dict[str, str]] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("FriendlyName", "")).strip()
            instance_id = str(item.get("InstanceId", "")).strip()
            match = re.search(r"SWD\\MMDEVAPI\\(.+)$", instance_id, re.I)
            if not name or not match:
                continue
            devices.append({"name": name, "id": match.group(1)})
        return devices

    def refresh_vlc_audio_devices(self) -> None:
        if self.vlc_audio_combo is None:
            return
        saved_device = str(app_state.load_config().get("vlc_audio_device", "")).strip()
        devices = self.discover_vlc_audio_devices()
        labels = ["Windows default"]
        self.vlc_audio_devices = {"Windows default": ""}
        used: set[str] = set(labels)
        selected = "Windows default"
        for device in devices:
            base = device["name"]
            label = base
            if label in used:
                label = f"{base} | {device['id']}"
            used.add(label)
            self.vlc_audio_devices[label] = device["id"]
            labels.append(label)
            if saved_device and saved_device.lower() == device["id"].lower():
                selected = label
        if saved_device and selected == "Windows default":
            label = f"Saved device not detected | {saved_device}"
            self.vlc_audio_devices[label] = saved_device
            labels.append(label)
            selected = label
        self.vlc_audio_combo["values"] = labels
        self.vlc_audio_var.set(selected)
        self.vlc_audio_status_var.set(
            f"Loaded {len(devices)} playback device(s)." if devices else "No Windows playback devices detected. Use Volume Mixer manually."
        )

    def save_vlc_audio_device(self) -> None:
        label = self.vlc_audio_var.get().strip() or "Windows default"
        device_id = self.vlc_audio_devices.get(label, "")
        config = app_state.load_config()
        config["vlc_audio_device"] = device_id
        app_state.save_config(config)
        if device_id:
            self.vlc_audio_status_var.set("Saved VLC output device. Relaunch runner streams for this to take effect.")
            self.log_status("Saved VLC output device. Relaunch runner streams for this to take effect.")
        else:
            self.vlc_audio_status_var.set("VLC will use the Windows default output device.")
            self.log_status("VLC audio output set to Windows default.")

    def save_vlc_audio_device_and_relaunch(self) -> None:
        self.save_vlc_audio_device()
        self.relaunch_current_race("Save VLC Audio Output & Relaunch")

    def clear_vlc_audio_device(self) -> None:
        self.vlc_audio_var.set("Windows default")
        self.save_vlc_audio_device()

    def load_runners_into_setup(self) -> None:
        self.launch_mod = load_launch_module()
        self.runners = []
        self.runner_combo_values = []
        self.runner_search_text = {}
        self.runner_by_combo = {}
        self.runner_display_by_combo = {}
        if self.launch_mod:
            try:
                self.runners = self.launch_mod.load_runners()
                for r in self.runners:
                    self.add_runner_combo_value(r.display_name, r)
                    if r.twitch_name and r.twitch_name.lower() != r.display_name.lower():
                        self.add_runner_combo_value(r.twitch_name, r)
                    for alias in getattr(r, "aliases", ()) or ():
                        if alias and alias.lower() not in {r.display_name.lower(), r.twitch_name.lower()}:
                            self.add_runner_combo_value(alias, r)
            except Exception as exc:
                messagebox.showwarning("Runner list", f"Could not load runners.csv:\n{exc}")
        self.runner_combo_values.sort(key=str.lower)
        for row in self.runner_rows.values():
            row.set_values(self.runner_combo_values)
        self.refresh_runner_editor()
        self.status_var.set(f"Loaded {len(self.runners)} runner(s).")

    def add_runner_combo_value(self, label_name: str, runner: Any) -> None:
        value = f"{label_name} - {runner.twitch_name}"
        if value in self.runner_by_combo:
            return
        self.runner_combo_values.append(value)
        alias_text = " ".join(getattr(runner, "aliases", ()) or ())
        self.runner_search_text[value] = f"{label_name} {runner.display_name} {runner.twitch_name} {alias_text}".lower()
        self.runner_by_combo[value] = runner
        self.runner_display_by_combo[value] = label_name

    def match_runner_values(self, query: str) -> list[str]:
        typed = query.strip().lower()
        if not typed:
            return self.runner_combo_values
        starts = []
        contains = []
        for value in self.runner_combo_values:
            search = self.runner_search_text.get(value, value.lower())
            label = self.runner_display_by_combo.get(value, value).lower()
            runner = self.runner_by_combo.get(value)
            twitch = getattr(runner, "twitch_name", "").lower() if runner else ""
            if label.startswith(typed) or twitch.startswith(typed):
                starts.append(value)
            elif typed in search:
                contains.append(value)
        return starts + contains

    def best_runner_value(self, query: str) -> Optional[str]:
        typed = query.strip().lower()
        if not typed:
            return None
        if query in self.runner_by_combo:
            return query
        matches = self.match_runner_values(query)
        for value in matches:
            label = self.runner_display_by_combo.get(value, value).lower()
            runner = self.runner_by_combo.get(value)
            twitch = getattr(runner, "twitch_name", "").lower() if runner else ""
            if typed in {label, twitch, value.lower()}:
                return value
        return matches[0] if matches else None

    def refresh_runner_editor(self) -> None:
        if not hasattr(self, "edit_runner_combo"):
            return
        values = [f"{r.display_name} - {r.twitch_name}" for r in self.runners]
        self.edit_runner_combo["values"] = values
        if values and self.edit_runner_var.get() not in values:
            self.edit_runner_var.set(values[0])
            self.load_runner_editor_selection()

    def load_runner_editor_selection(self, _event=None) -> None:
        value = self.edit_runner_var.get()
        twitch = value.rsplit(" - ", 1)[-1].strip() if " - " in value else ""
        for runner in self.runners:
            if runner.twitch_name == twitch:
                self.edit_display_var.set(runner.display_name)
                self.edit_twitch_var.set(runner.twitch_name)
                self.edit_aliases_var.set(";".join(getattr(runner, "aliases", ()) or ()))
                return

    def save_runner_editor(self) -> None:
        mod = self.launch_mod
        if not mod:
            messagebox.showerror("Runner list", "launch_crosskeys.py could not be loaded.")
            return
        original = self.edit_runner_var.get()
        original_twitch = original.rsplit(" - ", 1)[-1].strip() if " - " in original else ""
        display = self.edit_display_var.get().strip()
        twitch = mod.normalize_twitch_input(self.edit_twitch_var.get().strip())
        aliases = self.edit_aliases_var.get().strip()
        if not display or not mod.is_probable_twitch_name(twitch):
            messagebox.showwarning("Runner list", "Enter a display name and valid Twitch name.")
            return
        try:
            fieldnames, rows = mod.read_runner_csv_rows()
            self.backup_file(RUNNERS_CSV, "runners-before-edit", silent=True)
            display_key, twitch_key, aliases_key = mod.csv_keys(fieldnames)
            if aliases_key is None:
                aliases_key = "aliases"
                fieldnames.append(aliases_key)
                for row in rows:
                    row[aliases_key] = ""
            found = False
            for row in rows:
                if mod.norm_key(mod.normalize_twitch_input(row.get(twitch_key, ""))) == mod.norm_key(original_twitch):
                    row[display_key] = display
                    row[twitch_key] = twitch
                    row[aliases_key] = aliases
                    found = True
                    break
            if not found:
                rows.append({display_key: display, twitch_key: twitch, aliases_key: aliases})
            mod.write_runner_csv_rows(fieldnames, rows)
            self.load_runners_into_setup()
            self.edit_runner_var.set(f"{display} - {twitch}")
            self.refresh_runner_editor()
            self.log_status(f"Saved runner: {display} - {twitch}")
        except Exception as exc:
            messagebox.showerror("Runner list", str(exc))

    def delete_selected_runner(self) -> None:
        mod = self.launch_mod
        if not mod:
            messagebox.showerror("Runner list", "launch_crosskeys.py could not be loaded.")
            return
        selected = self.edit_runner_var.get()
        twitch = selected.rsplit(" - ", 1)[-1].strip() if " - " in selected else self.edit_twitch_var.get().strip()
        twitch = mod.normalize_twitch_input(twitch)
        if not twitch:
            messagebox.showwarning("Runner list", "Select a runner to delete.")
            return
        if not messagebox.askyesno("Delete runner", f"Delete twitch.tv/{twitch} from the runner list?"):
            return
        try:
            fieldnames, rows = mod.read_runner_csv_rows()
            display_key, twitch_key, _aliases_key = mod.csv_keys(fieldnames)
            kept = [
                row for row in rows
                if mod.norm_key(mod.normalize_twitch_input(row.get(twitch_key, ""))) != mod.norm_key(twitch)
            ]
            if len(kept) == len(rows):
                messagebox.showinfo("Delete runner", "That runner was not found in the CSV.")
                return
            self.backup_file(RUNNERS_CSV, "runners-before-delete", silent=True)
            mod.write_runner_csv_rows(fieldnames, kept)
            self.edit_runner_var.set("")
            self.edit_display_var.set("")
            self.edit_twitch_var.set("")
            self.edit_aliases_var.set("")
            self.load_runners_into_setup()
            self.log_status(f"Deleted runner: {twitch}")
        except Exception as exc:
            messagebox.showerror("Delete runner", str(exc))

    def merge_duplicate_runners(self) -> None:
        mod = self.launch_mod
        if not mod:
            messagebox.showerror("Runner list", "launch_crosskeys.py could not be loaded.")
            return
        try:
            fieldnames, rows = mod.read_runner_csv_rows()
            display_key, twitch_key, aliases_key = mod.csv_keys(fieldnames)
            if aliases_key is None:
                aliases_key = "aliases"
                fieldnames.append(aliases_key)
                for row in rows:
                    row[aliases_key] = ""

            merged: dict[str, dict[str, str]] = {}
            order: list[str] = []
            removed = 0
            for row in rows:
                twitch = mod.normalize_twitch_input(row.get(twitch_key, ""))
                key = mod.norm_key(twitch)
                if not key:
                    continue
                display = row.get(display_key, "").strip() or twitch
                aliases = list(mod.parse_aliases(row.get(aliases_key, "")))
                if key not in merged:
                    clean_row = dict(row)
                    clean_row[twitch_key] = twitch
                    clean_row[display_key] = display
                    clean_row[aliases_key] = ";".join(aliases)
                    merged[key] = clean_row
                    order.append(key)
                    continue
                removed += 1
                existing = merged[key]
                alias_values = list(mod.parse_aliases(existing.get(aliases_key, "")))
                known = {mod.norm_key(existing.get(display_key, "")), mod.norm_key(existing.get(twitch_key, ""))}
                known.update(mod.norm_key(value) for value in alias_values)
                for value in [display, row.get(twitch_key, ""), *aliases]:
                    value = str(value or "").strip()
                    if value and mod.norm_key(value) not in known:
                        alias_values.append(value)
                        known.add(mod.norm_key(value))
                existing[aliases_key] = ";".join(alias_values)

            if removed == 0:
                messagebox.showinfo("Merge duplicates", "No duplicate Twitch names were found.")
                return
            if not messagebox.askyesno("Merge duplicates", f"Merge duplicate Twitch entries and remove {removed} duplicate row(s)?"):
                return
            self.backup_file(RUNNERS_CSV, "runners-before-merge", silent=True)
            mod.write_runner_csv_rows(fieldnames, [merged[key] for key in order])
            self.load_runners_into_setup()
            self.refresh_runner_editor()
            self.log_status(f"Merged runner duplicates: removed {removed} duplicate row(s).")
            messagebox.showinfo("Merge duplicates", f"Merged duplicates and removed {removed} duplicate row(s).")
        except Exception as exc:
            messagebox.showerror("Merge duplicates", str(exc))

    def local_backup_dir(self) -> Path:
        backup_dir = app_state.STATE_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def backup_file(self, path: Path, label: str, silent: bool = False) -> Path | None:
        source = Path(path)
        if not source.exists():
            return None
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = source.suffix or ".bak"
        destination = self.local_backup_dir() / f"{label}_{timestamp}{suffix}"
        shutil.copy2(source, destination)
        if not silent:
            self.log_status(f"Backed up {source.name} to {destination}")
        return destination

    def backup_local_data(self) -> None:
        targets = [
            (RUNNERS_CSV, "runners"),
            (app_state.CROP_PRESETS_FILE, "crop_presets"),
            (LAYOUT_DESIGN_FILE, "layout_designer"),
        ]
        backed_up = []
        for path, label in targets:
            backup = self.backup_file(path, label, silent=True)
            if backup:
                backed_up.append(backup.name)
        if not backed_up:
            messagebox.showinfo("Local data backups", "No local data files were found to back up yet.")
            return
        self.log_status(f"Backed up local data: {', '.join(backed_up)}")
        messagebox.showinfo("Local data backups", "Backed up:\n" + "\n".join(backed_up))

    def restore_runner_list(self) -> None:
        path = filedialog.askopenfilename(
            title="Restore runner list",
            initialdir=str(self.local_backup_dir()),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno("Restore runner list", "Replace the current runner list with this CSV?"):
            return
        try:
            self.backup_file(RUNNERS_CSV, "runners-before-restore", silent=True)
            RUNNERS_CSV.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(path), RUNNERS_CSV)
            self.load_runners_into_setup()
            self.refresh_runner_editor()
            self.log_status(f"Restored runner list from {path}")
            messagebox.showinfo("Restore runner list", f"Restored runner list from:\n{path}")
        except Exception as exc:
            messagebox.showerror("Restore runner list", str(exc))

    def open_runner_csv(self) -> None:
        try:
            RUNNERS_CSV.parent.mkdir(parents=True, exist_ok=True)
            if not RUNNERS_CSV.exists():
                RUNNERS_CSV.write_text("display_name,twitch_name,aliases\n", encoding="utf-8")
            os.startfile(str(RUNNERS_CSV))
        except Exception as exc:
            messagebox.showerror("Runner list", str(exc))

    def update_mode(self) -> None:
        mode = int(self.mode_var.get())
        for slot, row in self.runner_rows.items():
            row.set_enabled(slot <= mode)

    def get_selected_runners(self) -> dict[int, Any]:
        selected: dict[int, Any] = {}
        mode = int(self.mode_var.get())
        for slot in range(1, mode + 1):
            selected[slot] = self.runner_rows[slot].to_runner()
        return selected

    def get_comms(self) -> str:
        mod = self.launch_mod
        raw = self.comms_var.get().strip()
        return mod.format_comms(raw) if mod else raw

    def save_new_runners_to_list(self, selected: dict[int, Any]) -> None:
        mod = self.launch_mod
        if not mod:
            return
        saved = []
        aliased = []
        existing = []
        for runner in selected.values():
            if not runner:
                continue
            if mod.runner_exists(runner.twitch_name):
                if mod.add_alias_to_existing_runner(runner.twitch_name, runner.display_name):
                    aliased.append(runner.display_name)
                else:
                    existing.append(runner.display_name)
                continue
            if messagebox.askyesno(
                "Save runner",
                f"Save {runner.display_name} / twitch.tv/{runner.twitch_name} to the runner dropdown for next time?",
            ):
                if mod.add_runner_to_csv(runner):
                    saved.append(runner.display_name)
        if saved or aliased or existing:
            self.load_runners_into_setup()
            pieces = []
            if saved:
                pieces.append("saved new runner(s): " + ", ".join(saved))
            if aliased:
                pieces.append("added alias(es): " + ", ".join(aliased))
            if existing:
                pieces.append("already in runner list: " + ", ".join(existing))
            self.log_status("; ".join(pieces))

    def write_names_only(self) -> None:
        mod = self.launch_mod
        if not mod:
            messagebox.showerror("Missing launcher", "launch_crosskeys.py could not be loaded.")
            return
        try:
            mode = int(self.mode_var.get())
            selected = self.get_selected_runners()
            self.save_new_runners_to_list(selected)
            comms = self.get_comms()
            mod.update_obs_text_files(mode, selected, comms)
            app_state.save_current_race(mode, selected, comms)
            self.reload_names()
            self.log_status("OBS text names updated.")
        except Exception as exc:
            messagebox.showerror("Could not write names", str(exc))

    def launch_from_gui(self) -> None:
        mod = self.launch_mod
        if not mod:
            messagebox.showerror("Missing launcher", "launch_crosskeys.py could not be loaded.")
            return
        try:
            mode = int(self.mode_var.get())
            selected = self.get_selected_runners()
            errors = self.launch_prereq_errors()
            if errors:
                messagebox.showerror("Launch blocked", "\n".join(errors))
                self.log_status("Launch blocked: " + "; ".join(errors))
                return
            available_slots, stream_errors = self.partition_available_streams(selected, range(1, mode + 1))
            if not available_slots:
                messagebox.showerror("Streams unavailable", "\n".join(stream_errors))
                self.log_status("Launch blocked: no selected streams are available.")
                return
            self.save_new_runners_to_list(selected)
            comms = self.get_comms()
            mod.update_obs_text_files(mode, selected, comms)
            mod.save_last_setup(mode, selected, comms)
            for slot in available_slots:
                mod.close_runner_window(slot)
                mod.launch_stream(slot, selected[slot])
            self.reload_names()
            launched_selected = {slot: selected[slot] for slot in available_slots}
            skipped = f" Skipped: {'; '.join(stream_errors)}" if stream_errors else ""
            self.log_status(f"Launched {len(available_slots)}/{mode} stream(s) and updated names.{skipped}")
            self.apply_saved_crops_after_launch(mode, launched_selected)
            if stream_errors:
                messagebox.showwarning("Some streams skipped", "Launched available streams.\n\nSkipped:\n" + "\n".join(stream_errors))
        except Exception as exc:
            messagebox.showerror("Launch failed", str(exc))

    def current_race_runners(self) -> tuple[int, dict[int, Any], str]:
        mod = self.launch_mod
        if not mod:
            raise RuntimeError("launch_crosskeys.py could not be loaded.")
        race = app_state.load_current_race()
        runners = race.get("runners", {})
        if not isinstance(runners, dict) or not runners:
            raise RuntimeError("No saved race is available to relaunch.")
        mode = int(str(race.get("mode", self.mode_var.get())).replace("P", "") or self.mode_var.get())
        selected: dict[int, Any] = {}
        for slot_raw, runner_data in runners.items():
            if not isinstance(runner_data, dict):
                continue
            try:
                slot = int(slot_raw)
            except ValueError:
                continue
            if slot < 1 or slot > mode:
                continue
            display = str(runner_data.get("display_name") or runner_data.get("twitch_name") or f"Runner {slot}").strip()
            twitch = str(runner_data.get("twitch_name") or "").strip()
            if twitch:
                selected[slot] = mod.Runner(display, twitch)
        if not selected:
            raise RuntimeError("The saved race has no usable runners.")
        return mode, selected, str(race.get("comms", "") or "")

    def relaunch_current_race(self, reason: str = "Relaunch") -> bool:
        mod = self.launch_mod
        if not mod:
            messagebox.showerror(reason, "launch_crosskeys.py could not be loaded.")
            return False
        try:
            mode, selected, comms = self.current_race_runners()
            errors = self.launch_prereq_errors()
            if errors:
                messagebox.showerror(f"{reason} blocked", "\n".join(errors))
                self.log_status(f"{reason} blocked: " + "; ".join(errors))
                return False
            available_slots, stream_errors = self.partition_available_streams(selected, sorted(selected))
            if not available_slots:
                messagebox.showerror(f"{reason} blocked", "\n".join(stream_errors))
                self.log_status(f"{reason} blocked: no saved streams are available.")
                return False
            if not messagebox.askyesno(reason, f"Close and relaunch {len(available_slots)} saved runner stream(s)?"):
                return False
            mod.update_obs_text_files(mode, selected, comms)
            mod.save_last_setup(mode, selected, comms)
            for slot in available_slots:
                mod.close_runner_window(slot)
                mod.launch_stream(slot, selected[slot])
            self.reload_names()
            launched_selected = {slot: selected[slot] for slot in available_slots}
            self.apply_saved_crops_after_launch(mode, launched_selected)
            skipped = f" Skipped: {'; '.join(stream_errors)}" if stream_errors else ""
            self.log_status(f"Relaunched {len(available_slots)} saved stream(s).{skipped}")
            if stream_errors:
                messagebox.showwarning("Some streams skipped", "Relaunched available streams.\n\nSkipped:\n" + "\n".join(stream_errors))
            return True
        except Exception as exc:
            messagebox.showerror(reason, str(exc))
            self.log_status(f"{reason} failed: {exc}")
            return False

    def replace_from_gui(self) -> None:
        self.launch_slot_from_setup(replace=True)

    def relaunch_slot_from_gui(self) -> None:
        self.launch_slot_from_setup(replace=False)

    def launch_slot_from_setup(self, replace: bool) -> None:
        mod = self.launch_mod
        if not mod:
            messagebox.showerror("Missing launcher", "launch_crosskeys.py could not be loaded.")
            return
        try:
            slot = int(self.replace_slot_var.get())
            runner = self.runner_rows[slot].to_runner()
            errors = self.launch_prereq_errors()
            if errors:
                title = "Replace blocked" if replace else "Relaunch blocked"
                messagebox.showerror(title, "\n".join(errors))
                self.log_status(f"{title}: " + "; ".join(errors))
                return
            _available_slots, stream_errors = self.partition_available_streams({slot: runner}, [slot])
            if stream_errors:
                messagebox.showerror("Stream unavailable", "\n".join(stream_errors))
                action = "Replace" if replace else "Relaunch"
                self.log_status(f"{action} blocked: " + "; ".join(stream_errors))
                return
            self.save_new_runners_to_list({slot: runner})
            action_word = "replace" if replace else "relaunch"
            if not messagebox.askyesno(f"{action_word.title()} runner", f"Close and {action_word} RUNNER {slot} as {runner.display_name}? "):
                return
            mod.close_runner_window(slot)
            mod.write_text_file(mod.OBS_TEXT_DIR / f"runner{slot}.txt", runner.display_name)
            with mod.LAST_SETUP.open("a", encoding="utf-8") as f:
                from datetime import datetime
                f.write(f"\nSlot {slot} relaunched from app at {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}: {runner.display_name} - twitch.tv/{runner.twitch_name}\n")
                f.write(f"  Runner {slot}: {runner.display_name} - twitch.tv/{runner.twitch_name}\n")
            app_state.update_current_race_slot(slot, runner)
            mod.launch_stream(slot, runner)
            self.reload_names()
            self.log_status(f"{'Replaced' if replace else 'Relaunched'} Runner {slot}: {runner.display_name}")
            self.apply_saved_crops_after_replace(slot, runner)
        except Exception as exc:
            messagebox.showerror("Replace failed" if replace else "Relaunch failed", str(exc))

    def clear_runner_fields(self) -> None:
        for row in self.runner_rows.values():
            row.clear()
        self.comms_var.set("")

    def take_screenshots(self) -> None:
        mode = int(self.mode_var.get())
        slots = "1,2" if mode == 2 else "1,2,3,4"
        if not SCREENSHOT_SCRIPT.exists():
            messagebox.showerror("Missing file", f"Could not find:\n{SCREENSHOT_SCRIPT}")
            return
        self.log_status(f"Capturing screenshots for runner slots {slots}...")
        threading.Thread(target=self.capture_screenshots_worker, args=(slots,), daemon=True).start()

    def capture_screenshots_worker(self, slots: str) -> None:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCREENSHOT_SCRIPT),
            "-SlotList",
            slots,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                creationflags=hidden_creationflags(),
            )
            self.after(
                0,
                lambda: self.finish_screenshot_capture(
                    slots,
                    result.returncode,
                    result.stdout,
                    result.stderr,
                ),
            )
        except Exception as exc:
            error = str(exc)
            self.after(0, lambda: messagebox.showerror("Screenshots failed", error))

    def finish_screenshot_capture(self, slots: str, returncode: int, stdout: str, stderr: str) -> None:
        self.refocus_app()
        output_lines = [line.strip() for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
        ok_count = sum(1 for line in output_lines if line.startswith("OK Runner"))
        requested_slots = {part for part in re.split(r"[,\s]+", slots.strip()) if part}
        missing = [
            line for line in output_lines
            if line.startswith("MISSING Runner") and self.missing_line_slot(line) in requested_slots
        ]
        if returncode != 0:
            details = "\n".join(output_lines[-12:]) or "No output was returned."
            self.log_status("Screenshot capture failed.")
            messagebox.showerror("Screenshots failed", details)
            return
        if missing:
            self.log_status(f"Captured {ok_count} screenshot(s); {len(missing)} runner window(s) missing.")
            messagebox.showwarning("Screenshots", "\n".join(missing))
            return
        self.log_status(f"Captured {ok_count} screenshot(s) for slots {slots}.")

    def missing_line_slot(self, line: str) -> str:
        match = re.search(r"MISSING Runner\s+([1-4])", line)
        return match.group(1) if match else ""

    def launch_action(self, *args: str) -> None:
        if not CONTROL_SCRIPT.exists():
            messagebox.showerror("Missing file", f"Could not find:\n{CONTROL_SCRIPT}")
            return
        run_console([PYTHON, str(CONTROL_SCRIPT), *args])

    def open_cropping_tool(self) -> None:
        tool = CROPPING_TOOL if CROPPING_TOOL.exists() else LEGACY_CROPPING_TOOL
        if not tool.exists():
            messagebox.showerror("Missing file", "Could not find cropping_tool.py")
            return
        run_hidden([GUI_PYTHON, str(tool)])

    def open_sync_tool(self) -> None:
        if not SYNC_TOOL.exists():
            messagebox.showerror("Missing file", f"Could not find:\n{SYNC_TOOL}")
            return
        run_hidden([GUI_PYTHON, str(SYNC_TOOL)])

    def open_discord_ptb(self) -> None:
        for path in DISCORD_PTB_PATHS:
            if path.exists():
                if path.name.lower() == "update.exe":
                    run_detached([str(path), "--processStart", "DiscordPTB.exe"])
                else:
                    run_detached([str(path)])
                return
        messagebox.showwarning("Discord PTB not found", "I could not find Discord PTB in the usual location.")

    def delete_screenshots(self) -> None:
        self.delete_image_folder(SCREENSHOT_DIR, "crop screenshot", "Delete crop screenshots")

    def delete_timer_screenshots(self) -> None:
        self.delete_image_folder(SYNC_SCREENSHOT_DIR, "timer image", "Delete timer images")

    def delete_image_folder(self, folder: Path, item_label: str, title: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}]
        if not files:
            self.status_var.set(f"No {item_label}s to delete.")
            return
        if not messagebox.askyesno(title, f"Delete {len(files)} {item_label} file(s)?"):
            return
        deleted = 0
        for path in files:
            try:
                path.unlink()
                deleted += 1
            except Exception:
                pass
        self.status_var.set(f"Deleted {deleted} {item_label}(s).")
        self.update_dashboard(include_obs=False)

    def read_text_file(self, filename: str) -> str:
        try:
            return (OBS_TEXT_DIR / filename).read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def save_one_name(self, filename: str) -> None:
        OBS_TEXT_DIR.mkdir(parents=True, exist_ok=True)
        value = self.name_vars[filename].get().strip()
        (OBS_TEXT_DIR / filename).write_text(value + "\n", encoding="utf-8")
        self.status_var.set(f"Saved {filename}")

    def reload_names(self) -> None:
        for filename, var in self.name_vars.items():
            var.set(self.read_text_file(filename))
        self.status_var.set("Reloaded names")

    def save_all_names(self) -> None:
        for filename in self.name_vars:
            self.save_one_name(filename)
        self.status_var.set("Saved all names")

    def load_saved_race_into_fields(self) -> None:
        race = app_state.load_current_race()
        runners = race.get("runners", {})
        if not isinstance(runners, dict) or not runners:
            messagebox.showwarning("No saved race", "No current race state has been saved yet.")
            return
        mode = str(race.get("mode", self.mode_var.get()))
        self.mode_var.set("2" if mode.startswith("2") else "4")
        self.update_mode()
        for row in self.runner_rows.values():
            row.clear()
        for slot_raw, runner in runners.items():
            if not isinstance(runner, dict):
                continue
            try:
                slot = int(slot_raw)
            except ValueError:
                continue
            if slot not in self.runner_rows:
                continue
            display = str(runner.get("display_name", "")).strip()
            twitch = str(runner.get("twitch_name", "")).strip()
            self.runner_rows[slot].selected_var.set(f"{display or twitch} - {twitch}" if twitch else display)
            self.runner_rows[slot].display_var.set(display or twitch)
            self.runner_rows[slot].twitch_var.set(twitch)
        self.comms_var.set(str(race.get("comms", "") or ""))
        self.log_status("Loaded saved race into setup fields.")

    def screenshot_count(self) -> int:
        try:
            return len([p for p in SCREENSHOT_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}])
        except Exception:
            return 0

    def crop_preset_counts(self, layout: str, runners: dict[str, Any]) -> tuple[int, int]:
        found = 0
        missing = 0
        for runner in runners.values():
            if not isinstance(runner, dict):
                continue
            twitch = str(runner.get("twitch_name") or "").strip()
            if not twitch:
                missing += 3
                continue
            for part in self.crop_parts_for_layout(layout):
                if app_state.get_crop_preset(twitch, part, layout):
                    found += 1
                else:
                    missing += 1
        return found, missing

    def update_dashboard(self, include_obs: bool = False) -> None:
        race = app_state.load_current_race()
        layout = app_state.normalize_layout(race.get("mode")) if race else app_state.normalize_layout(self.mode_var.get())
        runners = race.get("runners", {}) if isinstance(race.get("runners", {}), dict) else {}
        expected = 2 if layout == "2P" else 4
        runner_count = len(runners)
        found, missing = self.crop_preset_counts(layout, runners) if runners else (0, expected * 3)
        self.dashboard_layout_var.set(f"Layout: {layout}")
        self.dashboard_runners_var.set(f"Runners: {runner_count}/{expected}")
        if include_obs:
            self.dashboard_obs_var.set("OBS: checking...")
            threading.Thread(target=self.update_obs_dashboard_worker, daemon=True).start()

    def update_obs_dashboard_worker(self) -> None:
        try:
            client = obs_crop_service.connect()
            client.get_version()
            text = "OBS: connected"
        except Exception:
            text = "OBS: not connected"
        self.after(0, lambda: self.dashboard_obs_var.set(text))

    def refresh_checklist(self, include_obs: bool = True) -> None:
        if not hasattr(self, "checklist_text"):
            return
        self.checklist_text.delete("1.0", "end")
        self.checklist_text.insert("1.0", self.build_checklist_report(include_obs=include_obs))
        self.update_dashboard(include_obs=include_obs)

    def refresh_wizard_checks(self, include_obs: bool = True) -> None:
        frame = self.wizard_checks_frame
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        results = self.preflight_results(include_obs=include_obs)
        for row_index, (ok, label) in enumerate(results):
            row = tk.Frame(frame, bg=PANEL)
            row.grid(row=row_index, column=0, sticky="ew", pady=2)
            tk.Label(
                row,
                text="OK" if ok else "FIX",
                bg=PANEL,
                fg=GOOD if ok else WARN,
                width=6,
                anchor="w",
                font=("Segoe UI", 10, "bold"),
            ).pack(side="left")
            tk.Label(row, text=label, bg=PANEL, fg=TEXT, anchor="w", font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)
        frame.columnconfigure(0, weight=1)
        missing = len([1 for ok, _label in results if not ok])
        self.wizard_status_var.set("All setup checks passed." if missing == 0 else f"{missing} setup check(s) need attention.")

    def open_setup_guide(self) -> None:
        path = REPO_ROOT / "README_SETUP.md"
        if not path.exists():
            messagebox.showerror("Setup guide", f"Missing setup guide:\n{path}")
            return
        open_path(path)

    def create_start_menu_shortcut(self) -> None:
        script = BASE_DIR / "create_desktop_shortcut.ps1"
        if not script.exists():
            messagebox.showerror("Shortcut", f"Missing shortcut script:\n{script}")
            return
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Location",
                    "StartMenu",
                ],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=hidden_creationflags(),
            )
        except Exception as exc:
            messagebox.showerror("Shortcut failed", str(exc))
            return
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0:
            messagebox.showerror("Shortcut failed", output or f"Exit code {result.returncode}")
            return
        self.wizard_status_var.set(output or "Created Start Menu shortcut.")
        messagebox.showinfo("Shortcut", output or "Created Start Menu shortcut.")

    def wizard_load_audio_windows(self) -> None:
        self.show_page("Audio")
        self.load_audio_mapper()

    def wizard_refresh_checklist(self) -> None:
        self.refresh_checklist()
        self.show_page("Checklist")

    def build_checklist_report(self, include_obs: bool = True) -> str:
        race = app_state.load_current_race()
        lines = ["Event-Day Checklist", ""]

        for ok, label in self.preflight_results(include_obs=include_obs):
            lines.append(f"{'OK' if ok else 'FIX'} - {label}")

        lines.append("")
        if race:
            layout = app_state.normalize_layout(race.get("mode"))
            runners = race.get("runners", {})
            runner_count = len(runners) if isinstance(runners, dict) else 0
            expected_count = 2 if layout == "2P" else 4
            lines.append(f"{'OK' if runner_count == expected_count else 'FIX'} - Current race saved as {layout} with {runner_count}/{expected_count} runner(s)")
            if isinstance(runners, dict):
                lines.extend(self.crop_health_lines(layout, runners))
                if include_obs:
                    lines.extend(self.obs_source_health_lines(layout))
        else:
            lines.append("FIX - No current race saved yet")

        lines.append("")
        lines.append("OBS Text Files")
        for filename in ["runner1.txt", "runner2.txt", "runner3.txt", "runner4.txt", "comm_names.txt", "race_mode.txt"]:
            value = self.read_text_file(filename)
            label = filename.replace(".txt", "")
            status = "OK" if value else "CHECK"
            lines.append(f"{status} - {label}: {value or '(blank)'}")

        lines.append("")
        lines.append("Screenshots")
        screenshot_count = self.screenshot_count()
        lines.append(f"{'OK' if screenshot_count else 'CHECK'} - Screenshot files available: {screenshot_count}")

        lines.append("")
        lines.append("Manual checks")
        lines.append("CHECK - OBS is on the correct 2P or 4P scene")
        lines.append("CHECK - Discord voice/browser sources are ready")
        lines.append("CHECK - Audio levels look sane in OBS")
        lines.append("CHECK - Twitch dashboard/restream destination is ready")
        return "\n".join(lines)

    def crop_health_lines(self, layout: str, runners: dict[str, Any]) -> list[str]:
        lines = ["", "Crop Presets"]
        found = 0
        missing = 0
        for slot in ["1", "2", "3", "4"]:
            runner = runners.get(slot)
            if not isinstance(runner, dict):
                continue
            display = str(runner.get("display_name") or runner.get("twitch_name") or f"Runner {slot}")
            twitch = str(runner.get("twitch_name") or "").strip()
            if not twitch:
                lines.append(f"R{slot} {display}: missing Twitch name")
                continue
            parts = []
            for part in self.crop_parts_for_layout(layout):
                if app_state.get_crop_preset(twitch, part, layout):
                    found += 1
                    parts.append(f"{part}=OK")
                else:
                    missing += 1
                    parts.append(f"{part}=MISSING")
            lines.append(f"R{slot} {display}: " + ", ".join(parts))
        lines.append(f"Crop preset summary: {found} found, {missing} missing for {layout}")
        return lines

    def crop_parts_for_layout(self, layout: str) -> list[str]:
        layout = app_state.normalize_layout(layout)
        parts = ["Stream", "Tracker", "Timer"]
        if any(target_layout == layout and part == "Facecam" for _name, target_layout, _slot, part in obs_crop_service.designer_crop_targets()):
            parts.append("Facecam")
        return parts

    def obs_source_health_lines(self, layout: str) -> list[str]:
        lines = ["", "OBS Sources"]
        expected_slots = ["1", "2"] if layout == "2P" else ["1", "2", "3", "4"]
        expected = [f"{layout} R{slot} {part}" for slot in expected_slots for part in self.crop_parts_for_layout(layout)]
        try:
            client = obs_crop_service.connect()
            client.get_version()
            locations = obs_crop_service.find_crop_targets(client)
        except Exception as exc:
            lines.append(f"OBS source check failed: {exc}")
            return lines

        found = [source for source in expected if source in locations]
        missing = [source for source in expected if source not in locations]
        lines.append(f"Found {len(found)} of {len(expected)} expected {layout} crop targets.")
        if missing:
            lines.append("Missing OBS targets: " + ", ".join(missing))
        return lines

    def obs_settings_from_fields(self) -> dict[str, Any]:
        host = self.obs_host_var.get().strip() or "localhost"
        try:
            port = int(self.obs_port_var.get().strip() or "4455")
        except ValueError as exc:
            raise ValueError("OBS websocket port must be a number.") from exc
        return {
            "host": host,
            "port": port,
            "password": self.obs_password_var.get(),
        }

    def save_obs_settings(self) -> bool:
        try:
            obs_config = self.obs_settings_from_fields()
        except Exception as exc:
            messagebox.showerror("OBS settings", str(exc))
            return False
        config = app_state.load_config()
        config["obs_websocket"] = obs_config
        app_state.save_config(config)
        self.log_status(f"Saved OBS websocket settings: {obs_config['host']}:{obs_config['port']}")
        return True

    def export_settings(self) -> None:
        config = app_state.load_config()
        export_config = json.loads(json.dumps(config))
        if not messagebox.askyesno("Export settings", "Include OBS websocket password in the exported settings file?"):
            obs_config = export_config.get("obs_websocket", {})
            if isinstance(obs_config, dict):
                obs_config["password"] = ""
        data = {
            "format": "restream-control-settings",
            "version": 1,
            "config": export_config,
        }
        path = filedialog.asksaveasfilename(
            title="Export settings",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="restream-control-settings.json",
        )
        if not path:
            return
        Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.log_status(f"Exported settings to {path}")

    def import_settings(self) -> None:
        path = filedialog.askopenfilename(
            title="Import settings",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            config = data.get("config") if isinstance(data, dict) else None
            if not isinstance(config, dict):
                raise ValueError("This does not look like a Restream Control settings export.")
        except Exception as exc:
            messagebox.showerror("Import settings", str(exc))
            return
        if not messagebox.askyesno("Import settings", "Import these settings and update the app configuration?"):
            return
        app_state.save_config(config)
        self.reload_config_fields()
        self.log_status(f"Imported settings from {path}")

    def reload_config_fields(self) -> None:
        config = app_state.load_config()
        obs_config = config.get("obs_websocket", {})
        if isinstance(obs_config, dict):
            self.obs_host_var.set(str(obs_config.get("host", "localhost")))
            self.obs_port_var.set(str(obs_config.get("port", 4455)))
            self.obs_password_var.set(str(obs_config.get("password", "")))
        self.refresh_vlc_audio_devices()
        self.load_source_map_editor()

    def default_source_map(self) -> dict[str, str]:
        return {name: name for name in obs_crop_service.all_target_names()}

    def load_source_map_editor(self) -> None:
        if self.source_map_text is None:
            return
        config = app_state.load_config()
        source_map = config.get("obs_source_map", {})
        if not isinstance(source_map, dict) or not source_map:
            source_map = self.default_source_map()
        lines = [
            "# Left side: app expected source. Right side: your OBS source/group item name.",
            "# Edit the right side after '=' if your OBS names are different.",
            "# Example: 4P R1 Stream = Player 1 Capture",
            "",
        ]
        target_names = obs_crop_service.all_target_names()
        lines.extend(f"{logical} = {source_map.get(logical, logical)}" for logical in target_names)
        extra = sorted(str(key) for key in source_map if key not in target_names)
        lines.extend(f"{key} = {source_map.get(key, key)}" for key in extra)
        self.source_map_text.delete("1.0", "end")
        self.source_map_text.insert("1.0", "\n".join(lines))

    def fill_default_source_map(self) -> None:
        if self.source_map_text is None:
            return
        lines = [
            "# Left side: app expected source. Right side: your OBS source/group item name.",
            "# Edit the right side after '=' if your OBS names are different.",
            "# Example: 4P R1 Stream = Player 1 Capture",
            "",
        ]
        lines.extend(f"{name} = {name}" for name in obs_crop_service.all_target_names())
        self.source_map_text.delete("1.0", "end")
        self.source_map_text.insert("1.0", "\n".join(lines))

    def parse_source_map_editor(self) -> dict[str, str]:
        if self.source_map_text is None:
            return {}
        source_map = {}
        for raw_line in self.source_map_text.get("1.0", "end").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Mapping line is missing '=': {line}")
            logical, actual = [part.strip() for part in line.split("=", 1)]
            if not logical:
                raise ValueError(f"Mapping line has no expected source name: {line}")
            if actual:
                source_map[logical] = actual
        return source_map

    def save_source_map_editor(self) -> None:
        try:
            source_map = self.parse_source_map_editor()
        except Exception as exc:
            messagebox.showerror("OBS source mapping", str(exc))
            return
        config = app_state.load_config()
        config["obs_source_map"] = source_map
        app_state.save_config(config)
        self.log_status(f"Saved OBS source mapping with {len(source_map)} item(s).")

    def test_obs_connection(self) -> None:
        if not self.save_obs_settings():
            return
        try:
            client = obs_crop_service.connect()
            version = client.get_version()
        except Exception as exc:
            messagebox.showerror("OBS connection failed", str(exc))
            self.log_status(f"OBS websocket test failed: {exc}")
            return
        obs_version = getattr(version, "obs_version", None) or getattr(version, "obs_web_socket_version", None) or "connected"
        messagebox.showinfo("OBS connection", f"Connected to OBS websocket.\n\nVersion: {obs_version}")
        self.log_status("OBS websocket test succeeded.")

    def set_builder_text(self, text: str) -> None:
        if self.builder_text is None:
            return
        self.builder_text.configure(state="normal")
        self.builder_text.delete("1.0", "end")
        self.builder_text.insert("1.0", text)
        self.builder_text.configure(state="disabled")

    def selected_builder_layouts(self) -> list[str]:
        value = self.builder_layout_var.get().strip().upper()
        if value == "2P":
            return ["2P"]
        if value == "4P":
            return ["4P"]
        return ["2P", "4P"]

    def expected_builder_items(self, layout: str) -> dict[str, list[str]]:
        layout = app_state.normalize_layout(layout)
        if layout == "2P":
            runner_slots = [1, 2]
            crop_targets = [name for name, *_rest in obs_crop_service.TARGETS_2P]
        else:
            runner_slots = [1, 2, 3, 4]
            crop_targets = [name for name, *_rest in obs_crop_service.TARGETS_4P]
        return {
            "Scenes": [f"{layout} Restream"],
            "Crop sources": crop_targets,
            "Text sources": [f"Runner {slot} Name" for slot in runner_slots] + ["Comms Name"],
            "Background sources": [f"Background {layout}", f"Background {layout} Outlines", "Background Image [placeholder]"],
            "Audio sources": [source["name"] for source in self.builder_audio_sources(layout)],
        }

    def builder_audio_sources(self, layout: str) -> list[dict[str, Any]]:
        layout = app_state.normalize_layout(layout)
        slots = [1, 2] if layout == "2P" else [1, 2, 3, 4]
        sources: list[dict[str, Any]] = []
        for slot in slots:
            sources.append({
                "name": f"{layout} R{slot} Audio",
                "kind": "wasapi_process_output_capture",
                "settings": {
                    "window": f"RUNNER {slot} - VLC media player:Qt5QWindowIcon:vlc.exe",
                    "priority": 1,
                },
                "muted": True,
            })
        sources.extend([
            {
                "name": "Discord Audio",
                "kind": "audio_capture",
                "settings": {
                    "exclude": False,
                    "mode": 0,
                    "executable_list": ["Discord.exe", "DiscordPTB.exe", "DiscordCanary.exe"],
                },
                "muted": True,
            },
            {
                "name": "Mic Audio",
                "kind": "wasapi_input_capture",
                "settings": {
                    "device_id": "default",
                    "use_device_timing": False,
                },
                "muted": True,
            },
        ])
        return sources

    def load_obs_template(self) -> dict[str, Any]:
        if not OBS_TEMPLATE_FILE.exists():
            raise FileNotFoundError(f"OBS template not found: {OBS_TEMPLATE_FILE}")
        return json.loads(OBS_TEMPLATE_FILE.read_text(encoding="utf-8-sig"))

    def template_source(self, template: dict[str, Any], source_name: str) -> dict[str, Any]:
        for source in template.get("sources", []):
            if source.get("name") == source_name:
                return source
        raise KeyError(f"Template source not found: {source_name}")

    def template_scene_items(self, template: dict[str, Any], scene_name: str) -> list[dict[str, Any]]:
        source = self.template_source(template, scene_name)
        return list(source.get("settings", {}).get("items", []) or [])

    def builder_input_settings(self, template_source: dict[str, Any]) -> dict[str, Any]:
        settings = copy.deepcopy(template_source.get("settings", {}) or {})
        file_value = settings.get("file")
        if isinstance(file_value, str):
            normalized = file_value.replace("\\", "/")
            if normalized.startswith("obs-template/"):
                settings["file"] = str((REPO_ROOT / normalized).resolve())
            elif normalized.startswith("examples/obs_text/"):
                settings["file"] = str((OBS_TEXT_DIR / Path(normalized).name).resolve())
        source_kind = str(template_source.get("id", "") or "")
        if "window_capture" in source_kind:
            settings["client_area"] = False
        return settings

    def transform_from_template_item(self, item: dict[str, Any]) -> dict[str, Any]:
        pos = item.get("pos") or {}
        scale = item.get("scale") or {}
        bounds = item.get("bounds") or {}
        bounds_type_map = {
            0: "OBS_BOUNDS_NONE",
            1: "OBS_BOUNDS_STRETCH",
            2: "OBS_BOUNDS_SCALE_INNER",
            3: "OBS_BOUNDS_SCALE_OUTER",
            4: "OBS_BOUNDS_SCALE_TO_WIDTH",
            5: "OBS_BOUNDS_SCALE_TO_HEIGHT",
            6: "OBS_BOUNDS_MAX_ONLY",
        }
        bounds_type = int(item.get("bounds_type", 0))
        transform = {
            "alignment": int(item.get("align", 5)),
            "positionX": float(pos.get("x", 0.0)),
            "positionY": float(pos.get("y", 0.0)),
            "rotation": float(item.get("rot", 0.0)),
            "scaleX": float(scale.get("x", 1.0)),
            "scaleY": float(scale.get("y", 1.0)),
            "cropLeft": int(item.get("crop_left", 0)),
            "cropTop": int(item.get("crop_top", 0)),
            "cropRight": int(item.get("crop_right", 0)),
            "cropBottom": int(item.get("crop_bottom", 0)),
            "boundsType": bounds_type_map.get(bounds_type, "OBS_BOUNDS_NONE"),
            "boundsAlignment": int(item.get("bounds_align", 0)),
        }
        if bounds_type != 0:
            transform["boundsWidth"] = max(1.0, float(bounds.get("x", 1.0)))
            transform["boundsHeight"] = max(1.0, float(bounds.get("y", 1.0)))
        return transform

    def scene_item_map(self, client: Any, scene_name: str) -> dict[str, int]:
        try:
            resp = client.get_scene_item_list(scene_name)
            items = self.obs_response_value(resp, "sceneItems", "scene_items", default=[])
        except Exception:
            return {}
        item_map: dict[str, int] = {}
        for item in items or []:
            name = self.obs_response_value(item, "sourceName", "source_name", "name")
            item_id = self.obs_response_value(item, "sceneItemId", "scene_item_id")
            if name and item_id is not None:
                item_map[str(name)] = int(item_id)
        return item_map

    def scene_item_names(self, client: Any, scene_name: str) -> set[str]:
        return set(self.scene_item_map(client, scene_name).keys())

    def get_scene_item_id_value(self, response: Any) -> int:
        item_id = self.obs_response_value(response, "sceneItemId", "scene_item_id")
        if item_id is None:
            raise RuntimeError("OBS did not return a scene item id.")
        return int(item_id)

    def is_builder_container_name(self, source_name: str) -> bool:
        return bool(re.match(r"^[24]P R[1-4]$", source_name))

    def apply_template_scene_item(self, client: Any, scene_name: str, source_name: str, item_id: int, item: dict[str, Any]) -> None:
        try:
            client.set_scene_item_transform(scene_name, item_id, self.transform_from_template_item(item))
        except Exception as exc:
            raise RuntimeError(f"Could not position {source_name}: {exc}") from exc
        try:
            client.set_scene_item_enabled(scene_name, item_id, bool(item.get("visible", True)))
        except Exception:
            pass
        try:
            client.set_scene_item_locked(scene_name, item_id, bool(item.get("locked", False)))
        except Exception:
            pass

    def repair_template_input_settings(self, client: Any, source_name: str, template: dict[str, Any]) -> None:
        try:
            source_template = self.template_source(template, source_name)
        except KeyError:
            return
        source_kind = str(source_template.get("id", ""))
        if source_kind in {"scene", "group"}:
            return
        try:
            client.set_input_settings(source_name, self.builder_input_settings(source_template), True)
        except Exception:
            pass

    def ensure_template_window_capture_settings(self, client: Any, source_name: str, template: dict[str, Any]) -> bool:
        try:
            source_template = self.template_source(template, source_name)
        except KeyError:
            return False
        source_kind = str(source_template.get("id", "") or "")
        if "window_capture" not in source_kind:
            return False
        try:
            client.set_input_settings(source_name, {"client_area": False}, True)
            return True
        except Exception:
            return False

    def supported_obs_input_kinds(self, client: Any) -> set[str]:
        kinds: set[str] = set()
        for unversioned in (False, True):
            try:
                resp = client.get_input_kind_list(unversioned)
                values = self.obs_response_value(resp, "inputKinds", "input_kinds", default=[])
                kinds.update(str(value) for value in values or [])
            except Exception:
                pass
        return kinds

    def resolve_builder_input_kind(self, client: Any, source_kind: str, supported_kinds: set[str] | None = None) -> str:
        if not supported_kinds:
            return source_kind
        if source_kind == "text_gdiplus":
            for candidate in ["text_gdiplus_v3", "text_gdiplus_v2", "text_ft2_source_v2", "text_ft2_source"]:
                if candidate in supported_kinds:
                    return candidate
        if source_kind in supported_kinds:
            return source_kind
        if source_kind == "window_capture":
            for candidate in ["window_capture", "window_capture_v2"]:
                if candidate in supported_kinds:
                    return candidate
        if source_kind == "image_source":
            for candidate in ["image_source", "image_source_v2"]:
                if candidate in supported_kinds:
                    return candidate
        return source_kind

    def create_or_add_template_item(
        self,
        client: Any,
        scene_name: str,
        source_name: str,
        item: dict[str, Any],
        source_names: set[str],
        scene_items: dict[str, int],
        template: dict[str, Any],
        supported_kinds: set[str] | None = None,
    ) -> str:
        if source_name in scene_items:
            if self.ensure_template_window_capture_settings(client, source_name, template):
                return f"FIX     {source_name} client area unchecked"
            return f"SKIP    {source_name} already exists in {scene_name}"

        created_source = False
        if source_name not in source_names:
            source_template = self.template_source(template, source_name)
            source_kind = str(source_template.get("id", ""))
            if source_kind in {"scene", "group"}:
                return f"SKIP    {source_name} is a container source"
            settings = self.builder_input_settings(source_template)
            source_kind = self.resolve_builder_input_kind(client, source_kind, supported_kinds)
            response = client.create_input(scene_name, source_name, source_kind, settings, bool(item.get("visible", True)))
            item_id = self.get_scene_item_id_value(response)
            source_names.add(source_name)
            scene_items[source_name] = item_id
            created_source = True
        else:
            response = client.create_scene_item(scene_name, source_name, bool(item.get("visible", True)))
            item_id = self.get_scene_item_id_value(response)
            scene_items[source_name] = item_id

        self.apply_template_scene_item(client, scene_name, source_name, item_id, item)
        action = "CREATE" if created_source else "ADD"
        return f"{action:<7} {source_name} -> {scene_name}"

    def reset_template_item(
        self,
        client: Any,
        scene_name: str,
        source_name: str,
        item: dict[str, Any],
        source_names: set[str],
        scene_items: dict[str, int],
        template: dict[str, Any],
        supported_kinds: set[str] | None = None,
    ) -> str:
        item_id = scene_items.get(source_name)
        if item_id is not None:
            self.repair_template_input_settings(client, source_name, template)
            self.apply_template_scene_item(client, scene_name, source_name, item_id, item)
            return f"RESET   {source_name}"

        created_source = False
        if source_name not in source_names:
            source_template = self.template_source(template, source_name)
            source_kind = str(source_template.get("id", ""))
            if source_kind in {"scene", "group"}:
                return f"SKIP    {source_name} is a container source"
            settings = self.builder_input_settings(source_template)
            source_kind = self.resolve_builder_input_kind(client, source_kind, supported_kinds)
            response = client.create_input(scene_name, source_name, source_kind, settings, bool(item.get("visible", True)))
            item_id = self.get_scene_item_id_value(response)
            source_names.add(source_name)
            created_source = True
        else:
            response = client.create_scene_item(scene_name, source_name, bool(item.get("visible", True)))
            item_id = self.get_scene_item_id_value(response)

        scene_items[source_name] = item_id
        self.repair_template_input_settings(client, source_name, template)
        self.apply_template_scene_item(client, scene_name, source_name, item_id, item)
        action = "CREATE" if created_source else "ADD"
        return f"{action:<7} {source_name} -> {scene_name}"

    def apply_template_order(self, client: Any, scene_name: str, ordered_names: list[str], scene_items: dict[str, int]) -> list[str]:
        lines: list[str] = []
        for index, source_name in enumerate(ordered_names):
            item_id = scene_items.get(source_name)
            if item_id is None:
                continue
            try:
                client.set_scene_item_index(scene_name, item_id, index)
            except Exception as exc:
                lines.append(f"FAILED  layer order {source_name}: {exc}")
        return lines

    def resolve_builder_audio_kind(self, requested_kind: str, supported_kinds: set[str] | None) -> str | None:
        if not supported_kinds:
            return requested_kind
        if requested_kind in supported_kinds:
            return requested_kind
        fallbacks = {
            "wasapi_process_output_capture": ["audio_capture"],
            "audio_capture": ["wasapi_process_output_capture"],
            "wasapi_input_capture": [],
        }
        for candidate in fallbacks.get(requested_kind, []):
            if candidate in supported_kinds:
                return candidate
        return None

    def create_or_add_audio_source(
        self,
        client: Any,
        scene_name: str,
        source: dict[str, Any],
        source_names: set[str],
        scene_items: dict[str, int],
        supported_kinds: set[str] | None,
    ) -> str:
        source_name = str(source["name"])
        requested_kind = str(source["kind"])
        settings = copy.deepcopy(source.get("settings", {}))
        muted = bool(source.get("muted", True))
        audio_kind = self.resolve_builder_audio_kind(requested_kind, supported_kinds)
        if not audio_kind:
            return f"FAILED  {source_name}: OBS does not report supported audio source kind {requested_kind}"

        if requested_kind != audio_kind and audio_kind == "audio_capture":
            window = str(settings.get("window", ""))
            executable = "vlc.exe"
            match = re.match(r"^\[([^\]]+)\]:", window)
            if match:
                executable = match.group(1)
            settings = {
                "exclude": False,
                "mode": 0,
                "executable_list": [executable],
            }

        if source_name not in source_names:
            response = client.create_input(scene_name, source_name, audio_kind, settings, True)
            item_id = self.get_scene_item_id_value(response)
            source_names.add(source_name)
            scene_items[source_name] = item_id
            try:
                client.set_input_mute(source_name, muted)
            except Exception:
                pass
            return f"CREATE  {source_name} -> {scene_name}"

        if source_name in scene_items:
            return f"SKIP    {source_name} already exists in {scene_name}"

        response = client.create_scene_item(scene_name, source_name, True)
        item_id = self.get_scene_item_id_value(response)
        scene_items[source_name] = item_id
        return f"ADD     {source_name} -> {scene_name}"

    def create_missing_obs_sources(self) -> None:
        layouts = self.selected_builder_layouts()
        message = (
            "Create missing OBS scenes and default sources for "
            f"{', '.join(layouts)}?\n\n"
            "This will not delete sources and will not move existing scene items. Missing items use the default template positions."
        )
        if not messagebox.askyesno("Create OBS sources", message):
            return
        if not self.save_obs_settings():
            return

        self.builder_status_var.set("Creating missing OBS sources...")
        self.set_builder_text("Creating missing OBS sources...")
        try:
            template = self.load_obs_template()
            client = obs_crop_service.connect()
            supported_kinds = self.supported_obs_input_kinds(client)
            snapshot = self.scan_obs_snapshot(client)
        except Exception as exc:
            self.builder_status_var.set(f"Create failed: {exc}")
            self.set_builder_text(f"Create failed.\n\n{exc}")
            self.log_status(f"OBS builder create failed: {exc}")
            return

        lines = ["Create Missing OBS Defaults", ""]
        created = 0
        skipped = 0
        failed = 0
        scene_names = set(snapshot["scenes"])
        source_names = set(snapshot["all_sources"])

        for layout in layouts:
            scene_name = f"{layout} Restream"
            lines.append(f"{layout} layout")
            lines.append("-" * 40)
            if scene_name not in scene_names:
                try:
                    client.create_scene(scene_name)
                    scene_names.add(scene_name)
                    source_names.add(scene_name)
                    created += 1
                    lines.append(f"CREATE  {scene_name}")
                except Exception as exc:
                    failed += 1
                    lines.append(f"FAILED  {scene_name}: {exc}")
                    lines.append("")
                    continue
            else:
                skipped += 1
                lines.append(f"SKIP    {scene_name} already exists")

            scene_items = self.scene_item_map(client, scene_name)
            scene_started_empty = not scene_items
            ordered_names: list[str] = []
            for item in self.template_scene_items(template, scene_name):
                source_name = str(item.get("name") or "")
                if not source_name or self.is_builder_container_name(source_name):
                    continue
                ordered_names.append(source_name)
                try:
                    result = self.create_or_add_template_item(client, scene_name, source_name, item, source_names, scene_items, template, supported_kinds)
                    lines.append(result)
                    if result.startswith(("CREATE", "ADD")):
                        created += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    failed += 1
                    lines.append(f"FAILED  {source_name}: {exc}")
            if scene_started_empty:
                order_failures = self.apply_template_order(client, scene_name, ordered_names, scene_items)
                if order_failures:
                    failed += len(order_failures)
                    lines.extend(order_failures)
                else:
                    lines.append("CREATE  default layer order")
            else:
                lines.append("SKIP    layer order; scene already had items")

            for audio_source in self.builder_audio_sources(layout):
                try:
                    result = self.create_or_add_audio_source(client, scene_name, audio_source, source_names, scene_items, supported_kinds)
                    lines.append(result)
                    if result.startswith(("CREATE", "ADD")):
                        created += 1
                    elif result.startswith("FAILED"):
                        failed += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    failed += 1
                    lines.append(f"FAILED  {audio_source.get('name', 'audio source')}: {exc}")
            lines.append("")

        lines.append("Result")
        lines.append("-" * 40)
        lines.append(f"Created/added: {created}")
        lines.append(f"Skipped: {skipped}")
        lines.append(f"Failed: {failed}")
        lines.append("")
        lines.append("Run Scan OBS again to verify the layout.")

        self.builder_status_var.set(f"Create complete: {created} created/added, {skipped} skipped, {failed} failed.")
        self.set_builder_text("\n".join(lines))
        self.log_status(f"OBS builder create complete: {created} created/added, {skipped} skipped, {failed} failed.")

    def reset_to_default_template(self) -> None:
        layouts = self.selected_builder_layouts()
        message = (
            "Reset the included Restream Control template layout for "
            f"{', '.join(layouts)}?\n\n"
            "This moves, resizes, locks, and reorders existing template scene items back to the shipped default. "
            "It does not delete extra/custom sources and it leaves audio settings alone."
        )
        if not messagebox.askyesno("Reset OBS template", message):
            return
        if not self.save_obs_settings():
            return

        self.builder_status_var.set("Resetting OBS template...")
        self.set_builder_text("Resetting OBS template...")
        try:
            template = self.load_obs_template()
            client = obs_crop_service.connect()
            supported_kinds = self.supported_obs_input_kinds(client)
            snapshot = self.scan_obs_snapshot(client)
        except Exception as exc:
            self.builder_status_var.set(f"Reset failed: {exc}")
            self.set_builder_text(f"Reset failed.\n\n{exc}")
            self.log_status(f"OBS template reset failed: {exc}")
            return

        lines = ["Reset To Default Template", ""]
        reset = 0
        created = 0
        skipped = 0
        failed = 0
        scene_names = set(snapshot["scenes"])
        source_names = set(snapshot["all_sources"])

        for layout in layouts:
            scene_name = f"{layout} Restream"
            lines.append(f"{layout} layout")
            lines.append("-" * 40)
            if scene_name not in scene_names:
                try:
                    client.create_scene(scene_name)
                    scene_names.add(scene_name)
                    source_names.add(scene_name)
                    created += 1
                    lines.append(f"CREATE  {scene_name}")
                except Exception as exc:
                    failed += 1
                    lines.append(f"FAILED  {scene_name}: {exc}")
                    lines.append("")
                    continue

            scene_items = self.scene_item_map(client, scene_name)
            ordered_names: list[str] = []
            for item in self.template_scene_items(template, scene_name):
                source_name = str(item.get("name") or "")
                if not source_name or self.is_builder_container_name(source_name):
                    continue
                ordered_names.append(source_name)
                try:
                    result = self.reset_template_item(client, scene_name, source_name, item, source_names, scene_items, template, supported_kinds)
                    lines.append(result)
                    if result.startswith("RESET"):
                        reset += 1
                    elif result.startswith(("CREATE", "ADD")):
                        created += 1
                    elif result.startswith("FAILED"):
                        failed += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    failed += 1
                    lines.append(f"FAILED  {source_name}: {exc}")

            order_failures = self.apply_template_order(client, scene_name, ordered_names, scene_items)
            if order_failures:
                failed += len(order_failures)
                lines.extend(order_failures)
            else:
                lines.append("RESET   default layer order")
            lines.append("SKIP    audio settings unchanged")
            lines.append("")

        lines.append("Result")
        lines.append("-" * 40)
        lines.append(f"Reset: {reset}")
        lines.append(f"Created/added: {created}")
        lines.append(f"Skipped: {skipped}")
        lines.append(f"Failed: {failed}")
        lines.append("")
        lines.append("Run Scan OBS again to verify the template.")

        self.builder_status_var.set(f"Reset complete: {reset} reset, {created} created/added, {failed} failed.")
        self.set_builder_text("\n".join(lines))
        self.log_status(f"OBS template reset complete: {reset} reset, {created} created/added, {failed} failed.")

    def scan_obs_snapshot(self, client: Any) -> dict[str, set[str]]:
        scenes: set[str] = set()
        groups: set[str] = set()
        inputs: set[str] = set()
        scene_items: set[str] = set()

        try:
            resp = client.get_scene_list()
            for scene in self.obs_response_value(resp, "scenes", default=[]) or []:
                name = self.obs_response_value(scene, "sceneName", "scene_name", "name")
                if name:
                    scenes.add(str(name))
        except Exception:
            pass

        try:
            resp = client.get_group_list()
            for group in self.obs_response_value(resp, "groups", default=[]) or []:
                if group:
                    groups.add(str(group))
        except Exception:
            pass

        try:
            resp = client.get_input_list()
            for item in self.obs_response_value(resp, "inputs", "input_list", "inputList", default=[]) or []:
                name = self.obs_response_value(item, "inputName", "input_name", "name")
                if name:
                    inputs.add(str(name))
        except Exception:
            pass

        def add_items(container: str, group: bool = False) -> None:
            try:
                resp = client.get_group_scene_item_list(container) if group else client.get_scene_item_list(container)
                items = self.obs_response_value(resp, "sceneItems", "scene_items", default=[])
            except Exception:
                return
            for item in items or []:
                name = self.obs_response_value(item, "sourceName", "source_name", "name")
                if name:
                    scene_items.add(str(name))

        for scene in sorted(scenes):
            add_items(scene, group=False)
        for group in sorted(groups):
            add_items(group, group=True)

        all_sources = set().union(scenes, groups, inputs, scene_items)
        return {
            "scenes": scenes,
            "groups": groups,
            "inputs": inputs,
            "scene_items": scene_items,
            "all_sources": all_sources,
        }

    def scan_obs_builder(self) -> None:
        if not self.save_obs_settings():
            return
        layouts = self.selected_builder_layouts()
        self.builder_status_var.set("Scanning OBS...")
        self.set_builder_text("Scanning OBS...")
        try:
            client = obs_crop_service.connect()
            version = client.get_version()
            snapshot = self.scan_obs_snapshot(client)
        except Exception as exc:
            self.builder_status_var.set(f"OBS scan failed: {exc}")
            self.set_builder_text(f"OBS scan failed.\n\n{exc}")
            self.log_status(f"OBS builder scan failed: {exc}")
            return

        obs_version = getattr(version, "obs_version", None) or getattr(version, "obs_web_socket_version", None) or "connected"
        lines: list[str] = [
            "Template Setup Scan",
            f"OBS: {obs_version}",
            "",
            f"Detected scenes: {len(snapshot['scenes'])}",
            f"Detected groups: {len(snapshot['groups'])}",
            f"Detected inputs: {len(snapshot['inputs'])}",
            "",
        ]
        total_found = 0
        total_missing = 0
        source_names = snapshot["all_sources"]
        for layout in layouts:
            lines.append(f"{layout} layout")
            lines.append("-" * 40)
            expected = self.expected_builder_items(layout)
            for section, names in expected.items():
                if section == "Scenes":
                    available = snapshot["scenes"]
                else:
                    available = source_names
                found = [name for name in names if name in available]
                missing = [name for name in names if name not in available]
                total_found += len(found)
                total_missing += len(missing)
                lines.append(f"{section}: {len(found)}/{len(names)} found")
                for name in found:
                    lines.append(f"  OK      {name}")
                for name in missing:
                    lines.append(f"  MISSING {name}")
                lines.append("")
            lines.append("")

        lines.append("Next step")
        lines.append("-" * 40)
        if total_missing:
            lines.append("Create Missing Defaults can add the included template scenes/sources.")
            lines.append("Existing scene items are left where they are. Use Custom OBS Layout for custom drawn positions.")
        else:
            lines.append("Everything expected for the selected template exists. Use Custom OBS Layout if you want a custom drawn layout.")

        self.builder_status_var.set(f"Scan complete: {total_found} found, {total_missing} missing.")
        self.set_builder_text("\n".join(lines))
        self.log_status(f"OBS builder scan complete: {total_found} found, {total_missing} missing.")

    def obs_response_value(self, obj: Any, *names: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            for name in names:
                if name in obj:
                    return obj[name]
        for name in names:
            if hasattr(obj, name):
                return getattr(obj, name)
        return default

    def current_audio_mixer_names(self, client: Any) -> set[str]:
        names: set[str] = set()

        try:
            special = client.get_special_inputs()
            for value in [
                self.obs_response_value(special, "desktop1", "desktop_1"),
                self.obs_response_value(special, "desktop2", "desktop_2"),
                self.obs_response_value(special, "mic1", "mic_1"),
                self.obs_response_value(special, "mic2", "mic_2"),
                self.obs_response_value(special, "mic3", "mic_3"),
                self.obs_response_value(special, "mic4", "mic_4"),
            ]:
                if value:
                    names.add(str(value))
        except Exception:
            pass

        def add_scene_items(scene_name: str, seen: set[str] | None = None) -> None:
            if not scene_name:
                return
            seen = seen or set()
            if scene_name in seen:
                return
            seen.add(scene_name)
            try:
                resp = client.get_scene_item_list(scene_name)
                scene_items = self.obs_response_value(resp, "sceneItems", "scene_items", default=[])
            except Exception:
                return
            for item in scene_items or []:
                source_name = self.obs_response_value(item, "sourceName", "source_name")
                if not source_name:
                    continue
                source_name = str(source_name)
                names.add(source_name)
                is_group = bool(self.obs_response_value(item, "isGroup", "is_group", default=False))
                if is_group:
                    try:
                        group_resp = client.get_group_scene_item_list(source_name)
                        group_items = self.obs_response_value(group_resp, "sceneItems", "scene_items", default=[])
                    except Exception:
                        group_items = []
                    for group_item in group_items or []:
                        group_source_name = self.obs_response_value(group_item, "sourceName", "source_name")
                        if group_source_name:
                            names.add(str(group_source_name))

        try:
            current = client.get_current_program_scene()
            scene_name = self.obs_response_value(current, "currentProgramSceneName", "current_program_scene_name")
            if scene_name:
                add_scene_items(str(scene_name))
        except Exception:
            pass

        return names

    def audio_input_items(self, client: Any) -> list[dict[str, Any]]:
        resp = client.get_input_list()
        inputs = self.obs_response_value(resp, "inputs", "input_list", "inputList", default=[])
        mixer_names = self.current_audio_mixer_names(client)
        visual_only_kinds = {
            "color_source",
            "image_source",
            "slideshow",
            "text_ft2_source",
            "text_gdiplus",
            "text_gdiplus_v3",
            "window_capture",
        }
        audio_inputs: list[dict[str, Any]] = []
        for item in inputs or []:
            name = self.obs_response_value(item, "inputName", "input_name", "name")
            if not name:
                continue
            name = str(name)
            if mixer_names and name not in mixer_names:
                continue
            kind = self.obs_response_value(item, "inputKind", "input_kind", default="")
            kind = str(kind)
            if kind in visual_only_kinds:
                continue
            try:
                mute_resp = client.get_input_mute(name)
                volume_resp = client.get_input_volume(name)
            except Exception:
                continue
            muted = bool(self.obs_response_value(mute_resp, "inputMuted", "input_muted", default=False))
            volume_mul = self.obs_response_value(volume_resp, "inputVolumeMul", "input_volume_mul", default=1.0)
            try:
                volume_percent = int(round(float(volume_mul) * 100))
            except (TypeError, ValueError):
                volume_percent = 100
            audio_inputs.append({
                "name": name,
                "kind": kind,
                "muted": muted,
                "volume_percent": max(0, min(200, volume_percent)),
            })
        return audio_inputs

    def refresh_audio_controls(self) -> None:
        if self.audio_rows_frame is None:
            return
        self.save_obs_settings()
        try:
            client = obs_crop_service.connect()
            inputs = self.audio_input_items(client)
        except Exception as exc:
            self.audio_status_var.set(f"OBS audio refresh failed: {exc}")
            self.log_status(f"OBS audio refresh failed: {exc}")
            return

        for child in self.audio_rows_frame.winfo_children():
            child.destroy()
        self.audio_rows.clear()

        if not inputs:
            self.audio_status_var.set("No OBS audio-capable inputs found.")
            return

        for row_index, item in enumerate(inputs):
            name = item["name"]
            row = tk.Frame(self.audio_rows_frame, bg=PANEL)
            row.grid(row=row_index, column=0, sticky="ew", pady=3)
            row.columnconfigure(2, weight=1)

            tk.Label(row, text=name, bg=PANEL, fg=TEXT, anchor="w", width=36).grid(row=0, column=0, sticky="w", padx=(0, 8))

            muted_var = tk.BooleanVar(value=bool(item["muted"]))
            mute_button = self.button(row, "Unmute" if muted_var.get() else "Mute", lambda n=name: self.toggle_audio_mute(n), compact=True)
            mute_button.grid(row=0, column=1, sticky="w", padx=(0, 8))

            volume_var = tk.IntVar(value=int(item["volume_percent"]))
            volume_row = tk.Frame(row, bg=PANEL)
            volume_row.grid(row=0, column=2, sticky="ew")
            volume_row.columnconfigure(0, weight=1)
            scale = tk.Scale(
                volume_row,
                from_=0,
                to=200,
                orient="horizontal",
                variable=volume_var,
                bg=PANEL,
                fg=TEXT,
                troughcolor=INPUT_BG,
                activebackground=ACCENT,
                highlightthickness=0,
                length=220,
                showvalue=False,
            )
            scale.grid(row=0, column=0, sticky="ew")
            scale.bind("<ButtonRelease-1>", lambda _event, n=name: self.set_audio_volume(n))
            value_label = tk.Label(volume_row, text=f"{volume_var.get()}%", bg=PANEL, fg=MUTED, width=6, anchor="e")
            value_label.grid(row=0, column=1, sticky="e", padx=(8, 0))
            volume_var.trace_add("write", lambda *_args, v=volume_var, label=value_label: label.config(text=f"{v.get()}%"))

            self.audio_rows[name] = {
                "muted_var": muted_var,
                "mute_button": mute_button,
                "volume_var": volume_var,
            }

        self.audio_rows_frame.columnconfigure(0, weight=1)
        self.audio_status_var.set(f"Loaded {len(inputs)} OBS audio input(s).")
        self.log_status(f"Loaded {len(inputs)} OBS audio input(s).")

    def toggle_audio_mute(self, name: str) -> None:
        row = self.audio_rows.get(name)
        if not row:
            return
        muted_var: tk.BooleanVar = row["muted_var"]
        new_muted = not muted_var.get()
        try:
            client = obs_crop_service.connect()
            client.set_input_mute(name, new_muted)
        except Exception as exc:
            self.audio_status_var.set(f"Could not update {name}: {exc}")
            self.log_status(f"OBS audio mute failed for {name}: {exc}")
            return
        muted_var.set(new_muted)
        row["mute_button"].config(text="Unmute" if new_muted else "Mute")
        self.audio_status_var.set(f"{name}: {'muted' if new_muted else 'unmuted'}")

    def set_audio_volume(self, name: str) -> None:
        row = self.audio_rows.get(name)
        if not row:
            return
        percent = int(row["volume_var"].get())
        try:
            client = obs_crop_service.connect()
            client.set_input_volume(name, vol_mul=max(0.0, percent / 100.0))
        except Exception as exc:
            self.audio_status_var.set(f"Could not set {name} volume: {exc}")
            self.log_status(f"OBS audio volume failed for {name}: {exc}")
            return
        self.audio_status_var.set(f"{name}: volume {percent}%")

    def set_all_audio_mute(self, muted: bool) -> None:
        if not self.audio_rows:
            self.refresh_audio_controls()
        if not self.audio_rows:
            return
        try:
            client = obs_crop_service.connect()
            for name, row in self.audio_rows.items():
                client.set_input_mute(name, muted)
                row["muted_var"].set(muted)
                row["mute_button"].config(text="Unmute" if muted else "Mute")
        except Exception as exc:
            self.audio_status_var.set(f"Could not update all audio inputs: {exc}")
            self.log_status(f"OBS audio mute-all failed: {exc}")
            return
        self.audio_status_var.set("Muted all OBS audio inputs." if muted else "Unmuted all OBS audio inputs.")

    def audio_mapper_sources(self) -> list[dict[str, Any]]:
        choice = self.audio_mapper_layout_var.get().strip().upper()
        if choice == "BOTH":
            sources: list[dict[str, Any]] = []
            seen: set[str] = set()
            for layout in ["2P", "4P"]:
                for source in self.builder_audio_sources(layout):
                    name = str(source.get("name", ""))
                    if name and name not in seen:
                        sources.append(source)
                        seen.add(name)
            return sources
        if choice in {"2P", "4P"}:
            return self.builder_audio_sources(choice)
        layout = app_state.normalize_layout(self.mode_var.get())
        return self.builder_audio_sources(layout)

    def audio_mapper_layouts(self) -> list[str]:
        choice = self.audio_mapper_layout_var.get().strip().upper()
        if choice == "BOTH":
            return ["2P", "4P"]
        if choice in {"2P", "4P"}:
            return [choice]
        return [app_state.normalize_layout(self.mode_var.get())]

    def ensure_audio_mapper_sources(self, client: Any) -> list[str]:
        supported_kinds = self.supported_obs_input_kinds(client)
        snapshot = self.scan_obs_snapshot(client)
        scene_names = set(snapshot["scenes"])
        source_names = set(snapshot["all_sources"])
        lines: list[str] = []
        for layout in self.audio_mapper_layouts():
            scene_name = f"{layout} Restream"
            if scene_name not in scene_names:
                try:
                    client.create_scene(scene_name)
                    scene_names.add(scene_name)
                    source_names.add(scene_name)
                    lines.append(f"CREATE  {scene_name}")
                except Exception as exc:
                    lines.append(f"FAILED  {scene_name}: {exc}")
                    continue
            scene_items = self.scene_item_map(client, scene_name)
            for source in self.builder_audio_sources(layout):
                source_name = str(source.get("name", ""))
                if self.audio_mapper_rows and source_name not in self.audio_mapper_rows:
                    continue
                try:
                    lines.append(self.create_or_add_audio_source(client, scene_name, source, source_names, scene_items, supported_kinds))
                except Exception as exc:
                    lines.append(f"FAILED  {source_name}: {exc}")
        return lines

    def obs_property_items(self, client: Any, source_name: str, prop_name: str) -> list[dict[str, Any]]:
        try:
            resp = client.get_input_properties_list_property_items(source_name, prop_name)
        except Exception:
            return []
        items = self.obs_response_value(resp, "propertyItems", "property_items", "items", default=[])
        result: list[dict[str, Any]] = []
        for item in items or []:
            name = self.obs_response_value(item, "itemName", "item_name", "name")
            value = self.obs_response_value(item, "itemValue", "item_value", "value", default=name)
            enabled = bool(self.obs_response_value(item, "itemEnabled", "item_enabled", "enabled", default=True))
            if name is not None and value is not None:
                result.append({"name": str(name), "value": str(value), "enabled": enabled})
        return result

    def obs_input_settings(self, client: Any, source_name: str) -> dict[str, Any]:
        try:
            resp = client.get_input_settings(source_name)
        except Exception:
            return {}
        settings = self.obs_response_value(resp, "inputSettings", "input_settings", default={})
        return settings if isinstance(settings, dict) else {}

    def ensure_combo_value(self, values: list[str], current: str) -> list[str]:
        if current and current not in values:
            return [current] + values
        return values

    def preferred_audio_window_value(self, source_name: str, current: str, items: list[dict[str, Any]]) -> str:
        enabled_values = {item["value"] for item in items if item["enabled"]}
        if current in enabled_values:
            return current
        match = re.search(r"\bR([1-4])\s+Audio\b", source_name, re.I)
        if not match:
            return current
        needle = f"RUNNER {match.group(1)} - VLC media player"
        for item in items:
            if item["enabled"] and needle in item["value"]:
                return item["value"]
        for item in items:
            if item["enabled"] and needle in item["name"]:
                return item["value"]
        if current.startswith("[vlc.exe]:") or not current:
            return f"{needle}:Qt5QWindowIcon:vlc.exe"
        return current

    def load_audio_mapper(self) -> None:
        if self.audio_mapper_frame is None:
            return
        try:
            client = obs_crop_service.connect()
        except Exception as exc:
            self.audio_mapper_status_var.set(f"OBS not connected: {exc}")
            return

        for child in self.audio_mapper_frame.winfo_children():
            child.destroy()
        self.audio_mapper_rows.clear()

        row_index = 0
        for source in self.audio_mapper_sources():
            source_name = str(source["name"])
            kind = str(source["kind"])
            settings = self.obs_input_settings(client, source_name)
            current_window = str(settings.get("window", source.get("settings", {}).get("window", "")) or "")
            current_priority = str(settings.get("priority", source.get("settings", {}).get("priority", 0)))
            current_device = str(settings.get("device_id", source.get("settings", {}).get("device_id", "")) or "")
            if str(source.get("kind")) == "wasapi_process_output_capture" and re.search(r"\bR[1-4]\s+Audio\b", source_name, re.I):
                current_priority = str(source.get("settings", {}).get("priority", 1))

            row = tk.Frame(self.audio_mapper_frame, bg=PANEL)
            row.grid(row=row_index, column=0, sticky="ew", pady=3)
            row.columnconfigure(1, weight=1)
            tk.Label(row, text=source_name, bg=PANEL, fg=TEXT, anchor="w", width=18).grid(row=0, column=0, sticky="w", padx=(0, 8))

            window_var = tk.StringVar(value=current_window or current_device)
            priority_var = tk.StringVar(value=current_priority)

            if kind == "wasapi_input_capture":
                items = self.obs_property_items(client, source_name, "device_id")
                item_values = [item["value"] for item in items if item["enabled"]]
                item_labels = {item["value"]: item["name"] for item in items}
                values = self.ensure_combo_value(item_values, current_device)
                target_combo = ttk.Combobox(row, textvariable=window_var, values=values, state="readonly" if values else "normal")
                target_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), ipady=5)
                priority_combo = ttk.Combobox(row, textvariable=priority_var, values=[""], state="disabled", width=28)
                priority_combo.grid(row=0, column=2, sticky="w", padx=(0, 8), ipady=5)
                row_data = {"source": source, "target_var": window_var, "priority_var": priority_var, "labels": item_labels}
            elif kind == "audio_capture":
                current_text = ", ".join(source.get("settings", {}).get("executable_list", []))
                window_var.set(current_text)
                tk.Label(row, text=current_text, bg=INPUT_BG, fg=TEXT, anchor="w").grid(row=0, column=1, sticky="ew", padx=(0, 8), ipady=8)
                priority_combo = ttk.Combobox(row, textvariable=priority_var, values=["Managed by executable list"], state="disabled", width=34)
                priority_combo.set("Managed by executable list")
                priority_combo.grid(row=0, column=2, sticky="w", padx=(0, 8), ipady=5)
                row_data = {"source": source, "target_var": window_var, "priority_var": priority_var, "labels": {}}
            else:
                items = self.obs_property_items(client, source_name, "window")
                item_values = [item["value"] for item in items if item["enabled"]]
                item_labels = {item["value"]: item["name"] for item in items}
                current_window = self.preferred_audio_window_value(source_name, current_window, items)
                window_var.set(current_window)
                values = self.ensure_combo_value(item_values, current_window)
                target_combo = ttk.Combobox(row, textvariable=window_var, values=values, state="readonly" if values else "normal")
                target_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), ipady=5)
                priority_combo = ttk.Combobox(
                    row,
                    textvariable=priority_var,
                    values=["1 - Window title must match", "0 - Match title, otherwise same type", "2 - Match title, otherwise same executable"],
                    state="readonly",
                    width=34,
                )
                if priority_var.get() in {"0", "1", "2"}:
                    priority_combo.set({
                        "1": "1 - Window title must match",
                        "0": "0 - Match title, otherwise same type",
                        "2": "2 - Match title, otherwise same executable",
                    }[priority_var.get()])
                priority_combo.grid(row=0, column=2, sticky="w", padx=(0, 8), ipady=5)
                row_data = {"source": source, "target_var": window_var, "priority_var": priority_var, "labels": item_labels}

            self.audio_mapper_rows[source_name] = row_data
            row_index += 1

        self.audio_mapper_frame.columnconfigure(0, weight=1)
        self.audio_mapper_status_var.set(f"Loaded {len(self.audio_mapper_rows)} audio mapping row(s).")

    def priority_value_from_label(self, value: str) -> int:
        match = re.match(r"^\s*([0-2])\b", value)
        if match:
            return int(match.group(1))
        try:
            return int(value)
        except Exception:
            return 0

    def apply_audio_mapper(self) -> None:
        if not self.audio_mapper_rows:
            self.load_audio_mapper()
        if not self.audio_mapper_rows:
            return
        try:
            client = obs_crop_service.connect()
        except Exception as exc:
            self.audio_mapper_status_var.set(f"OBS not connected: {exc}")
            return

        applied = 0
        ensure_lines = self.ensure_audio_mapper_sources(client)
        failed: list[str] = [line for line in ensure_lines if line.startswith("FAILED")]
        for source_name, row in self.audio_mapper_rows.items():
            source = row["source"]
            kind = str(source["kind"])
            target = str(row["target_var"].get()).strip()
            if not target:
                continue
            if kind == "wasapi_input_capture":
                settings = {"device_id": target, "use_device_timing": False}
            elif kind == "audio_capture":
                settings = {"exclude": False, "mode": 0, "executable_list": source.get("settings", {}).get("executable_list", [])}
            else:
                settings = {"window": target, "priority": self.priority_value_from_label(str(row["priority_var"].get()))}
            try:
                client.set_input_settings(source_name, settings, True)
                client.set_input_mute(source_name, True)
                applied += 1
            except Exception as exc:
                failed.append(f"{source_name}: {exc}")

        if failed:
            self.audio_mapper_status_var.set(f"Applied {applied}; {len(failed)} failed.")
            messagebox.showwarning("Audio mapping", "\n".join(failed[:8]))
        else:
            created_or_added = len([line for line in ensure_lines if line.startswith(("CREATE", "ADD"))])
            self.audio_mapper_status_var.set(f"Applied {applied} audio mapping(s). {created_or_added} source(s) created/added. Sources remain muted.")

    def runner_mapping_for_crops(self, mode: int | None = None, selected: dict[int, Any] | None = None) -> tuple[str, dict[str, dict[str, str]]]:
        if selected:
            layout = app_state.normalize_layout(mode)
            runners = {
                str(slot): {
                    "display_name": str(getattr(runner, "display_name", "")).strip(),
                    "twitch_name": str(getattr(runner, "twitch_name", "")).strip(),
                }
                for slot, runner in selected.items()
                if runner
            }
            return layout, runners

        race = app_state.load_current_race()
        runners = race.get("runners", {})
        if not isinstance(runners, dict) or not runners:
            raise RuntimeError("Launch/write a race first so runner slots are saved.")
        return app_state.normalize_layout(race.get("mode")), runners

    def apply_saved_crops(self, mode: int | None = None, selected: dict[int, Any] | None = None) -> tuple[int, list[str], str, list[str]]:
        layout, runners = self.runner_mapping_for_crops(mode, selected)
        client = obs_crop_service.connect()
        client.get_version()
        locations = obs_crop_service.find_crop_targets(client)

        applied = 0
        missing = []
        applied_map = []
        for slot_raw, runner in sorted(runners.items(), key=lambda item: int(item[0])):
            if not isinstance(runner, dict):
                continue
            twitch = (runner.get("twitch_name") or "").strip()
            display = runner.get("display_name") or twitch or f"Runner {slot_raw}"
            if not twitch:
                missing.append(f"R{slot_raw} {display}: missing Twitch name")
                continue
            for part in self.crop_parts_for_layout(layout):
                source = f"{layout} R{slot_raw} {part}"
                preset = app_state.get_crop_preset(twitch, part, layout)
                if not preset:
                    missing.append(f"R{slot_raw} {display}: {part}")
                    continue
                try:
                    crop = obs_crop_service.crop_tuple_from_preset(preset)
                    obs_crop_service.set_crop(client, locations, source, crop)
                    applied += 1
                    if part == "Stream":
                        applied_map.append(f"R{slot_raw}={display}")
                except Exception as exc:
                    missing.append(f"{source}: {exc}")
        return applied, missing, layout, applied_map

    def apply_saved_crops_after_launch(self, mode: int, selected: dict[int, Any]) -> None:
        try:
            applied, missing, layout, applied_map = self.apply_saved_crops(mode, selected)
        except Exception as exc:
            self.log_status(f"Streams launched. Saved crops were not auto-applied: {exc}")
            return
        mapping = " | " + ", ".join(applied_map) if applied_map else ""
        if applied:
            self.log_status(f"Launched streams and auto-applied {applied} saved OBS crop(s) for {layout}.{mapping}")
        elif missing:
            self.log_status(f"Launched streams. No saved OBS crops found yet for {layout}.")
        else:
            self.log_status(f"Launched streams. No saved OBS crops to apply for {layout}.")

    def apply_saved_crops_after_replace(self, slot: int, runner: Any) -> None:
        race = app_state.load_current_race()
        try:
            mode = int(race.get("mode") or self.mode_var.get() or 4)
        except ValueError:
            mode = 4
        try:
            applied, missing, layout, applied_map = self.apply_saved_crops(mode, {slot: runner})
        except Exception as exc:
            self.log_status(f"Replaced Runner {slot}. Saved crops were not auto-applied: {exc}")
            return
        mapping = " | " + ", ".join(applied_map) if applied_map else ""
        if applied:
            self.log_status(f"Replaced Runner {slot} and auto-applied {applied} saved OBS crop(s) for {layout}.{mapping}")
        elif missing:
            self.log_status(f"Replaced Runner {slot}. No saved OBS crops found yet for {layout}.")
        else:
            self.log_status(f"Replaced Runner {slot}. No saved OBS crops to apply for {layout}.")

    def apply_saved_crops_from_main(self) -> None:
        try:
            applied, missing, layout, applied_map = self.apply_saved_crops()
        except Exception as exc:
            messagebox.showerror("Apply saved crops failed", str(exc))
            return
        mapping = " | " + ", ".join(applied_map) if applied_map else ""
        self.log_status(f"Applied {applied} saved OBS crop(s) for {layout}.{mapping}")
        if missing:
            messagebox.showinfo("Apply saved crops", f"Applied {applied} crop(s).\n\nMissing or failed:\n" + "\n".join(missing))
        else:
            messagebox.showinfo("Apply saved crops", f"Applied all {applied} saved crop(s) for {layout}.")

    def streamlink_available(self) -> bool:
        return shutil.which("streamlink") is not None

    def vlc_available(self) -> bool:
        vlc_candidates = [
            Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe"),
            Path(r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"),
        ]
        return any(path.exists() for path in vlc_candidates) or shutil.which("vlc") is not None

    def launch_prereq_errors(self) -> list[str]:
        errors = []
        if not self.streamlink_available():
            errors.append("Streamlink was not found. Install Streamlink or add it to PATH.")
        if not self.vlc_available():
            errors.append("VLC was not found. Install VLC or add vlc.exe to PATH.")
        return errors

    def partition_available_streams(self, selected: dict[int, Any], slots: Any) -> tuple[list[int], list[str]]:
        available_slots = []
        errors = []
        for slot in slots:
            slot_int = int(slot)
            runner = selected.get(slot_int)
            if not runner:
                continue
            self.log_status(f"Checking Runner {slot} stream: {runner.display_name}...")
            self.update_idletasks()
            ok, detail = self.check_twitch_stream_available(runner.twitch_name)
            if ok:
                available_slots.append(slot_int)
            else:
                errors.append(f"Runner {slot} {runner.display_name}: {detail}")
        if available_slots:
            self.log_status(f"Stream availability check passed for {len(available_slots)} slot(s).")
        return available_slots, errors

    def check_twitch_stream_available(self, twitch_name: str) -> tuple[bool, str]:
        twitch = str(twitch_name or "").strip().lstrip("@")
        if not twitch:
            return False, "missing Twitch name"
        command = ["streamlink", "--json", f"https://twitch.tv/{twitch}"]
        try:
            result = subprocess.run(
                command,
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=12,
                creationflags=hidden_creationflags(),
            )
        except subprocess.TimeoutExpired:
            return False, "Streamlink timed out while checking the channel"
        except FileNotFoundError:
            return False, "Streamlink was not found"
        except Exception as exc:
            return False, str(exc)

        output = (result.stdout or "").strip()
        if result.returncode != 0:
            detail = self.parse_streamlink_error(result.stdout, result.stderr)
            return False, detail

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return True, "Streamlink returned stream data"
        streams = data.get("streams") if isinstance(data, dict) else None
        if isinstance(streams, dict) and streams:
            return True, "live"
        return False, "no playable streams found; the channel may be offline"

    def parse_streamlink_error(self, stdout: str, stderr: str) -> str:
        raw = (stderr or stdout or "").strip()
        for text in [stdout, stderr]:
            text = (text or "").strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                for key in ["error", "message", "error_message"]:
                    value = data.get(key)
                    if value:
                        return str(value).strip()
        for line in raw.splitlines():
            clean_line = line.strip()
            if clean_line and clean_line not in {"{", "}"}:
                return clean_line
        return "Streamlink could not find playable streams"

    def preflight_results(self, include_obs: bool = True) -> list[tuple[bool, str]]:
        obs_ok = False
        try:
            if include_obs:
                client = obs_crop_service.connect()
                client.get_version()
                obs_ok = True
        except Exception:
            obs_ok = False
        results = [
            (bundled_or_exists(CONTROL_SCRIPT), "Launcher module"),
            (bundled_or_exists(SYNC_TOOL), "Sync module"),
            (SCREENSHOT_SCRIPT.exists(), f"Screenshot helper: {SCREENSHOT_SCRIPT}"),
            (RUNNERS_CSV.exists(), f"Runner CSV: {RUNNERS_CSV}"),
            (app_state.IS_FROZEN or CROPPING_TOOL.exists() or LEGACY_CROPPING_TOOL.exists(), "Cropping module"),
            (importlib.util.find_spec("PIL") is not None, "Python package: Pillow"),
            (importlib.util.find_spec("obsws_python") is not None, "Python package: obsws-python"),
            (self.streamlink_available(), "Command available: streamlink"),
            (self.vlc_available(), "VLC installed or available on PATH"),
        ]
        if include_obs:
            results.append((obs_ok, "OBS websocket connection"))
        else:
            results.append((True, "OBS websocket connection: not checked"))
        return results

    def check_required_files(self) -> None:
        results = self.preflight_results()
        ok_lines = [label for ok, label in results if ok]
        missing = [label for ok, label in results if not ok]
        message = "OK:\n" + "\n".join(ok_lines)
        message += f"\n\nOBS text output folder:\n{OBS_TEXT_DIR}"
        message += f"\n\nScreenshot folder:\n{SCREENSHOT_DIR}"
        message += "\n\nMake sure OBS text sources point at the OBS text output folder above."
        if missing:
            message += "\n\nMissing:\n" + "\n".join(missing)
            messagebox.showwarning("Preflight check", message)
        else:
            messagebox.showinfo("Preflight check", message)

    def diagnostics_report(self) -> str:
        lines = [
            "Restream Control Diagnostics",
            "-" * 32,
            f"Packaged exe: {'yes' if app_state.IS_FROZEN else 'no'}",
            f"Python: {sys.version.split()[0]}",
            f"Platform: {sys.platform}",
            f"App folder: {BASE_DIR}",
            f"Repo/root folder: {REPO_ROOT}",
            f"Runner CSV: {RUNNERS_CSV} ({'found' if RUNNERS_CSV.exists() else 'missing'})",
            f"OBS text folder: {OBS_TEXT_DIR}",
            f"Screenshot folder: {SCREENSHOT_DIR}",
            f"State folder: {app_state.STATE_DIR}",
            f"VLC found: {'yes' if self.vlc_available() else 'no'}",
            f"Streamlink found: {'yes' if self.streamlink_available() else 'no'}",
        ]
        obs_config = app_state.load_config().get("obs_websocket", {})
        if isinstance(obs_config, dict):
            lines.append(f"OBS websocket: {obs_config.get('host', 'localhost')}:{obs_config.get('port', 4455)}")
        lines.append("")
        lines.append("Checks:")
        for ok, label in self.preflight_results(include_obs=True):
            lines.append(f"{'OK' if ok else 'MISSING'} - {label}")
        if app_state.CRASH_LOG_FILE.exists():
            lines.append("")
            lines.append(f"Crash log: {app_state.CRASH_LOG_FILE}")
        return "\n".join(lines)

    def copy_diagnostics(self) -> None:
        report = self.diagnostics_report()
        self.clipboard_clear()
        self.clipboard_append(report)
        self.log_status("Copied diagnostics to clipboard.")
        messagebox.showinfo("Diagnostics", "Copied diagnostics to clipboard.")

    def refresh_status(self) -> None:
        # Reload module so app picks up launcher changes after replacement.
        self.launch_mod = load_launch_module()
        pieces = []
        pieces.append(f"Folder: {BASE_DIR}")
        pieces.append("Launcher: " + ("OK" if bundled_or_exists(CONTROL_SCRIPT) else "Missing"))
        pieces.append("Runners: " + ("OK" if RUNNERS_CSV.exists() else "Missing"))
        pieces.append("Cropping: " + ("OK" if (app_state.IS_FROZEN or CROPPING_TOOL.exists() or LEGACY_CROPPING_TOOL.exists()) else "Missing"))
        pieces.append("Sync: " + ("OK" if bundled_or_exists(SYNC_TOOL) else "Missing"))
        self.status_var.set("  |  ".join(pieces))
        self.update_dashboard(include_obs=True)
        if hasattr(self, "checklist_text"):
            self.refresh_checklist(include_obs=False)
        if self.name_vars:
            self.reload_names()


def log_crash(exc: BaseException) -> None:
    app_state.ensure_state_dir()
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    app_state.CRASH_LOG_FILE.write_text(details, encoding="utf-8")


if __name__ == "__main__":
    try:
        app = RestreamApp()
        app.mainloop()
    except Exception as exc:
        log_crash(exc)
        raise
