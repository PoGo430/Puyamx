"""The chip drawing: a package with clickable pins.

Left click selects a pin, Delete clears the selected pin, right click clears the pin under the mouse
(no menu, no dialog).  Colours show what a pin does; a red frame marks a pin with a problem.
"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

COLORS = {
    "unused": "#d9dde3", "gpio_in": "#7fb3ff", "gpio_out": "#4f8ff7", "exti": "#9b8cff", "analog": "#ffb45e",
    "af": "#5ccf8e", "power": "#e3777a", "ground": "#8a8f98", "nc": "#f1f1f1", "reset": "#f7e07a", "boot": "#f7e07a",
}


def layout_kind(ptype, n):
    return "dual" if ptype.startswith(("TSSOP", "SOP", "SSOP", "MSOP", "DIP")) else "quad"


class ChipView(QWidget):
    selected = Signal(str)          # port name ("PA5") or "" ; for a non-GPIO pin "pin:<n>"
    clear_requested = Signal(str)   # Delete / right click on a pin with a function

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.problem_ports = {}     # port -> "error" | "warning"
        self.sel = None             # selected pin number
        self.hover = None
        self.rects = {}             # pin number -> QRectF
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(520, 500)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------------------------------------------------------------ data
    def set_project(self, project):
        self.project = project
        self.sel = None
        self.update()

    def set_problems(self, mapping):
        self.problem_ports = mapping
        self.update()

    def pins(self):
        return self.project.chip.pins(self.project.package) if self.project else []

    def pin_by_port(self, port):
        for pin in self.pins():
            if port in pin.ports:
                return pin
        return None

    def select_port(self, port):
        pin = self.pin_by_port(port)
        self.sel = pin.n if pin else None
        self.update()

    def port_of(self, pin):
        """The port of a pin: the used one of a dual-bonded pad, else the first."""
        if not pin.ports:
            return ""
        for q in pin.ports:
            if q in self.project.pins:
                return q
        return pin.ports[0]

    # ------------------------------------------------------------------ geometry
    def compute(self):
        pins = self.pins()
        n = len([p for p in pins if not p.exposed_pad])
        pk = self.project.chip.packages[self.project.package]
        kind = layout_kind(pk["type"], n)
        w, h = self.width(), self.height()
        rects = {}
        if kind == "dual":
            half = n // 2
            pitch = min(34.0, (h - 120) / max(half, 1))
            body_h = pitch * half + 24
            body_w = min(260.0, w - 300)
            x0, y0 = (w - body_w) / 2, (h - body_h) / 2
            self.body = QRectF(x0, y0, body_w, body_h)
            pw, ph = 70.0, pitch - 6
            for i in range(half):
                y = y0 + 12 + i * pitch + 3
                rects[i + 1] = QRectF(x0 - pw, y, pw, ph)
                rects[n - i] = QRectF(x0 + body_w, y, pw, ph)
        else:
            per = n // 4
            pitch = min(38.0, (min(w - 2 * 270, h - 2 * 210) - 20) / max(per, 1))
            side = pitch * per + 20
            cx, cy = w / 2, h / 2
            x0, y0 = cx - side / 2, cy - side / 2
            self.body = QRectF(x0, y0, side, side)
            pl, pt = 74.0, pitch - 6
            for i in range(per):                          # left, top -> bottom
                rects[1 + i] = QRectF(x0 - pl, y0 + 10 + i * pitch + 3, pl, pt)
            for i in range(per):                          # bottom, left -> right
                rects[1 + per + i] = QRectF(x0 + 10 + i * pitch + 3, y0 + side, pt, pl)
            for i in range(per):                          # right, bottom -> top
                rects[1 + 2 * per + i] = QRectF(x0 + side, y0 + side - 10 - (i + 1) * pitch + 3, pl, pt)
            for i in range(per):                          # top, right -> left
                rects[1 + 3 * per + i] = QRectF(x0 + side - 10 - (i + 1) * pitch + 3, y0 - pl, pt, pl)
        self.kind = kind
        self.rects = rects

    # ------------------------------------------------------------------ painting
    def color_of(self, pin):
        p = self.project
        if pin.exposed_pad:
            return COLORS["ground"]
        if pin.kind == "power":
            return COLORS["ground"] if pin.name == "VSS" else COLORS["power"]
        if pin.kind == "nc":
            return COLORS["nc"]
        port = self.port_of(pin)
        d = p.pins.get(port)
        if d:
            return COLORS.get(d["func"], COLORS["unused"])
        if port == p.chip.d.get("nrst"):
            return COLORS["reset"]
        return COLORS["unused"]

    def paintEvent(self, ev):
        if not self.project:
            return
        self.compute()
        g = QPainter(self)
        g.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        g.fillRect(self.rect(), pal.window())
        pk = self.project.chip.packages[self.project.package]
        # body
        g.setPen(QPen(pal.mid().color(), 2))
        g.setBrush(QBrush(pal.base().color().darker(105) if pal.base().color().lightness() > 128 else pal.base().color().lighter(130)))
        g.drawRoundedRect(self.body, 10, 10)
        f = QFont(self.font())
        f.setPointSizeF(11)
        f.setBold(True)
        g.setFont(f)
        g.setPen(pal.text().color())
        title = f"{self.project.part or self.project.chip.name}"
        g.drawText(self.body.adjusted(8, 8, -8, -8), Qt.AlignCenter | Qt.TextWordWrap, f"{title}\n{pk['type']} ({pk['code']})")
        # pin 1 dot
        r1 = self.rects.get(1)
        if r1 is not None:
            g.setBrush(pal.text())
            g.drawEllipse(QPointF(self.body.left() + 14, self.body.top() + 14) if self.kind == "dual" else QPointF(self.body.left() + 14, self.body.top() + 14), 4, 4)
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        g.setFont(small)
        for pin in self.pins():
            if pin.exposed_pad:
                ep = QRectF(self.body.center().x() - 34, self.body.center().y() + 30, 68, 34)
                g.setBrush(QColor(COLORS["ground"]))
                g.setPen(Qt.NoPen)
                g.drawRoundedRect(ep, 4, 4)
                g.setPen(Qt.white)
                g.drawText(ep, Qt.AlignCenter, "EP / VSS")
                continue
            rc = self.rects.get(pin.n)
            if rc is None:
                continue
            col = QColor(self.color_of(pin))
            port = self.port_of(pin)
            sev = max(({"error": 2, "warning": 1}.get(self.problem_ports.get(q), 0) for q in pin.ports), default=0)
            border = QColor("#d83a3a") if sev == 2 else QColor("#e0a020") if sev == 1 else QColor("#00000044")
            if pin.n == self.sel:
                border = QColor("#1b60ff")
            g.setPen(QPen(border, 3 if (sev or pin.n == self.sel) else 1))
            g.setBrush(col.lighter(115) if pin.n == self.hover else col)
            g.drawRoundedRect(rc, 3, 3)
            g.setPen(QColor("#10131a") if col.lightness() > 120 else Qt.white)
            d = self.project.pins.get(port) if pin.kind == "io" else None
            label = pin.label if pin.kind == "io" else pin.name
            if pin.kind == "nc":
                label = "NC"
            text = f"{pin.n}  {label}"
            if d:
                nm = d["label"] or (d["signal"] if d["func"] == "af" else "")
                short = nm if len(nm) < 14 else nm[:13] + "…"
                text = f"{pin.n}  {label}" + (f"  {short}" if short else "")
            vertical = self.kind == "quad" and rc.height() > rc.width()
            if vertical:
                g.save()
                g.translate(rc.center())
                g.rotate(-90 if rc.top() > self.body.center().y() else 90)
                g.drawText(QRectF(-rc.height() / 2, -rc.width() / 2, rc.height(), rc.width()), Qt.AlignCenter, f"{pin.n}")
                g.restore()
                self._outside_label(g, pin, rc, label, d)
            else:
                left = rc.right() <= self.body.left() + 1
                g.drawText(rc.adjusted(4, 0, -4, 0), (Qt.AlignLeft if left else Qt.AlignRight) | Qt.AlignVCenter, f"{pin.n}")
                self._outside_label(g, pin, rc, label, d)
        g.end()

    def _outside_label(self, g, pin, rc, label, d):
        pal = self.palette()
        g.setPen(pal.text().color())
        txt = label
        if d:
            extra = d["label"] or (d["signal"] if d["func"] == "af" else "")
            if extra:
                txt = f"{label}  → {extra}"
        if self.kind == "dual":
            left = rc.right() <= self.body.left() + 1
            box = QRectF(rc.left() - 190, rc.top(), 186, rc.height()) if left else QRectF(rc.right() + 4, rc.top(), 186, rc.height())
            g.drawText(box, (Qt.AlignRight if left else Qt.AlignLeft) | Qt.AlignVCenter, txt)
        else:
            c = self.body.center()
            if rc.right() <= self.body.left() + 1:
                box = QRectF(rc.left() - 180, rc.top(), 176, rc.height()); al = Qt.AlignRight | Qt.AlignVCenter
                g.drawText(box, al, txt)
            elif rc.left() >= self.body.right() - 1:
                box = QRectF(rc.right() + 4, rc.top(), 176, rc.height()); al = Qt.AlignLeft | Qt.AlignVCenter
                g.drawText(box, al, txt)
            elif rc.top() >= self.body.bottom() - 1:
                g.save(); g.translate(rc.center().x(), rc.bottom() + 6); g.rotate(90)
                g.drawText(QRectF(0, -rc.width() / 2, 140, rc.width()), Qt.AlignLeft | Qt.AlignVCenter, txt); g.restore()
            else:
                g.save(); g.translate(rc.center().x(), rc.top() - 6); g.rotate(-90)
                g.drawText(QRectF(0, -rc.width() / 2, 140, rc.width()), Qt.AlignLeft | Qt.AlignVCenter, txt); g.restore()

    # ------------------------------------------------------------------ mouse / keyboard
    def pin_at(self, pos):
        if not self.project:
            return None
        self.compute()
        for n, rc in self.rects.items():
            if rc.adjusted(-2, -2, 2, 2).contains(pos):
                for pin in self.pins():
                    if pin.n == n:
                        return pin
        return None

    def mousePressEvent(self, ev):
        pin = self.pin_at(ev.position())
        self.setFocus()
        if pin is None:
            return
        if ev.button() == Qt.LeftButton:
            self.sel = pin.n
            self.update()
            self.selected.emit(self.port_of(pin) if pin.kind == "io" else f"pin:{pin.n}")
        elif ev.button() == Qt.RightButton and pin.kind == "io":
            port = self.port_of(pin)
            self.sel = pin.n
            self.update()
            self.selected.emit(port)
            if port in self.project.pins:
                self.clear_requested.emit(port)

    def mouseMoveEvent(self, ev):
        pin = self.pin_at(ev.position())
        n = pin.n if pin else None
        if n != self.hover:
            self.hover = n
            self.update()
        if pin:
            QToolTip.showText(ev.globalPosition().toPoint(), self.tooltip_for(pin), self)
        else:
            QToolTip.hideText()

    def tooltip_for(self, pin):
        if pin.kind != "io":
            return f"pin {pin.n}: {pin.name}" if pin.kind == "power" else f"pin {pin.n}: not connected"
        lines = [f"pin {pin.n}: {pin.label}" + ("  (one pad, two ports)" if pin.shared else "")]
        if pin.notes:
            lines.append("also: " + ", ".join(pin.notes))
        for q in pin.ports:
            d = self.project.pins.get(q)
            if d:
                lines.append(f"{q}: {d['signal'] if d['func'] == 'af' else d['func']}" + (f" '{d['label']}'" if d["label"] else ""))
        lines.append("click: select   Delete / right click: set unused")
        return "\n".join(lines)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel is not None:
            for pin in self.pins():
                if pin.n == self.sel and pin.kind == "io":
                    port = self.port_of(pin)
                    if port in self.project.pins:
                        self.clear_requested.emit(port)
                    return
        super().keyPressEvent(ev)

    def leaveEvent(self, ev):
        self.hover = None
        self.update()
