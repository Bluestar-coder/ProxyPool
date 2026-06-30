from __future__ import annotations

_BASE = """
QMainWindow, QDialog {{
    background: {bg};
    color: {fg};
}}
QWidget {{
    background: {bg};
    color: {fg};
    font-size: 13px;
}}
QMenuBar {{
    background: {surface};
    color: {fg};
    border-bottom: 1px solid {border};
    padding: 2px;
}}
QMenuBar::item:selected {{
    background: {selection};
    color: {fg_bright};
}}
QMenu {{
    background: {surface};
    color: {fg};
    border: 1px solid {border};
}}
QMenu::item:selected {{
    background: {accent};
    color: white;
}}
QToolBar {{
    background: {surface};
    border-bottom: 1px solid {border};
    spacing: 4px;
    padding: 4px 6px;
}}
QPushButton {{
    background: {btn};
    color: {fg};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 5px 12px;
    min-width: 64px;
}}
QPushButton:hover {{
    background: {btn_hover};
    border-color: {accent};
}}
QPushButton:pressed {{
    background: {selection};
}}
QPushButton:disabled {{
    color: {fg_dim};
    border-color: {border};
}}
QPushButton#startBtn {{
    background: {accent};
    color: white;
    border: none;
    font-weight: bold;
}}
QPushButton#startBtn:hover {{
    background: {accent_hover};
}}
QPushButton#startBtn:disabled {{
    background: {btn};
    color: {fg_dim};
    border: 1px solid {border};
}}
QPushButton#stopBtn {{
    background: transparent;
    color: {fg_dim};
    border: 1px solid {border};
}}
QPushButton#stopBtn:hover {{
    border-color: {error};
    color: {error};
}}
QPushButton#stopBtn:disabled {{
    color: {fg_dim};
    border-color: {border};
    opacity: 0.4;
}}
QTableView {{
    background: {bg};
    alternate-background-color: {surface};
    color: {fg};
    border: 1px solid {border};
    gridline-color: {border};
    selection-background-color: {selection};
    selection-color: {fg_bright};
}}
QTableView QHeaderView::section {{
    background: {surface};
    color: {fg};
    border: none;
    border-right: 1px solid {border};
    border-bottom: 1px solid {border};
    padding: 4px 8px;
    font-weight: bold;
}}
QTextEdit {{
    background: {surface};
    color: {fg};
    border: 1px solid {border};
    font-family: "Menlo", "Monaco", "Courier New";
    font-size: 12px;
}}
QLineEdit, QSpinBox, QComboBox {{
    background: {input_bg};
    color: {fg};
    border: 1px solid {border};
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: {accent};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {accent};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background: {surface};
    color: {fg};
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: white;
}}
QLabel {{
    background: transparent;
    color: {fg};
}}
QLabel#statLabel {{
    background: transparent;
    color: {fg_dim};
    font-size: 12px;
    padding: 0 2px;
}}
QLabel#statValue {{
    background: {surface};
    color: {fg};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 1px 10px;
    font-size: 12px;
    font-weight: bold;
    min-width: 24px;
}}
QLabel#statValid {{
    background: {surface};
    color: {success};
    border: 1px solid {success};
    border-radius: 10px;
    padding: 1px 10px;
    font-size: 12px;
    font-weight: bold;
    min-width: 24px;
}}
QLabel#statInvalid {{
    background: {surface};
    color: {error};
    border: 1px solid {error};
    border-radius: 10px;
    padding: 1px 10px;
    font-size: 12px;
    font-weight: bold;
    min-width: 24px;
}}
QLabel#statUnknown {{
    background: {surface};
    color: {fg_dim};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 1px 10px;
    font-size: 12px;
    font-weight: bold;
    min-width: 24px;
}}
QSplitter::handle {{
    background: {border};
}}
QScrollBar:vertical {{
    background: {bg};
    width: 10px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {border};
    border-radius: 5px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {fg_dim};
}}
QScrollBar:horizontal {{
    background: {bg};
    height: 10px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {border};
    border-radius: 5px;
    min-width: 20px;
}}
QStatusBar {{
    background: {accent};
    color: white;
    font-size: 12px;
}}
QGroupBox {{
    border: 1px solid {border};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 4px;
    color: {fg};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    color: {accent};
}}
QCheckBox {{
    color: {fg};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {border};
    border-radius: 3px;
    background: {input_bg};
}}
QCheckBox::indicator:hover {{
    border-color: {accent};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjMiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCI+PHBvbHlsaW5lIHBvaW50cz0iMjAgNiA5IDE3IDQgMTIiPjwvcG9seWxpbmU+PC9zdmc+);
}}
QDialogButtonBox QPushButton {{
    min-width: 70px;
}}
"""

_DARK_PLUS = {
    "bg":           "#1e1e1e",
    "surface":      "#2d2d2d",
    "fg":           "#cccccc",
    "fg_bright":    "#ffffff",
    "fg_dim":       "#858585",
    "accent":       "#007acc",
    "accent_hover": "#1a8cd8",
    "selection":    "#264f78",
    "border":       "#404040",
    "btn":          "#3a3a3a",
    "btn_hover":    "#4a4a4a",
    "input_bg":     "#3c3c3c",
    "success":      "#4ec9b0",
    "error":        "#f14c4c",
    "warning":      "#ce9178",
}

_MONOKAI = {
    "bg":           "#272822",
    "surface":      "#2f3027",
    "fg":           "#f8f8f2",
    "fg_bright":    "#ffffff",
    "fg_dim":       "#75715e",
    "accent":       "#66d9e8",
    "accent_hover": "#7de6f5",
    "selection":    "#49483e",
    "border":       "#3e3d32",
    "btn":          "#3e3d32",
    "btn_hover":    "#55544a",
    "input_bg":     "#3e3d32",
    "success":      "#a6e22e",
    "error":        "#f92672",
    "warning":      "#fd971f",
}

_SOLARIZED_DARK = {
    "bg":           "#002b36",
    "surface":      "#073642",
    "fg":           "#839496",
    "fg_bright":    "#93a1a1",
    "fg_dim":       "#586e75",
    "accent":       "#268bd2",
    "accent_hover": "#3a9fdf",
    "selection":    "#0d4c5e",
    "border":       "#144f5e",
    "btn":          "#073642",
    "btn_hover":    "#0d4c5e",
    "input_bg":     "#073642",
    "success":      "#859900",
    "error":        "#dc322f",
    "warning":      "#cb4b16",
}

THEMES: dict[str, dict] = {
    "Dark+":           _DARK_PLUS,
    "Monokai":         _MONOKAI,
    "Solarized Dark":  _SOLARIZED_DARK,
}

DEFAULT_THEME = "Dark+"


def build_stylesheet(name: str) -> str:
    colors = THEMES.get(name, _DARK_PLUS)
    return _BASE.format(**colors)
