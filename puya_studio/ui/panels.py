"""Side panel for the selected pin and the pages (clock, timers, UART, SPI, I2C, ADC, interrupts, power)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton,
                               QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import codegen, project as projmod, timing
from ..project import EXTI_EDGES, PULLS, SPEEDS, periph_defaults

FUNC_COLORS = {"unused": None, "gpio_in": "#7fb3ff", "gpio_out": "#4f8ff7", "exti": "#9b8cff", "analog": "#ffb45e", "af": "#5ccf8e"}


def combo(items, current=None, parent=None):
    c = QComboBox(parent)
    for it in items:
        if isinstance(it, tuple):
            c.addItem(str(it[0]), it[1])
        else:
            c.addItem(str(it), it)
    if current is not None:
        i = c.findData(current)
        c.setCurrentIndex(max(i, 0))
    return c


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


class PinPanel(QWidget):
    """Everything about the selected pin, always visible: no popup is needed to assign, rename or clear a pin."""
    changed = Signal()
    port_chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.port = None
        self._busy = False
        lay = QVBoxLayout(self)
        self.title = QLabel("Click a pin on the drawing")
        self.title.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.pad_box = QGroupBox("This pad serves two ports")
        self.pad_lay = QHBoxLayout(self.pad_box)
        lay.addWidget(self.pad_box)
        self.pad_buttons = []
        lay.addWidget(QLabel("Function:"))
        self.funcs = QListWidget()
        self.funcs.setSelectionMode(QAbstractItemView.SingleSelection)
        self.funcs.itemClicked.connect(self.on_func)
        lay.addWidget(self.funcs, 1)
        self.unused_btn = QPushButton("Unused  (Delete)")
        self.unused_btn.setToolTip("Clear this pin. Same as the Delete key or a right click on the pin.")
        self.unused_btn.clicked.connect(self.on_unused)
        lay.addWidget(self.unused_btn)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("name used in the C code, e.g. LED")
        self.name.textEdited.connect(self.on_edit)
        form.addRow("Name", self.name)
        self.pull = combo(PULLS)
        self.speed = combo(SPEEDS)
        self.otype = combo([("push-pull", "pp"), ("open-drain", "od")])
        self.init = combo([("low", "low"), ("high", "high")])
        self.edge = combo(EXTI_EDGES)
        self.rows = {}
        for key, w, lab in (("pull", self.pull, "Pull"), ("speed", self.speed, "Speed"), ("otype", self.otype, "Output type"),
                            ("init", self.init, "Start level"), ("edge", self.edge, "Edge")):
            form.addRow(lab, w)
            w.currentIndexChanged.connect(self.on_edit)
            self.rows[key] = (form, w, lab)
        lay.addLayout(form)
        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet("color: gray;")
        lay.addWidget(self.notes)
        self.show_port(None, None)

    # ------------------------------------------------------------------
    def show_port(self, project, port):
        self.project, self.port = project, port
        self._busy = True
        self.funcs.clear()
        for b in self.pad_buttons:
            b.deleteLater()
        self.pad_buttons = []
        self.pad_box.setVisible(False)
        enabled = bool(project and port and port in project.chip.ports)
        for w in (self.funcs, self.unused_btn, self.name):
            w.setEnabled(enabled)
        if not enabled:
            self.title.setText("Click a pin on the drawing" if not (port or "").startswith("pin:") else "")
            self.info.setText("")
            if port and port.startswith("pin:") and project:
                pin = [p for p in project.chip.pins(project.package) if p.n == int(port[4:])][0]
                self.title.setText(f"Pin {pin.n}: {pin.name}")
                self.info.setText("Power pin." if pin.kind == "power" else "Not connected.")
            self._set_rows(None)
            self.notes.setText("")
            self._busy = False
            return
        c = project.chip
        pin = [p for p in c.pins(project.package) if port in p.ports][0]
        d = project.pins.get(port)
        self.title.setText(f"Pin {pin.n}: {port}")
        extra = []
        if pin.notes:
            extra.append("Also: " + ", ".join(pin.notes))
        analog = c.analog_of(port)
        if analog:
            extra.append("Analog: " + ", ".join(analog))
        self.info.setText("  ".join(extra))
        if pin.shared:
            self.pad_box.setVisible(True)
            for q in pin.ports:
                rb = QRadioButton(q)
                rb.setChecked(q == port)
                rb.toggled.connect(lambda on, q=q: on and self.port_chosen.emit(q))
                self.pad_lay.addWidget(rb)
                self.pad_buttons.append(rb)
        in_use = {}
        for q, dd in project.pins.items():
            if dd["func"] == "af":
                in_use[dd["signal"]] = q
        current = None
        for f in project.functions_for(port):
            text = f["label"]
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, f["id"])
            if f["id"].startswith("af:") and in_use.get(f["signal"]) not in (None, port):
                it.setText(f"{text}   (also on {in_use[f['signal']]})")
                it.setForeground(QColor("#c07000"))
            self.funcs.addItem(it)
            cur_id = "unused" if not d else (f"af:{d['signal']}" if d["func"] == "af" else d["func"])
            if f["id"] == cur_id:
                current = it
        if current:
            self.funcs.setCurrentItem(current)
            self.funcs.scrollToItem(current)
        self.name.setText(d["label"] if d else "")
        self._set_rows(d)
        self.notes.setText(self.hint(project, port, d))
        self._busy = False

    def hint(self, project, port, d):
        c = project.chip
        notes = []
        if port in c.d["swd"].values():
            notes.append("Debug pin: if you use it for something else you may lose the programming connection.")
        if port == c.d["nrst"]:
            notes.append("Reset pin: using it as GPIO needs the NRST_MODE option byte.")
        if c.d.get("boot0") == port:
            notes.append("BOOT0 pin: its level at reset selects the start-up source.")
        return " ".join(notes)

    def _set_rows(self, d):
        func = d["func"] if d else "unused"
        vis = {"pull": func in ("gpio_in", "gpio_out", "exti", "af"), "speed": func in ("gpio_out", "af"),
               "otype": func in ("gpio_out", "af"), "init": func == "gpio_out", "edge": func == "exti"}
        for key, (form, w, lab) in self.rows.items():
            form.labelForField(w).setVisible(vis[key])
            w.setVisible(vis[key])
            if d:
                i = w.findData(d[key]) if w.findData(d[key]) >= 0 else w.findText(d[key])
                w.setCurrentIndex(max(i, 0))

    # ------------------------------------------------------------------
    def on_func(self, item):
        if self._busy or not self.project or not self.port:
            return
        fid = item.data(Qt.UserRole)
        opts = {}
        if self.port in self.project.pins:
            opts = {k: self.project.pins[self.port][k] for k in ("label", "pull", "speed", "otype", "init", "edge")}
        try:
            self.project.assign(self.port, fid, **opts)
        except ValueError:
            return
        self.show_port(self.project, self.port)
        self.changed.emit()

    def on_unused(self):
        if self.project and self.port:
            self.project.clear(self.port)
            self.show_port(self.project, self.port)
            self.changed.emit()

    def on_edit(self, *a):
        if self._busy or not self.project or not self.port or self.port not in self.project.pins:
            return
        d = self.project.pins[self.port]
        d["label"] = self.name.text().strip()
        d["pull"], d["speed"], d["otype"], d["init"], d["edge"] = (self.pull.currentData() or self.pull.currentText(), self.speed.currentData() or self.speed.currentText(),
                                                                  self.otype.currentData(), self.init.currentData(), self.edge.currentData() or self.edge.currentText())
        self.changed.emit()


class Page(QScrollArea):
    """Base class: scrollable page that is rebuilt from the project when `refresh()` is called."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.setWidgetResizable(True)
        self.inner = QWidget()
        self.setWidget(self.inner)
        self.lay = QVBoxLayout(self.inner)
        self._busy = False

    def set_project(self, project):
        self.project = project
        self.refresh()

    def clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    def _clear_layout(self, l):
        while l.count():
            it = l.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def emit(self, *a):
        if not self._busy:
            self.changed.emit()

    def refresh(self):
        self._busy = True
        self.clear()
        if self.project:
            self.build()
        self.lay.addStretch(1)
        self._busy = False

    def build(self):
        pass


