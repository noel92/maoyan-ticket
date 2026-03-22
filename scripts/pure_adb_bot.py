import argparse
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

import yaml

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None


def find_adb() -> str:
    candidates = [
        'adb',
        str(Path.home() / 'AppData/Local/Microsoft/WinGet/Packages/Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe/platform-tools/adb.exe'),
    ]
    for adb in candidates:
        try:
            subprocess.run([adb, 'version'], check=True, capture_output=True, text=True)
            return adb
        except Exception:
            continue
    raise RuntimeError('adb not found. Please install Android Platform Tools and ensure adb is available.')


def run_cmd(args: list[str], check: bool = True, capture: bool = True, text: bool = True):
    return subprocess.run(args, check=check, capture_output=capture, text=text)


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
        raise RuntimeError(f'Device not authorized/ready. adb devices:\n' + '\n'.join(lines))


def adb_shell(adb: str, serial: str | None, shell_cmd: list[str]) -> str:
    cmd = [adb]
    if serial:
        cmd += ['-s', serial]
    cmd += ['shell'] + shell_cmd
    return run_cmd(cmd).stdout.strip()


def get_system_setting(adb: str, serial: str | None, key: str) -> str:
    return adb_shell(adb, serial, ['settings', 'get', 'system', key]).strip()


def set_system_setting(adb: str, serial: str | None, key: str, value: str):
    adb_shell(adb, serial, ['settings', 'put', 'system', key, value])


def tap(adb: str, serial: str | None, x: int, y: int):
    adb_shell(adb, serial, ['input', 'tap', str(x), str(y)])


