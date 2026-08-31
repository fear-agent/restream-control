import os
import json
import re
import subprocess
import time
import base64
from io import BytesIO
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

import app_state
import obs_crop_service
import stream_syncer

try:
    _dwmapi = stream_syncer.ctypes.WinDLL("dwmapi", use_last_error=True)
    _DwmGetWindowAttribute = _dwmapi.DwmGetWindowAttribute
    _DwmGetWindowAttribute.argtypes = [
        stream_syncer.wintypes.HWND,
        stream_syncer.wintypes.DWORD,
        stream_syncer.ctypes.c_void_p,
        stream_syncer.wintypes.DWORD,
    ]
    _DwmGetWindowAttribute.restype = stream_syncer.wintypes.HRESULT
except Exception:
    _DwmGetWindowAttribute = None

DWMWA_EXTENDED_FRAME_BOUNDS = 9

try:
    import obsws_python as obs
except Exception:
    obs = None

APP_TITLE = "Cropping Tool"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 4455
ROOT_DIR = str(app_state.APP_DIR)
CONFIG_FILE = str(app_state.CROPPING_CONFIG_FILE)
SCREENSHOT_DIR = str(app_state.config_path("screenshot_dir"))

BG = "#101113"
PANEL = "#202327"
PANEL_2 = "#2a2f35"
INPUT_BG = "#111315"
TEXT = "#f9fafb"
MUTED = "#9ca3af"
ACCENT = "#0f766e"
BORDER = "#3f454b"

TARGETS_4P = [
    ("4P R1 Stream", "4P", "R1", "Stream"),
    ("4P R1 Tracker", "4P", "R1", "Tracker"),
    ("4P R1 Timer", "4P", "R1", "Timer"),
    ("4P R2 Stream", "4P", "R2", "Stream"),
    ("4P R2 Tracker", "4P", "R2", "Tracker"),
    ("4P R2 Timer", "4P", "R2", "Timer"),
    ("4P R3 Stream", "4P", "R3", "Stream"),
    ("4P R3 Tracker", "4P", "R3", "Tracker"),
    ("4P R3 Timer", "4P", "R3", "Timer"),
    ("4P R4 Stream", "4P", "R4", "Stream"),
    ("4P R4 Tracker", "4P", "R4", "Tracker"),
    ("4P R4 Timer", "4P", "R4", "Timer"),
]

TARGETS_2P = [
    ("2P R1 Stream", "2P", "R1", "Stream"),
    ("2P R1 Tracker", "2P", "R1", "Tracker"),
    ("2P R1 Timer", "2P", "R1", "Timer"),
    ("2P R2 Stream", "2P", "R2", "Stream"),
    ("2P R2 Tracker", "2P", "R2", "Tracker"),
    ("2P R2 Timer", "2P", "R2", "Timer"),
]

ALL_TARGETS = obs_crop_service.all_target_names()
EMPTY_CROP_TEXT = "Left: -    Right: -\nTop: -     Bottom: -"


def load_config():
    app_config = app_state.load_config()
    obs_config = app_config.get("obs_websocket", {})
    if not os.path.exists(CONFIG_FILE):
        return {
            "host": obs_config.get("host", DEFAULT_HOST),
            "port": obs_config.get("port", DEFAULT_PORT),
            "password": obs_config.get("password", ""),
        }
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "host": data.get("host", DEFAULT_HOST),
            "port": int(data.get("port", DEFAULT_PORT)),
            "password": data.get("password", ""),
        }
    except Exception:
        return {"host": DEFAULT_HOST, "port": DEFAULT_PORT, "password": ""}


def save_config(host, port, password):
    config = app_state.load_config()
    config["obs_websocket"] = {"host": host, "port": int(port), "password": password}
    app_state.save_config(config)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"host": host, "port": int(port), "password": password}, f, indent=2)
    except Exception:
        pass