def spin(lo, hi, val, step=1, parent=None, suffix=""):
    s = QSpinBox(parent)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(int(val))
    if suffix:
        s.setSuffix(suffix)
    return s


def dspin(lo, hi, val, dec=3, suffix=""):
    s = QDoubleSpinBox()
    s.setDecimals(dec)
    s.setRange(lo, hi)
    s.setValue(float(val))
    if suffix:
        s.setSuffix(suffix)
    return s


class ProjectPage(Page):
    """Chip, orderable part number and the manual package / memory choice."""

    def build(self):
        p = self.project
        c = p.chip
        form = QFormLayout()
        form.addRow("Chip", QLabel(f"<b>{c.name}</b>  ({c.d['core']}, up to {c.max_hz // 1_000_000} MHz, {c.d['vdd_min']}-{c.d['vdd_max']} V)"))
        self.partc = combo([(f"{x['part']}   {x['flash_kb']} KB flash / {x['ram_kb']} KB RAM   {c.package_label(x['package'])}", x["part"])
                            for x in sorted(c.parts, key=lambda x: (x["package"], -x["flash_kb"]))], p.part)
        self.partc.currentIndexChanged.connect(self.on_part)
        form.addRow("Part number", self.partc)
        lay2 = QLabel("Or choose the pieces yourself:")
        form.addRow(lay2)
        self.pkgc = combo([(c.package_label(k), k) for k in sorted(c.packages)], p.package)
        self.pkgc.currentIndexChanged.connect(self.on_pkg)
        form.addRow("Package / pinout", self.pkgc)
        flashes = sorted({x["flash_kb"] for x in c.parts_for_package(p.package)})
        self.memc = combo([(f"{k} KB flash / {dict((x['flash_kb'], x['ram_kb']) for x in c.parts)[k]} KB RAM", k) for k in flashes], p.flash_kb)
        self.memc.currentIndexChanged.connect(self.on_mem)
        form.addRow("Memory", self.memc)
        self.vdd = dspin(1.7, 5.5, p.vdd, 2, " V")
        self.vdd.valueChanged.connect(self.on_vdd)
        form.addRow("Supply voltage", self.vdd)
        self.lay.addLayout(form)
        for n in c.notes:
            lab = QLabel("Note: " + n)
            lab.setWordWrap(True)
            lab.setStyleSheet("color: gray;")
            self.lay.addWidget(lab)
        src = QLabel("Data sources: " + "; ".join(s["doc"] for s in c.d["sources"]))
        src.setWordWrap(True)
        src.setStyleSheet("color: gray;")
        self.lay.addWidget(src)

    def on_part(self):
        if self._busy:
            return
        self.project.set_part(self.partc.currentData())
        self.changed.emit()
        self.refresh()

    def on_pkg(self):
        if self._busy:
            return
        self.project.set_package(self.pkgc.currentData())
        self.changed.emit()
        self.refresh()

    def on_mem(self):
        if self._busy:
            return
        try:
            self.project.set_memory(self.memc.currentData())
        except ValueError:
            return
        self.changed.emit()
        self.refresh()

    def on_vdd(self, v):
        if not self._busy:
            self.project.vdd = v
            self.changed.emit()


