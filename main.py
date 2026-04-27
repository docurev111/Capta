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
from pynput.keyboard import Controller, Key


class CaptaApp:
    SPLIT_SECONDS = 30 * 60
    SAVE_INTERVAL_SECONDS = 60
    AUTO_RESTART_DELAY_SECONDS = 5
    MIN_AUTO_RESTART_DELAY_SECONDS = 5

    def __init__(self) -> None:
        self.app_data_dir = self.get_app_data_dir()
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.stats_path = self.app_data_dir / "stats.json"
        self.config_path = self.app_data_dir / "config.json"
        self.keyboard_controller = Controller()
        self.state_lock = threading.Lock()
        self.stop_event = threading.Event()

        self.is_recording = False
        self.segment_start_monotonic: float | None = None
        self.total_seconds_today = 0
        self.last_session_date = ""
        self.ignore_page_up_presses = 0

        self.drag_start_x = 0
        self.drag_start_y = 0
        self.resize_start_x = 0
        self.resize_start_y = 0
        self.resize_start_width = 0
        self.resize_start_height = 0

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

        self.daily_worker = threading.Thread(
            target=self.daily_loop,
            name="capta-daily-loop",
            daemon=True,
        )
        self.daily_worker.start()

        self.ui_update_loop()

    def on_drag_start(self, event: tk.Event) -> None:
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_drag_move(self, event: tk.Event) -> None:
        x = self.root.winfo_x() + event.x - self.drag_start_x
        y = self.root.winfo_y() + event.y - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def on_resize_start(self, event: tk.Event) -> None:
        self.resize_start_x = event.x_root
        self.resize_start_y = event.y_root
        self.resize_start_width = self.root.winfo_width()
        self.resize_start_height = self.root.winfo_height()

    def on_resize_move(self, event: tk.Event) -> None:
        dx = event.x_root - self.resize_start_x
        dy = event.y_root - self.resize_start_y
        new_width = max(220, self.resize_start_width + dx)
        new_height = max(70, self.resize_start_height + dy)
        self.root.geometry(f"{new_width}x{new_height}")

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
            self.total_seconds_today = 0
            self.last_session_date = today_str
            self.save_stats()
            return

        try:
            data = json.loads(self.stats_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.total_seconds_today = 0
            self.last_session_date = today_str
            self.save_stats()
            return

        stored_total = data.get("total_seconds_today", 0)
        stored_date = data.get("last_session_date", today_str)

        if stored_date != today_str:
            self.total_seconds_today = 0
            self.last_session_date = today_str
            self.save_stats()
            return

        self.total_seconds_today = int(stored_total)
        self.last_session_date = stored_date

    def load_config(self) -> None:
        defaults = {
            "split_minutes": 30,
            "auto_restart_delay_seconds": self.AUTO_RESTART_DELAY_SECONDS,
            "save_interval_seconds": self.SAVE_INTERVAL_SECONDS,
        }

        data = defaults.copy()
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except (OSError, json.JSONDecodeError):
                data = defaults.copy()

        split_minutes = int(data.get("split_minutes", defaults["split_minutes"]))
        auto_restart_delay = int(
            data.get("auto_restart_delay_seconds", defaults["auto_restart_delay_seconds"])
        )
        save_interval = int(
            data.get("save_interval_seconds", defaults["save_interval_seconds"])
        )

        self.SPLIT_SECONDS = max(1, split_minutes) * 60
        self.AUTO_RESTART_DELAY_SECONDS = max(
            self.MIN_AUTO_RESTART_DELAY_SECONDS, auto_restart_delay
        )
        self.SAVE_INTERVAL_SECONDS = max(1, save_interval)

        normalized = {
            "split_minutes": self.SPLIT_SECONDS // 60,
            "auto_restart_delay_seconds": self.AUTO_RESTART_DELAY_SECONDS,
            "save_interval_seconds": self.SAVE_INTERVAL_SECONDS,
        }
        self.config_path.write_text(
            json.dumps(normalized, indent=2),
            encoding="utf-8",
        )

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
            self.total_seconds_today = 0
            self.last_session_date = today_str
            self.save_stats()

    def on_key_press(self, key: Key) -> None:
        if key != Key.page_up:
            return

        with self.state_lock:
            if self.ignore_page_up_presses > 0:
                self.ignore_page_up_presses -= 1
                return

        self.toggle_recording()

    def toggle_recording(self) -> None:
        with self.state_lock:
            self.rollover_if_new_day()
            if not self.is_recording:
                self.is_recording = True
                self.segment_start_monotonic = time.monotonic()
            else:
                self.is_recording = False
                self.segment_start_monotonic = None
                self.save_stats()

    def press_page_up_ignored(self) -> None:
        with self.state_lock:
            self.ignore_page_up_presses += 1

        self.keyboard_controller.press(Key.page_up)
        self.keyboard_controller.release(Key.page_up)

    def perform_split(self) -> None:
        self.press_page_up_ignored()
        time.sleep(self.AUTO_RESTART_DELAY_SECONDS)
        self.press_page_up_ignored()

        with self.state_lock:
            if self.is_recording:
                self.segment_start_monotonic = time.monotonic()

    def segment_loop(self) -> None:
        while not self.stop_event.is_set():
            should_split = False
            with self.state_lock:
                if self.is_recording and self.segment_start_monotonic is not None:
                    elapsed = time.monotonic() - self.segment_start_monotonic
                    if elapsed >= self.SPLIT_SECONDS:
                        should_split = True

            if should_split:
                self.perform_split()

            self.stop_event.wait(0.25)

    def daily_loop(self) -> None:
        seconds_since_last_save = 0
        while not self.stop_event.is_set():
            self.stop_event.wait(1)
            if self.stop_event.is_set():
                break

            with self.state_lock:
                self.rollover_if_new_day()
                if self.is_recording:
                    self.total_seconds_today += 1

                seconds_since_last_save += 1
                if seconds_since_last_save >= self.SAVE_INTERVAL_SECONDS:
                    self.save_stats()
                    seconds_since_last_save = 0

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
        with self.state_lock:
            is_recording = self.is_recording
            total_today = self.total_seconds_today
            segment_start = self.segment_start_monotonic

        segment_seconds = 0
        if is_recording and segment_start is not None:
            segment_seconds = int(time.monotonic() - segment_start)

        if is_recording:
            self.status_label.configure(
                text=f"● REC [{self.format_mmss(segment_seconds)}]",
                fg="#FF4D4D",
            )
        else:
            self.status_label.configure(
                text=f"○ IDLE [{self.format_mmss(segment_seconds)}]",
                fg="#FFFFFF",
            )

        self.daily_label.configure(text=f"Today: {self.format_hms(total_today)}")
        self.root.after(250, self.ui_update_loop)

    def shutdown(self) -> None:
        self.stop_event.set()
        try:
            self.listener.stop()
        except RuntimeError:
            pass
        self.save_stats()
        self.root.destroy()

    def exit_process(self) -> None:
        self.shutdown()
        os._exit(0)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    app = CaptaApp()
    app.run()
