import json
import os
import shutil
import threading
import time
import tkinter as tk
from datetime import date
from pathlib import Path
import sys

from pynput import keyboard
from pynput.keyboard import Controller, Key, KeyCode


class CaptaApp:
    SPLIT_SECONDS = 30 * 60
    SAVE_INTERVAL_SECONDS = 60
    AUTO_RESTART_DELAY_SECONDS = 5
    MIN_AUTO_RESTART_DELAY_SECONDS = 5
    DEFAULT_HOTKEY = "page_up"

    def __init__(self) -> None:
        self.app_data_dir = self.get_app_data_dir()
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.stats_path = self.app_data_dir / "stats.json"
        self.config_path = self.app_data_dir / "config.json"
        self.keyboard_controller = Controller()
        self.state_lock = threading.Lock()
        self.stop_event = threading.Event()

        self.is_recording = False
        self.is_waiting_restart = False
        self.segment_start_monotonic: float | None = None
        self.restart_wait_started_monotonic: float | None = None
        self.last_today_update_monotonic: float | None = None
        self.total_seconds_today = 0.0
        self.last_session_date = ""
        self.ignore_hotkey_presses = 0
        self.hotkey_spec = self.DEFAULT_HOTKEY
        self.hotkey_display = "Page Up"
        self.hotkey_special: Key | None = Key.page_up
        self.hotkey_char: str | None = None
        self.last_stats_save_monotonic = time.monotonic()

        self.drag_start_x = 0
        self.drag_start_y = 0
        self.resize_start_x = 0
        self.resize_start_y = 0
        self.resize_start_width = 0
        self.resize_start_height = 0
        self.settings_visible = False
        self.pending_resize_width = 240
        self.pending_resize_height = 70
        self.resize_job_id: str | None = None
        self.is_resizing = False
        self.last_status_text = ""
        self.last_status_fg = ""
        self.last_daily_text = ""
        self.last_hotkey_text = ""

        self.migrate_legacy_file("config.json", self.config_path)
        self.migrate_legacy_file("stats.json", self.stats_path)
        self.load_config()
        self.load_stats()

        self.root = tk.Tk()
        self.root.title("Capta")
        self.root.configure(bg="#121212")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry("240x70+40+40")
        self.root.minsize(220, 70)
        self.pending_resize_width = 240
        self.pending_resize_height = 70

        self.title_bar = tk.Frame(self.root, bg="#121212")
        self.title_bar.pack(fill="x", padx=8, pady=(6, 0))

        self.title_label = tk.Label(
            self.title_bar,
            text="Capta",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg="#121212",
        )
        self.title_label.pack(side="left")

        self.settings_button = tk.Button(
            self.title_bar,
            text="⚙",
            font=("Segoe UI", 9),
            fg="#FFFFFF",
            bg="#121212",
            activeforeground="#FFFFFF",
            activebackground="#222222",
            bd=0,
            padx=6,
            pady=0,
            command=self.toggle_settings_panel,
        )
        self.settings_button.pack(side="right")

        self.exit_button = tk.Button(
            self.title_bar,
            text="X",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg="#121212",
            activeforeground="#FFFFFF",
            activebackground="#222222",
            bd=0,
            padx=6,
            pady=0,
            command=self.exit_process,
        )
        self.exit_button.pack(side="right")

        self.content_frame = tk.Frame(self.root, bg="#121212")
        self.content_frame.pack(fill="both", expand=True, padx=12, pady=(2, 6))

        self.status_label = tk.Label(
            self.content_frame,
            text="○ IDLE [00:00]",
            font=("Segoe UI", 12, "bold"),
            fg="#FFFFFF",
            bg="#121212",
        )
        self.status_label.pack(anchor="w", pady=(0, 2))

        self.daily_label = tk.Label(
            self.content_frame,
            text="Today: 00:00:00",
            font=("Segoe UI", 10),
            fg="#FFFFFF",
            bg="#121212",
        )
        self.daily_label.pack(anchor="w")

        self.hotkey_label = tk.Label(
            self.content_frame,
            text=f"Hotkey: {self.hotkey_display}",
            font=("Segoe UI", 9),
            fg="#B5B5B5",
            bg="#121212",
        )
        self.hotkey_label.pack(anchor="w", pady=(2, 0))

        self.settings_frame = tk.Frame(self.root, bg="#121212")
        self.settings_inputs = tk.Frame(self.settings_frame, bg="#121212")
        self.settings_inputs.pack(fill="x", padx=12, pady=(2, 6))

        self.split_minutes_var = tk.StringVar(value=str(self.SPLIT_SECONDS // 60))
        self.restart_delay_var = tk.StringVar(value=str(self.AUTO_RESTART_DELAY_SECONDS))
        self.save_interval_var = tk.StringVar(value=str(self.SAVE_INTERVAL_SECONDS))
        self.hotkey_var = tk.StringVar(value=self.hotkey_spec)

        self.make_settings_row(
            self.settings_inputs,
            "Split (min)",
            self.split_minutes_var,
        )
        self.make_settings_row(
            self.settings_inputs,
            "Restart delay (s)",
            self.restart_delay_var,
        )
        self.make_settings_row(
            self.settings_inputs,
            "Save interval (s)",
            self.save_interval_var,
        )
        self.make_settings_row(
            self.settings_inputs,
            "Hotkey",
            self.hotkey_var,
        )

        self.settings_status_label = tk.Label(
            self.settings_frame,
            text="",
            font=("Segoe UI", 9),
            fg="#FF8A8A",
            bg="#121212",
            anchor="w",
            justify="left",
        )
        self.settings_status_label.pack(fill="x", padx=12, pady=(0, 4))

        self.settings_actions = tk.Frame(self.settings_frame, bg="#121212")
        self.settings_actions.pack(fill="x", padx=12, pady=(0, 6))

        self.apply_button = tk.Button(
            self.settings_actions,
            text="Apply",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg="#1F6FEB",
            activeforeground="#FFFFFF",
            activebackground="#245EBF",
            bd=0,
            padx=10,
            pady=2,
            command=self.apply_settings,
        )
        self.apply_button.pack(side="left")

        self.cancel_button = tk.Button(
            self.settings_actions,
            text="Close",
            font=("Segoe UI", 9),
            fg="#FFFFFF",
            bg="#2A2A2A",
            activeforeground="#FFFFFF",
            activebackground="#3A3A3A",
            bd=0,
            padx=10,
            pady=2,
            command=self.hide_settings_panel,
        )
        self.cancel_button.pack(side="left", padx=(6, 0))

        self.resize_grip = tk.Label(
            self.root,
            text="◢",
            font=("Segoe UI", 8),
            fg="#888888",
            bg="#121212",
            cursor="size_nw_se",
        )
        self.resize_grip.place(relx=1.0, rely=1.0, anchor="se", x=-3, y=-3)

        self.title_bar.bind("<ButtonPress-1>", self.on_drag_start)
        self.title_bar.bind("<B1-Motion>", self.on_drag_move)
        self.title_label.bind("<ButtonPress-1>", self.on_drag_start)
        self.title_label.bind("<B1-Motion>", self.on_drag_move)
        self.resize_grip.bind("<ButtonPress-1>", self.on_resize_start)
        self.resize_grip.bind("<B1-Motion>", self.on_resize_move)
        self.resize_grip.bind("<ButtonRelease-1>", self.on_resize_end)
        self.root.protocol("WM_DELETE_WINDOW", self.exit_process)
        self.root.bind("<Escape>", lambda _event: self.exit_process())

        self.listener = keyboard.Listener(on_press=self.on_key_press)
        self.listener.start()

        self.segment_worker = threading.Thread(
            target=self.segment_loop,
            name="capta-segment-loop",
            daemon=True,
        )
        self.segment_worker.start()

        self.ui_update_loop()

    def on_drag_start(self, event: tk.Event) -> None:
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_drag_move(self, event: tk.Event) -> None:
        x = self.root.winfo_x() + event.x - self.drag_start_x
        y = self.root.winfo_y() + event.y - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def on_resize_start(self, event: tk.Event) -> None:
        self.is_resizing = True
        self.resize_start_x = event.x_root
        self.resize_start_y = event.y_root
        self.resize_start_width = self.root.winfo_width()
        self.resize_start_height = self.root.winfo_height()
        self.pending_resize_width = self.resize_start_width
        self.pending_resize_height = self.resize_start_height

    def on_resize_move(self, event: tk.Event) -> None:
        dx = event.x_root - self.resize_start_x
        dy = event.y_root - self.resize_start_y
        self.pending_resize_width = max(220, self.resize_start_width + dx)
        self.pending_resize_height = max(70, self.resize_start_height + dy)
        if self.resize_job_id is None:
            # Throttle expensive geometry updates during drag-resize.
            self.resize_job_id = self.root.after(16, self.apply_pending_resize)

    def on_resize_end(self, _event: tk.Event) -> None:
        self.is_resizing = False
        self.apply_pending_resize()

    def apply_pending_resize(self) -> None:
        self.resize_job_id = None
        current_width = self.root.winfo_width()
        current_height = self.root.winfo_height()
        if (
            current_width != self.pending_resize_width
            or current_height != self.pending_resize_height
        ):
            self.root.geometry(f"{self.pending_resize_width}x{self.pending_resize_height}")

    def make_settings_row(
        self,
        parent: tk.Frame,
        label_text: str,
        variable: tk.StringVar,
    ) -> None:
        row = tk.Frame(parent, bg="#121212")
        row.pack(fill="x", pady=2)

        label = tk.Label(
            row,
            text=label_text,
            font=("Segoe UI", 9),
            fg="#E1E1E1",
            bg="#121212",
            width=16,
            anchor="w",
        )
        label.pack(side="left")

        entry = tk.Entry(
            row,
            textvariable=variable,
            font=("Segoe UI", 9),
            fg="#FFFFFF",
            bg="#1D1D1D",
            insertbackground="#FFFFFF",
            relief="flat",
            width=16,
        )
        entry.pack(side="left", padx=(4, 0))

    @staticmethod
    def get_app_data_dir() -> Path:
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "Capta"
        return Path.home() / ".capta"

    @staticmethod
    def legacy_file_candidates(filename: str) -> list[Path]:
        candidates: list[Path] = []
        try:
            candidates.append(Path(__file__).resolve().with_name(filename))
        except OSError:
            pass

        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().with_name(filename))

        candidates.append(Path.cwd() / filename)
        return candidates

    def migrate_legacy_file(self, filename: str, destination: Path) -> None:
        if destination.exists():
            return

        for source in self.legacy_file_candidates(filename):
            if source.exists() and source != destination:
                try:
                    shutil.copy2(source, destination)
                except OSError:
                    pass
                return

    def load_stats(self) -> None:
        today_str = date.today().isoformat()
        if not self.stats_path.exists():
            self.total_seconds_today = 0.0
            self.last_session_date = today_str
            self.save_stats()
            return

        try:
            data = json.loads(self.stats_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.total_seconds_today = 0.0
            self.last_session_date = today_str
            self.save_stats()
            return

        stored_total = data.get("total_seconds_today", 0)
        stored_date = data.get("last_session_date", today_str)

        if stored_date != today_str:
            self.total_seconds_today = 0.0
            self.last_session_date = today_str
            self.save_stats()
            return

        try:
            self.total_seconds_today = max(0.0, float(stored_total))
        except (TypeError, ValueError):
            self.total_seconds_today = 0.0
        self.last_session_date = stored_date

    @staticmethod
    def parse_int(value: object, default: int, minimum: int) -> int:
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return max(minimum, default)

    def configure_hotkey(self, raw_hotkey: object) -> None:
        hotkey = str(raw_hotkey).strip().lower().replace(" ", "_")
        special_keys: dict[str, Key] = {
            "page_up": Key.page_up,
            "page_down": Key.page_down,
            "home": Key.home,
            "end": Key.end,
            "insert": Key.insert,
            "delete": Key.delete,
            "space": Key.space,
            "tab": Key.tab,
            "enter": Key.enter,
            "esc": Key.esc,
            "escape": Key.esc,
        }

        for i in range(1, 13):
            special_keys[f"f{i}"] = getattr(Key, f"f{i}")

        if hotkey in special_keys:
            self.hotkey_spec = hotkey
            self.hotkey_special = special_keys[hotkey]
            self.hotkey_char = None
            self.hotkey_display = hotkey.replace("_", " ").title()
            return

        if len(hotkey) == 1:
            self.hotkey_spec = hotkey
            self.hotkey_special = None
            self.hotkey_char = hotkey
            self.hotkey_display = hotkey.upper()
            return

        self.hotkey_spec = self.DEFAULT_HOTKEY
        self.hotkey_special = Key.page_up
        self.hotkey_char = None
        self.hotkey_display = "Page Up"

    def hotkey_matches(self, key: Key | KeyCode) -> bool:
        if self.hotkey_special is not None:
            return key == self.hotkey_special

        if self.hotkey_char is None:
            return False

        if isinstance(key, KeyCode):
            key_char = key.char.lower() if key.char else ""
            return key_char == self.hotkey_char
        return False

    def load_config(self) -> None:
        defaults = {
            "split_minutes": 30,
            "auto_restart_delay_seconds": self.AUTO_RESTART_DELAY_SECONDS,
            "save_interval_seconds": self.SAVE_INTERVAL_SECONDS,
            "hotkey": self.DEFAULT_HOTKEY,
        }

        data = defaults.copy()
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (OSError, json.JSONDecodeError):
                data = defaults.copy()

        split_minutes = self.parse_int(
            data.get("split_minutes", defaults["split_minutes"]),
            defaults["split_minutes"],
            1,
        )
        auto_restart_delay = self.parse_int(
            data.get("auto_restart_delay_seconds", defaults["auto_restart_delay_seconds"]),
            defaults["auto_restart_delay_seconds"],
            self.MIN_AUTO_RESTART_DELAY_SECONDS,
        )
        save_interval = self.parse_int(
            data.get("save_interval_seconds", defaults["save_interval_seconds"]),
            defaults["save_interval_seconds"],
            1,
        )
        self.configure_hotkey(data.get("hotkey", defaults["hotkey"]))

        self.SPLIT_SECONDS = split_minutes * 60
        self.AUTO_RESTART_DELAY_SECONDS = auto_restart_delay
        self.SAVE_INTERVAL_SECONDS = save_interval

        self.write_config(
            split_minutes=self.SPLIT_SECONDS // 60,
            auto_restart_delay_seconds=self.AUTO_RESTART_DELAY_SECONDS,
            save_interval_seconds=self.SAVE_INTERVAL_SECONDS,
            hotkey=self.hotkey_spec,
        )

    def write_config(
        self,
        split_minutes: int,
        auto_restart_delay_seconds: int,
        save_interval_seconds: int,
        hotkey: str,
    ) -> None:
        normalized = {
            "split_minutes": self.SPLIT_SECONDS // 60,
            "auto_restart_delay_seconds": self.AUTO_RESTART_DELAY_SECONDS,
            "save_interval_seconds": self.SAVE_INTERVAL_SECONDS,
            "hotkey": hotkey,
        }
        normalized["split_minutes"] = split_minutes
        normalized["auto_restart_delay_seconds"] = auto_restart_delay_seconds
        normalized["save_interval_seconds"] = save_interval_seconds
        self.config_path.write_text(
            json.dumps(normalized, indent=2),
            encoding="utf-8",
        )

    def validate_hotkey(self, raw_hotkey: str) -> tuple[bool, str]:
        normalized = raw_hotkey.strip().lower().replace(" ", "_")
        allowed_named = {
            "page_up",
            "page_down",
            "home",
            "end",
            "insert",
            "delete",
            "space",
            "tab",
            "enter",
            "esc",
            "escape",
        }
        for i in range(1, 13):
            allowed_named.add(f"f{i}")

        if len(normalized) == 1 or normalized in allowed_named:
            return True, normalized
        return False, normalized

    def refresh_settings_form(self) -> None:
        self.split_minutes_var.set(str(self.SPLIT_SECONDS // 60))
        self.restart_delay_var.set(str(self.AUTO_RESTART_DELAY_SECONDS))
        self.save_interval_var.set(str(self.SAVE_INTERVAL_SECONDS))
        self.hotkey_var.set(self.hotkey_spec)

    def toggle_settings_panel(self) -> None:
        if self.settings_visible:
            self.hide_settings_panel()
        else:
            self.show_settings_panel()

    def show_settings_panel(self) -> None:
        self.settings_visible = True
        self.refresh_settings_form()
        self.settings_status_label.configure(text="", fg="#FF8A8A")
        self.settings_frame.pack(fill="x")
        width = max(300, self.root.winfo_width())
        self.pending_resize_width = width
        self.pending_resize_height = 250
        self.apply_pending_resize()

    def hide_settings_panel(self) -> None:
        self.settings_visible = False
        self.settings_frame.pack_forget()
        width = max(220, self.root.winfo_width())
        self.pending_resize_width = width
        self.pending_resize_height = 90
        self.apply_pending_resize()

    def apply_settings(self) -> None:
        split_minutes = self.parse_int(self.split_minutes_var.get(), 30, 1)
        restart_delay = self.parse_int(
            self.restart_delay_var.get(),
            self.MIN_AUTO_RESTART_DELAY_SECONDS,
            self.MIN_AUTO_RESTART_DELAY_SECONDS,
        )
        save_interval = self.parse_int(self.save_interval_var.get(), 60, 1)
        raw_hotkey = self.hotkey_var.get()
        valid_hotkey, normalized_hotkey = self.validate_hotkey(raw_hotkey)

        if not valid_hotkey:
            self.settings_status_label.configure(
                text="Invalid hotkey. Use one key (e.g. r) or names like page_up/f1.",
                fg="#FF8A8A",
            )
            return

        with self.state_lock:
            self.SPLIT_SECONDS = split_minutes * 60
            self.AUTO_RESTART_DELAY_SECONDS = restart_delay
            self.SAVE_INTERVAL_SECONDS = save_interval
            self.configure_hotkey(normalized_hotkey)
            self.write_config(
                split_minutes=self.SPLIT_SECONDS // 60,
                auto_restart_delay_seconds=self.AUTO_RESTART_DELAY_SECONDS,
                save_interval_seconds=self.SAVE_INTERVAL_SECONDS,
                hotkey=self.hotkey_spec,
            )
            self.last_stats_save_monotonic = time.monotonic()

        self.settings_status_label.configure(
            text="Settings saved.",
            fg="#79D68B",
        )
        self.refresh_settings_form()

    def save_stats(self) -> None:
        payload = {
            "total_seconds_today": int(self.total_seconds_today),
            "last_session_date": self.last_session_date,
        }
        self.stats_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def rollover_if_new_day(self) -> None:
        today_str = date.today().isoformat()
        if self.last_session_date != today_str:
            self.total_seconds_today = 0.0
            self.last_session_date = today_str
            self.save_stats()

    def sync_today_locked(self, now: float) -> None:
        if not self.is_recording or self.is_waiting_restart:
            return

        if self.last_today_update_monotonic is None:
            self.last_today_update_monotonic = now
            return

        elapsed = max(0.0, now - self.last_today_update_monotonic)
        self.total_seconds_today += elapsed
        self.last_today_update_monotonic = now

    def on_key_press(self, key: Key | KeyCode) -> None:
        if not self.hotkey_matches(key):
            return

        with self.state_lock:
            if self.ignore_hotkey_presses > 0:
                self.ignore_hotkey_presses -= 1
                return

        self.toggle_recording()

    def toggle_recording(self) -> None:
        now = time.monotonic()
        with self.state_lock:
            self.rollover_if_new_day()
            self.sync_today_locked(now)
            if not self.is_recording:
                self.is_recording = True
                self.is_waiting_restart = False
                self.segment_start_monotonic = now
                self.restart_wait_started_monotonic = None
                self.last_today_update_monotonic = now
            else:
                self.is_recording = False
                self.is_waiting_restart = False
                self.segment_start_monotonic = None
                self.restart_wait_started_monotonic = None
                self.last_today_update_monotonic = None
                self.save_stats()
                self.last_stats_save_monotonic = now

    def press_hotkey_ignored(self) -> None:
        with self.state_lock:
            self.ignore_hotkey_presses += 1

        key_to_press: Key | str
        if self.hotkey_special is not None:
            key_to_press = self.hotkey_special
        else:
            key_to_press = self.hotkey_char or self.DEFAULT_HOTKEY

        self.keyboard_controller.press(key_to_press)
        self.keyboard_controller.release(key_to_press)

    def perform_split(self) -> None:
        split_started_at = time.monotonic()
        with self.state_lock:
            if not self.is_recording or self.is_waiting_restart:
                return
            self.sync_today_locked(split_started_at)
            # Enter waiting state during restart delay.
            self.is_waiting_restart = True
            self.restart_wait_started_monotonic = split_started_at
            self.segment_start_monotonic = None
            self.last_today_update_monotonic = split_started_at

        self.press_hotkey_ignored()
        time.sleep(self.AUTO_RESTART_DELAY_SECONDS)

        with self.state_lock:
            if not self.is_recording or not self.is_waiting_restart:
                self.restart_wait_started_monotonic = None
                return

        self.press_hotkey_ignored()

        restarted_at = time.monotonic()
        with self.state_lock:
            if not self.is_recording:
                self.is_waiting_restart = False
                self.restart_wait_started_monotonic = None
                self.segment_start_monotonic = None
                self.last_today_update_monotonic = None
                return

            self.is_waiting_restart = False
            self.restart_wait_started_monotonic = None
            self.segment_start_monotonic = restarted_at
            self.last_today_update_monotonic = restarted_at

    def segment_loop(self) -> None:
        while not self.stop_event.is_set():
            should_split = False
            with self.state_lock:
                if (
                    self.is_recording
                    and not self.is_waiting_restart
                    and self.segment_start_monotonic is not None
                ):
                    elapsed = time.monotonic() - self.segment_start_monotonic
                    if elapsed >= self.SPLIT_SECONDS:
                        should_split = True

            if should_split:
                self.perform_split()

            self.stop_event.wait(0.25)

    @staticmethod
    def format_hms(total_seconds: int) -> str:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    @staticmethod
    def format_mmss(total_seconds: int) -> str:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02}:{seconds:02}"

    def ui_update_loop(self) -> None:
        now = time.monotonic()
        with self.state_lock:
            self.rollover_if_new_day()
            self.sync_today_locked(now)
            is_recording = self.is_recording
            is_waiting_restart = self.is_waiting_restart
            total_today = int(self.total_seconds_today)
            segment_start = self.segment_start_monotonic
            restart_wait_started = self.restart_wait_started_monotonic
            auto_restart_delay = self.AUTO_RESTART_DELAY_SECONDS
            if now - self.last_stats_save_monotonic >= self.SAVE_INTERVAL_SECONDS:
                self.save_stats()
                self.last_stats_save_monotonic = now

        segment_seconds = 0
        if is_recording and not is_waiting_restart and segment_start is not None:
            segment_seconds = int(max(0.0, now - segment_start))
        wait_remaining_seconds = 0
        if is_recording and is_waiting_restart and restart_wait_started is not None:
            waited = max(0.0, now - restart_wait_started)
            wait_remaining_seconds = int(max(0.0, auto_restart_delay - waited))

        if is_recording and is_waiting_restart:
            next_status_text = f"◌ WAIT [{self.format_mmss(wait_remaining_seconds)}]"
            next_status_fg = "#F3C969"
        elif is_recording:
            next_status_text = f"● REC [{self.format_mmss(segment_seconds)}]"
            next_status_fg = "#FF4D4D"
        else:
            next_status_text = f"○ IDLE [{self.format_mmss(segment_seconds)}]"
            next_status_fg = "#FFFFFF"

        next_daily_text = f"Today: {self.format_hms(total_today)}"
        next_hotkey_text = f"Hotkey: {self.hotkey_display}"

        if (
            next_status_text != self.last_status_text
            or next_status_fg != self.last_status_fg
        ):
            self.status_label.configure(text=next_status_text, fg=next_status_fg)
            self.last_status_text = next_status_text
            self.last_status_fg = next_status_fg

        if next_daily_text != self.last_daily_text:
            self.daily_label.configure(text=next_daily_text)
            self.last_daily_text = next_daily_text

        if next_hotkey_text != self.last_hotkey_text:
            self.hotkey_label.configure(text=next_hotkey_text)
            self.last_hotkey_text = next_hotkey_text

        refresh_ms = 300 if self.is_resizing else 250
        self.root.after(refresh_ms, self.ui_update_loop)

    def shutdown(self) -> None:
        self.stop_event.set()
        try:
            self.listener.stop()
        except RuntimeError:
            pass
        with self.state_lock:
            self.rollover_if_new_day()
            self.sync_today_locked(time.monotonic())
        self.save_stats()
        if self.root.winfo_exists():
            self.root.quit()
            self.root.destroy()

    def exit_process(self) -> None:
        self.shutdown()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    app = CaptaApp()
    app.run()