class ClockPage(Page):
    def build(self):
        p, c = self.project, self.project.chip
        cl = p.clock
        form = QFormLayout()
        srcs = ["HSI", "HSE"] + (["PLL"] if c.clock["pll"] else []) + ["LSI", "LSE"]
        self.src = combo(srcs, cl["source"])
        self.src.currentIndexChanged.connect(self.on_change)
        form.addRow("System clock source", self.src)
        freqs = sorted(int(v) for v in c.clock["hsi"]["freqs_hz"].values())
        self.hsi = combo([(f"{f / 1e6:g} MHz", f) for f in freqs], cl["hsi_hz"])
        self.hsi.currentIndexChanged.connect(self.on_change)
        form.addRow("HSI oscillator", self.hsi)
        self.hsidiv = combo([(f"/ {d}", d) for d in timing.HSIDIV_CODES], cl["hsidiv"])
        self.hsidiv.currentIndexChanged.connect(self.on_change)
        form.addRow("HSI divider", self.hsidiv)
        hse = c.clock["hse"]
        lbl = "HSE crystal / clock" if hse.get("crystal_hz") else "HSE external clock"
        self.hse = dspin(0.032, 48, cl["hse_hz"] / 1e6, 3, " MHz")
        self.hse.valueChanged.connect(self.on_change)
        form.addRow(lbl, self.hse)
        self.bypass = QCheckBox("external clock signal instead of a crystal (bypass)")
        self.bypass.setChecked(bool(cl.get("hse_bypass")) or not hse.get("crystal_hz"))
        self.bypass.setEnabled(bool(hse.get("crystal_hz")))
        self.bypass.toggled.connect(self.on_change)
        form.addRow("", self.bypass)
        if c.clock["pll"]:
            self.pllsrc = combo(["HSI", "HSE"], cl.get("pll_src", "HSI"))
            self.pllsrc.currentIndexChanged.connect(self.on_change)
            form.addRow("PLL source (x2)", self.pllsrc)
        else:
            self.pllsrc = None
        self.ahb = combo([(f"/ {d}", d) for d in timing.AHB_CODES], cl["ahb_div"])
        self.ahb.currentIndexChanged.connect(self.on_change)
        form.addRow("AHB divider (HCLK)", self.ahb)
        self.apb = combo([(f"/ {d}", d) for d in timing.APB_CODES], cl["apb_div"])
        self.apb.currentIndexChanged.connect(self.on_change)
        form.addRow("APB divider (PCLK)", self.apb)
        self.tick = combo([("off", 0), ("100 Hz", 100), ("1 kHz", 1000), ("10 kHz", 10000)], cl.get("systick_hz", 1000))
        self.tick.currentIndexChanged.connect(self.on_change)
        form.addRow("SysTick (millis, delay_ms)", self.tick)
        mco = cl.get("mco")
        self.mco_on = QCheckBox("clock output on a pin with the MCO function")
        self.mco_on.setChecked(bool(mco))
        self.mco_on.toggled.connect(self.on_change)
        form.addRow("MCO", self.mco_on)
        self.mco_src = combo([(v, v) for k, v in sorted(c.clock["mco"]["sel"].items())], (mco or {}).get("src", "SYSCLK"))
        self.mco_src.currentIndexChanged.connect(self.on_change)
        form.addRow("MCO source", self.mco_src)
        self.mco_div = combo([(f"/ {d}", d) for d in c.clock["mco"]["div"]], (mco or {}).get("div", 1))
        self.mco_div.currentIndexChanged.connect(self.on_change)
        form.addRow("MCO divider", self.mco_div)
        self.lay.addLayout(form)
        self.readout = QLabel()
        self.readout.setTextFormat(Qt.RichText)
        self.readout.setStyleSheet("font-family: monospace; padding: 8px;")
        self.lay.addWidget(self.readout)
        self.update_readout()

    def on_change(self, *a):
        if self._busy:
            return
        cl = self.project.clock
        cl["source"] = self.src.currentData() or self.src.currentText()
        cl["hsi_hz"] = self.hsi.currentData()
        cl["hsidiv"] = self.hsidiv.currentData()
        cl["hse_hz"] = int(round(self.hse.value() * 1e6))
        cl["hse_bypass"] = self.bypass.isChecked()
        if self.pllsrc is not None:
            cl["pll_src"] = self.pllsrc.currentData() or self.pllsrc.currentText()
        cl["ahb_div"] = self.ahb.currentData()
        cl["apb_div"] = self.apb.currentData()
        cl["systick_hz"] = self.tick.currentData()
        cl["mco"] = {"src": self.mco_src.currentData(), "div": self.mco_div.currentData()} if self.mco_on.isChecked() else None
        self.update_readout()
        self.changed.emit()

    def update_readout(self):
        r = timing.clock_tree(self.project.chip, self.project.clock)

        def mhz(v):
            return f"{v / 1e6:.3f} MHz"
        txt = (f"SYSCLK  {mhz(r.sysclk)}<br>HCLK    {mhz(r.hclk)}<br>PCLK    {mhz(r.pclk)}<br>"
               f"TIM clk {mhz(r.tim_clk)}<br>flash wait states: {r.flash_latency}")
        for sev, t in r.problems:
            txt += f"<br><span style='color:{'#d83a3a' if sev == 'error' else '#c08000'}'>{sev}: {t}</span>"
        self.readout.setText(txt)


