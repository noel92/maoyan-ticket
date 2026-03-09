import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml


def run_cmd(args: list[str], check: bool = True, capture: bool = True, text: bool = True):
    return subprocess.run(args, check=check, capture_output=capture, text=text)


def find_adb() -> str:
    candidates = [
        'adb',
        str(Path.home() / 'AppData/Local/Microsoft/WinGet/Packages/Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe/platform-tools/adb.exe'),
    ]
    for adb in candidates:
        try:
            run_cmd([adb, 'version'])
            return adb
        except Exception:
            continue
    raise RuntimeError('adb not found. Please install Android Platform Tools and ensure adb is available.')


def ensure_device(adb: str, serial: str | None) -> None:
    cmd = [adb]
    if serial:
        cmd += ['-s', serial]
    cmd += ['devices']

    out = run_cmd(cmd).stdout.strip().splitlines()
    lines = [line for line in out[1:] if line.strip()]
    if not lines:
        raise RuntimeError('No connected device found. Please connect phone with USB debugging enabled.')

    if serial:
        ok = any(line.startswith(f'{serial}\tdevice') for line in lines)
    else:
        ok = any('\tdevice' in line for line in lines)

    if not ok:
        raise RuntimeError('Device not authorized/ready. Check adb devices and authorize USB debugging.')


def get_screen_size(adb: str, serial: str | None) -> tuple[int, int]:
    cmd = [adb]
    if serial:
        cmd += ['-s', serial]
    cmd += ['shell', 'wm', 'size']
    out = run_cmd(cmd).stdout

    m = re.search(r'(\d+)x(\d+)', out)
    if not m:
        raise RuntimeError(f'Failed to parse screen size from output: {out}')
    return int(m.group(1)), int(m.group(2))


def pick_touch_device(adb: str, serial: str | None) -> tuple[str, int, int]:
    cmd = [adb]
    if serial:
        cmd += ['-s', serial]
    cmd += ['shell', 'getevent', '-lp']
    out = run_cmd(cmd).stdout

    sections = re.split(r'\n\s*add device \d+: ', out)
    candidates: list[tuple[str, int, int, int]] = []

    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue

        first_line_end = sec.find('\n')
        first_line = sec if first_line_end == -1 else sec[:first_line_end]
        device_path = first_line.strip()

        name_match = re.search(r'name:\s+"([^"]+)"', sec)
        name = name_match.group(1).lower() if name_match else ''

        x_match = re.search(r'ABS_MT_POSITION_X\s*:.*max\s+(\d+)', sec)
        y_match = re.search(r'ABS_MT_POSITION_Y\s*:.*max\s+(\d+)', sec)

        if not x_match or not y_match:
            continue

        x_max = int(x_match.group(1))
        y_max = int(y_match.group(1))

        score = 0
        if 'touch' in name or 'ts' in name or 'screen' in name:
            score += 2
        if '/dev/input/event' in device_path:
            score += 1

        candidates.append((device_path, x_max, y_max, score))

    if not candidates:
        raise RuntimeError('Cannot find touch input device with ABS_MT_POSITION_X/Y.')

    candidates.sort(key=lambda x: x[3], reverse=True)
    best = candidates[0]
    return best[0], best[1], best[2]


def capture_one_tap(adb: str, serial: str | None, device_path: str, timeout_sec: float) -> tuple[int, int]:
    cmd = [adb]
    if serial:
        cmd += ['-s', serial]
    cmd += ['shell', 'getevent', '-lt', device_path]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    x_raw = None
    y_raw = None
    touched = False
    start = time.time()

    try:
        while True:
            if time.time() - start > timeout_sec:
                raise RuntimeError(f'Capture timeout ({timeout_sec}s). Please run again and tap the button once.')

            line = proc.stdout.readline() if proc.stdout else ''
            if not line:
                if proc.poll() is not None:
                    raise RuntimeError('getevent process ended unexpectedly.')
                continue

            if 'ABS_MT_POSITION_X' in line:
                m = re.search(r'ABS_MT_POSITION_X\s+([0-9a-fA-F]+)', line)
                if m:
                    x_raw = int(m.group(1), 16)
            elif 'ABS_MT_POSITION_Y' in line:
                m = re.search(r'ABS_MT_POSITION_Y\s+([0-9a-fA-F]+)', line)
                if m:
                    y_raw = int(m.group(1), 16)
            elif 'BTN_TOUCH' in line and ('DOWN' in line or '00000001' in line):
                touched = True
            elif (
                ('BTN_TOUCH' in line and ('UP' in line or '00000000' in line))
                or ('ABS_MT_TRACKING_ID' in line and 'ffffffff' in line.lower())
            ):
                if touched and x_raw is not None and y_raw is not None:
                    return x_raw, y_raw
                touched = False
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