def swipe(adb: str, serial: str | None, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
    adb_shell(adb, serial, ['input', 'swipe', str(x1), str(y1), str(x2), str(y2), str(duration_ms)])


def keyevent(adb: str, serial: str | None, key: str):
    adb_shell(adb, serial, ['input', 'keyevent', key])


def text_input(adb: str, serial: str | None, text: str):
    safe = text.replace(' ', '%s')
    adb_shell(adb, serial, ['input', 'text', safe])


def screenshot(adb: str, serial: str | None, save_path: Path):
    cmd = [adb]
    if serial:
        cmd += ['-s', serial]
    cmd += ['exec-out', 'screencap', '-p']
    p = subprocess.run(cmd, check=True, capture_output=True)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(p.stdout)


def capture_screen_image(adb: str, serial: str | None):
    if cv2 is None or np is None:
        raise RuntimeError('opencv-python and numpy are required for page-change detection.')

    cmd = [adb]
    if serial:
        cmd += ['-s', serial]
    cmd += ['exec-out', 'screencap', '-p']
    p = subprocess.run(cmd, check=True, capture_output=True)
    arr = np.frombuffer(p.stdout, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError('Failed to decode screenshot from adb.')
    return img


def compute_change_ratio(base_img, current_img, roi: dict | None = None, pixel_diff_threshold: int = 20) -> float:
    h, w = base_img.shape[:2]
    if current_img.shape[:2] != (h, w):
        raise RuntimeError('Screen size changed during detection.')

    if roi:
        x = int(roi.get('x', 0))
        y = int(roi.get('y', 0))
        rw = int(roi.get('w', w))
        rh = int(roi.get('h', h))
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        rw = max(1, min(w - x, rw))
        rh = max(1, min(h - y, rh))
        base = base_img[y:y + rh, x:x + rw]
        curr = current_img[y:y + rh, x:x + rw]
    else:
        base = base_img
        curr = current_img

    base_gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
    curr_gray = cv2.cvtColor(curr, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(base_gray, curr_gray)
    changed_pixels = np.count_nonzero(diff >= pixel_diff_threshold)
    total_pixels = diff.shape[0] * diff.shape[1]
    return float(changed_pixels) / float(total_pixels)


def tap_then_if_changed_tap(
    adb: str,
    serial: str | None,
    first_x: int,
    first_y: int,
    second_x: int,
    second_y: int,
    third_x: int | None = None,
    third_y: int | None = None,
    timeout_sec: float = 2.0,
    check_interval_sec: float = 0.08,
    change_ratio_threshold: float = 0.012,
    roi: dict | None = None,
    tap_on_timeout: bool = False,
    debug_ratio_log: bool = False,
    min_detect_delay_sec: float = 0.30,
    required_consecutive_hits: int = 2,
    debug_show_touches: bool = False,
    post_second_enable: bool = True,
    post_second_detect_timeout_sec: float = 1.5,
    post_second_check_interval_sec: float = 0.05,
    post_second_change_ratio_threshold: float = 0.012,
    post_second_min_detect_delay_sec: float = 0.15,
    post_second_required_consecutive_hits: int = 1,
    post_second_burst_duration_sec: float = 3.0,
    post_second_burst_interval_ms: int = 15,
    post_second_alternate_with_third: bool = False,
    post_second_burst_on_timeout: bool = False,
    debug_post_second_ratio_log: bool = False,
):
    if timeout_sec <= 0:
        raise RuntimeError('tap_then_if_changed_tap timeout_sec must be > 0')
    if check_interval_sec <= 0:
        raise RuntimeError('tap_then_if_changed_tap check_interval_sec must be > 0')
    if change_ratio_threshold <= 0:
        raise RuntimeError('tap_then_if_changed_tap change_ratio_threshold must be > 0')
    if min_detect_delay_sec < 0:
        raise RuntimeError('tap_then_if_changed_tap min_detect_delay_sec must be >= 0')
    if required_consecutive_hits < 1:
        raise RuntimeError('tap_then_if_changed_tap required_consecutive_hits must be >= 1')
    if post_second_detect_timeout_sec <= 0:
        raise RuntimeError('tap_then_if_changed_tap post_second_detect_timeout_sec must be > 0')
    if post_second_check_interval_sec <= 0:
        raise RuntimeError('tap_then_if_changed_tap post_second_check_interval_sec must be > 0')
    if post_second_change_ratio_threshold <= 0:
        raise RuntimeError('tap_then_if_changed_tap post_second_change_ratio_threshold must be > 0')
    if post_second_min_detect_delay_sec < 0:
        raise RuntimeError('tap_then_if_changed_tap post_second_min_detect_delay_sec must be >= 0')
    if post_second_required_consecutive_hits < 1:
        raise RuntimeError('tap_then_if_changed_tap post_second_required_consecutive_hits must be >= 1')
    if post_second_burst_duration_sec <= 0:
        raise RuntimeError('tap_then_if_changed_tap post_second_burst_duration_sec must be > 0')
    if post_second_burst_interval_ms < 1:
        raise RuntimeError('tap_then_if_changed_tap post_second_burst_interval_ms must be >= 1')
    if post_second_alternate_with_third and (third_x is None or third_y is None):
        raise RuntimeError('tap_then_if_changed_tap requires third_x/third_y when post_second_alternate_with_third=true')

    previous_show_touches = None
    if debug_show_touches:
        previous_show_touches = get_system_setting(adb, serial, 'show_touches')
        set_system_setting(adb, serial, 'show_touches', '1')
        print('[INFO] debug show_touches=1 enabled')

    def run_post_second_burst():
        if post_second_alternate_with_third:
            deadline = time.perf_counter() + post_second_burst_duration_sec
            taps = 0
            use_second = True
            while time.perf_counter() < deadline:
                if use_second:
                    tap(adb, serial, second_x, second_y)
                else:
                    tap(adb, serial, int(third_x), int(third_y))
                use_second = not use_second
                taps += 1
                time.sleep(post_second_burst_interval_ms / 1000.0)
            print(
                f'[OK] post-second alternate burst taps={taps} '
                f'points=({second_x},{second_y})<->({int(third_x)},{int(third_y)}) '
                f'duration={post_second_burst_duration_sec}s interval={post_second_burst_interval_ms}ms'
            )
            return

        rapid_tap(
            adb,
            serial,
            second_x,
            second_y,
            post_second_burst_duration_sec,
            post_second_burst_interval_ms,
        )

    def detect_second_jump_and_burst(base_img_for_second):
        if not post_second_enable:
            return

        print('[INFO] second tap sent, waiting for next page change...')
        start2 = time.perf_counter()
        checks2 = 0
        max_ratio2 = 0.0
        hits2 = 0

        while time.perf_counter() - start2 <= post_second_detect_timeout_sec:
            elapsed2 = time.perf_counter() - start2
            curr2 = capture_screen_image(adb, serial)
            ratio2 = compute_change_ratio(base_img_for_second, curr2, roi=roi)
            checks2 += 1
            if ratio2 > max_ratio2:
                max_ratio2 = ratio2
            if debug_post_second_ratio_log:
                print(f'[DEBUG] post-second ratio check={checks2} elapsed={elapsed2:.3f}s ratio={ratio2:.4f}')

            if elapsed2 < post_second_min_detect_delay_sec:
                time.sleep(post_second_check_interval_sec)
                continue

            if ratio2 >= post_second_change_ratio_threshold:
                hits2 += 1
            else:
                hits2 = 0

            if hits2 >= post_second_required_consecutive_hits:
                run_post_second_burst()
                print(
                    f'[OK] post-second page changed ratio={ratio2:.4f}, burst tap '
                    f'(alternate={post_second_alternate_with_third})'
                )
                return

            time.sleep(post_second_check_interval_sec)

        if post_second_burst_on_timeout:
            run_post_second_burst()
            print(
                f'[WARN] post-second change timeout {post_second_detect_timeout_sec}s '
                f'(max_ratio={max_ratio2:.4f}), forced burst tap '
                f'(alternate={post_second_alternate_with_third})'
            )
            return

        print(
            f'[WARN] post-second change timeout {post_second_detect_timeout_sec}s '
            f'(max_ratio={max_ratio2:.4f}), skip burst tap'
        )

    try:
        base_img = capture_screen_image(adb, serial)
        tap(adb, serial, first_x, first_y)
        print(f'[INFO] first tap at ({first_x},{first_y}), waiting page change...')

        start = time.perf_counter()
        checks = 0
        max_ratio = 0.0
        consecutive_hits = 0
        while time.perf_counter() - start <= timeout_sec:
            elapsed = time.perf_counter() - start
            curr_img = capture_screen_image(adb, serial)
            ratio = compute_change_ratio(base_img, curr_img, roi=roi)
            checks += 1
            if ratio > max_ratio:
                max_ratio = ratio
            if debug_ratio_log:
                print(f'[DEBUG] change_ratio check={checks} elapsed={elapsed:.3f}s ratio={ratio:.4f}')

            if elapsed < min_detect_delay_sec:
                time.sleep(check_interval_sec)
                continue

            if ratio >= change_ratio_threshold:
                consecutive_hits += 1
            else:
                consecutive_hits = 0

            if consecutive_hits >= required_consecutive_hits:
                base_img_for_second = curr_img.copy()
                tap(adb, serial, second_x, second_y)
                print(
                    f'[OK] page changed ratio={ratio:.4f} threshold={change_ratio_threshold:.4f} '
                    f'checks={checks}, hits={consecutive_hits}, second tap=({second_x},{second_y})'
                )
                detect_second_jump_and_burst(base_img_for_second)
                return
            time.sleep(check_interval_sec)

        if tap_on_timeout:
            base_img_for_second = capture_screen_image(adb, serial)
            tap(adb, serial, second_x, second_y)
            print(
                f'[WARN] no page change in {timeout_sec}s (max_ratio={max_ratio:.4f}), '
                f'forced second tap=({second_x},{second_y})'
            )
            detect_second_jump_and_burst(base_img_for_second)
            return

        print(
            f'[WARN] no page change in {timeout_sec}s (max_ratio={max_ratio:.4f}), '
            f'skipped second tap=({second_x},{second_y})'
        )
    finally:
        if debug_show_touches and previous_show_touches in {'0', '1'}:
            set_system_setting(adb, serial, 'show_touches', previous_show_touches)
            print(f'[INFO] debug show_touches restored={previous_show_touches}')


def click_image(adb: str, serial: str | None, template_path: Path, threshold: float, timeout_sec: int, interval_sec: float):
    if cv2 is None or np is None:
        raise RuntimeError('opencv-python and numpy are required for click_image action.')

    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise RuntimeError(f'Cannot read template image: {template_path}')

    t_h, t_w = template.shape[:2]
    start = time.time()
    while time.time() - start <= timeout_sec:
        cmd = [adb]
        if serial:
            cmd += ['-s', serial]
        cmd += ['exec-out', 'screencap', '-p']
        p = subprocess.run(cmd, check=True, capture_output=True)

        arr = np.frombuffer(p.stdout, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            time.sleep(interval_sec)
            continue

        result = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= threshold:
            x = int(max_loc[0] + t_w / 2)
            y = int(max_loc[1] + t_h / 2)
            tap(adb, serial, x, y)
            print(f'[OK] click_image matched={max_val:.3f} tap=({x},{y})')
            return

        time.sleep(interval_sec)

    raise RuntimeError(f'click_image timeout: {template_path.name}, threshold={threshold}')


def wait_until(target_time: str):
    """Wait until local time reaches target_time.

    Supported formats:
    - YYYY-mm-dd HH:MM:SS
    - YYYY-mm-dd HH:MM:SS.mmm
    - HH:MM:SS
    - HH:MM:SS.mmm
    """
    now = dt.datetime.now()
    parsed = None
    date_formats = [
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d %H:%M:%S',
    ]
    time_formats = [
        '%H:%M:%S.%f',
        '%H:%M:%S',
    ]

    for fmt in date_formats:
        try:
            parsed = dt.datetime.strptime(target_time, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        for fmt in time_formats:
            try:
                t = dt.datetime.strptime(target_time, fmt).time()
                parsed = dt.datetime.combine(now.date(), t)
                if parsed < now:
                    parsed += dt.timedelta(days=1)
                break
            except ValueError:
                continue

    if parsed is None:
        raise RuntimeError(f'Invalid wait_until time format: {target_time}')

    remaining = (parsed - dt.datetime.now()).total_seconds()
    if remaining <= 0:
        print(f'[INFO] wait_until already reached: {parsed}')
        return

    print(f'[INFO] waiting until {parsed} ({remaining:.3f}s)')

    # Coarse sleep first, then short spin for better timing accuracy.
    if remaining > 0.25:
        time.sleep(remaining - 0.2)
    while dt.datetime.now() < parsed:
        pass


def rapid_tap(adb: str, serial: str | None, x: int, y: int, duration_sec: float, interval_ms: int, max_taps: int | None = None):
    if duration_sec <= 0:
        raise RuntimeError('rapid_tap duration_sec must be > 0')
    if interval_ms < 1:
        raise RuntimeError('rapid_tap interval_ms must be >= 1')

    deadline = time.perf_counter() + duration_sec
    taps = 0

    while time.perf_counter() < deadline:
        tap(adb, serial, x, y)
        taps += 1
        if max_taps is not None and taps >= max_taps:
            break
        time.sleep(interval_ms / 1000.0)

    print(f'[OK] rapid_tap taps={taps} point=({x},{y}) duration={duration_sec}s interval={interval_ms}ms')


def rapid_tap_count_shell(
    adb: str,
    serial: str | None,
    x: int,
    y: int,
    count: int,
    show_touches_debug: bool = False,
    preview_taps: int = 0,
    preview_interval_ms: int = 120,
):
    if count <= 0:
        raise RuntimeError('rapid_tap_count count must be > 0')

    if preview_taps < 0:
        raise RuntimeError('rapid_tap_count preview_taps must be >= 0')

    previous_show_touches = None
    if show_touches_debug:
        previous_show_touches = get_system_setting(adb, serial, 'show_touches')
        set_system_setting(adb, serial, 'show_touches', '1')
        print('[INFO] debug show_touches=1 enabled')

    print(f'[INFO] rapid_tap_count target point=({x},{y}), count={count}')

    try:
        for i in range(preview_taps):
            tap(adb, serial, x, y)
            print(f'[DEBUG] preview tap {i + 1}/{preview_taps} at ({x},{y})')
            time.sleep(preview_interval_ms / 1000.0)

        script = f'i=0; while [ $i -lt {count} ]; do input tap {x} {y}; i=$((i+1)); done'
        cmd = [adb]
        if serial:
            cmd += ['-s', serial]
        cmd += ['shell', 'sh', '-c', script]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f'[OK] rapid_tap_count taps={count} point=({x},{y}) mode=shell-loop')
    finally:
        if show_touches_debug and previous_show_touches in {'0', '1'}:
            set_system_setting(adb, serial, 'show_touches', previous_show_touches)
            print(f'[INFO] debug show_touches restored={previous_show_touches}')


def execute_actions(cfg: dict):
    adb = find_adb()
    serial = cfg.get('serial')
    ensure_device(adb, serial)

    actions = cfg.get('actions', [])
    if not actions:
        raise RuntimeError('No actions found in config file.')

    print(f'[INFO] Using adb: {adb}')
    print(f'[INFO] Serial: {serial or "(auto)"}')

    for idx, action in enumerate(actions, start=1):
        t = action.get('type')
        print(f'[STEP {idx}] {t}')

        if t == 'wait':
            time.sleep(float(action.get('seconds', 1)))
        elif t == 'wait_until':
            wait_until(str(action['time']))
        elif t == 'tap':
            tap(adb, serial, int(action['x']), int(action['y']))
        elif t == 'rapid_tap':
            rapid_tap(
                adb,
                serial,
                int(action['x']),
                int(action['y']),
                float(action.get('duration_sec', 3.0)),
                int(action.get('interval_ms', 30)),
                int(action['max_taps']) if 'max_taps' in action else None,
            )
        elif t == 'rapid_tap_count':
            rapid_tap_count_shell(
                adb,
                serial,
                int(action['x']),
                int(action['y']),
                int(action.get('count', 80)),
                bool(action.get('show_touches_debug', False)),
                int(action.get('preview_taps', 0)),
                int(action.get('preview_interval_ms', 120)),
            )
        elif t == 'tap_then_if_changed_tap':
            tap_then_if_changed_tap(
                adb,
                serial,
                int(action['first_x']),
                int(action['first_y']),
                int(action['second_x']),
                int(action['second_y']),
                int(action['third_x']) if 'third_x' in action else None,
                int(action['third_y']) if 'third_y' in action else None,
                float(action.get('timeout_sec', 2.0)),
                float(action.get('check_interval_sec', 0.08)),
                float(action.get('change_ratio_threshold', 0.012)),
                action.get('roi'),
                bool(action.get('tap_on_timeout', False)),
                bool(action.get('debug_ratio_log', False)),
                float(action.get('min_detect_delay_sec', 0.30)),
                int(action.get('required_consecutive_hits', 2)),
                bool(action.get('debug_show_touches', False)),
                bool(action.get('post_second_enable', True)),
                float(action.get('post_second_detect_timeout_sec', 1.5)),
                float(action.get('post_second_check_interval_sec', 0.05)),
                float(action.get('post_second_change_ratio_threshold', 0.012)),
                float(action.get('post_second_min_detect_delay_sec', 0.15)),
                int(action.get('post_second_required_consecutive_hits', 1)),
                float(action.get('post_second_burst_duration_sec', 3.0)),
                int(action.get('post_second_burst_interval_ms', 15)),
                bool(action.get('post_second_alternate_with_third', False)),
                bool(action.get('post_second_burst_on_timeout', False)),
                bool(action.get('debug_post_second_ratio_log', False)),
            )
        elif t == 'swipe':
            swipe(
                adb,
                serial,
                int(action['x1']),
                int(action['y1']),
                int(action['x2']),
                int(action['y2']),
                int(action.get('duration_ms', 300)),
            )
        elif t == 'text':
            text_input(adb, serial, str(action['value']))
        elif t == 'keyevent':
            keyevent(adb, serial, str(action['key']))
        elif t == 'screenshot':
            path = Path(action.get('path', 'output/screen.png'))
            screenshot(adb, serial, path)
            print(f'[OK] screenshot saved: {path}')
        elif t == 'click_image':
            template = Path(action['template'])
            click_image(
                adb,
                serial,
                template,
                float(action.get('threshold', 0.85)),
                int(action.get('timeout_sec', 10)),
                float(action.get('interval_sec', 0.5)),
            )
        else:
            raise RuntimeError(f'Unknown action type: {t}')

    print('[DONE] Flow completed.')


def main():
    parser = argparse.ArgumentParser(description='Pure ADB Android automation without installing phone-side helper app.')
    parser.add_argument('--config', required=True, help='YAML config file path')
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise RuntimeError(f'Config file not found: {config_path}')

    with config_path.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

    execute_actions(cfg)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'[ERR] {e}')
        sys.exit(1)