class CropPanel(tk.Frame):
    def __init__(self, parent, standalone=False):
        super().__init__(parent, bg=BG)
        self.root = self.winfo_toplevel()
        if standalone:
            self.root.title(APP_TITLE)
            self.root.geometry("1280x760")
            self.root.minsize(1000, 620)
            self.root.configure(bg=BG)

        self.client = None
        self.connected = False
        self.source_locations = {}
        self.current_race = app_state.load_current_race()
        self.current_race_mtime = self.current_race_file_mtime()
        self.runner_option_slots = {}

        self.image = None
        self.tk_image = None
        self.image_path = None
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.rect_id = None
        self.start_x = None
        self.start_y = None
        self.crop = None
        self.runner_crop_slot_var = tk.StringVar()
        self.active_runner_var = tk.StringVar(value="No runner selected")
        self.runner_crop_part_var = tk.StringVar(value="Stream")
        self.capture_mode_var = tk.StringVar(value=str(app_state.load_config().get("playback_engine", "VLC Windows")))
        self.capture_playback_var = tk.StringVar()
        self.screenshot_button_text = tk.StringVar(value="Take Screenshot")
        self.instructions_var = tk.StringVar()
        self.part_status_vars = {}
        self.part_rows = {}
        self.part_apply_buttons = {}
        self.part_status_labels = {}
        self.show_obs_settings_var = tk.BooleanVar(value=False)

        self.config_data = load_config()
        self._setup_style()
        self._build_ui()
        self.refresh_memory_status()
        self.bind_all("<FocusIn>", self.on_focus_refresh_race)
        self.after(400, self.connect_to_obs)

    def current_race_file_mtime(self):
        try:
            return app_state.CURRENT_RACE_FILE.stat().st_mtime
        except FileNotFoundError:
            return None

    def on_focus_refresh_race(self, _event=None):
        mtime = self.current_race_file_mtime()
        if mtime != self.current_race_mtime:
            self.current_race_mtime = mtime
            self.refresh_current_race()

    def _setup_style(self):
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
        self.style.configure("TEntry", fieldbackground=INPUT_BG, foreground=TEXT, bordercolor=BORDER)
        self.style.configure("TCombobox", fieldbackground=INPUT_BG, background=PANEL_2, foreground=TEXT, arrowcolor=TEXT, padding=(8, 6))
        self.style.map("TCombobox", fieldbackground=[("readonly", INPUT_BG), ("!disabled", INPUT_BG)], foreground=[("readonly", TEXT), ("!disabled", TEXT)])
        self.option_add("*TCombobox*Listbox.background", INPUT_BG)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "white")

    def _build_ui(self):
        content = ttk.Frame(self)
        content.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(content)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(content, width=300)
        right.pack(side=tk.LEFT, fill=tk.Y)
        right.pack_propagate(False)

        topbar = ttk.Frame(left)
        topbar.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(topbar, text="Playback:").pack(side=tk.LEFT, padx=(6, 4))
        ttk.Label(topbar, textvariable=self.capture_playback_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(topbar, textvariable=self.screenshot_button_text, command=self.capture_and_load_selected_slot).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(topbar, text="Refresh OBS Layout", command=self.refresh_obs_layout).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(topbar, text="Delete Current", command=self.delete_current_screenshot).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(topbar, text="Clear Screenshot Folder", command=self.clear_screenshot_folder).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(topbar, text="Reapply This Runner", command=self.apply_all_runner_crops).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(topbar, text="Reapply All Runners", command=self.apply_all_race_crops).pack(side=tk.LEFT, padx=(6,0))
        self.image_label = ttk.Label(topbar, text="No screenshot loaded")
        self.image_label.pack(side=tk.LEFT, padx=10)

        ttk.Label(left, textvariable=self.instructions_var, foreground=MUTED).pack(fill=tk.X, padx=10, pady=(0, 6))

        self.canvas = tk.Canvas(left, bg="#111111", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))
        self.canvas.bind("<Configure>", lambda e: self.redraw_image())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        runner_memory = ttk.LabelFrame(right, text="Runner Crops")
        runner_memory.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(
            runner_memory,
            textvariable=self.active_runner_var,
            font=("Segoe UI", 14, "bold"),
            foreground=TEXT,
            wraplength=270,
        ).pack(fill=tk.X, padx=6, pady=(6, 2))
        self.runner_combo = ttk.Combobox(runner_memory, textvariable=self.runner_crop_slot_var, state="readonly")
        self.runner_combo.pack(fill=tk.X, padx=6, pady=(2, 4))
        self.runner_combo.bind("<<ComboboxSelected>>", lambda _event: self.select_runner_target())

        for label, part in [("Game", "Stream"), ("Tracker", "Tracker"), ("Timer", "Timer"), ("Facecam", "Facecam")]:
            row = ttk.Frame(runner_memory)
            row.pack(fill=tk.X, padx=6, pady=(3, 5))
            self.part_rows[part] = row
            action_row = ttk.Frame(row)
            action_row.pack(fill=tk.X)
            ttk.Label(action_row, text=label, width=8).pack(side=tk.LEFT)
            button = ttk.Button(action_row, text="Apply", command=lambda p=part: self.save_apply_runner_part_crop(p))
            button.pack(side=tk.LEFT)
            self.part_apply_buttons[part] = button
            var = tk.StringVar(value="no current runner")
            self.part_status_vars[part] = var
            status = ttk.Label(row, textvariable=var, foreground=MUTED, wraplength=250)
            status.pack(fill=tk.X, padx=(8, 0), pady=(2, 0))
            self.part_status_labels[part] = status

        results = ttk.LabelFrame(right, text="Current Crop")
        results.pack(fill=tk.X, padx=8, pady=4)
        self.crop_var = tk.StringVar(value=EMPTY_CROP_TEXT)
        ttk.Label(results, textvariable=self.crop_var, justify=tk.LEFT, width=30).pack(anchor="w", padx=6, pady=6)
        self.memory_status_var = tk.StringVar(value="")
        ttk.Label(results, textvariable=self.memory_status_var, wraplength=260).pack(anchor="w", padx=6, pady=(0, 4))

        self.status_var = tk.StringVar(value="Not connected")
        self.status_label = ttk.Label(right, textvariable=self.status_var, foreground="red")
        self.status_label.pack(anchor="w", padx=10, pady=(10, 4))

        obs_toggle = ttk.Checkbutton(
            right,
            text="Show OBS connection settings",
            variable=self.show_obs_settings_var,
            command=self.toggle_obs_settings,
        )
        obs_toggle.pack(anchor="w", padx=8, pady=(6, 2), side=tk.BOTTOM)

        self.conn = ttk.LabelFrame(right, text="OBS Connection")
        row = ttk.Frame(self.conn); row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(row, text="Host").pack(side=tk.LEFT)
        self.host_var = tk.StringVar(value=self.config_data["host"])
        ttk.Entry(row, textvariable=self.host_var, width=12).pack(side=tk.RIGHT)
        row = ttk.Frame(self.conn); row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(row, text="Port").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value=str(self.config_data["port"]))
        ttk.Entry(row, textvariable=self.port_var, width=12).pack(side=tk.RIGHT)
        row = ttk.Frame(self.conn); row.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(row, text="Password").pack(side=tk.LEFT)
        self.password_var = tk.StringVar(value=self.config_data["password"])
        ttk.Entry(row, textvariable=self.password_var, show="*", width=12).pack(side=tk.RIGHT)
        row = ttk.Frame(self.conn); row.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(row, text="Connect", command=self.connect_to_obs).pack(side=tk.LEFT)
        ttk.Button(row, text="Refresh", command=self.refresh_sources).pack(side=tk.LEFT, padx=4)
        self.toggle_obs_settings()

        target_names = obs_crop_service.all_target_names()
        self.target_var = tk.StringVar(value=target_names[0] if target_names else "")
        self.refresh_runner_options()
        self.set_playback_engine(self.capture_mode_var.get(), refresh=False)
        self.update_capture_mode_ui()

    def toggle_obs_settings(self):
        if self.show_obs_settings_var.get():
            self.conn.pack(fill=tk.X, padx=8, pady=8, side=tk.BOTTOM)
        else:
            self.conn.pack_forget()

    def _build_target_tab(self, notebook, label, targets):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=label)
        rows = {}
        for source, _, runner, part in targets:
            if runner not in rows:
                row_frame = ttk.LabelFrame(frame, text=runner)
                row_frame.pack(fill=tk.X, padx=6, pady=5)
                rows[runner] = row_frame
            ttk.Button(rows[runner], text=part, command=lambda s=source: self.apply_target_button(s)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=3, pady=5)

    def set_status(self, text, ok=False):
        self.status_var.set(text)
        self.status_label.configure(foreground=("green" if ok else "red"))

    def connect_to_obs(self):
        if obs is None:
            self.set_status("obsws-python not installed")
            return
        host = self.host_var.get().strip() or DEFAULT_HOST
        try:
            port = int(self.port_var.get().strip() or DEFAULT_PORT)
        except ValueError:
            self.set_status("Invalid port")
            return
        password = self.password_var.get()
        try:
            self.client = obs.ReqClient(host=host, port=port, password=password, timeout=3)
            self.client.get_version()
            self.connected = True
            save_config(host, port, password)
            self.set_status("Connected to OBS", ok=True)
            self.refresh_sources(show_message=False)
        except Exception as e:
            self.client = None
            self.connected = False
            self.set_status(f"Not connected: {e}")

    def refresh_sources(self, show_message=True):
        if not self.client:
            if show_message:
                messagebox.showwarning("Not connected", "Connect to OBS first.")
            return
        self.source_locations = obs_crop_service.find_crop_targets(self.client)
        found = sorted(self.source_locations.keys())
        if found and self.target_var.get() not in found:
            self.target_var.set(found[0])
        self.update_part_statuses()
        if show_message:
            messagebox.showinfo("Sources refreshed", f"Found {len(found)} crop targets in OBS.")

    def ensure_source_location(self, source_name):
        """Refresh once, then reconnect if OBS's scene-item cache is stale."""
        if source_name in self.source_locations:
            return self.source_locations[source_name]
        try:
            self.refresh_sources(show_message=False)
        except Exception:
            pass
        if source_name in self.source_locations:
            return self.source_locations[source_name]

        self.client = None
        self.connected = False
        self.connect_to_obs()
        return self.source_locations.get(source_name)

    def refresh_obs_layout(self):
        """Reload current OBS crop items after a custom layout change."""
        if not self.client or not self.connected:
            self.connect_to_obs()
        if not self.client or not self.connected:
            return
        self.refresh_current_race()
        self.refresh_sources(show_message=False)
        self.update_capture_mode_ui()
        self.select_runner_target(update_status=False)
        self.refresh_memory_status()
        self.update_part_statuses()
        self.set_status("OBS crop layout refreshed", ok=True)

    def open_image(self):
        path = filedialog.askopenfilename(title="Open screenshot", filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif"), ("All files", "*.*")])
        if not path:
            return
        self.load_image_file(path)

    def load_image_file(self, path):
        try:
            self.image = Image.open(path).convert("RGB")
            self.image_path = path
            self.image_label.configure(text=os.path.basename(path))
            self.crop = None
            self.crop_var.set(EMPTY_CROP_TEXT)
            self.redraw_image()
        except Exception as e:
            messagebox.showerror("Image error", str(e))

    def is_media_feed_mode(self):
        return self.capture_mode_var.get() == "OBS Media Feeds"

    def set_playback_engine(self, engine, refresh=True):
        self.capture_mode_var.set("OBS Media Feeds" if str(engine) == "OBS Media Feeds" else "VLC Windows")
        self.capture_playback_var.set("Direct to OBS" if self.is_media_feed_mode() else "Standard VLC")
        self.update_capture_mode_ui()
        if refresh:
            self.select_runner_target(update_status=False)
            self.refresh_memory_status()
            self.update_part_statuses()

    def preset_part_name(self, part):
        return f"Media {part}" if self.is_media_feed_mode() else part

    def source_name_for_slot_part(self, slot, part):
        prefix = "Media " if self.is_media_feed_mode() else ""
        return f"{self.race_mode_label()} R{int(slot)} {prefix}{part}"

    def update_capture_mode_ui(self):
        if self.is_media_feed_mode():
            self.screenshot_button_text.set("Capture OBS Feed")
            self.instructions_var.set(
                "Choose a runner, capture its raw OBS media feed, draw a box around the Game/Tracker/Timer/Facecam area, then click Apply."
            )
        else:
            self.screenshot_button_text.set("Take Screenshot")
            self.instructions_var.set(
                "Choose a runner, take a screenshot, draw a box around the Game/Tracker/Timer area, then click Apply."
            )
        facecam_row = self.part_rows.get("Facecam")
        if facecam_row:
            has_facecam = "Facecam" in self.crop_parts_for_current_layout()
            if not has_facecam:
                facecam_row.pack_forget()
            elif not facecam_row.winfo_manager():
                facecam_row.pack(fill=tk.X, padx=6, pady=3)

    def on_capture_mode_changed(self, _event=None):
        self.update_capture_mode_ui()
        self.select_runner_target(update_status=False)
        self.refresh_memory_status()
        self.update_part_statuses()

    def capture_and_load_selected_slot(self):
        slot = self.selected_runner_slot()
        if not slot:
            messagebox.showwarning("No runner", "Select a current runner before taking a screenshot.")
            return
        if self.is_media_feed_mode():
            try:
                path = self.capture_obs_media_source(int(slot))
                self.load_image_file(path)
                self.set_status(f"Captured OBS media feed for Runner {slot}", ok=True)
                self.refocus_tool()
            except Exception as error:
                messagebox.showerror(
                    "OBS media screenshot failed",
                    f"Could not capture Runner {slot}'s media feed.\n\n{error}\n\n"
                    "Create the media layouts and start that runner's feed first.",
                )
                self.set_status(f"OBS media screenshot failed: {error}")
            return
        try:
            path = self.capture_runner_slot_fast(int(slot))
            self.load_image_file(path)
            self.set_status(f"Loaded screenshot for Runner {slot}", ok=True)
            self.refocus_tool()
            return
        except Exception as fast_error:
            self.set_status(f"Fast screenshot failed, using helper: {fast_error}", ok=False)

        ps1 = os.path.join(ROOT_DIR, "capture_runner_screenshots.ps1")
        if not os.path.exists(ps1):
            messagebox.showerror("Missing screenshot helper", ps1)
            return
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", ps1,
                    "-SlotList", str(slot),
                    "-OutputDir", SCREENSHOT_DIR,
                ],
                cwd=ROOT_DIR,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as e:
            messagebox.showerror("Screenshot failed", str(e))
            return
        if result.returncode != 0:
            messagebox.showerror("Screenshot failed", result.stderr or result.stdout or f"Exit code {result.returncode}")
            return
        folder = SCREENSHOT_DIR
        pattern = re.compile(rf"runner{slot}_.*\.(?:png|jpg|jpeg|bmp|webp)$", re.I)
        try:
            files = [
                os.path.join(folder, name)
                for name in os.listdir(folder)
                if pattern.match(name) and os.path.isfile(os.path.join(folder, name))
            ]
        except FileNotFoundError:
            files = []
        if not files:
            messagebox.showwarning("No screenshot", result.stdout or f"No screenshot was created for Runner {slot}.")
            return
        newest = max(files, key=os.path.getmtime)
        self.load_image_file(newest)
        self.set_status(f"Loaded screenshot for Runner {slot}", ok=True)
        self.refocus_tool()

    def capture_runner_slot_fast(self, slot):
        if stream_syncer.ImageGrab is None:
            raise RuntimeError("Pillow ImageGrab is not available.")
        windows = stream_syncer.list_runner_windows()
        window = windows.get(int(slot))
        if window is None:
            raise RuntimeError(f"RUNNER {slot} VLC window not found.")
        stream_syncer.ShowWindow(window.hwnd, stream_syncer.SW_RESTORE)
        stream_syncer.BringWindowToTop(window.hwnd)
        stream_syncer.SetForegroundWindow(window.hwnd)
        time.sleep(0.08)
        rect = self.visible_window_rect(window.hwnd)
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        if right <= left or bottom <= top:
            raise RuntimeError(f"RUNNER {slot} window has an invalid size.")
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = os.path.join(SCREENSHOT_DIR, f"runner{slot}_{time.strftime('%Y%m%d-%H%M%S')}.png")
        image = stream_syncer.ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB")
        image.save(path)
        return path

    def capture_obs_media_source(self, slot):
        if not self.client or not self.connected:
            self.connect_to_obs()
        if not self.client or not self.connected:
            raise RuntimeError("OBS is not connected.")
        source_name = self.source_name_for_slot_part(slot, "Stream")
        location = self.ensure_source_location(source_name)
        if not location:
            raise RuntimeError(f"OBS source not found: {source_name}.")
        container_name, item_id = location
        transform = self.client.get_scene_item_transform(container_name, item_id).scene_item_transform
        width = max(8, int(transform.get("sourceWidth") or 1280))
        height = max(8, int(transform.get("sourceHeight") or 720))
        stored = obs_crop_service.media_item_location(source_name)
        screenshot_source = stored[2] if stored and stored[2] else source_name
        response = self.client.get_source_screenshot(screenshot_source, "png", width, height, 90)
        image_data = getattr(response, "image_data", "")
        if not image_data:
            raise RuntimeError(f"OBS returned no image data for {source_name}.")
        encoded = image_data.split(",", 1)[1] if "," in image_data else image_data
        image = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGB")
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = os.path.join(SCREENSHOT_DIR, f"media_runner{slot}_{time.strftime('%Y%m%d-%H%M%S')}.png")
        image.save(path)
        return path

    def visible_window_rect(self, hwnd):
        rect = stream_syncer.RECT()
        if _DwmGetWindowAttribute is not None:
            hr = _DwmGetWindowAttribute(
                hwnd,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                stream_syncer.ctypes.byref(rect),
                stream_syncer.ctypes.sizeof(rect),
            )
            if hr == 0:
                return rect
        if not stream_syncer.GetWindowRect(hwnd, stream_syncer.ctypes.byref(rect)):
            raise RuntimeError("Could not read VLC window position.")
        return rect

    def refocus_tool(self):
        try:
            top = self.winfo_toplevel()
            top.lift()
            top.focus_force()
        except tk.TclError:
            pass

    def delete_current_screenshot(self):
        if not self.image_path:
            messagebox.showinfo("No screenshot", "No screenshot is currently loaded.")
            return
        path = self.image_path
        if not os.path.exists(path):
            messagebox.showinfo("Already gone", "That screenshot file no longer exists.")
            return
        name = os.path.basename(path)
        if not messagebox.askyesno("Delete screenshot", f"Delete this screenshot?\n\n{name}"):
            return
        try:
            self.image.close() if self.image else None
        except Exception:
            pass
        try:
            os.remove(path)
            self.image = None
            self.tk_image = None
            self.image_path = None
            self.crop = None
            self.canvas.delete("all")
            self.image_label.configure(text="No screenshot loaded")
            self.crop_var.set(EMPTY_CROP_TEXT)
        except Exception as e:
            messagebox.showerror("Delete failed", str(e))

    def clear_screenshot_folder(self):
        folder = SCREENSHOT_DIR
        if not os.path.isdir(folder):
            messagebox.showinfo("No folder", f"Screenshot folder not found:\n{folder}")
            return
        files = [
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f)) and os.path.splitext(f)[1].lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}
        ]
        if not files:
            messagebox.showinfo("No screenshots", "No screenshot files found to delete.")
            return
        if not messagebox.askyesno("Clear screenshots", f"Delete {len(files)} screenshot file(s) from crop_screenshots?"):
            return
        current_abs = os.path.abspath(self.image_path) if self.image_path else None
        deleted = 0
        failed = 0
        for path in files:
            try:
                if current_abs and os.path.abspath(path) == current_abs:
                    try:
                        self.image.close() if self.image else None
                    except Exception:
                        pass
                    self.image = None
                    self.tk_image = None
                    self.image_path = None
                    self.crop = None
                    self.canvas.delete("all")
                    self.image_label.configure(text="No screenshot loaded")
                    self.crop_var.set(EMPTY_CROP_TEXT)
                os.remove(path)
                deleted += 1
            except Exception:
                failed += 1
        messagebox.showinfo("Screenshots cleared", f"Deleted {deleted} screenshot(s)." + (f"\nFailed: {failed}." if failed else ""))

    def redraw_image(self):
        self.canvas.delete("all")
        self.rect_id = None
        if self.image is None:
            return
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self.image.size
        self.scale = min(cw / iw, ch / ih)
        dw, dh = int(iw * self.scale), int(ih * self.scale)
        self.offset_x = (cw - dw) // 2
        self.offset_y = (ch - dh) // 2
        resized = self.image.resize((dw, dh), Image.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized)
        self.canvas.create_image(self.offset_x, self.offset_y, anchor="nw", image=self.tk_image)
        if self.crop:
            l, r, t, b = self.crop
            x1 = self.offset_x + l * self.scale
            y1 = self.offset_y + t * self.scale
            x2 = self.offset_x + (iw - r) * self.scale
            y2 = self.offset_y + (ih - b) * self.scale
            self.rect_id = self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2)

    def canvas_to_image(self, x, y):
        if self.image is None:
            return None
        ix = round((x - self.offset_x) / self.scale)
        iy = round((y - self.offset_y) / self.scale)
        iw, ih = self.image.size
        ix = max(0, min(iw, ix))
        iy = max(0, min(ih, iy))
        return ix, iy

    def on_press(self, event):
        if self.image is None:
            return
        pos = self.canvas_to_image(event.x, event.y)
        if pos is None:
            return
        self.start_x, self.start_y = pos
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None

    def on_drag(self, event):
        if self.image is None or self.start_x is None:
            return
        pos = self.canvas_to_image(event.x, event.y)
        if pos is None:
            return
        x2, y2 = pos
        x1, y1 = self.start_x, self.start_y
        cx1 = self.offset_x + x1 * self.scale
        cy1 = self.offset_y + y1 * self.scale
        cx2 = self.offset_x + x2 * self.scale
        cy2 = self.offset_y + y2 * self.scale
        if self.rect_id:
            self.canvas.coords(self.rect_id, cx1, cy1, cx2, cy2)
        else:
            self.rect_id = self.canvas.create_rectangle(cx1, cy1, cx2, cy2, outline="red", width=2)

    def on_release(self, event):
        if self.image is None or self.start_x is None:
            return
        pos = self.canvas_to_image(event.x, event.y)
        if pos is None:
            return
        x2, y2 = pos
        x1, y1 = self.start_x, self.start_y
        left = min(x1, x2)
        top = min(y1, y2)
        right_edge = max(x1, x2)
        bottom_edge = max(y1, y2)
        iw, ih = self.image.size
        right = iw - right_edge
        bottom = ih - bottom_edge
        self.crop = (int(left), int(right), int(top), int(bottom))
        self.crop_var.set(f"Left: {self.crop[0]}    Right: {self.crop[1]}\nTop: {self.crop[2]}     Bottom: {self.crop[3]}")
        self.start_x = self.start_y = None

    def race_mode_label(self):
        mode = self.current_race.get("mode", 4)
        return "2P" if mode == 2 else "4P"

    def refresh_runner_options(self):
        if not hasattr(self, "runner_combo"):
            return
        self.runner_option_slots = {}
        runners = self.current_race.get("runners", {})
        values = []
        if isinstance(runners, dict):
            mode = int(self.current_race.get("mode", 4) or 4)
            for slot in range(1, mode + 1):
                runner = runners.get(str(slot))
                if not isinstance(runner, dict):
                    continue
                display = runner.get("display_name") or runner.get("twitch_name") or f"Runner {slot}"
                label = f"R{slot} - {display}"
                self.runner_option_slots[label] = slot
                values.append(label)
        self.runner_combo.configure(values=values)
        if values and self.runner_crop_slot_var.get() not in values:
            self.runner_crop_slot_var.set(values[0])
        self.select_runner_target(update_status=False)
        self.update_part_statuses()

    def selected_runner_slot(self):
        value = self.runner_crop_slot_var.get()
        return self.runner_option_slots.get(value)

    def source_for_runner_part(self, part=None):
        slot = self.selected_runner_slot()
        if not slot:
            return None
        return self.source_name_for_slot_part(slot, part or self.runner_crop_part_var.get())

    def select_runner_target(self, update_status=True):
        source = self.source_for_runner_part()
        if source and hasattr(self, "target_var"):
            self.target_var.set(source)
        self.update_active_runner_label()
        if update_status:
            self.refresh_memory_status()
            self.update_part_statuses()

    def update_active_runner_label(self):
        runner = self.runner_for_selected_slot()
        slot = self.selected_runner_slot()
        if not runner or not slot:
            self.active_runner_var.set("No runner selected")
            return
        display = runner.get("display_name") or runner.get("twitch_name") or f"Runner {slot}"
        self.active_runner_var.set(f"R{slot}: {display}")

    def runner_for_selected_slot(self):
        slot = self.selected_runner_slot()
        runners = self.current_race.get("runners", {})
        if not slot or not isinstance(runners, dict):
            return None
        runner = runners.get(str(slot))
        return runner if isinstance(runner, dict) else None

    def display_part_label(self, part):
        return "Game" if part == "Stream" else part

    def crop_parts_for_current_layout(self):
        layout = self.race_mode_label()
        parts = ["Stream", "Tracker", "Timer"]
        if any(target_layout == layout and part == "Facecam" for _name, target_layout, _slot, part in obs_crop_service.designer_crop_targets()):
            parts.append("Facecam")
        return parts

    def update_part_statuses(self):
        if not self.part_status_vars:
            return
        runner = self.runner_for_selected_slot()
        if not runner:
            for part, var in self.part_status_vars.items():
                var.set("no current runner")
                button = self.part_apply_buttons.get(part)
                if button:
                    button.state(["disabled"])
                label = self.part_status_labels.get(part)
                if label:
                    label.configure(foreground=MUTED)
            return
        twitch = (runner.get("twitch_name") or "").strip()
        display = runner.get("display_name") or twitch or "runner"
        layout = self.race_mode_label()
        for part, var in self.part_status_vars.items():
            source = self.source_for_runner_part(part)
            available = not self.is_media_feed_mode() or bool(source and source in self.source_locations)
            button = self.part_apply_buttons.get(part)
            if button:
                button.state(["!disabled"] if available else ["disabled"])
            label = self.part_status_labels.get(part)
            if not available:
                var.set("not used in this custom layout")
                if label:
                    label.configure(foreground=MUTED)
                continue
            preset = app_state.get_crop_preset(twitch, self.preset_part_name(part), layout) if twitch else None
            if preset:
                var.set(f"Saved for {display} ({layout})")
                if label:
                    label.configure(foreground=ACCENT)
            else:
                var.set(f"Not saved for {display} ({layout})")
                if label:
                    label.configure(foreground=MUTED)

    def set_runner_part(self, part):
        self.runner_crop_part_var.set(part)
        self.select_runner_target(update_status=False)

    def load_runner_part_crop(self, part):
        self.set_runner_part(part)
        self.load_saved_crop()
        self.update_part_statuses()

    def save_apply_runner_part_crop(self, part):
        self.set_runner_part(part)
        source = self.target_var.get()
        if self.is_media_feed_mode() and source not in self.source_locations:
            messagebox.showinfo(
                "Part not in layout",
                f"{self.display_part_label(part)} is not used for this runner in the current custom layout.",
            )
            return
        self.apply_to_source(source)
        self.update_part_statuses()

    def load_selected_runner_crop(self):
        self.select_runner_target(update_status=False)
        self.load_saved_crop()
        self.update_part_statuses()

    def save_selected_runner_crop(self):
        self.select_runner_target(update_status=False)
        if self.save_current_crop():
            self.update_part_statuses()

    def apply_selected_runner_crop(self):
        self.select_runner_target(update_status=False)
        _source_name, _details, _runner, preset = self.selected_memory_context()
        if preset:
            crop = preset.get("crop", {})
            try:
                self.set_crop((crop["left"], crop["right"], crop["top"], crop["bottom"]))
            except Exception as e:
                messagebox.showerror("Saved crop error", str(e))
                return
        self.apply_to_source(self.target_var.get())
        self.update_part_statuses()

    def apply_all_runner_crops(self):
        runner = self.runner_for_selected_slot()
        if not runner:
            messagebox.showwarning("No runner", "Select a current runner first.")
            return
        twitch = (runner.get("twitch_name") or "").strip()
        if not twitch:
            messagebox.showwarning("No Twitch name", "The selected runner is missing a Twitch name.")
            return
        applied = 0
        missing = []
        layout = self.race_mode_label()
        for part in self.crop_parts_for_current_layout():
            source = self.source_for_runner_part(part)
            if self.is_media_feed_mode() and source not in self.source_locations:
                continue
            preset = app_state.get_crop_preset(twitch, self.preset_part_name(part), layout)
            if not source or not preset:
                missing.append(part)
                continue
            crop_data = preset.get("crop", {})
            try:
                crop = (crop_data["left"], crop_data["right"], crop_data["top"], crop_data["bottom"])
            except Exception:
                missing.append(part)
                continue
            if self.apply_crop_to_source(source, crop, save_memory=False):
                applied += 1
        self.update_part_statuses()
        if missing:
            messagebox.showinfo("Apply all crops", f"Applied {applied} saved crop(s). Missing: {', '.join(missing)}.")
        else:
            messagebox.showinfo("Apply all crops", f"Applied all {applied} saved crop(s).")

    def apply_all_race_crops(self):
        self.refresh_current_race()
        runners = self.current_race.get("runners", {})
        if not isinstance(runners, dict) or not runners:
            messagebox.showwarning("No race", "Launch or write a race first so runner slots are saved.")
            return
        layout = self.race_mode_label()
        try:
            mode = int(self.current_race.get("mode", 4) or 4)
        except Exception:
            mode = 4
        applied = 0
        missing = []
        failed = []
        for slot in range(1, mode + 1):
            runner = runners.get(str(slot))
            if not isinstance(runner, dict):
                missing.append(f"R{slot}: no runner")
                continue
            twitch = (runner.get("twitch_name") or "").strip()
            display = runner.get("display_name") or twitch or f"Runner {slot}"
            if not twitch:
                missing.append(f"R{slot} {display}: missing Twitch name")
                continue
            for part in self.crop_parts_for_current_layout():
                source = self.source_name_for_slot_part(slot, part)
                if self.is_media_feed_mode() and source not in self.source_locations:
                    continue
                preset = app_state.get_crop_preset(twitch, self.preset_part_name(part), layout)
                if not preset:
                    missing.append(f"R{slot} {display}: {self.display_part_label(part)}")
                    continue
                crop_data = preset.get("crop", {})
                try:
                    crop = (crop_data["left"], crop_data["right"], crop_data["top"], crop_data["bottom"])
                except Exception:
                    missing.append(f"R{slot} {display}: bad {self.display_part_label(part)} crop")
                    continue
                if self.apply_crop_to_source(source, crop, save_memory=False):
                    applied += 1
                else:
                    failed.append(source)
        self.update_part_statuses()
        self.refresh_memory_status()
        self.set_status(f"Reapplied {applied} saved crop(s) for {layout}", ok=not failed)
        details = []
        if missing:
            details.append("Missing:\n" + "\n".join(missing[:20]))
        if failed:
            details.append("Failed:\n" + "\n".join(failed[:20]))
        if details:
            messagebox.showinfo("Reapply saved crops", f"Applied {applied} saved crop(s).\n\n" + "\n\n".join(details))
        else:
            messagebox.showinfo("Reapply saved crops", f"Applied all {applied} saved crop(s) for {layout}.")

    def apply_target_button(self, source_name):
        self.target_var.set(source_name)
        self.refresh_memory_status()
        self.apply_to_source(source_name)

    def target_details(self, source_name):
        match = re.match(r"^(?P<mode>[24]P)\s+R(?P<slot>[1-4])\s+(?:Media\s+)?(?P<part>Stream|Tracker|Timer|Facecam)$", source_name, re.I)
        if not match:
            return None
        return {
            "mode": match.group("mode").upper(),
            "slot": int(match.group("slot")),
            "part": match.group("part").title(),
        }

    def runner_for_source(self, source_name):
        details = self.target_details(source_name)
        if not details:
            return None, None
        runners = self.current_race.get("runners", {})
        if not isinstance(runners, dict):
            return details, None
        runner = runners.get(str(details["slot"]))
        return details, runner if isinstance(runner, dict) else None

    def refresh_current_race(self):
        self.current_race = app_state.load_current_race()
        self.current_race_mtime = self.current_race_file_mtime()
        self.refresh_runner_options()
        self.refresh_memory_status()

    def selected_memory_context(self):
        source_name = self.target_var.get()
        details, runner = self.runner_for_source(source_name)
        if not details or not runner:
            return source_name, details, runner, None
        twitch = (runner.get("twitch_name") or "").strip()
        if not twitch:
            return source_name, details, runner, None
        return source_name, details, runner, app_state.get_crop_preset(
            twitch, self.preset_part_name(details["part"]), details["mode"]
        )

    def refresh_memory_status(self):
        if not hasattr(self, "memory_status_var"):
            return
        source_name, details, runner, preset = self.selected_memory_context()
        if not details:
            self.memory_status_var.set("Select a known target to use crop memory.")
            return
        if not runner:
            self.memory_status_var.set(f"{source_name}: no current runner saved for slot {details['slot']}.")
            return
        display = runner.get("display_name") or runner.get("twitch_name") or "runner"
        if preset:
            updated = preset.get("updated_at", "unknown time")
            self.memory_status_var.set(f"Saved {details['part']} crop found for {display}. Updated {updated}.")
        else:
            self.memory_status_var.set(f"No saved {details['part']} crop for {display} yet.")

    def set_crop(self, crop):
        self.crop = (int(crop[0]), int(crop[1]), int(crop[2]), int(crop[3]))
        self.crop_var.set(f"Left: {self.crop[0]}    Right: {self.crop[1]}\nTop: {self.crop[2]}     Bottom: {self.crop[3]}")
        self.redraw_image()

    def load_saved_crop(self):
        _source_name, details, runner, preset = self.selected_memory_context()
        if not details or not runner:
            messagebox.showwarning("No runner", "No current runner is saved for the selected target.")
            return
        if not preset:
            messagebox.showinfo("No saved crop", "No saved crop exists for this runner and source type yet.")
            return
        crop = preset.get("crop", {})
        try:
            self.set_crop((crop["left"], crop["right"], crop["top"], crop["bottom"]))
            self.refresh_memory_status()
        except Exception as e:
            messagebox.showerror("Saved crop error", str(e))

    def save_current_crop(self, show_warnings=True):
        if not self.crop:
            if show_warnings:
                messagebox.showwarning("No crop", "Drag a rectangle or load a saved crop first.")
            return False
        source_name, details, runner, _preset = self.selected_memory_context()
        if not details or not runner:
            if show_warnings:
                messagebox.showwarning("No runner", "No current runner is saved for the selected target.")
            return False
        twitch = (runner.get("twitch_name") or "").strip()
        if not twitch:
            if show_warnings:
                messagebox.showwarning("No Twitch name", "The current runner state is missing a Twitch name.")
            return False
        app_state.save_crop_preset(
            twitch,
            runner.get("display_name", twitch),
            self.preset_part_name(details["part"]),
            self.crop,
            details["mode"],
        )
        self.refresh_memory_status()
        self.update_part_statuses()
        self.set_status(f"Saved crop for {source_name}", ok=True)
        return True

    def apply_crop_to_source(self, source_name, crop, save_memory=True):
        if not self.client or not self.connected:
            self.connect_to_obs()
            if not self.client or not self.connected:
                return False
        if not self.ensure_source_location(source_name):
            messagebox.showerror("Source not found", f"Could not find OBS source:\n\n{source_name}\n\nCheck the source name and click Refresh.")
            return False
        try:
            obs_crop_service.set_crop(self.client, self.source_locations, source_name, crop)
            self.target_var.set(source_name)
            if save_memory:
                self.save_current_crop(show_warnings=False)
            self.set_status(f"Applied to {source_name}", ok=True)
            return True
        except Exception as e:
            messagebox.showerror("Apply failed", str(e))
            self.set_status("Apply failed")
            return False

    def apply_to_source(self, source_name):
        if not self.crop:
            messagebox.showwarning("No crop", "Drag a rectangle around the area to keep first.")
            return
        self.apply_crop_to_source(source_name, self.crop)


class CropTool(CropPanel):
    def __init__(self):
        root = tk.Tk()
        self._root_window = root
        super().__init__(root, standalone=True)
        self.pack(fill=tk.BOTH, expand=True)

    def mainloop(self, *args, **kwargs):
        return self._root_window.mainloop(*args, **kwargs)


if __name__ == "__main__":
    app = CropTool()
    app.mainloop()
