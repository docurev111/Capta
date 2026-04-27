# Capta

Capta is a lightweight Windows utility that automates 30-minute Medal recording splits using the `Page Up` key.

## Features

- Global `Page Up` hotkey toggle:
  - `IDLE -> REC` starts the recording session timer
  - `REC -> IDLE` stops the recording session timer
- Automatic split loop while recording:
  1. Sends `Page Up` to end the current clip
  2. Waits `auto_restart_delay_seconds` (minimum 5s)
  3. Sends `Page Up` again to start the next clip
- Ignores its own simulated `Page Up` presses to prevent recursive toggles
- Persistent daily tracking in `stats.json`:
  - `total_seconds_today`
  - `last_session_date`
- Auto-save progress every `save_interval_seconds`
- Minimal, dark, always-on-top Tkinter overlay:
  - Draggable
  - Resizable with bottom-right grip
  - Exit button that fully terminates the process

## Requirements

- Windows
- Python 3.10+ (tested on 3.14)

Install dependencies:

```bash
python -m pip install pynput pyautogui
```

## Run from source

```bash
python main.py
```

## Configuration

Edit `config.json`:

```json
{
  "split_minutes": 30,
  "auto_restart_delay_seconds": 5,
  "save_interval_seconds": 60
}
```

Notes:
- `auto_restart_delay_seconds` is clamped to a minimum of `5`
- `save_interval_seconds` controls how often `stats.json` is written to disk

## Build EXE

Install builder:

```bash
python -m pip install pyinstaller
```

Build:

```bash
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Capta main.py
```

Output:
- `dist/Capta.exe`

## Usage

1. Make sure Medal is using `Page Up` as its record/split hotkey.
2. Launch `Capta.exe` (or `python main.py`).
3. Press `Page Up` once to start automation.
4. Press `Page Up` again to stop.

## Project Files

- `main.py` - app logic, hotkey listener, UI, timers
- `config.json` - user-tunable runtime settings
- `stats.json` - auto-generated daily session stats
- `dist/Capta.exe` - packaged executable