def to_screen_xy(x_raw: int, y_raw: int, x_max: int, y_max: int, width: int, height: int) -> tuple[int, int]:
    # Map raw touch axis values to screen pixel coordinates.
    x = int(round((x_raw / x_max) * (width - 1))) if x_max > 0 else x_raw
    y = int(round((y_raw / y_max) * (height - 1))) if y_max > 0 else y_raw
    return max(0, min(width - 1, x)), max(0, min(height - 1, y))


def update_yaml_single(config_path: Path, action_type: str, x: int, y: int) -> bool:
    with config_path.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

    actions = cfg.get('actions', [])
    for action in actions:
        if action.get('type') == action_type:
            action['x'] = int(x)
            action['y'] = int(y)
            with config_path.open('w', encoding='utf-8') as f:
                yaml.safe_dump(cfg, f, allow_unicode=False, sort_keys=False)
            return True
    return False


def update_yaml_double(config_path: Path, action_type: str, first_xy: tuple[int, int], second_xy: tuple[int, int]) -> bool:
    with config_path.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

    actions = cfg.get('actions', [])
    for action in actions:
        if action.get('type') == action_type:
            action['first_x'] = int(first_xy[0])
            action['first_y'] = int(first_xy[1])
            action['second_x'] = int(second_xy[0])
            action['second_y'] = int(second_xy[1])
            with config_path.open('w', encoding='utf-8') as f:
                yaml.safe_dump(cfg, f, allow_unicode=False, sort_keys=False)
            return True
    return False


def resolve_default_config() -> str:
    # Prefer timed config for current workflow; fallback to fast config for compatibility.
    timed = Path('configs/maoyan_timed_fast_click.yaml')
    fast = Path('configs/maoyan_fast_click.yaml')
    if timed.exists():
        return str(timed)
    return str(fast)


def main() -> int:
    parser = argparse.ArgumentParser(description='Capture tap coordinates from Android and write to YAML config.')
    parser.add_argument('--serial', default='', help='Device serial (optional)')
    parser.add_argument('--config', default='', help='YAML config path (default: timed config if present)')
    parser.add_argument('--action-type', default='tap_then_if_changed_tap', help='Action type to update coordinates')
    parser.add_argument('--capture-count', type=int, choices=[1, 2], default=2, help='Number of taps to capture (default: 2)')
    parser.add_argument('--timeout', type=float, default=15.0, help='Tap capture timeout seconds')
    args = parser.parse_args()

    if not args.config:
        args.config = resolve_default_config()

    adb = find_adb()
    serial = args.serial or None
    ensure_device(adb, serial)

    width, height = get_screen_size(adb, serial)
    device_path, x_max, y_max = pick_touch_device(adb, serial)

    print(f'[INFO] adb={adb}')
    print(f'[INFO] serial={serial or "(auto)"}')
    print(f'[INFO] screen={width}x{height}')
    print(f'[INFO] touch_device={device_path}, raw_max=({x_max},{y_max})')

    captures: list[tuple[int, int]] = []
    for i in range(args.capture_count):
        if args.capture_count == 1:
            print('[STEP] Tap target button on phone once...')
        else:
            label = 'first' if i == 0 else 'second'
            print(f'[STEP] Tap {label} target point on phone...')

        x_raw, y_raw = capture_one_tap(adb, serial, device_path, args.timeout)
        x, y = to_screen_xy(x_raw, y_raw, x_max, y_max, width, height)
        captures.append((x, y))
        if args.capture_count == 1:
            print(f'[OK] captured raw=({x_raw},{y_raw}) -> screen=({x},{y})')
        else:
            idx_label = 'first' if i == 0 else 'second'
            print(f'[OK] captured {idx_label}: raw=({x_raw},{y_raw}) -> screen=({x},{y})')

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path

    if not config_path.exists():
        print(f'[WARN] config not found, skip write: {config_path}')
        return 0

    if args.capture_count == 1:
        updated = update_yaml_single(config_path, args.action_type, captures[0][0], captures[0][1])
    else:
        updated = update_yaml_double(config_path, args.action_type, captures[0], captures[1])

    if updated:
        if args.capture_count == 1:
            print(
                f'[DONE] updated {config_path} action={args.action_type} '
                f'with x={captures[0][0]}, y={captures[0][1]}'
            )
        else:
            print(
                f'[DONE] updated {config_path} action={args.action_type} with '
                f'first=({captures[0][0]},{captures[0][1]}), '
                f'second=({captures[1][0]},{captures[1][1]})'
            )
    else:
        print(f'[WARN] no action type "{args.action_type}" in {config_path}, skip write')

    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\n[ERR] canceled by user')
        raise SystemExit(1)
    except Exception as e:
        print(f'[ERR] {e}')
        raise SystemExit(1)
