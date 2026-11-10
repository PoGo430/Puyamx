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
    a = ap.parse_args(argv)
    if a.cmd == "examples":
        for e in examples.EXAMPLES:
            print(f"{e.id:14} {e.title}")
        return 0
    if a.cmd == "tools":
        print("compiler:", toolchain.gcc_version() or "NOT FOUND")
        print("folder  :", toolchain.find_gcc_bin())
        return 0 if toolchain.find_gcc_bin() else 1
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


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("new", "build", "check", "gen", "examples", "tools", "--version", "-h", "--help"):
        sys.exit(cli(argv))
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
