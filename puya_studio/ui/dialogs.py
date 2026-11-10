"""New project dialog: chip, part number (or package/memory by hand), example with wiring."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout)

from .. import chips, examples
from ..project import Project
from .panels import combo


class NewProjectDialog(QDialog):
    def __init__(self, parent=None, default_folder=None):
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.resize(900, 640)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        lay.addLayout(left, 1)
        form = QFormLayout()
        self.chipc = combo([(chips.load(n).name, n) for n in chips.CHIP_NAMES])
        self.chipc.currentIndexChanged.connect(self.on_chip)
        form.addRow("Chip", self.chipc)
        self.partc = QComboBox()
        self.partc.currentIndexChanged.connect(self.update_examples)
        form.addRow("Part number", self.partc)
        self.manual = QCheckBox("choose package and memory by hand")
        self.manual.toggled.connect(self.on_manual)
        form.addRow("", self.manual)
        self.pkgc = QComboBox()
        self.pkgc.currentIndexChanged.connect(self.on_pkg)
        self.memc = QComboBox()
        self.memc.currentIndexChanged.connect(self.update_examples)
        form.addRow("Package / pinout", self.pkgc)
        form.addRow("Memory", self.memc)
        self.name = QLineEdit("my_project")
        form.addRow("Project name", self.name)
        row = QHBoxLayout()
        self.folder = QLineEdit(default_folder or os.path.join(os.path.expanduser("~"), "PuyaProjects"))
        b = QPushButton("Browse...")
        b.clicked.connect(self.browse)
        row.addWidget(self.folder, 1)
        row.addWidget(b)
        form.addRow("Folder", row)
        left.addLayout(form)
        left.addWidget(QLabel("Example:"))
        self.exlist = QListWidget()
        self.exlist.currentItemChanged.connect(self.on_example)
        left.addWidget(self.exlist, 1)
        right = QVBoxLayout()
        lay.addLayout(right, 1)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("font-weight: bold;")
        right.addWidget(self.desc)
        right.addWidget(QLabel("Wiring for the chosen package:"))
        self.wiring = QPlainTextEdit()
        self.wiring.setReadOnly(True)
        right.addWidget(self.wiring, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        self.ok_button = bb.button(QDialogButtonBox.Ok)
        self.on_chip()

    # ------------------------------------------------------------------
    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Folder for the project", self.folder.text())
        if d:
            self.folder.setText(d)

    def chip(self):
        return chips.load(self.chipc.currentData())

    def on_chip(self):
        c = self.chip()
        self.partc.blockSignals(True)
        self.partc.clear()
        for x in sorted(c.parts, key=lambda x: (x["package"], -x["flash_kb"])):
            self.partc.addItem(f"{x['part']}   {x['flash_kb']} KB / {x['ram_kb']} KB   {c.package_label(x['package'])}", x["part"])
        # default: the biggest part of the first package that has the most pins
        best = max(c.parts, key=lambda x: (c.packages[x["package"]]["pin_count"], x["flash_kb"]))
        self.partc.setCurrentIndex(self.partc.findData(best["part"]))
        self.partc.blockSignals(False)
        self.pkgc.blockSignals(True)
        self.pkgc.clear()
        for k in sorted(c.packages):
            self.pkgc.addItem(c.package_label(k), k)
        self.pkgc.setCurrentIndex(self.pkgc.findData(best["package"]))
        self.pkgc.blockSignals(False)
        self.on_manual(self.manual.isChecked())
        self.on_pkg()

    def on_manual(self, on):
        self.pkgc.setEnabled(on)
        self.memc.setEnabled(on)
        self.partc.setEnabled(not on)
        self.update_examples()

    def on_pkg(self, *a):
        c = self.chip()
        pk = self.pkgc.currentData()
        self.memc.blockSignals(True)
        self.memc.clear()
        for x in sorted(c.parts_for_package(pk), key=lambda x: -x["flash_kb"]):
            self.memc.addItem(f"{x['flash_kb']} KB flash / {x['ram_kb']} KB RAM", x["flash_kb"])
        self.memc.blockSignals(False)
        self.update_examples()

    def selection(self):
        """(chip id, part, package, flash_kb)"""
        c = self.chip()
        if self.manual.isChecked():
            return c.id, None, self.pkgc.currentData(), self.memc.currentData()
        part = c.part(self.partc.currentData())
        return c.id, part["part"], part["package"], part["flash_kb"]

    def make_project(self):
        cid, part, pk, flash = self.selection()
        p = Project(cid)
        if part:
            p.set_part(part)
        else:
            p.set_package(pk)
            if flash:
                p.set_memory(flash)
        return p

    def update_examples(self, *a):
        cid, part, pk, flash = self.selection()
        keep = self.exlist.currentItem().data(Qt.UserRole) if self.exlist.currentItem() else "empty"
        self.exlist.blockSignals(True)
        self.exlist.clear()
        it = QListWidgetItem("Empty project")
        it.setData(Qt.UserRole, "empty")
        self.exlist.addItem(it)
        for e in examples.EXAMPLES:
            ok, why = examples.supported(e, cid, part, pk)
            li = QListWidgetItem(e.title if ok else f"{e.title}   (not for this package)")
            li.setData(Qt.UserRole, e.id)
            if not ok:
                li.setFlags(li.flags() & ~Qt.ItemIsEnabled)
                li.setToolTip(why)
            self.exlist.addItem(li)
        for i in range(self.exlist.count()):
            if self.exlist.item(i).data(Qt.UserRole) == keep and self.exlist.item(i).flags() & Qt.ItemIsEnabled:
                self.exlist.setCurrentRow(i)
        if self.exlist.currentRow() < 0:
            self.exlist.setCurrentRow(0)
        self.exlist.blockSignals(False)
        self.on_example()

    def example_id(self):
        it = self.exlist.currentItem()
        return it.data(Qt.UserRole) if it else "empty"

    def on_example(self, *a):
        eid = self.example_id()
        if eid == "empty":
            self.desc.setText("Empty project: choose pins and settings yourself.")
            self.wiring.setPlainText("")
            return
        cid, part, pk, flash = self.selection()
        e = examples.BY_ID[eid]
        self.desc.setText(f"{e.title}: {e.description}")
        try:
            p, sec, wiring = examples.build(eid, cid, part, pk, None if part else flash)
            self.wiring.setPlainText("\n".join(wiring) if wiring else "No external parts.")
        except examples.Unsupported as ex:
            self.wiring.setPlainText(f"Not possible on this package: {ex}")
