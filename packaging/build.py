"""Build the one-file program:  python packaging/build.py     ->  dist/puya-studio  (dist/puya-studio.exe on Windows)

Needs: pip install -r requirements-dev.txt.  The compiler is fetched and trimmed first (packaging/fetch_tools.py).
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WIN = sys.platform.startswith("win")
SEP = ";" if WIN else ":"


def main():
    key = "win32" if WIN else "linux"
    tools = os.path.join(HERE, f"tools-{key}", "arm-none-eabi")
    if not os.path.exists(os.path.join(tools, "bin")):
        subprocess.check_call([sys.executable, os.path.join(HERE, "fetch_tools.py")])
    for d in ("build", "dist"):
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", "puya-studio",
           "--console",
           "--paths", ROOT,
           "--add-data", f"{os.path.join(ROOT, 'puya_studio', 'chips')}{SEP}puya_studio/chips",
           "--add-data", f"{os.path.join(ROOT, 'puya_studio', 'data')}{SEP}puya_studio/data",
           "--add-data", f"{tools}{SEP}tools/arm-none-eabi",
           "--collect-all", "pyocd", "--collect-all", "cmsis_pack_manager", "--collect-all", "libusb_package",
           "--copy-metadata", "pyocd", "--copy-metadata", "libusb-package",
           "--hidden-import", "serial.tools.list_ports", "--hidden-import", "usb.backend.libusb1",
           "--exclude-module", "tkinter", "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtQml",
           "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.Qt3DCore", "--exclude-module", "PySide6.QtMultimedia",
           os.path.join(HERE, "launcher.py")]
    subprocess.check_call(cmd, cwd=ROOT)
    exe = os.path.join(ROOT, "dist", "puya-studio" + (".exe" if WIN else ""))
    print(f"built {exe}  ({os.path.getsize(exe) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
