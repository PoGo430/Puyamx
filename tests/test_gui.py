"""Drive the whole window offscreen: every page, every pin function on every chip. Any exception fails the test."""
import os
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidgetItem

from puya_studio import chips, examples
from puya_studio.project import Project
from puya_studio.ui.dialogs import NewProjectDialog
from puya_studio.ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_swallowed_exceptions(monkeypatch):
    """PySide prints exceptions raised in slots and carries on; turn them into test failures."""
    errors = []
    old = sys.excepthook
    sys.excepthook = lambda t, v, tb: errors.append((t, v, tb))
    yield
    sys.excepthook = old
    if errors:
        import traceback
        pytest.fail("".join(traceback.format_exception(*errors[0])))


def pump():
    app.processEvents()


def make_window(chip="py32f030", package=None):
    w = MainWindow()
    p = Project(chip, package=package)
    w.set_project(p, None)
    w.show()
    pump()
    return w


def click_func(w, port, fid):
    """Click a function in the side panel, like a user."""
    w.panel.show_port(w.project, port)
    for i in range(w.panel.funcs.count()):
        it = w.panel.funcs.item(i)
        if it.data(Qt.UserRole) == fid:
            w.panel.funcs.setCurrentItem(it)
            w.panel.on_func(it)
            return
    raise AssertionError(f"{fid} not offered for {port}")


@pytest.mark.parametrize("chip", chips.CHIP_NAMES)
def test_every_page_and_every_pin_function(chip):
    w = make_window(chip)
    # every page
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i)
        pump()
        w.tabs.widget(i).grab()
    w.tabs.setCurrentWidget(w.pinout)
    # every function of every pin of every package, set through the panel, then cleared with Delete
    for pk in sorted(w.project.chip.packages):
        w.project.set_package(pk)
        w.chipview.set_project(w.project)
        w.panel.show_port(w.project, None)
        for port in sorted(w.project.package_ports()):
            w.chipview.select_port(port)
            w.on_pin_selected(port)
            for f in w.project.functions_for(port):
                click_func(w, port, f["id"])
                pump()
                if f["id"] != "unused":
                    assert port in w.project.pins
            w.chipview.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
            pump()
            assert port not in w.project.pins
        w.run_checks()
        w.grab()
    for i in range(w.tabs.count()):         # all pages again, now with everything in the project
        w.tabs.setCurrentIndex(i)
        pump()


@pytest.mark.parametrize("chip", chips.CHIP_NAMES)
def test_pin_clicks_and_reset_ways(chip):
    w = make_window(chip)
    w.chipview.resize(900, 700)
    pump()
    w.chipview.compute()
    pins = [p for p in w.chipview.pins() if p.kind == "io"]
    pin = pins[3]
    port = w.chipview.port_of(pin)
    def where():                                   # the layout can change size after a click: ask again
        w.chipview.compute()
        return w.chipview.rects[pin.n].center().toPoint()
    QTest.mouseClick(w.chipview, Qt.LeftButton, Qt.NoModifier, where())
    assert w.chipview.sel == pin.n and w.panel.port == port
    click_func(w, port, "gpio_out")
    assert w.project.pins[port]["func"] == "gpio_out"
    # 1) Unused button
    w.panel.unused_btn.click()
    assert port not in w.project.pins
    # 2) Delete key on the selected pin
    click_func(w, port, "gpio_in")
    w.chipview.setFocus()
    QTest.keyClick(w.chipview, Qt.Key_Delete)
    assert port not in w.project.pins
    # 3) right click resets at once, without a menu
    click_func(w, port, "gpio_out")
    QTest.mouseClick(w.chipview, Qt.RightButton, Qt.NoModifier, where())
    assert port not in w.project.pins


