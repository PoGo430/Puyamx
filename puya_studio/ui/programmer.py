"""Programmer panel (flash, info, option bytes, erase) and serial monitor."""
import os

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QApplication)

from .. import flasher, option_bytes, serial_isp
from .panels import combo


class Task(QThread):
    log = Signal(str)
    done = Signal(object, str)          # result, error text

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.log.emit), "")
        except Exception as e:
            self.done.emit(None, str(e))


class OptionBytesDialog(QDialog):
    """Shows every option byte field; nothing is written from here (the panel plans and confirms first)."""

    def __init__(self, chip, words, valid, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Option bytes of {chip.name}")
        self.chip = chip
        self.words = dict(words)
        lay = QVBoxLayout(self)
        bad = [n for n, v in valid.items() if not v]
        if bad:
            lay.addWidget(QLabel("<b style='color:#c08000'>Some option words have a wrong complement (" + ", ".join(bad) + "): the chip uses default values for them.</b>"))
        lay.addWidget(QLabel("Changes that could lock the chip or make it hard to reach are marked when you press Apply."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Field", "Value", "Meaning"])
        self.widgets = {}
        for name, addr, fields in option_bytes.layout(chip):
            for fn, (lsb, width) in fields.items():
                r = self.table.rowCount()
                self.table.insertRow(r)
                self.table.setItem(r, 0, QTableWidgetItem(f"{name}.{fn}"))
                sp = QSpinBox()
                sp.setRange(0, (1 << width) - 1)
                sp.setValue((words[name] >> lsb) & ((1 << width) - 1))
                sp.setDisplayIntegerBase(16 if width > 4 else 10)
                self.table.setCellWidget(r, 1, sp)
                self.table.setItem(r, 2, QTableWidgetItem(self.meaning(f"{fn}", chip)))
                self.widgets[(name, fn)] = sp
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.default_btn = QPushButton("Production values")
        self.default_btn.clicked.connect(self.reset_defaults)
        bb.addButton(self.default_btn, QDialogButtonBox.ActionRole)
        lay.addWidget(bb)
        self.resize(640, 480)

    @staticmethod
    def meaning(f, chip):
        return {"RDP": "0xAA = open, anything else = read-out protection", "NRST_MODE": "1 = reset pin used as GPIO", "SWD_MODE": "see RM: moves the SWD pins",
                "BOR_EN": "brown-out reset on", "BOR_LEV": "threshold 1.8 V + 0.2 V x value (rising)", "IWDG_SW": "0 = watchdog starts by itself",
                "WWDG_SW": "0 = window watchdog starts by itself", "nBOOT1": "boot selection together with BOOT0", "BOOT0": "boot selection",
                "BOOT_SIZE": "load-flash area size", "WRP": "0 = sector write-protected", "SDK_STRT": "SDK area start (2 KB steps)",
                "SDK_END": "SDK area end (2 KB steps)", "IWDG_STOP": "watchdog runs in stop mode"}.get(f, "")

    def reset_defaults(self):
        d = option_bytes.defaults(self.chip)
        for (name, fn), sp in self.widgets.items():
            lsb, width = option_bytes.layout_dict(self.chip)[name][fn]
            sp.setValue((d[name] >> lsb) & ((1 << width) - 1))

    def result_words(self):
        w = dict(self.words)
        for (name, fn), sp in self.widgets.items():
            w = option_bytes.set_field(self.chip, w, name, fn, sp.value())
        return w


class ProgrammerPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.w = window
        self.tasks = []
        self.swd_factory = None                         # tests replace this with a fake
        self.confirm_text = self._ask_typed             # tests replace this too
        lay = QVBoxLayout(self)
        box = QGroupBox("How to connect")
        f = QFormLayout(box)
        self.rb_swd = QRadioButton("Debug probe (SWD): ST-Link V2, DAPLink / CMSIS-DAP")
        self.rb_isp = QRadioButton("USB-serial adapter and the chip's boot loader (not PY32F002B)")
        self.rb_swd.setChecked(True)
        f.addRow(self.rb_swd)
        self.probes = QComboBox()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        row = QHBoxLayout()
        row.addWidget(self.probes, 1)
        row.addWidget(self.refresh_btn)
        f.addRow("Probe", row)
        self.under_reset = QCheckBox("connect under reset (use this if the chip does not answer, e.g. SWD pins reassigned)")
        f.addRow("", self.under_reset)
        self.speed = combo([("100 kHz", 100_000), ("1 MHz", 1_000_000), ("4 MHz", 4_000_000)], 1_000_000)
        f.addRow("SWD speed", self.speed)
        f.addRow(self.rb_isp)
        self.ports = QComboBox()
        f.addRow("Serial port", self.ports)
        self.baud = combo([("115200", 115200), ("57600", 57600), ("230400", 230400), ("460800", 460800)], 115200)
        f.addRow("Boot loader baud", self.baud)
        f.addRow("", QLabel("Boot loader: BOOT0 (PF4) high at reset; adapter TX to PA3/PA10/PA15, RX to PA2/PA9/PA14. Adapters with DTR/RTS wired to BOOT0/NRST do it automatically."))
        lay.addWidget(box)
        btns = QHBoxLayout()
        self.b_flash = QPushButton("Build and flash")
        self.b_info = QPushButton("Chip info")
        self.b_erase = QPushButton("Erase chip...")
        self.b_opt = QPushButton("Option bytes...")
        self.b_udev = QPushButton("Probe setup (Linux udev)")
        for b in (self.b_flash, self.b_info, self.b_erase, self.b_opt, self.b_udev):
            btns.addWidget(b)
        lay.addLayout(btns)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        self.b_flash.clicked.connect(lambda: self.w.flash())
        self.b_info.clicked.connect(self.chip_info)
        self.b_erase.clicked.connect(self.erase_chip)
        self.b_opt.clicked.connect(self.option_bytes)
        self.b_udev.clicked.connect(self.show_udev)
        self.refresh_devices()

    # ------------------------------------------------------------------
    def refresh_devices(self):
        self.probes.clear()
        for p in flasher.list_probes():
            self.probes.addItem(f"{p['kind']}: {p['name']}  [{p['uid']}]", p["uid"])
        if not self.probes.count():
            self.probes.addItem("no probe found", None)
        self.ports.clear()
        for p in flasher.list_serial_ports():
            self.ports.addItem(p["name"], p["device"])
        if not self.ports.count():
            self.ports.addItem("no serial port found", None)

    def say(self, text):
        self.log.appendPlainText(text)
        self.w.output.appendPlainText(text)

    def project(self):
        return self.w.project

    def make_swd(self):
        p = self.project()
        kw = dict(uid=self.probes.currentData(), speed=self.speed.currentData(), mode="under-reset" if self.under_reset.isChecked() else "attach", log=self.say)
        if self.swd_factory:
            return self.swd_factory(p.chip, p.flash_kb, **kw)
        return flasher.Swd(p.chip, p.flash_kb, **kw)

    def run(self, fn, done):
        t = Task(fn, self)
        t.log.connect(self.say)

        def finished(res, err):
            if err:
                self.say(f"error: {err}")
                self.w.bottom.setCurrentWidget(self.w.output)
            else:
                done(res)
            if t in self.tasks:
                self.tasks.remove(t)
        t.done.connect(finished)
        self.tasks.append(t)
        t.start()
        return t

    def wait(self):
        for t in list(self.tasks):
            t.wait(60000)
        QApplication.processEvents()

    # ------------------------------------------------------------------ actions
    def flash(self, build):
        p = self.project()
        if build is None or not build.ok:
            return
        self.w.bottom.setCurrentWidget(self.w.output)
        if self.rb_isp.isChecked():
            dev = self.ports.currentData()
            if not dev:
                self.say("error: no serial port selected")
                return
            data = flasher.firmware_bytes(build.bin)
            return self.run(lambda log: flasher.isp_flash(p.chip, dev, data, self.baud.currentData(), log), lambda r: self.say("done: programmed through the boot loader"))

        def job(log):
            with self.make_swd() as s:
                info = s.info()
                if info["read_protected"]:
                    raise flasher.ProgrammerError("the chip is read-protected (RDP). Erasing it destroys its contents: use 'Erase chip...' first if you want that.")
                s.program(build.hex)
                s.reset_run()
            return True
        return self.run(job, lambda r: self.say("done: programmed and started"))

    def chip_info(self):
        p = self.project()

        def job(log):
            if self.rb_isp.isChecked():
                dev = self.ports.currentData()
                port = serial_isp.open_port(dev, self.baud.currentData())
                try:
                    serial_isp.enter_bootloader(port)
                    isp = serial_isp.Isp(port, log)
                    isp.sync()
                    pid = isp.identify()
                    return {"boot loader": f"v{isp.version >> 4}.{isp.version & 15}", "ID": hex(pid)}
                finally:
                    serial_isp.leave_bootloader(port)
                    port.close()
            with self.make_swd() as s:
                return s.info()
        return self.run(job, lambda r: self.say("chip: " + ", ".join(f"{k}={v}" for k, v in r.items())))

    def erase_chip(self):
        if QMessageBox.question(self.w, "Erase chip", "The whole flash will be erased (and read protection removed if it is on). Continue?") != QMessageBox.Yes:
            return

        def job(log):
            if self.rb_isp.isChecked():
                port = serial_isp.open_port(self.ports.currentData(), self.baud.currentData())
                try:
                    serial_isp.enter_bootloader(port)
                    isp = serial_isp.Isp(port, log)
                    isp.sync()
                    try:
                        isp.erase_all()
                    except serial_isp.IspError:
                        log("mass erase refused (read protection?): removing read protection, which erases the flash")
                        isp.unlock_read_protection()
                finally:
                    serial_isp.leave_bootloader(port)
                    port.close()
                return True
            with self.make_swd() as s:
                s.erase_chip()
            return True
        return self.run(job, lambda r: self.say("done: flash erased"))

    def _ask_typed(self, word, text):
        ans, ok = QInputDialog.getText(self.w, "Confirm", f"{text}\n\nType {word} to go on:")
        return ok and ans.strip().upper() == word

    def confirm(self, plan):
        chip = self.project().chip
        text = "\n\n".join(f"- {d.text}" for d in plan.dangers)
        if plan.needs_typed_confirmation:
            return self.confirm_text(option_bytes.confirmation_word(chip, plan), text)
        if plan.dangers:
            return QMessageBox.question(self.w, "Option bytes", text + "\n\nWrite anyway?") == QMessageBox.Yes
        return True

    def option_bytes(self):
        p = self.project()
        if self.rb_isp.isChecked():
            QMessageBox.information(self.w, "Option bytes", "Use the debug probe (SWD) to edit option bytes. (The serial boot loader can only restore defaults.)")
            return

        def read_job(log):
            with self.make_swd() as s:
                return s.info()
        return self.run(read_job, self._edit_options)

    def _edit_options(self, info):
        p = self.project()
        dlg = OptionBytesDialog(p.chip, info["option_words"], info["option_valid"], self.w)
        if getattr(self, "option_dialog_hook", None):
            self.option_dialog_hook(dlg)
        if dlg.exec() != QDialog.Accepted:
            return
        new = dlg.result_words()
        plan = option_bytes.plan(p.chip, info["option_words"], new, p.vdd)
        if plan.empty:
            self.say("option bytes: nothing changed")
            return
        self.say("option bytes: " + ", ".join(f"{k}: {a} -> {b}" for k, (a, b) in plan.changes.items()))
        if not self.confirm(plan):
            self.say("option bytes: cancelled, nothing was written")
            return

        def write_job(log):
            with self.make_swd() as s:
                s.write_options(new)
            return True
        self.run(write_job, lambda r: self.say("option bytes written; the chip reloads them (reset)"))

    def show_udev(self):
        dlg = QDialog(self.w)
        dlg.setWindowTitle("Probe setup")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Linux: save this as /etc/udev/rules.d/49-puya-probes.rules, then run  sudo udevadm control --reload  and plug the probe in again.\n"
                             "Windows: DAPLink / CMSIS-DAP v2 need no driver. ST-Link V2 clones need the WinUSB driver (install with Zadig)."))
        t = QPlainTextEdit(flasher.UDEV_RULES)
        t.setReadOnly(True)
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.resize(760, 520)
        dlg.exec()


class MonitorPanel(QWidget):
    """Plain serial terminal: shows what the program prints with usartN_puts()."""
    line_in = Signal(str)

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.thread = None
        self.port = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.ports = QComboBox()
        self.baud = QComboBox()
        self.baud.setEditable(True)
        for b in (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600):
            self.baud.addItem(str(b))
        self.baud.setCurrentText("115200")
        self.btn = QPushButton("Start")
        self.btn.clicked.connect(self.toggle)
        clr = QPushButton("Clear")
        clr.clicked.connect(lambda: self.text.clear())
        rf = QPushButton("Refresh ports")
        rf.clicked.connect(self.refresh)
        for wdg in (QLabel("Port"), self.ports, QLabel("Baud"), self.baud, self.btn, clr, rf):
            top.addWidget(wdg)
        lay.addLayout(top)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        lay.addWidget(self.text, 1)
        send = QHBoxLayout()
        self.send_edit = QLineEdit()
        self.send_edit.returnPressed.connect(self.send)
        sb = QPushButton("Send")
        sb.clicked.connect(self.send)
        send.addWidget(self.send_edit, 1)
        send.addWidget(sb)
        lay.addLayout(send)
        self.line_in.connect(self.append)
        self.refresh()

    def refresh(self):
        cur = self.ports.currentData()
        self.ports.clear()
        for p in flasher.list_serial_ports():
            self.ports.addItem(p["name"], p["device"])
        i = self.ports.findData(cur)
        if i >= 0:
            self.ports.setCurrentIndex(i)

    def use_project_baud(self):
        p = self.w.project
        if p:
            for u in p.chip.features["usart"]:
                s = p.periph.get(u)
                if s and s.get("enabled"):
                    self.baud.setCurrentText(str(s["baud"]))
                    return

    def toggle(self):
        if self.port:
            return self.stop()
        dev = self.ports.currentData()
        if not dev:
            self.append("[no serial port]\n")
            return
        import serial
        try:
            self.port = serial.Serial(dev, int(self.baud.currentText()), timeout=0.1)
        except Exception as e:
            self.append(f"[cannot open {dev}: {e}]\n")
            self.port = None
            return
        self.btn.setText("Stop")
        self.thread = MonitorThread(self.port, self.line_in.emit)
        self.thread.start()

    def stop(self):
        if self.thread:
            self.thread.stop()
            self.thread.wait(2000)
            self.thread = None
        if self.port:
            try:
                self.port.close()
            finally:
                self.port = None
        self.btn.setText("Start")

    def send(self):
        if self.port and self.send_edit.text():
            self.port.write((self.send_edit.text() + "\r\n").encode())
            self.send_edit.clear()

    def append(self, text):
        self.text.moveCursor(self.text.textCursor().End)
        self.text.insertPlainText(text)
        self.text.moveCursor(self.text.textCursor().End)


class MonitorThread(QThread):
    def __init__(self, port, emit):
        super().__init__()
        self.port, self.emit, self._stop = port, emit, False

    def stop(self):
        self._stop = True

    def run(self):
        while not self._stop:
            try:
                data = self.port.read(256)
            except Exception as e:
                self.emit(f"[{e}]\n")
                return
            if data:
                self.emit(data.decode("utf8", errors="replace"))