class UsartPage(Page):
    def build(self):
        p, c = self.project, self.project.chip
        clk = timing.clock_tree(c, p.clock)
        sigs = p.signals_in_use()
        for u in c.features["usart"]:
            s = p.periph.get(u)
            box = QGroupBox(u)
            form = QFormLayout(box)
            en = QCheckBox("enabled")
            en.setChecked(bool(s and s.get("enabled")))
            form.addRow(en)
            pins = [f"{k.split('_')[1]} on {', '.join(v)}" for k, v in sigs.items() if k.startswith(u + "_")]
            form.addRow("Pins", QLabel(", ".join(pins) if pins else "none: set them on the Pinout page (e.g. " + f"{u}_TX)"))
            if s and s.get("enabled"):
                baud = QComboBox()
                baud.setEditable(True)
                for b in (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1000000):
                    baud.addItem(str(b))
                baud.setCurrentText(str(s["baud"]))
                bits = combo([("7", 7), ("8", 8), ("9", 9)], s["bits"])
                par = combo(["none", "even", "odd"], s["parity"])
                stop = combo([("1", 1), ("2", 2)], s["stop"])
                irq = QCheckBox("receive interrupt (ring buffer)")
                irq.setChecked(bool(s.get("irq_rx")))
                form.addRow("Baud rate", baud)
                form.addRow("Data bits", bits)
                form.addRow("Parity", par)
                form.addRow("Stop bits", stop)
                form.addRow("", irq)
                brr, actual, err = timing.usart_brr(clk.pclk or 1, s["baud"])
                form.addRow("Real baud rate", QLabel("impossible" if brr is None else f"{actual:.0f}  (error {err:.2f} %)"))

                def apply(u=u, baud=baud, bits=bits, par=par, stop=stop, irq=irq):
                    if self._busy:
                        return
                    st = self.project.periph[u]
                    try:
                        st["baud"] = max(1, int(baud.currentText()))
                    except ValueError:
                        return
                    st["bits"], st["parity"], st["stop"], st["irq_rx"] = bits.currentData(), par.currentText(), stop.currentData(), irq.isChecked()
                    st["auto"] = False
                    self.changed.emit()
                baud.editTextChanged.connect(lambda *_: apply())
                for w in (bits, par, stop):
                    w.currentIndexChanged.connect(lambda *_: apply())
                irq.toggled.connect(lambda *_: apply())
            en.toggled.connect(lambda on, u=u: self.toggle(u, on))
            self.lay.addWidget(box)

    def toggle(self, inst, on):
        if self._busy:
            return
        if on:
            self.project.periph.setdefault(inst, periph_defaults(self.project.chip, inst))["enabled"] = True
            self.project.periph[inst]["auto"] = False
        elif inst in self.project.periph:
            self.project.periph[inst]["enabled"] = False
        self.changed.emit()
        self.refresh()


