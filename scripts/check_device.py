import subprocess
from pathlib import Path


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
    raise SystemExit('[ERR] adb not found.')


def main() -> int:
    adb = find_adb()
    out = subprocess.run([adb, 'devices'], check=True, capture_output=True, text=True).stdout
    print(out)
    lines = [line for line in out.strip().splitlines()[1:] if line.strip()]
    if any('\tdevice' in line for line in lines):
        print('[OK] Device is connected and authorized.')
        return 0
    print('[ERR] No authorized device found.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
