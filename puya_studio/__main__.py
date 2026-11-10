"""Puya Studio entry point:  puya-studio [folder]   or   puya-studio new|build|check|examples|gen ...  (no window)."""
import argparse
import os
import sys


def cli(argv):
    from . import __version__, checks, codegen, chips, examples, toolchain
    from .project import Project
    ap = argparse.ArgumentParser(prog="puya-studio", description="CubeMX-style tool for PY32F030 / PY32F003 / PY32F002B")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    n = sub.add_parser("new", help="create a project from an example")
    n.add_argument("folder")
    n.add_argument("-c", "--chip", default="py32f030", choices=chips.CHIP_NAMES)
    n.add_argument("-e", "--example", default="blink")
    n.add_argument("-p", "--part")
    n.add_argument("--package")
    for name in ("build", "check", "gen"):
        s = sub.add_parser(name)
        s.add_argument("folder")
    sub.add_parser("examples", help="list the examples")
    sub.add_parser("tools", help="show which compiler is used")
    st = sub.add_parser("selftest", help="check compiler, flash algorithms and window (used by the CI on the finished program)")
    st.add_argument("--screenshot", help="write a PNG of the window")
    a = ap.parse_args(argv)
    if a.cmd == "examples":
        for e in examples.EXAMPLES:
            print(f"{e.id:14} {e.title}")
        return 0
    if a.cmd == "tools":
        print("compiler:", toolchain.gcc_version() or "NOT FOUND")
        print("folder  :", toolchain.find_gcc_bin())
        return 0 if toolchain.find_gcc_bin() else 1
    if a.cmd == "selftest":
        return selftest(a.screenshot)
    if a.cmd == "new":
        if a.example == "empty":
            p, sec = Project(a.chip), None
            if a.part:
                p.set_part(a.part)
        else:
            p, sec, wiring = examples.build(a.example, a.chip, a.part, a.package)
            print("\n".join(wiring))
        p.name = os.path.basename(os.path.abspath(a.folder))
        codegen.generate(p, a.folder, sec)
        print("created", a.folder)
        return 0
    if a.cmd == "gen":
        codegen.generate(Project.load(a.folder), a.folder)
        return 0
    if a.cmd == "check":
        probs = checks.check(Project.load(a.folder))
        for x in probs:
            print(x)
        return 1 if any(x.severity == "error" for x in probs) else 0
    if a.cmd == "build":
        p = Project.load(a.folder)
        codegen.generate(p, a.folder)
        r = toolchain.build(a.folder, p.name)
        print(r.log, end="")
        if r.ok:
            print(f"ROM {r.rom}/{r.flash_size} bytes, RAM {r.ram}/{r.ram_size} bytes")
        return 0 if r.ok else 1
    return None


def selftest(screenshot=None):
    import tempfile
    from . import chips, codegen, examples, flasher, toolchain
    print("version  :", __import__("puya_studio").__version__)
    print("compiler :", toolchain.gcc_version() or "NOT FOUND")
    if not toolchain.find_gcc_bin():
        return 1
    for cid in chips.CHIP_NAMES:
        p, sec, _ = examples.build("uart_hello", cid)
        folder = tempfile.mkdtemp()
        codegen.generate(p, folder, sec)
        r = toolchain.build(folder, "selftest")
        print(f"build    : {cid:10} {'ok' if r.ok and not r.warnings else 'FAILED'}  ROM {r.rom} RAM {r.ram}")
        if not r.ok or r.warnings:
            print(r.log)
            return 1
    from pyocd.target import TARGET
    from pyocd.target.pack import pack_target
    pack_target.PackTargets.populate_targets_from_pack(flasher.pack_path())
    names = [flasher.target_name(c, 16) for c in chips.all_chips()]
    missing = [n for n in names if n not in TARGET]
    print("pyocd    :", "flash algorithms for", ", ".join(names), "- ok" if not missing else f"MISSING {missing}")
    if missing:
        return 1
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    p, sec, _ = examples.build("uart_hello", "py32f030", package="LQFP32-K1")
    w.set_project(p, None)
    w.resize(1500, 900)
    w.show()
    app.processEvents()
    w.chipview.select_port("PA10")
    w.panel.show_port(p, "PA10")
    app.processEvents()
    if screenshot:
        w.grab().save(screenshot)
    print("window   : ok")
    print("SELFTEST OK")
    return 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("new", "build", "check", "gen", "examples", "tools", "selftest", "--version", "-h", "--help"):
        sys.exit(cli(argv))
    if sys.platform.startswith("win") and getattr(sys, "frozen", False):
        try:                                     # the window is the program: close the console that Windows opened for it
            import ctypes
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow
    app = QApplication(sys.argv)
    w = MainWindow()
    if argv and os.path.isdir(argv[0]):
        w.open_folder(argv[0])
    else:
        from .project import Project
        w.set_project(Project("py32f030"), None)
        w.show()
        w.new_project()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