class SpiPage(Page):
    def build(self):
        p, c = self.project, self.project.chip
        clk = timing.clock_tree(c, p.clock)
        sigs = p.signals_in_use()
        for sp in c.features["spi"]:
            s = p.periph.get(sp)
            box = QGroupBox(sp)
            form = QFormLayout(box)
            en = QCheckBox("enabled")
            en.setChecked(bool(s and s.get("enabled")))
            form.addRow(en)
            pins = [f"{k.split('_')[1]} on {', '.join(v)}" for k, v in sigs.items() if k.startswith(sp + "_")]
            form.addRow("Pins", QLabel(", ".join(pins) if pins else "none: set them on the Pinout page"))
            if s and s.get("enabled"):
                mode = combo(["master", "slave"], s["mode"])
                speed = spin(1000, 24_000_000, s["speed_hz"], 100_000, suffix=" Hz")
                cpol = combo([("0 (idle low)", 0), ("1 (idle high)", 1)], s["cpol"])
                cpha = combo([("0 (first edge)", 0), ("1 (second edge)", 1)], s["cpha"])
                first = combo([("MSB first", "msb"), ("LSB first", "lsb")], s["first"])
                bits = combo([("8 bit", 8), ("16 bit", 16)], s["bits"])
                for lab, w in (("Mode", mode), ("Clock", speed), ("CPOL", cpol), ("CPHA", cpha), ("Bit order", first), ("Frame", bits)):
                    form.addRow(lab, w)
                br, actual = timing.spi_prescaler(clk.pclk or 1, s["speed_hz"])
                form.addRow("Real clock", QLabel(f"{actual / 1e6:.3f} MHz  (PCLK / {2 ** (br + 1)})"))

                def apply(sp=sp, mode=mode, speed=speed, cpol=cpol, cpha=cpha, first=first, bits=bits):
                    if self._busy:
                        return
                    st = self.project.periph[sp]
                    st.update(mode=mode.currentText(), speed_hz=speed.value(), cpol=cpol.currentData(), cpha=cpha.currentData(),
                              first=first.currentData(), bits=bits.currentData(), auto=False)
                    self.changed.emit()
                for w in (mode, cpol, cpha, first, bits):
                    w.currentIndexChanged.connect(lambda *_: apply())
                speed.editingFinished.connect(apply)
            en.toggled.connect(lambda on, sp=sp: self.toggle(sp, on))
            self.lay.addWidget(box)

    toggle = UsartPage.toggle


