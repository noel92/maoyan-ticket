import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Python launcher for pure ADB bot.')
    parser.add_argument(
        '--config',
        default='configs/adb_flow.example.yaml',
        help='YAML config path (default: configs/adb_flow.example.yaml)',
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    bot_script = project_root / 'scripts' / 'pure_adb_bot.py'
    config_path = (project_root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)

    if not bot_script.exists():
        print(f'[ERR] Bot script not found: {bot_script}')
        return 1

    if not config_path.exists():
        print(f'[ERR] Config file not found: {config_path}')
        return 1

    cmd = [sys.executable, str(bot_script), '--config', str(config_path)]
    print(f'[INFO] Running: {" ".join(cmd)}')
    proc = subprocess.run(cmd)
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main())
