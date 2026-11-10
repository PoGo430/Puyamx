"""The main window: pin drawing + pin panel, pages, Problems / Build / Monitor dock, Generate, Build, Flash."""
import os
import re
import subprocess
import sys

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QToolBar, QVBoxLayout, QWidget)

from .. import __version__, checks, codegen, examples, toolchain
from ..project import FILE_NAME, Project
from .chip_view import ChipView
from .dialogs import NewProjectDialog
from .programmer import MonitorPanel, ProgrammerPanel
from .panels import (AdcPage, ClockPage, I2cPage, InterruptPage, PinPanel, PowerPage, ProjectPage, SpiPage, TimerPage,
                     UsartPage)

SEV_COLOR = {"error": "#d83a3a", "warning": "#c08000", "info": "#5a6270"}


class CodePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.files = QComboBox()
        self.files.currentIndexChanged.connect(self.load)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save)
        self.open_btn = QPushButton("Open folder")
        self.open_btn.clicked.connect(self.open_folder)
        top.addWidget(self.files, 1)
        top.addWidget(self.save_btn)
        top.addWidget(self.open_btn)
        lay.addLayout(top)
        self.edit = QPlainTextEdit()
        f = QFont("monospace")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(10)
        self.edit.setFont(f)
        self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(self.edit, 1)
        lay.addWidget(QLabel("Write your code between  /* USER CODE BEGIN ... */  and  /* USER CODE END ... */ : it is kept when the project is generated again."))

    def set_folder(self, folder):
        self.folder = folder
        cur = self.files.currentText()
        self.files.blockSignals(True)
        self.files.clear()
        if folder and os.path.isdir(folder):
            names = [n for n in ("main.c", "interrupts.c", "init.c", "init.h") if os.path.exists(os.path.join(folder, n))]
            extra = sorted(n for n in os.listdir(folder) if n.endswith((".c", ".h")) and n not in names and not n.startswith(("py32", "startup")))
            self.files.addItems(names + extra)
        i = self.files.findText(cur)
        self.files.setCurrentIndex(max(i, 0))
        self.files.blockSignals(False)
        self.load()

    def load(self, *a):
        name = self.files.currentText()
        if not self.folder or not name:
            self.edit.setPlainText("")
            return
        with open(os.path.join(self.folder, name), encoding="utf8", errors="replace") as f:
            self.edit.setPlainText(f.read())
        self.edit.document().setModified(False)

    def save(self):
        name = self.files.currentText()
        if self.folder and name:
            with open(os.path.join(self.folder, name), "w", encoding="utf8", newline="\n") as f:
                f.write(self.edit.toPlainText())
            self.edit.document().setModified(False)

    def goto(self, file, line):
        i = self.files.findText(os.path.basename(file))
        if i >= 0:
            self.files.setCurrentIndex(i)
        block = self.edit.document().findBlockByLineNumber(max(0, line - 1))
        cur = self.edit.textCursor()
        cur.setPosition(block.position())
        self.edit.setTextCursor(cur)
        self.edit.centerCursor()
        self.edit.setFocus()

    def open_folder(self):
        if not self.folder:
            return
        if sys.platform.startswith("win"):
            os.startfile(self.folder)          # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", self.folder])
        else:
            subprocess.Popen(["xdg-open", self.folder])


class Worker(QThread):
    line = Signal(str)
    finished_ok = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.result = None

    def run(self):
        try:
            self.result = self.fn(self.line.emit)
        except Exception as e:                     # shown in the Output tab
            self.line.emit(f"error: {e}")
            self.result = None
        self.finished_ok.emit(self.result)