class I2cPage(Page):
    def build(self):
        p, c = self.project, self.project.chip
        clk = timing.clock_tree(c, p.clock)
        sigs = p.signals_in_use()
        for ic in c.features["i2c"]:
            s = p.periph.get(ic)
            box = QGroupBox(ic + "  (master mode)")
            form = QFormLayout(box)
            en = QCheckBox("enabled")
            en.setChecked(bool(s and s.get("enabled")))
            form.addRow(en)
            pins = [f"{k.split('_')[1]} on {', '.join(v)}" for k, v in sigs.items() if k.startswith(ic + "_")]
            form.addRow("Pins", QLabel(", ".join(pins) if pins else "none: set SCL and SDA on the Pinout page"))
            if s and s.get("enabled"):
                speed = combo([("100 kHz (standard)", 100_000), ("400 kHz (fast)", 400_000)], s["speed_hz"])
                form.addRow("Speed", speed)
                t = timing.i2c_timing(clk.pclk or 1, s["speed_hz"])
                form.addRow("Real clock", QLabel("PCLK too low" if t is None else f"{t['actual_hz'] / 1e3:.1f} kHz  (CCR {t['CCR']}, TRISE {t['TRISE']})"))
                form.addRow("", QLabel("Needs external pull-up resistors (4.7 kOhm)."))

                def apply(ic=ic, speed=speed):
                    if self._busy:
                        return
                    self.project.periph[ic]["speed_hz"] = speed.currentData()
                    self.project.periph[ic]["auto"] = False
                    self.changed.emit()
                speed.currentIndexChanged.connect(lambda *_: apply())
            en.toggled.connect(lambda on, ic=ic: self.toggle(ic, on))
            self.lay.addWidget(box)

    toggle = UsartPage.toggle


class AdcPage(Page):
    def build(self):
        p, c = self.project, self.project.chip
        s = p.periph.get("ADC")
        box = QGroupBox("ADC (12 bit)")
        form = QFormLayout(box)
        en = QCheckBox("enabled")
        en.setChecked(bool(s and s.get("enabled")))
        form.addRow(en)
        chans = p.adc_channels()
        form.addRow("Channels on pins", QLabel(", ".join(f"ADC_IN{n} on {q}" for n, q in chans) if chans else "none: set a pin to Analog on the Pinout page"))
        if s and s.get("enabled"):
            res = combo([("12 bit", 12), ("10 bit", 10), ("8 bit", 8), ("6 bit", 6)], s["resolution"])
            smp = spin(0, 7, s["sample"])
            temp = QCheckBox(f"temperature sensor (channel {c.adc['internal']['TS_VIN']})")
            temp.setChecked(bool(s["temp"]))
            vref = QCheckBox(f"internal reference VREFINT (channel {c.adc['internal']['VREFINT']})")
            vref.setChecked(bool(s["vref"]))
            form.addRow("Resolution", res)
            form.addRow("Sample time setting", smp)
            form.addRow("Internal channels", temp)
            form.addRow("", vref)
            code, hz = timing.adc_clock_div(timing.clock_tree(c, p.clock).pclk or 1)
            form.addRow("ADC clock", QLabel(f"PCLK / {2 ** code} = {hz / 1e6:g} MHz"))

            def apply():
                if self._busy:
                    return
                self.project.periph["ADC"].update(resolution=res.currentData(), sample=smp.value(), temp=temp.isChecked(), vref=vref.isChecked())
                self.changed.emit()
            res.currentIndexChanged.connect(lambda *_: apply())
            smp.valueChanged.connect(lambda *_: apply())
            temp.toggled.connect(lambda *_: apply())
            vref.toggled.connect(lambda *_: apply())

        def toggle(on):
            if self._busy:
                return
            self.project.periph.setdefault("ADC", periph_defaults(c, "ADC"))["enabled"] = on
            self.changed.emit()
            self.refresh()
        en.toggled.connect(toggle)
        self.lay.addWidget(box)
        self.lay.addWidget(QLabel("The C code gets  uint16_t adc_read(channel)  (one conversion, polling)."))


