"""Sistema de design: paleta de livro-razão / cartório. Modo claro em papel
e tinta; modo escuro em azul-marinho com texto azul-claro e acento em
dourado (a mesma ideia de "documento formal", só na paleta noturna).
Tipografia: serifada elegante pra títulos, Segoe UI pra corpo — ambas
nativas do Windows, com fallback razoável em outros SOs para
desenvolvimento."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from .. import preferencias

FONT_DISPLAY = 'Constantia, Cambria, Georgia, "Liberation Serif", serif'
FONT_BODY = '"Segoe UI Variable Text", "Segoe UI", "Segoe UI Variable", "Noto Sans", Inter, sans-serif'
FONT_MONO = 'Consolas, "Cascadia Mono", "Liberation Mono", "DejaVu Sans Mono", monospace'

PALETA_CLARA = {
    "INK": "#1B2A41",
    "INK_MUTED": "#5B6472",
    "PAPER": "#F7F4EC",
    "PAPER_RAISED": "#FFFFFF",
    "BRASS": "#B08D57",
    "BRASS_DARK": "#8C6C3E",
    "SEAL_GREEN": "#2F5233",
    "SEAL_RED": "#7A2E2E",
    "HAIRLINE": "#D9D3C2",
    "ALT_ROW": "#FBF9F3",
    "ENTROU_BG": "#EFE3C8",
    "ENTROU_FG": "#6B4E1E",
    "SAIU_BG": "#F0DCD8",
    "SAIU_FG": "#7A2E2E",
}

PALETA_ESCURA = {
    "INK": "#BFE3FA",
    "INK_MUTED": "#7FA0BE",
    "PAPER": "#0E1A2B",
    "PAPER_RAISED": "#16273F",
    "BRASS": "#E8C05E",
    "BRASS_DARK": "#C79A3D",
    "SEAL_GREEN": "#7ED9A8",
    "SEAL_RED": "#F0897E",
    "HAIRLINE": "#28405E",
    "ALT_ROW": "#122236",
    "ENTROU_BG": "#3D3313",
    "ENTROU_FG": "#F0C869",
    "SAIU_BG": "#3D2220",
    "SAIU_FG": "#F0897E",
}

class _EstadoTema(QObject):
    """Singleton do módulo: guarda o modo atual (claro/escuro), persiste a
    escolha em disco, e avisa (via Signal) quem precisa reagir a uma troca —
    principalmente widgets que fixam cor num styleSheet só na construção,
    porque o QSS global já se atualiza sozinho com setStyleSheet de novo."""

    mudou = Signal()

    def __init__(self) -> None:
        super().__init__()
        modo = preferencias.obter("modo")
        self.modo = modo if modo in ("claro", "escuro") else "claro"

    def paleta(self) -> dict:
        return PALETA_ESCURA if self.modo == "escuro" else PALETA_CLARA

    def alternar(self) -> None:
        self.modo = "escuro" if self.modo == "claro" else "claro"
        preferencias.salvar_chave("modo", self.modo)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet())
        self.mudou.emit()


_estado = _EstadoTema()


def estado() -> _EstadoTema:
    return _estado


def cor(nome: str) -> str:
    return _estado.paleta()[nome]


def INK() -> str:
    return cor("INK")


def INK_MUTED() -> str:
    return cor("INK_MUTED")


def PAPER() -> str:
    return cor("PAPER")


def PAPER_RAISED() -> str:
    return cor("PAPER_RAISED")


def BRASS() -> str:
    return cor("BRASS")


def BRASS_DARK() -> str:
    return cor("BRASS_DARK")


def SEAL_GREEN() -> str:
    return cor("SEAL_GREEN")


def SEAL_RED() -> str:
    return cor("SEAL_RED")


def HAIRLINE() -> str:
    return cor("HAIRLINE")


def ALT_ROW() -> str:
    return cor("ALT_ROW")


def ENTROU_BG() -> str:
    return cor("ENTROU_BG")


def ENTROU_FG() -> str:
    return cor("ENTROU_FG")


def SAIU_BG() -> str:
    return cor("SAIU_BG")


def SAIU_FG() -> str:
    return cor("SAIU_FG")


def _rgb(hex_cor: str) -> str:
    """"#RRGGBB" -> "R, G, B", pra usar dentro de rgba(...) no QSS."""
    h = hex_cor.lstrip("#")
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"


def build_stylesheet() -> str:
    p = _estado.paleta()
    brass_rgb = _rgb(p["BRASS"])
    return f"""
    * {{
        font-family: {FONT_BODY};
        font-size: 13px;
        color: {p["INK"]};
    }}

    QMainWindow, QWidget {{
        background: {p["PAPER"]};
    }}

    QToolTip {{
        background: {p["PAPER_RAISED"]};
        color: {p["INK"]};
        border: 1px solid {p["HAIRLINE"]};
        padding: 4px 6px;
    }}

    QLabel[role="titulo"] {{
        font-family: {FONT_DISPLAY};
        font-size: 20px;
        font-weight: 600;
        color: {p["INK"]};
    }}

    QLabel[role="subtitulo"] {{
        color: {p["INK_MUTED"]};
        font-size: 12px;
    }}

    QLabel[role="secao"] {{
        font-family: {FONT_DISPLAY};
        font-size: 15px;
        font-weight: 600;
        color: {p["INK"]};
        padding-top: 4px;
    }}

    QFrame[role="card"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 6px;
    }}

    QFrame[role="hairline"] {{
        background: {p["HAIRLINE"]};
        max-height: 1px;
        min-height: 1px;
        border: none;
    }}

    QFrame#sidebar {{
        background: {p["PAPER_RAISED"]};
        border: none;
        border-right: 1px solid {p["HAIRLINE"]};
    }}

    QLabel[role="navSecao"] {{
        color: {p["INK_MUTED"]};
        font-size: 11px;
        font-weight: 700;
        padding: 10px 22px 6px 22px;
    }}

    QPushButton[role="navItem"], QPushButton[role="navSub"] {{
        background: transparent;
        border: none;
        border-left: 3px solid transparent;
        border-radius: 0;
        text-align: left;
        color: {p["INK_MUTED"]};
        font-weight: 500;
        padding: 8px 22px 8px 19px;
    }}

    QPushButton[role="navSub"] {{
        padding-left: 34px;
        font-size: 12px;
    }}

    QPushButton[role="navItem"]:hover, QPushButton[role="navSub"]:hover {{
        background: rgba({brass_rgb}, 0.12);
        color: {p["INK"]};
    }}

    QPushButton[role="navItem"]:pressed, QPushButton[role="navSub"]:pressed {{
        background: rgba({brass_rgb}, 0.18);
        color: {p["INK"]};
    }}

    QPushButton[role="navItem"]:checked, QPushButton[role="navSub"]:checked {{
        background: rgba({brass_rgb}, 0.14);
        border-left: 3px solid {p["BRASS"]};
        color: {p["INK"]};
        font-weight: 600;
    }}

    QLineEdit, QDoubleSpinBox, QSpinBox, QDateEdit, QComboBox, QTextEdit {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 4px;
        padding: 6px 8px;
        selection-background-color: {p["BRASS"]};
        selection-color: {p["PAPER_RAISED"]};
    }}

    QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QDateEdit:focus,
    QComboBox:focus, QTextEdit:focus {{
        border: 1px solid {p["BRASS"]};
    }}

    QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled, QDateEdit:disabled,
    QComboBox:disabled, QTextEdit:disabled {{
        background: {p["PAPER"]};
        color: {p["INK_MUTED"]};
    }}

    QLineEdit[role="mono"], QDoubleSpinBox[role="mono"], QLabel[role="mono"] {{
        font-family: {FONT_MONO};
    }}

    QPushButton {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["INK"]};
        border-radius: 4px;
        padding: 7px 16px;
        font-weight: 500;
        color: {p["INK"]};
    }}

    QPushButton:hover {{
        background: {p["INK"]};
        color: {p["PAPER_RAISED"]};
    }}

    QPushButton:pressed {{
        background: {p["BRASS_DARK"]};
        border-color: {p["BRASS_DARK"]};
        color: {p["PAPER_RAISED"]};
    }}

    QPushButton:disabled {{
        color: {p["INK_MUTED"]};
        border-color: {p["HAIRLINE"]};
        background: {p["PAPER"]};
    }}

    QPushButton[role="primario"] {{
        background: {p["INK"]};
        color: {p["PAPER_RAISED"]};
        border-color: {p["INK"]};
    }}

    QPushButton[role="primario"]:hover {{
        background: {p["BRASS_DARK"]};
        border-color: {p["BRASS_DARK"]};
    }}

    QPushButton[role="primario"]:disabled {{
        background: {p["PAPER"]};
        color: {p["INK_MUTED"]};
        border-color: {p["HAIRLINE"]};
    }}

    QPushButton[role="perigo"] {{
        border-color: {p["SEAL_RED"]};
        color: {p["SEAL_RED"]};
    }}

    QPushButton[role="perigo"]:hover {{
        background: {p["SEAL_RED"]};
        color: {p["PAPER_RAISED"]};
    }}

    QPushButton[role="perigo"]:disabled {{
        color: {p["INK_MUTED"]};
        border-color: {p["HAIRLINE"]};
        background: {p["PAPER"]};
    }}

    QPushButton[role="chevron"] {{
        border-radius: 18px;
        min-width: 36px;
        max-width: 36px;
        min-height: 36px;
        max-height: 36px;
        font-size: 16px;
        padding: 0;
    }}

    QTableWidget {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 6px;
        gridline-color: {p["HAIRLINE"]};
        alternate-background-color: {p["ALT_ROW"]};
    }}

    QHeaderView::section {{
        background: {p["INK"]};
        color: {p["PAPER_RAISED"]};
        padding: 8px;
        border: none;
        font-weight: 600;
    }}

    QTableWidget::item {{
        padding: 4px;
    }}

    QTableWidget::item:selected {{
        background: {p["BRASS"]};
        color: {p["PAPER_RAISED"]};
    }}

    QSplitter::handle {{
        background: {p["HAIRLINE"]};
    }}

    QSplitter::handle:horizontal {{
        width: 3px;
        margin: 0 2px;
    }}

    QSplitter::handle:vertical {{
        height: 3px;
        margin: 2px 0;
    }}

    QSplitter::handle:hover {{
        background: {p["BRASS"]};
    }}

    QScrollBar:vertical {{
        background: {p["PAPER"]};
        width: 10px;
    }}

    QScrollBar::handle:vertical {{
        background: {p["HAIRLINE"]};
        border-radius: 5px;
        min-height: 24px;
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    """
