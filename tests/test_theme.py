import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QPushButton

from ui.theme import APP_STYLE_SHEET, FONT_FALLBACKS, apply_theme


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_theme_can_be_applied(self):
        family = apply_theme(self.app)

        self.assertIn(family, FONT_FALLBACKS)
        self.assertEqual(self.app.property("themeFontFamily"), family)
        self.assertEqual(self.app.styleSheet(), APP_STYLE_SHEET)
        self.assertEqual(
            self.app.palette().color(QPalette.Window).name(),
            "#f3f6fa",
        )

    def test_dynamic_property_selectors_and_widgets_are_valid(self):
        apply_theme(self.app)
        widgets = [
            QPushButton("Save"),
            QPushButton("Delete"),
            QPushButton("Cancel"),
            QFrame(),
            QLabel("Unsaved"),
            QLabel("Saved"),
            QLabel("Invalid value"),
        ]
        properties = [
            ("role", "primary"),
            ("role", "danger"),
            ("role", "secondary"),
            ("card", True),
            ("state", "dirty"),
            ("state", "clean"),
            ("role", "error"),
        ]

        for widget, (name, value) in zip(widgets, properties):
            widget.setProperty(name, value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        for selector in (
            'QPushButton[role="primary"]',
            'QPushButton[role="danger"]',
            'QPushButton[role="secondary"]',
            'QFrame[card="true"]',
            'QLabel[state="dirty"]',
            'QLabel[state="clean"]',
            'QLabel[role="error"]',
        ):
            self.assertIn(selector, APP_STYLE_SHEET)

        self.assertNotIn("transform", APP_STYLE_SHEET.casefold())
        self.assertIn("alternate-background-color", APP_STYLE_SHEET)


if __name__ == "__main__":
    unittest.main()