class TimerPage(Page):
    def build(self):
        p, c = self.project, self.project.chip
        clk = timing.clock_tree(c, p.clock)
        sigs = p.signals_in_use()
        for t, info in c.features["timers"].items():
            s = p.periph.get(t)
            box = QGroupBox(f"{t}  ({info['bits']} bit, {info['kind']}, {info['channels']} channel{'s' if info['channels'] > 1 else ''})")
            form = QFormLayout(box)
            en = QCheckBox("enabled")
            en.setChecked(bool(s and s.get("enabled")))
            form.addRow(en)
            if s and s.get("enabled"):
                freq = dspin(0.01, 10_000_000, s["freq_hz"], 3, " Hz")
                irq = QCheckBox("update interrupt")
                irq.setChecked(bool(s.get("irq")))
                form.addRow("Update / PWM frequency", freq)
                r = timing.timer_for_freq(clk.tim_clk or 1, s["freq_hz"], info["bits"])
                form.addRow("Real frequency", QLabel("impossible" if r is None else f"{r[2]:.4f} Hz  (prescaler {r[0] + 1}, reload {r[1] + 1}, error {r[3]:.3f} %)"))
                form.addRow("", irq)
                duty_widgets = {}
                for k, ports in sorted((k, v) for k, v in sigs.items() if k.startswith(t + "_CH")):
                    ch = k.split("_CH")[1].rstrip("N")
                    if k.endswith("N") or ch in duty_widgets:
                        continue
                    d = dspin(0, 100, s["duty"].get(ch, 50.0), 1, " %")
                    duty_widgets[ch] = d
                    form.addRow(f"Channel {ch} duty  ({k} on {', '.join(ports)})", d)
                if not duty_widgets:
                    form.addRow("", QLabel("No channel pin yet: this is a plain timer. Set TIMx_CHy on a pin for PWM output."))

                def apply(t=t, freq=freq, irq=irq, dw=duty_widgets):
                    if self._busy:
                        return
                    st = self.project.periph[t]
                    st["freq_hz"], st["irq"], st["auto"] = freq.value(), irq.isChecked(), False
                    st["duty"] = {ch: w.value() for ch, w in dw.items()}
                    self.changed.emit()
                freq.editingFinished.connect(apply)
                irq.toggled.connect(lambda *_: apply())
                for w in duty_widgets.values():
                    w.editingFinished.connect(apply)
            en.toggled.connect(lambda on, t=t: self.toggle(t, on))
            self.lay.addWidget(box)

    toggle = UsartPage.toggle


