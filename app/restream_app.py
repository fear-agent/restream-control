#!/usr/bin/env python3
"""
Restream Control App v3.1
Styling cleanup for setup controls; no functional changes.
Keeps the proven external Cropping Tool, Sync Tool, and screenshot helper.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

import app_state
import obs_crop_service

APP_TITLE = "Restream Control"
BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
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


def load_launch_module() -> Optional[Any]:
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
        self.geometry("1240x780")
        self.minsize(1040, 680)
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
        self.dashboard_crops_var = tk.StringVar(value="Crops: -")
        self.dashboard_screenshots_var = tk.StringVar(value="Screenshots: -")
        self.mode_var = tk.StringVar(value="4")
        self.comms_var = tk.StringVar()
        self.replace_slot_var = tk.StringVar(value="1")
        obs_config = app_state.load_config().get("obs_websocket", {})
        self.obs_host_var = tk.StringVar(value=str(obs_config.get("host", "localhost")))
        self.obs_port_var = tk.StringVar(value=str(obs_config.get("port", 4455)))
        self.obs_password_var = tk.StringVar(value=str(obs_config.get("password", "")))
        self.edit_runner_var = tk.StringVar()
        self.edit_display_var = tk.StringVar()
        self.edit_twitch_var = tk.StringVar()
        self.edit_aliases_var = tk.StringVar()
        self.source_map_text: Optional[tk.Text] = None

        self._setup_style()
        self._build()
        self.load_runners_into_setup()
        self.show_page("Setup")
        self.refresh_status()

    def log_status(self, message: str) -> None:
        self.status_var.set(message)
        self.log_var.set(message)
        app_state.append_log(message)
        self.update_dashboard(include_obs=False)

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
            background=[("readonly", PANEL_2), ("active", ACCENT), ("!disabled", PANEL_2)],
            arrowcolor=[("disabled", MUTED), ("readonly", TEXT), ("active", "white"), ("!disabled", TEXT)],
        )
        self.option_add("*TCombobox*Listbox.background", INPUT_BG)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "white")
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

    def _build(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True)

        sidebar = tk.Frame(root, bg=SIDEBAR, width=190)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        title = tk.Label(sidebar, text="Restream\nControl", bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 18, "bold"), justify="left")
        title.pack(anchor="w", padx=18, pady=(18, 16))

        for name in ["Setup", "Checklist", "Names", "Settings"]:
            btn = tk.Button(
                sidebar,
                text=name,
                anchor="w",
                relief="flat",
                bd=0,
                bg=SIDEBAR,
                fg=TEXT,
                activebackground=ACCENT,
                activeforeground="white",
                font=("Segoe UI", 11),
                padx=18,
                pady=10,
                command=lambda n=name: self.show_page(n),
            )
            btn.pack(fill="x", padx=8, pady=2)
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
            self.dashboard_crops_var,
            self.dashboard_screenshots_var,
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

        for name in ["Setup", "Checklist", "Names", "Settings"]:
            page = ScrollablePage(self.page_container)
            self.pages[name] = page
            self.page_bodies[name] = page.inner

        self._build_setup(self.page_bodies["Setup"])
        self._build_checklist(self.page_bodies["Checklist"])
        self._build_names(self.page_bodies["Names"])
        self._build_settings(self.page_bodies["Settings"])

    def show_page(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.page_title.config(text=name)
        self.current_page = name
        for key, btn in self.nav_buttons.items():
            if key == name:
                btn.config(bg=ACCENT, fg="white", font=("Segoe UI", 11, "bold"))
            else:
                btn.config(bg=SIDEBAR, fg=TEXT, font=("Segoe UI", 11))

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
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=BORDER,
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
        self.button(actions, "Write Names Only", self.write_names_only).pack(side="left", padx=8)
        self.button(actions, "Clear Fields", self.clear_runner_fields).pack(side="left", padx=8)
        self.button(actions, "Open Cropping Tool", self.open_cropping_tool).pack(side="right", padx=(8, 0))
        self.button(actions, "Open Sync Tool", self.open_sync_tool).pack(side="right", padx=(8, 0))

        p2 = self.panel(parent, "Replace One Runner")
        rr = tk.Frame(p2, bg=PANEL)
        rr.pack(fill="x", padx=16, pady=(4, 16))
        tk.Label(rr, text="Slot", bg=PANEL, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 8))
        slot_combo = ttk.Combobox(rr, textvariable=self.replace_slot_var, values=["1", "2", "3", "4"], width=8, state="readonly")
        slot_combo.pack(side="left", padx=(0, 12), ipady=5)
        self.button(rr, "Replace Selected Slot", self.replace_from_gui, primary=True).pack(side="left", padx=(0, 8))
        tk.Label(rr, text="Uses that slot's runner row above.", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")

        self.update_mode()

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
        self.button(actions, "Open Cropping Tool", self.open_cropping_tool).pack(side="left", padx=8)

        actions2 = tk.Frame(p, bg=PANEL)
        actions2.pack(fill="x", padx=16, pady=(0, 10))
        self.button(actions2, "Open Sync Tool", self.open_sync_tool).pack(side="left", padx=(0, 8))
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

        runner_panel = self.panel(parent, "Runner List")
        edit_top = tk.Frame(runner_panel, bg=PANEL)
        edit_top.pack(fill="x", padx=16, pady=(4, 8))
        self.edit_runner_combo = ttk.Combobox(edit_top, textvariable=self.edit_runner_var, state="readonly", width=42)
        self.edit_runner_combo.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        self.edit_runner_combo.bind("<<ComboboxSelected>>", self.load_runner_editor_selection)
        self.button(edit_top, "Reload", self.refresh_runner_editor, compact=True).pack(side="left")

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
            # Also reflect the same values in the Names tab immediately.
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

    def replace_from_gui(self) -> None:
        mod = self.launch_mod
        if not mod:
            messagebox.showerror("Missing launcher", "launch_crosskeys.py could not be loaded.")
            return
        try:
            slot = int(self.replace_slot_var.get())
            runner = self.runner_rows[slot].to_runner()
            errors = self.launch_prereq_errors()
            if errors:
                messagebox.showerror("Replace blocked", "\n".join(errors))
                self.log_status("Replace blocked: " + "; ".join(errors))
                return
            _available_slots, stream_errors = self.partition_available_streams({slot: runner}, [slot])
            if stream_errors:
                messagebox.showerror("Stream unavailable", "\n".join(stream_errors))
                self.log_status("Replace blocked: " + "; ".join(stream_errors))
                return
            self.save_new_runners_to_list({slot: runner})
            if not messagebox.askyesno("Replace runner", f"Close and relaunch RUNNER {slot} as {runner.display_name}? "):
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
            self.log_status(f"Replaced Runner {slot}: {runner.display_name}")
            self.apply_saved_crops_after_replace(slot, runner)
        except Exception as exc:
            messagebox.showerror("Replace failed", str(exc))

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
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}]
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
            return len([p for p in SCREENSHOT_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}])
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
            for part in ["Stream", "Tracker", "Timer"]:
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
        self.dashboard_crops_var.set(f"Crops: {found} OK / {missing} missing")
        self.dashboard_screenshots_var.set(f"Screenshots: {self.screenshot_count()}")
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
            for part in ["Stream", "Tracker", "Timer"]:
                if app_state.get_crop_preset(twitch, part, layout):
                    found += 1
                    parts.append(f"{part}=OK")
                else:
                    missing += 1
                    parts.append(f"{part}=MISSING")
            lines.append(f"R{slot} {display}: " + ", ".join(parts))
        lines.append(f"Crop preset summary: {found} found, {missing} missing for {layout}")
        return lines

    def obs_source_health_lines(self, layout: str) -> list[str]:
        lines = ["", "OBS Sources"]
        expected_slots = ["1", "2"] if layout == "2P" else ["1", "2", "3", "4"]
        expected = [f"{layout} R{slot} {part}" for slot in expected_slots for part in ["Stream", "Tracker", "Timer"]]
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
            data = json.loads(Path(path).read_text(encoding="utf-8"))
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
        self.load_source_map_editor()

    def default_source_map(self) -> dict[str, str]:
        return {name: name for name in obs_crop_service.ALL_TARGETS}

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
        lines.extend(f"{logical} = {source_map.get(logical, logical)}" for logical in obs_crop_service.ALL_TARGETS)
        extra = sorted(str(key) for key in source_map if key not in obs_crop_service.ALL_TARGETS)
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
        lines.extend(f"{name} = {name}" for name in obs_crop_service.ALL_TARGETS)
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
            for part in ["Stream", "Tracker", "Timer"]:
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
            (CONTROL_SCRIPT.exists(), f"Launcher script: {CONTROL_SCRIPT}"),
            (SYNC_TOOL.exists(), f"Sync tool: {SYNC_TOOL}"),
            (SCREENSHOT_SCRIPT.exists(), f"Screenshot helper: {SCREENSHOT_SCRIPT}"),
            (RUNNERS_CSV.exists(), f"Runner CSV: {RUNNERS_CSV}"),
            (CROPPING_TOOL.exists() or LEGACY_CROPPING_TOOL.exists(), "Cropping tool script"),
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

    def refresh_status(self) -> None:
        # Reload module so app picks up launcher changes after replacement.
        self.launch_mod = load_launch_module()
        pieces = []
        pieces.append(f"Folder: {BASE_DIR}")
        pieces.append("Launcher: " + ("OK" if CONTROL_SCRIPT.exists() else "Missing"))
        pieces.append("Runners: " + ("OK" if RUNNERS_CSV.exists() else "Missing"))
        pieces.append("Cropping: " + ("OK" if (CROPPING_TOOL.exists() or LEGACY_CROPPING_TOOL.exists()) else "Missing"))
        pieces.append("Sync: " + ("OK" if SYNC_TOOL.exists() else "Missing"))
        self.status_var.set("  |  ".join(pieces))
        self.update_dashboard(include_obs=True)
        if hasattr(self, "checklist_text"):
            self.refresh_checklist(include_obs=False)
        if self.name_vars:
            self.reload_names()


if __name__ == "__main__":
    app = RestreamApp()
    app.mainloop()
