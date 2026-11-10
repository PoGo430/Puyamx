"""Dev tool: render the window offscreen for the README (docs/screenshot.png)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from PySide6.QtWidgets import QApplication

from puya_studio import examples
from puya_studio.ui.main_window import MainWindow

app = QApplication([])
w = MainWindow()
p, sec, wiring = examples.build("adc_pot", "py32f030", package="LQFP32-K1")
p.name = "adc_pot"
p.assign("PA6", "af:TIM3_CH1", label="FAN")
p.assign("PB1", "exti", label="BTN", pull="up")
p.assign("PA13", "gpio_out", label="DEBUG")          # a debug pin: shows a warning
w.set_project(p, None)
w.resize(1500, 920)
w.show()
app.processEvents()
w.on_changed()
w.run_checks()
w.chipview.select_port("PA6")
w.panel.show_port(p, "PA6")
app.processEvents()
out = sys.argv[1] if len(sys.argv) > 1 else "docs/screenshot.png"
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
w.grab().save(out)
print("wrote", out)