class InterruptPage(Page):
    def build(self):
        p, c = self.project, self.project.chip
        g = codegen.Gen(p)
        auto = g.irq_list()
        self.table = QTableWidget(len(c.interrupts), 5)
        self.table.setHorizontalHeaderLabels(["IRQ", "Name", "Enabled", "Priority (0 = highest)", "Reason"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._items = {}
        for row, (n, name) in enumerate(sorted(c.interrupts.items())):
            self.table.setItem(row, 0, QTableWidgetItem(str(n)))
            self.table.setItem(row, 1, QTableWidgetItem(name))
            cb = QCheckBox()
            forced = name in auto
            extra = name in p.irq["extra"]
            cb.setChecked(forced or extra)
            cb.setEnabled(not forced)
            sp = spin(0, 3, auto[name][0] if forced else p.irq["extra"].get(name, 2))
            self.table.setCellWidget(row, 2, cb)
            self.table.setCellWidget(row, 3, sp)
            self.table.setItem(row, 4, QTableWidgetItem(", ".join(auto[name][1]) if forced else ""))
            cb.toggled.connect(lambda on, name=name, sp=sp: self.set_extra(name, on, sp.value()))
            sp.valueChanged.connect(lambda v, name=name: self.set_prio(name, v))
        self.table.resizeColumnsToContents()
        self.lay.addWidget(QLabel("Interrupts are switched on by the pages (UART receive, timer update, pin interrupts). "
                                  "Others can be enabled here: the C code gets an empty handler with a USER CODE section."))
        self.lay.addWidget(self.table, 1)

    def set_extra(self, name, on, prio):
        if self._busy:
            return
        if on:
            self.project.irq["extra"][name] = prio
        else:
            self.project.irq["extra"].pop(name, None)
        self.changed.emit()

    def set_prio(self, name, v):
        if self._busy:
            return
        self.project.irq["prio"][name] = v
        if name in self.project.irq["extra"]:
            self.project.irq["extra"][name] = v
        for st in self.project.periph.values():
            pass
        self.changed.emit()


class PowerPage(Page):
    def build(self):
        p, c = self.project, self.project.chip
        box = QGroupBox("Low-power modes")
        v = QVBoxLayout(box)
        self.rb = {}
        for key, text in (("none", "Run: no low-power helper is used by the example code"),
                          ("sleep", "Sleep: enter_sleep() stops the CPU clock (WFI); any interrupt wakes it"),
                          ("stop", "Stop: enter_stop() stops all high-speed clocks; wake up with a pin interrupt (EXTI)")):
            rb = QRadioButton(text)
            rb.setChecked(p.power.get("idle") == key)
            rb.toggled.connect(lambda on, key=key: on and self.set_idle(key))
            v.addWidget(rb)
            self.rb[key] = rb
        v.addWidget(QLabel("enter_sleep() and enter_stop() are always generated; this setting is what the Problems list checks."))
        self.lay.addWidget(box)
        has_lpr = "LPR" in c.reg("PWR", "CR1")["fields"]
        if has_lpr:
            self.lpr = QCheckBox("low-power voltage regulator in stop mode (PWR_CR1.LPR)")
            self.lpr.setChecked(bool(p.power.get("stop_lpr")))
            self.lpr.toggled.connect(self.set_lpr)
            self.lay.addWidget(self.lpr)
        wake = [q for q, d in p.pins.items() if d["func"] == "exti"]
        self.lay.addWidget(QLabel("Wake-up pins (EXTI): " + (", ".join(wake) if wake else "none yet: set a pin to 'GPIO input with interrupt'")))
        iw = p.periph.get("IWDG") or {"enabled": False, "timeout_ms": 1000}
        wd = QGroupBox("Independent watchdog (runs from the 32 kHz LSI, also in sleep and stop)")
        form = QFormLayout(wd)
        en = QCheckBox("start the watchdog at the end of Init_All()")
        en.setChecked(bool(iw.get("enabled")))
        to = spin(1, 30000, iw.get("timeout_ms", 1000), 100, suffix=" ms")
        form.addRow(en)
        form.addRow("Timeout", to)
        r = timing.iwdg_for_timeout(c.clock["lsi_hz"], iw.get("timeout_ms", 1000))
        form.addRow("Real timeout", QLabel("too long" if r is None else f"{r[2]:.0f} ms"))
        self.lay.addWidget(wd)

        def apply(*_):
            if self._busy:
                return
            self.project.periph["IWDG"] = {"enabled": en.isChecked(), "timeout_ms": to.value()}
            self.changed.emit()
        en.toggled.connect(apply)
        to.editingFinished.connect(apply)

    def set_idle(self, key):
        if not self._busy:
            self.project.power["idle"] = key
            self.changed.emit()

    def set_lpr(self, on):
        if not self._busy:
            self.project.power["stop_lpr"] = on
            self.changed.emit()
