# maoyan-ticket - Pure ADB Automation

This project includes a no-install Android automation workflow.
No helper app is installed on the phone; actions are executed through ADB only.

## Environment Setup (Windows)

1. Install ADB (Android Platform Tools):

```powershell
winget install --id Google.PlatformTools -s winget --accept-source-agreements --accept-package-agreements --disable-interactivity
```

2. Create Python virtual environment:

```powershell
py -m venv .venv
```

3. Install Python dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

4. Enable Android developer mode and USB debugging on your phone, then connect via USB.

5. Verify device connectivity:

```powershell
.\.venv\Scripts\python.exe scripts/check_device.py
```

## Run (Python)

Check device first:

```bash
D:/Dev/maoyan-ticket/.venv/Scripts/python.exe scripts/check_device.py
```

```bash
D:/Dev/maoyan-ticket/.venv/Scripts/python.exe scripts/run_pure_adb_bot.py
```

Optional custom config:

```bash
D:/Dev/maoyan-ticket/.venv/Scripts/python.exe scripts/run_pure_adb_bot.py --config configs/adb_flow.example.yaml
```

Ticket fast-click config:

```bash
D:/Dev/maoyan-ticket/.venv/Scripts/python.exe scripts/run_pure_adb_bot.py --config configs/maoyan_fast_click.yaml
```

Timed trigger config (fire two-step click at exact time):

```bash
D:/Dev/maoyan-ticket/.venv/Scripts/python.exe scripts/run_pure_adb_bot.py --config configs/maoyan_timed_fast_click.yaml
```

Auto-capture two tap coordinates and write YAML (`first_*` and `second_*`):

```bash
D:/Dev/maoyan-ticket/.venv/Scripts/python.exe scripts/capture_tap_point.py --config configs/maoyan_timed_fast_click.yaml --action-type tap_then_if_changed_tap
```

If `--config` is omitted, the tool will default to `configs/maoyan_timed_fast_click.yaml` when present.

Single-tap compatibility mode (write `x/y`):

```bash
D:/Dev/maoyan-ticket/.venv/Scripts/python.exe scripts/capture_tap_point.py --capture-count 1 --config configs/adb_flow.example.yaml --action-type tap
```

## Files

- `scripts/pure_adb_bot.py`: Main runner
- `scripts/run_pure_adb_bot.py`: Python launcher
- `scripts/check_device.py`: Python device check
- `scripts/capture_tap_point.py`: Capture one tap and write x/y into YAML
- `configs/adb_flow.example.yaml`: Action flow config
- `configs/maoyan_fast_click.yaml`: Ticket rush quick-click config
- `configs/maoyan_timed_fast_click.yaml`: Timed two-step click config
- `output/`: Screenshots and artifacts

## Action Types

- `wait`
- `wait_until` (time trigger)
- `tap`
- `rapid_tap` (high-frequency repeated tap)
- `rapid_tap_count` (faster shell-loop burst tap)
- `tap_then_if_changed_tap` (tap B only after page change)
- `swipe`
- `text`
- `keyevent`
- `screenshot`
- `click_image` (desktop OpenCV matching)

## Notes

- For stable automation, prioritize `click_image` + retries over fixed coordinates.
- Ensure phone stays unlocked while running scripts.
- For ticket rush scenarios, open the target page manually first, then run `configs/maoyan_fast_click.yaml`.
- Use `capture_tap_point.py` to avoid manual coordinate guessing.

`rapid_tap_count` debug options:
- `show_touches_debug: true` to show touch dots on phone during tapping.
- `preview_taps: 3` to perform visible test taps before burst tapping.
- `preview_interval_ms: 120` preview tap interval.

`tap_then_if_changed_tap` key options:
- `first_x/first_y`: first tap position (e.g., immediate purchase button).
- `second_x/second_y`: second tap position (e.g., confirm button).
- `change_ratio_threshold`: lower means more sensitive to page change (`0.010~0.020`).
- `tap_on_timeout`: force second tap if no change is detected before timeout.
- `min_detect_delay_sec`: ignore early UI ripple after first tap (recommend `0.25~0.50`).
- `required_consecutive_hits`: require N consecutive ratio hits before second tap (recommend `2`).
- `debug_show_touches`: show touch dots during this action and auto-restore setting.