class MainWindow(QMainWindow):
    def __init__(self, project=None, folder=None):
        super().__init__()
        self.setWindowTitle("Puya Studio")
        self.resize(1500, 900)
        self.project = None
        self.folder = None
        self.auto_confirm = False           # tests answer the safety questions themselves
        self.last_build = None
        self.workers = []
        # centre: tabs; right: pin panel; bottom: problems
        self.tabs = QTabWidget()
        self.pinout = QWidget()
        pl = QHBoxLayout(self.pinout)
        self.chipview = ChipView()
        self.panel = PinPanel()
        self.panel.setMinimumWidth(300)
        self.panel.setMaximumWidth(380)
        pl.addWidget(self.chipview, 1)
        pl.addWidget(self.panel)
        self.pages = {
            "Project": ProjectPage(), "Pinout": self.pinout, "Clock": ClockPage(), "Timers / PWM": TimerPage(),
            "UART": UsartPage(), "SPI": SpiPage(), "I2C": I2cPage(), "ADC": AdcPage(), "Interrupts": InterruptPage(),
            "Low power": PowerPage(), "Code": CodePage(),
        }
        for name, w in self.pages.items():
            self.tabs.addTab(w, name)
            if hasattr(w, "changed") and not isinstance(w, CodePage):
                w.changed.connect(lambda w=w: self.on_changed(w))
        self.tabs.setCurrentWidget(self.pinout)
        self.tabs.currentChanged.connect(self.on_tab)
        self.setCentralWidget(self.tabs)
        self.stale = set()
        # bottom dock
        self.bottom = QTabWidget()
        self.problems = QListWidget()
        self.problems.itemDoubleClicked.connect(self.jump_to_problem)
        self.diag = QListWidget()
        self.diag.itemDoubleClicked.connect(self.jump_to_diag)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("monospace"))
        self.programmer_panel = ProgrammerPanel(self)
        self.programmer = self.programmer_panel
        self.monitor = MonitorPanel(self)
        self.bottom.addTab(self.problems, "Problems")
        self.bottom.addTab(self.diag, "Build errors")
        self.bottom.addTab(self.output, "Output")
        from PySide6.QtWidgets import QScrollArea
        prog_scroll = QScrollArea()
        prog_scroll.setWidgetResizable(True)
        prog_scroll.setWidget(self.programmer_panel)
        self.prog_scroll = prog_scroll
        self.bottom.addTab(prog_scroll, "Programmer")
        self.bottom.addTab(self.monitor, "Monitor")
        dock = QDockWidget("", self)
        dock.setWidget(self.bottom)
        dock.setTitleBarWidget(QWidget())
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.dock = dock
        self.bottom.setMaximumHeight(260)
        self.bottom.setMinimumHeight(150)
        self.resizeDocks([dock], [210], Qt.Vertical)
        self.status = self.statusBar()
        self.usage = QLabel("")
        self.status.addPermanentWidget(self.usage)
        self.build_actions()
        self.chipview.selected.connect(self.on_pin_selected)
        self.chipview.clear_requested.connect(self.on_clear)
        self.panel.changed.connect(lambda: self.on_changed(self.panel))
        self.panel.port_chosen.connect(self.on_port_chosen)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.run_checks)
        if project:
            self.set_project(project, folder)

    # ------------------------------------------------------------------ actions
    def build_actions(self):
        tb = QToolBar("main")
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, slot, key=None, menu=None, tip=None, toolbar=True):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(QKeySequence(key))
            if tip:
                a.setToolTip(tip)
            if menu is not None:
                menu.addAction(a)
            if toolbar:
                tb.addAction(a)
            return a
        mf = self.menuBar().addMenu("&File")
        self.a_new = act("New...", self.new_project, "Ctrl+N", mf)
        self.a_open = act("Open...", self.open_project, "Ctrl+O", mf)
        self.a_save = act("Save", self.save_project, "Ctrl+S", mf, toolbar=False)
        mf.addSeparator()
        act("Quit", self.close, "Ctrl+Q", mf, toolbar=False)
        mb = self.menuBar().addMenu("&Project")
        self.a_gen = act("Generate code", self.generate, "Ctrl+G", mb, "Write the C project (your USER CODE stays)")
        self.a_build = act("Build", self.build, "Ctrl+B", mb, "Compile with arm-none-eabi-gcc")
        self.a_flash = act("Flash", self.flash, "Ctrl+U", mb, "Build and write the chip")
        self.a_mon = act("Monitor", self.start_monitor, "Ctrl+M", mb, "Serial monitor")
        mh = self.menuBar().addMenu("&Help")
        act("About", self.about, None, mh, toolbar=False)

    # ------------------------------------------------------------------ project handling
    def set_project(self, project, folder=None):
        self.project = project
        self.folder = folder
        self.chipview.set_project(project)
        self.panel.show_port(project, None)
        for name, w in self.pages.items():
            if hasattr(w, "set_project"):
                w.set_project(project)
        self.pages["Code"].set_folder(folder)
        self.setWindowTitle(f"Puya Studio - {project.name} ({project.part or project.chip.name})" + (f" - {folder}" if folder else ""))
        self.run_checks()

    def new_project(self):
        dlg = NewProjectDialog(self, os.path.dirname(self.folder) if self.folder else None)
        if dlg.exec() != dlg.Accepted:
            return
        self.create_from_dialog(dlg)

    def create_from_dialog(self, dlg):
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", dlg.name.text().strip() or "project")
        folder = os.path.join(dlg.folder.text(), name)
        cid, part, pk, flash = dlg.selection()
        eid = dlg.example_id()
        sections = None
        if eid == "empty":
            p = dlg.make_project()
        else:
            p, sections, _ = examples.build(eid, cid, part, pk, None if part else flash)
        p.name = name
        os.makedirs(folder, exist_ok=True)
        self.set_project(p, folder)
        codegen.generate(p, folder, sections)
        self.pages["Code"].set_folder(folder)
        self.status.showMessage(f"Created {folder}", 5000)

    def open_project(self):
        d = QFileDialog.getExistingDirectory(self, "Open a project folder (contains project.pstudio)")
        if d:
            self.open_folder(d)

    def open_folder(self, d):
        if not os.path.exists(os.path.join(d, FILE_NAME)):
            QMessageBox.warning(self, "Open", f"There is no {FILE_NAME} in {d}.")
            return
        self.set_project(Project.load(d), d)

    def save_project(self):
        if self.project and self.folder:
            self.project.save(self.folder)
            self.pages["Code"].save()

    # ------------------------------------------------------------------ editing
    def on_pin_selected(self, port):
        self.panel.show_port(self.project, port)

    def on_clear(self, port):
        self.project.clear(port)
        self.panel.show_port(self.project, port)
        self.on_changed(self.panel)

    def on_port_chosen(self, port):
        self.chipview.select_port(port)
        self.panel.show_port(self.project, port)

    def on_changed(self, sender=None):
        for name, w in self.pages.items():
            if w is sender or not hasattr(w, "refresh"):
                continue
            if w is self.tabs.currentWidget():
                w.refresh()
            else:
                self.stale.add(w)
        self.chipview.update()
        if self.folder:
            try:
                self.project.save(self.folder)
            except OSError:
                pass
        self.timer.start()

    def on_tab(self, i):
        w = self.tabs.widget(i)
        if w in self.stale and hasattr(w, "refresh"):
            w.refresh()
            self.stale.discard(w)
        if isinstance(w, CodePage):
            w.set_folder(self.folder)

    # ------------------------------------------------------------------ problems
    def run_checks(self):
        if not self.project:
            return
        probs = checks.check(self.project)
        self.current_problems = probs
        self.problems.clear()
        marks = {}
        for pr in probs:
            it = QListWidgetItem(f"{pr.severity.upper():8} {pr.text}")
            it.setForeground(QColor(SEV_COLOR[pr.severity]))
            it.setData(Qt.UserRole, pr.target)
            self.problems.addItem(it)
            if pr.target[0] == "pin":
                old = marks.get(pr.target[1])
                if old != "error":
                    marks[pr.target[1]] = pr.severity
        self.chipview.set_problems(marks)
        ne = sum(1 for x in probs if x.severity == "error")
        nw = sum(1 for x in probs if x.severity == "warning")
        self.bottom.setTabText(0, f"Problems ({ne} errors, {nw} warnings)")
        self.status.showMessage(f"{ne} errors, {nw} warnings", 3000)

    def jump_to_problem(self, item):
        self.jump(item.data(Qt.UserRole))

    def jump(self, target):
        kind, ident = target
        if kind == "pin":
            self.tabs.setCurrentWidget(self.pinout)
            self.chipview.select_port(ident)
            self.panel.show_port(self.project, ident)
            self.chipview.setFocus()
        elif kind == "clock":
            self.tabs.setCurrentWidget(self.pages["Clock"])
        elif kind == "power":
            self.tabs.setCurrentWidget(self.pages["Low power"])
        elif kind == "periph":
            page = ("UART" if ident.startswith("USART") else "SPI" if ident.startswith("SPI") else "I2C" if ident.startswith("I2C")
                    else "ADC" if ident == "ADC" else "Low power" if ident == "IWDG" else "Timers / PWM")
            self.tabs.setCurrentWidget(self.pages[page])
        else:
            self.tabs.setCurrentWidget(self.pages["Project"])

    # ------------------------------------------------------------------ generate / build / flash
    def need_folder(self):
        if not self.project:
            return False
        if self.folder:
            return True
        d = QFileDialog.getExistingDirectory(self, "Choose a folder for the project")
        if not d:
            return False
        self.folder = os.path.join(d, self.project.name)
        return True

    def confirm_dangerous(self):
        risky = [x for x in checks.check(self.project) if x.code in ("swd-pin", "nrst-pin")]
        if not risky or self.auto_confirm:
            return True
        text = "\n".join(f"- {x.text}" for x in risky) + "\n\nGenerate anyway?"
        return QMessageBox.question(self, "Debug / reset pin changed", text) == QMessageBox.Yes

    def generate(self):
        if not self.need_folder():
            return False
        if self.pages["Code"].edit.document().isModified():
            self.pages["Code"].save()
        if not self.confirm_dangerous():
            return False
        try:
            codegen.generate(self.project, self.folder)
        except codegen.GenError as e:
            self.output.appendPlainText(f"error: {e}")
            self.bottom.setCurrentWidget(self.output)
            return False
        self.pages["Code"].set_folder(self.folder)
        self.status.showMessage(f"Generated into {self.folder}", 4000)
        return True

    def build(self):
        if not self.generate():
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = toolchain.build(self.folder, re.sub(r"\W", "_", self.project.name) or "firmware")
        finally:
            QApplication.restoreOverrideCursor()
        self.last_build = r
        self.output.setPlainText(r.log or "build ok")
        self.diag.clear()
        for d in r.diagnostics:
            it = QListWidgetItem(f"{d.file}:{d.line}: {d.severity}: {d.message}")
            it.setForeground(QColor(SEV_COLOR.get(d.severity, "#000000")))
            it.setData(Qt.UserRole, (d.file, d.line))
            self.diag.addItem(it)
        if r.ok:
            self.usage.setText(f"ROM {r.rom} / {r.flash_size} B ({100 * r.rom / max(1, r.flash_size):.1f} %)    "
                               f"RAM {r.ram} / {r.ram_size} B ({100 * r.ram / max(1, r.ram_size):.1f} %)")
            self.bottom.setTabText(1, f"Build errors ({len(r.warnings)} warnings)")
            self.bottom.setCurrentWidget(self.output)
        else:
            self.usage.setText("build failed")
            self.bottom.setTabText(1, f"Build errors ({len(r.errors)})")
            self.bottom.setCurrentWidget(self.diag)
        return r

    def jump_to_diag(self, item):
        data = item.data(Qt.UserRole)
        if data and data[0]:
            self.tabs.setCurrentWidget(self.pages["Code"])
            self.pages["Code"].set_folder(self.folder)
            self.pages["Code"].goto(data[0], data[1])

    def flash(self):
        r = self.build()
        if not r or not r.ok:
            return None
        self.bottom.setCurrentWidget(self.prog_scroll)
        return self.programmer.flash(r)

    def start_monitor(self):
        self.bottom.setCurrentWidget(self.monitor)
        self.monitor.use_project_baud()
        self.monitor.refresh()

    def about(self):
        QMessageBox.about(self, "Puya Studio",
                          f"<b>Puya Studio {__version__}</b><br>A CubeMX-style tool for PY32F030, PY32F003 and PY32F002B.<br>"
                          f"Compiler: {toolchain.gcc_version() or 'not found'}")
