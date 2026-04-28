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
  - In-app settings panel (`⚙`) for timer values and hotkey
  - Exit button that fully terminates the process

## For End Users (No Python Needed)

- Download `Capta.exe` from this repo (or Releases)
- Run `Capta.exe`
- Make sure Medal uses `Page Up` as its record/split hotkey

## Usage

1. Launch `Capta.exe`.
2. Press `Page Up` once to start automation (`REC`).
3. Press `Page Up` again to stop (`IDLE`).

## Configuration

Edit `config.json` in:

- `%APPDATA%\Capta\config.json`

```json
{
  "split_minutes": 30,
  "auto_restart_delay_seconds": 5,
  "save_interval_seconds": 60,
  "hotkey": "page_up"
}
```

Notes:
- `auto_restart_delay_seconds` is clamped to a minimum of `5`
- `save_interval_seconds` controls how often `%APPDATA%\Capta\stats.json` is written to disk
- `hotkey` controls both the global toggle and simulated split key press
  - Supported named keys: `page_up`, `page_down`, `home`, `end`, `insert`, `delete`, `space`, `tab`, `enter`, `esc`, `f1`-`f12`
  - Single character hotkeys are also supported (example: `"r"`)

## Developer Setup (Source + Build)

Requirements:
- Windows
- Python 3.10+ (tested on 3.14)

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run from source:

```bash
python main.py
```

Build EXE:

Install builder:

```bash
python -m pip install pyinstaller
```

Build:

```bash
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Capta --icon logo.ico main.py
```

Output:
- `dist/Capta.exe`

## Project Files

- `main.py` - app logic, hotkey listener, UI, timers
- `%APPDATA%\Capta\config.json` - user-tunable runtime settings
- `%APPDATA%\Capta\stats.json` - auto-generated daily session stats
- `dist/Capta.exe` - packaged executable