def test_problem_double_click_jumps_to_the_cause():
    w = make_window("py32f030")
    w.project.assign("PA2", "af:USART1_TX")
    w.project.assign("PA7", "af:USART1_TX")
    w.on_changed()
    w.run_checks()
    items = [w.problems.item(i) for i in range(w.problems.count())]
    dup = [it for it in items if "one pin" in it.text()]
    assert dup
    w.tabs.setCurrentWidget(w.pages["Clock"])
    w.problems.itemDoubleClicked.emit(dup[0])
    assert w.tabs.currentWidget() is w.pinout
    assert w.panel.port in ("PA2", "PA7")
    w.project.clock.update(source="PLL", hsi_hz=24_000_000, ahb_div=1)
    w.project.periph.clear()
    w.project.pins.clear()
    w.project.chip.clock  # noqa
    w.run_checks()
    ok = [w.problems.item(i) for i in range(w.problems.count())]
    assert not [i for i in ok if i.text().startswith("ERROR")]


def test_dual_bonded_pad_choice():
    w = make_window("py32f030", package="TSSOP20-F4")
    w.chipview.select_port("PA5")
    w.on_pin_selected("PA5")
    assert w.panel.pad_box.isVisibleTo(w.panel) and len(w.panel.pad_buttons) == 2
    w.panel.pad_buttons[1].setChecked(True)
    pump()
    assert w.panel.port == "PB4"


def test_new_project_dialog_and_generate_build(tmp_path):
    w = make_window("py32f030")
    dlg = NewProjectDialog(w, str(tmp_path))
    for ci in range(dlg.chipc.count()):
        dlg.chipc.setCurrentIndex(ci)
        pump()
        dlg.manual.setChecked(True)
        for pi in range(dlg.pkgc.count()):
            dlg.pkgc.setCurrentIndex(pi)
            for ei in range(dlg.exlist.count()):
                dlg.exlist.setCurrentRow(ei)
                pump()
        dlg.manual.setChecked(False)
    dlg.chipc.setCurrentIndex(0)
    dlg.name.setText("demo")
    for ei in range(dlg.exlist.count()):
        if dlg.exlist.item(ei).data(Qt.UserRole) == "uart_hello":
            dlg.exlist.setCurrentRow(ei)
    w.create_from_dialog(dlg)
    assert os.path.exists(os.path.join(str(tmp_path), "demo", "main.c"))
    assert w.project.pins
    w.auto_confirm = True
    from puya_studio import toolchain
    if toolchain.find_gcc_bin():
        r = w.build()
        assert r.ok and not r.warnings
        assert "ROM" in w.usage.text()
        # a compile error shows up as a clickable entry that jumps into the code
        main = os.path.join(str(tmp_path), "demo", "main.c")
        txt = open(main).read().replace("/* USER CODE BEGIN 3 */", "/* USER CODE BEGIN 3 */\n  this is not C;")
        open(main, "w").write(txt)
        r = w.build()
        assert not r.ok and w.diag.count() >= 1
        w.jump_to_diag(w.diag.item(0))
        assert w.tabs.currentWidget() is w.pages["Code"]
        assert w.pages["Code"].files.currentText() == "main.c"


def test_manual_package_and_memory_choice():
    w = make_window("py32f003")
    page = w.pages["Project"]
    i = page.pkgc.findData("SOP20-F1")
    page.pkgc.setCurrentIndex(i)
    pump()
    assert w.project.package == "SOP20-F1"
    page.memc.setCurrentIndex(page.memc.findData(16))
    assert w.project.flash_kb == 16 and w.project.ram_kb == 2
    assert w.project.part == "PY32F003F14S6"


def test_pages_reflect_pin_changes():
    w = make_window("py32f030")
    w.tabs.setCurrentWidget(w.pages["Timers / PWM"])
    pump()
    click_func(w, "PA6", "af:TIM3_CH1")
    w.on_changed(w.panel)
    assert w.project.periph["TIM3"]["enabled"]
    w.tabs.setCurrentWidget(w.pages["Timers / PWM"])
    pump()
    w.tabs.setCurrentWidget(w.pages["Interrupts"])
    pump()
    w.tabs.setCurrentWidget(w.pages["Low power"])
    pump()
    assert w.pages["Interrupts"].table.rowCount() == len(w.project.chip.interrupts)
