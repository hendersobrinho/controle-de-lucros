"""Sistema de design nas cores da marca (logo Mfinanceiro): marinho, laranja
e turquesa. Modo claro em branco-azulado com texto marinho; modo escuro no
próprio marinho, com o laranja de acento.
Tipografia: serifada elegante pra títulos, Segoe UI pra corpo — ambas
nativas do Windows, com fallback razoável em outros SOs para
desenvolvimento."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from .. import preferencias
from .icones import pasta_assets

# Uma família só para tudo, humanista e de traço arredondado. A versão
# anterior usava serifa (Constantia/Cambria) nos títulos, o que dava ao
# programa um ar de documento antigo; o corpo já era sem serifa, e a mistura
# das duas era o que mais pesava.
#
# A ordem é deliberada: no Windows, que é onde o programa roda instalado, a
# Segoe UI Variable/Segoe UI é a fonte do próprio sistema — a mais comum que
# existe por lá, e a que faz o programa parecer parte do ambiente em vez de
# um intruso. As seguintes cobrem Linux e macOS sem depender de nada
# empacotado junto.
_FAMILIA = (
    '"Segoe UI Variable Text", "Segoe UI", Inter, "SF Pro Text", '
    '"Noto Sans", Cantarell, "DejaVu Sans", sans-serif'
)

FONT_DISPLAY = (
    '"Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", Inter, '
    '"SF Pro Display", "Noto Sans", Cantarell, sans-serif'
)
FONT_BODY = _FAMILIA
FONT_MONO = 'Consolas, "Cascadia Mono", "Liberation Mono", "DejaVu Sans Mono", monospace'

# Cores da marca (logo Mfinanceiro): azul-marinho #203461, laranja #F9B259 e
# turquesa #4BBDCD. Os nomes das chaves ficaram os da paleta antiga (tinta,
# latão, papel) pra não espalhar a troca pelo programa inteiro: BRASS agora é
# o laranja da marca, SEAL_GREEN o turquesa (escurecido onde vira texto, pra
# manter contraste de leitura) e INK o marinho.
PALETA_CLARA = {
    "INK": "#203461",
    "INK_MUTED": "#5A6680",
    "PAPER": "#F2F5F9",
    "PAPER_RAISED": "#FFFFFF",
    "BRASS": "#F9B259",
    "BRASS_DARK": "#B8660E",
    "SEAL_GREEN": "#16798A",
    "SEAL_RED": "#9A3434",
    "HAIRLINE": "#D7DEE8",
    "ALT_ROW": "#F7F9FC",
    "ENTROU_BG": "#FDEBD2",
    "ENTROU_FG": "#8A4B07",
    "SAIU_BG": "#F7E0DE",
    "SAIU_FG": "#9A3434",
    # O painel de destaque das telas de distribuição: o marinho da marca
    # cheio, com texto branco por cima.
    "HERO_BG": "#203461",
    "HERO_BG_2": "#2B4580",
    "HERO_FG": "#FFFFFF",
    "HERO_MUTED": "#B9C6E4",
}

# O modo escuro é o marinho da marca, com o laranja e o turquesa claros por
# cima. Todos os pares de texto/fundo ficam acima de 4.5:1 de contraste.
PALETA_ESCURA = {
    "INK": "#E4E9F2",
    "INK_MUTED": "#9DA9C0",
    "PAPER": "#17213A",
    "PAPER_RAISED": "#202C48",
    "BRASS": "#F9B259",
    "BRASS_DARK": "#E89A3A",
    "SEAL_GREEN": "#72D0DD",
    "SEAL_RED": "#EBA39C",
    "HAIRLINE": "#33415F",
    "ALT_ROW": "#1C2742",
    "ENTROU_BG": "#45361F",
    "ENTROU_FG": "#FBC983",
    "SAIU_BG": "#45282B",
    "SAIU_FG": "#EBA39C",
    "HERO_BG": "#26365C",
    "HERO_BG_2": "#30467A",
    "HERO_FG": "#FFFFFF",
    "HERO_MUTED": "#AEBBD8",
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
    # Barra normal mesmo no Windows: o QSS entende "C:/..." e se perde com "\".
    marcado = (pasta_assets() / "marcado.svg").as_posix()
    return f"""
    * {{
        font-family: {FONT_BODY};
        font-size: 14px;
        color: {p["INK"]};
    }}

    QMainWindow, QWidget {{
        background: {p["PAPER"]};
    }}

    /* Seletor de tipo em QSS pega as subclasses também, então a regra acima
       pinta cada QLabel com o fundo da página — e dentro de um cartão (que é
       mais claro) cada rótulo vira uma tarja visível. Texto não tem fundo
       próprio: acompanha o que estiver atrás dele. */
    QLabel, QCheckBox, QRadioButton {{
        background: transparent;
    }}

    /* A caixinha desenhada aqui, e não pelo estilo nativo: com o fundo
       transparente (sem a tarja bege dentro dos cartões), o desenho nativo
       sumia com a caixa desmarcada. Marcada: dourado com o "✓" branco. */
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p["INK_MUTED"]};
        background: {p["PAPER_RAISED"]};
    }}
    QCheckBox::indicator {{
        border-radius: 4px;
    }}
    QRadioButton::indicator {{
        border-radius: 9px;
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {p["BRASS"]};
    }}
    QCheckBox::indicator:checked {{
        background: {p["BRASS_DARK"]};
        border-color: {p["BRASS_DARK"]};
        image: url("{marcado}");
    }}
    /* A bolinha do rádio é uma borda grossa dourada em volta do miolo. */
    QRadioButton::indicator:checked {{
        border: 5px solid {p["BRASS_DARK"]};
        width: 8px;
        height: 8px;
    }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
        border-color: {p["HAIRLINE"]};
        background: {p["ALT_ROW"]};
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

    /* Rótulo de campo desabilitado recua junto com o campo. Sem isto o
       formulário bloqueado fica com os rótulos em contraste cheio ao lado de
       campos apagados, e a tela não parece bloqueada — parece quebrada. */
    QLabel:disabled {{
        color: {p["INK_MUTED"]};
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

    /* Cartão de participação (aba Sócios): um por empresa do sócio. O latão
       na borda ao passar o mouse diz que o cartão inteiro abre a edição. */
    QFrame[role="cartaoParticipacao"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 8px;
    }}
    QFrame[role="cartaoParticipacao"]:hover {{
        border: 1px solid {p["BRASS"]};
    }}
    QFrame[role="cartaoParticipacao"][encerrado="true"] {{
        background: {p["ALT_ROW"]};
    }}
    QLabel[role="nomeEmpresaCartao"] {{
        font-family: {FONT_DISPLAY};
        font-size: 15px;
        font-weight: 600;
    }}
    /* Rótulo pequeno acima de cada valor: diz o que o número é sem disputar
       atenção com ele. */
    QLabel[role="rotuloCampo"] {{
        color: {p["INK_MUTED"]};
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel[role="valorCampo"] {{
        font-size: 14px;
    }}
    QLabel[role="destaqueParticipacao"] {{
        font-family: {FONT_DISPLAY};
        font-size: 18px;
        font-weight: 600;
    }}
    QLabel[role="etiquetaSituacao"] {{
        font-size: 11px;
        font-weight: 600;
        border-radius: 9px;
        padding: 2px 10px;
    }}
    QLabel[role="etiquetaSituacao"][tom="ativo"] {{
        color: {p["SEAL_GREEN"]};
        border: 1px solid {p["SEAL_GREEN"]};
    }}
    /* A descrição da alteração, entre aspas embaixo do título: é o "do que
       se trata" escrito por quem cadastrou. */
    QLabel[role="descricaoAlteracao"] {{
        font-size: 14px;
        font-style: italic;
        padding-top: 4px;
    }}
    QLabel[role="descricaoAlteracao"][vazia="true"] {{
        color: {p["INK_MUTED"]};
        font-size: 12px;
    }}
    QLabel[role="etiquetaSituacao"][tom="mudou"] {{
        color: {p["BRASS_DARK"]};
        border: 1px solid {p["BRASS"]};
    }}
    QLabel[role="etiquetaSituacao"][tom="neutro"] {{
        color: {p["INK_MUTED"]};
        border: 1px solid {p["HAIRLINE"]};
    }}
    /* Faixa do ano na distribuição trimestral: um cartão por trimestre, o
       escolhido com a borda laranja, e o total do ano em laranja-claro. */
    QFrame[role="cartaoTrimestre"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 8px;
    }}
    QFrame[role="cartaoTrimestre"]:hover {{
        border-color: {p["BRASS"]};
    }}
    QFrame[role="cartaoTrimestre"][escolhido="true"] {{
        border: 2px solid {p["BRASS"]};
        background: {p["PAPER_RAISED"]};
    }}
    QFrame[role="cartaoTrimestre"]:disabled {{
        background: {p["ALT_ROW"]};
    }}
    QFrame[role="cartaoAno"] {{
        background: {p["ENTROU_BG"]};
        border: 1px solid {p["ENTROU_BG"]};
        border-radius: 8px;
    }}
    /* Painel de destaque das telas de distribuição. */
    QFrame[role="hero"] {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p["HERO_BG"]}, stop:1 {p["HERO_BG_2"]});
        border: none;
        border-radius: 12px;
    }}
    QFrame[role="hero"] QLabel {{
        color: {p["HERO_FG"]};
        background: transparent;
    }}
    QFrame[role="hero"] QLabel[role="heroRotulo"] {{
        color: {p["HERO_MUTED"]};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.6px;
    }}
    QFrame[role="hero"] QLabel[role="heroValor"] {{
        font-family: {FONT_DISPLAY};
        font-size: 30px;
        font-weight: 700;
    }}
    QFrame[role="hero"] QLabel[role="heroValorMenor"] {{
        font-family: {FONT_DISPLAY};
        font-size: 17px;
        font-weight: 600;
    }}
    QFrame[role="hero"] QLabel[role="heroNota"] {{
        color: {p["HERO_MUTED"]};
        font-size: 12px;
    }}
    QFrame[role="hero"] QFrame[role="heroDivisor"] {{
        background: rgba(255, 255, 255, 0.16);
        max-width: 1px;
        min-width: 1px;
        border: none;
    }}
    QFrame[role="hero"] QPushButton {{
        background: rgba(255, 255, 255, 0.10);
        border: 1px solid rgba(255, 255, 255, 0.28);
        color: {p["HERO_FG"]};
        border-radius: 15px;
        padding: 5px 14px;
        font-size: 12px;
    }}
    QFrame[role="hero"] QPushButton:hover {{
        background: rgba(255, 255, 255, 0.20);
    }}
    QFrame[role="hero"] QPushButton[trancado="true"] {{
        background: {p["BRASS"]};
        border-color: {p["BRASS"]};
        color: #203461;
        font-weight: 600;
    }}
    QFrame[role="hero"] QLabel[role="heroAno"] {{
        color: #203461;
        background: {p["BRASS"]};
        border-radius: 13px;
        padding: 3px 14px;
        font-size: 14px;
        font-weight: 700;
    }}
    /* O ano das telas de distribuição: grande, no centro das setas. */
    QSpinBox[role="anoGrande"] {{
        font-family: {FONT_DISPLAY};
        font-size: 20px;
        font-weight: 700;
        padding: 4px 6px;
        color: {p["INK"]};
        border: 2px solid {p["BRASS"]};
        border-radius: 8px;
    }}
    /* Importação: os formatos como cartões, os passos numerados e os
       botões grandes de ação. */
    QFrame[role="cartaoFormato"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 8px;
    }}
    QFrame[role="cartaoFormato"]:hover {{
        border-color: {p["BRASS"]};
    }}
    QFrame[role="cartaoFormato"][escolhido="true"] {{
        border: 2px solid {p["BRASS"]};
        background: {p["ALT_ROW"]};
    }}
    QFrame[role="linhaLayout"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 6px;
    }}
    QFrame[role="linhaLayout"]:hover {{
        border-color: {p["BRASS"]};
    }}
    QFrame[role="linhaLayout"][escolhido="true"] {{
        border: 2px solid {p["BRASS"]};
        background: {p["ALT_ROW"]};
    }}
    QLabel[role="marcaRadio"] {{
        color: {p["BRASS_DARK"]};
        font-size: 15px;
    }}
    QLabel[role="formatoEscolhido"] {{
        background: {p["ALT_ROW"]};
        border-left: 4px solid {p["BRASS"]};
        border-radius: 4px;
        padding: 8px 12px;
        color: {p["INK"]};
        font-size: 13px;
    }}
    QLabel[role="marcaSelecionado"] {{
        color: {p["BRASS_DARK"]};
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel[role="numeroPasso"] {{
        background: {p["INK"]};
        color: {p["PAPER_RAISED"]};
        border-radius: 15px;
        font-weight: 700;
        font-size: 14px;
    }}
    QPushButton[role="acaoGrande"], QPushButton[role="acaoGrandePrimaria"] {{
        text-align: left;
        padding: 10px 18px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
    }}
    QPushButton[role="acaoGrandePrimaria"] {{
        background: {p["INK"]};
        color: {p["PAPER_RAISED"]};
        border: 1px solid {p["INK"]};
    }}
    QPushButton[role="acaoGrandePrimaria"]:hover {{
        background: {p["BRASS_DARK"]};
        border-color: {p["BRASS_DARK"]};
    }}
    /* Confirmação do que acabou de dar certo. */
    QLabel[role="sucesso"] {{
        background: {p["ALT_ROW"]};
        color: {p["SEAL_GREEN"]};
        border: 1px solid {p["SEAL_GREEN"]};
        border-left: 5px solid {p["SEAL_GREEN"]};
        border-radius: 6px;
        padding: 10px 14px;
        font-weight: 600;
    }}
    /* Janelas de cadastro (ui/formulario.py). */
    QLabel[role="info"] {{
        color: {p["BRASS_DARK"]};
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel[role="dicaCampo"] {{
        color: {p["INK_MUTED"]};
        font-size: 11px;
    }}
    QLabel[role="operador"] {{
        color: {p["BRASS_DARK"]};
        font-family: {FONT_DISPLAY};
        font-size: 22px;
        font-weight: 700;
    }}
    QPushButton[role="segmento"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 0;
        padding: 8px 14px;
        color: {p["INK_MUTED"]};
    }}
    QPushButton[role="segmento"][posicao="inicio"] {{
        border-top-left-radius: 6px;
        border-bottom-left-radius: 6px;
    }}
    QPushButton[role="segmento"][posicao="fim"] {{
        border-top-right-radius: 6px;
        border-bottom-right-radius: 6px;
        border-left: none;
    }}
    QPushButton[role="segmento"][posicao="meio"] {{
        border-left: none;
    }}
    QPushButton[role="segmento"]:checked {{
        background: {p["INK"]};
        border-color: {p["INK"]};
        color: {p["PAPER_RAISED"]};
        font-weight: 600;
    }}
    /* Dashboards. */
    QPushButton[role="fichaAno"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 14px;
        padding: 5px 14px;
        min-height: 16px;
        font-size: 13px;
        font-weight: 600;
        color: {p["INK_MUTED"]};
    }}
    QPushButton[role="fichaAno"]:hover {{
        border-color: {p["BRASS"]};
        color: {p["INK"]};
    }}
    QPushButton[role="fichaAno"]:checked {{
        background: {p["INK"]};
        border-color: {p["INK"]};
        color: {p["PAPER_RAISED"]};
    }}
    QFrame[role="cartaoAtencao"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-left: 5px solid {p["HAIRLINE"]};
        border-radius: 8px;
    }}
    QFrame[role="cartaoAtencao"][tom="alerta"] {{ border-left-color: {p["SAIU_FG"]}; }}
    QFrame[role="cartaoAtencao"][tom="aviso"] {{ border-left-color: {p["BRASS"]}; }}
    QFrame[role="cartaoAtencao"][tom="ok"] {{ border-left-color: {p["SEAL_GREEN"]}; }}
    QFrame[role="cartaoAtencao"][tom="info"] {{ border-left-color: {p["INK"]}; }}
    QLabel[role="numeroAtencao"] {{
        font-family: {FONT_DISPLAY};
        font-size: 22px;
        font-weight: 700;
        color: {p["INK"]};
    }}
    QFrame[role="cartaoAtencao"][tom="alerta"] QLabel[role="numeroAtencao"] {{ color: {p["SAIU_FG"]}; }}
    QFrame[role="cartaoAtencao"][tom="ok"] QLabel[role="numeroAtencao"] {{ color: {p["SEAL_GREEN"]}; }}
    QLabel[role="variacao"] {{
        border-radius: 10px;
        padding: 2px 10px;
        font-size: 12px;
        font-weight: 700;
    }}
    QLabel[role="variacao"][tom="sobe"] {{ background: {p["SEAL_GREEN"]}; color: {p["PAPER_RAISED"]}; }}
    QLabel[role="variacao"][tom="desce"] {{ background: {p["SAIU_FG"]}; color: {p["PAPER_RAISED"]}; }}
    /* Aviso dentro da tela: faixa clara com borda à esquerda, em vez de um
       bloco de cor chapada que gritava mais que os próprios números. */
    QLabel[role="alerta"] {{
        background: {p["ENTROU_BG"]};
        color: {p["ENTROU_FG"]};
        border-left: 4px solid {p["BRASS"]};
        border-radius: 4px;
        padding: 9px 12px;
        font-size: 12px;
    }}
    QLabel[role="sinalSoma"] {{
        color: {p["INK_MUTED"]};
        font-size: 22px;
        font-weight: 300;
    }}
    QLabel[role="etiquetaSituacao"][tom="saiu"] {{
        color: {p["SAIU_FG"]};
        background: {p["SAIU_BG"]};
        border: 1px solid {p["SAIU_BG"]};
    }}
    /* Abas da ficha do sócio: texto solto com sublinhado laranja na
       escolhida — mesma linguagem da barra lateral, sem caixas em volta. */
    QWidget[role="faixaAbas"] {{
        background: transparent;
    }}
    QPushButton[role="abaFicha"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 13px;
        padding: 4px 12px;
        min-height: 16px;
        font-size: 13px;
        color: {p["INK"]};
        font-weight: 500;
    }}
    QPushButton[role="abaFicha"]:hover {{
        border-color: {p["BRASS"]};
        background: {p["PAPER_RAISED"]};
    }}
    QPushButton[role="abaFicha"]:checked {{
        background: {p["INK"]};
        border-color: {p["INK"]};
        color: {p["PAPER_RAISED"]};
    }}
    QPushButton[role="abaFicha"][apagada="true"] {{
        color: {p["INK_MUTED"]};
        font-style: italic;
    }}
    QPushButton[role="abaFicha"][apagada="true"]:checked {{
        color: {p["PAPER_RAISED"]};
    }}
    QListWidget[role="listaFichas"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 8px;
        outline: none;
    }}
    /* Atalho de um clique (R$ 1,00 / R$ 0,01): pílula pequena ao lado do
       campo, pra não competir com os botões de verdade da tela. */
    QPushButton[role="atalho"] {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 12px;
        padding: 3px 10px;
        font-size: 12px;
        color: {p["INK_MUTED"]};
    }}
    QPushButton[role="atalho"]:hover {{
        border-color: {p["BRASS"]};
        color: {p["INK"]};
    }}
    /* Os números que resumem a empresa no topo da ficha. */
    QLabel[role="numeroFicha"] {{
        font-family: {FONT_DISPLAY};
        font-size: 19px;
        font-weight: 600;
    }}
    QLabel[role="linkFicha"] {{
        color: {p["BRASS_DARK"]};
        font-size: 13px;
    }}

    /* Tela vazia é convite pra agir: texto maior e centrado, não um aviso. */
    QLabel[role="vazioTitulo"] {{
        font-family: {FONT_DISPLAY};
        font-size: 16px;
        font-weight: 600;
    }}
    QLabel[role="vazioTexto"] {{
        color: {p["INK_MUTED"]};
        font-size: 13px;
    }}
    QScrollArea[role="listaCartoes"], QScrollArea[role="listaCartoes"] > QWidget > QWidget {{
        background: transparent;
        border: none;
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
        selection-color: #203461;
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

    /* Botão secundário: contorno fino e discreto em repouso. O contorno
       grosso em tinta cheia que havia antes fazia toda a barra de ações
       parecer uma fileira de botões primários competindo entre si. */
    QPushButton {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 6px;
        padding: 8px 18px;
        font-weight: 500;
        min-height: 20px;
        color: {p["INK"]};
    }}

    QPushButton:hover {{
        background: {p["ALT_ROW"]};
        border-color: {p["INK_MUTED"]};
    }}

    QPushButton:pressed {{
        background: {p["HAIRLINE"]};
        border-color: {p["INK_MUTED"]};
    }}

    /* Foco visível: quem usa o programa pelo teclado precisa enxergar onde
       está, e o retângulo pontilhado padrão do Qt some no fundo claro. */
    QPushButton:focus {{
        border-color: {p["BRASS"]};
        outline: none;
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
        font-weight: 600;
    }}

    QPushButton[role="primario"]:hover {{
        background: {p["BRASS_DARK"]};
        border-color: {p["BRASS_DARK"]};
    }}

    QPushButton[role="primario"]:pressed {{
        background: {p["BRASS"]};
        border-color: {p["BRASS"]};
        color: {p["INK"]};
    }}

    QPushButton[role="primario"]:focus {{
        border-color: {p["BRASS"]};
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
        border-color: {p["SEAL_RED"]};
        color: {p["PAPER_RAISED"]};
    }}

    QPushButton[role="perigo"]:pressed {{
        background: {p["SEAL_RED"]};
        border-color: {p["SEAL_RED"]};
        color: {p["PAPER_RAISED"]};
    }}

    QPushButton[role="perigo"]:disabled {{
        color: {p["INK_MUTED"]};
        border-color: {p["HAIRLINE"]};
        background: {p["PAPER"]};
    }}

    /* Menus suspensos seguem o tema como o resto: sem isto o Qt desenha o
       padrão do sistema, que no modo escuro sai claro e destoa. */
    QMenu {{
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        padding: 4px;
    }}

    QMenu::item {{
        color: {p["INK"]};
        padding: 7px 24px 7px 14px;
        border-radius: 3px;
    }}

    QMenu::item:selected {{
        background: {p["INK"]};
        color: {p["PAPER_RAISED"]};
    }}

    QMenu::item:disabled {{
        color: {p["INK_MUTED"]};
    }}

    QMenu::separator {{
        height: 1px;
        background: {p["HAIRLINE"]};
        margin: 5px 10px;
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

    /* Um ponto menor que o resto: a tabela é grade densa, e o corpo a 14px
       empurrava oito colunas para fora do painel — aí a barra de rolagem
       horizontal voltava, que é justamente o que a gente tirou. Em formulário
       e rótulo o 14 fica; aqui a leitura é de varredura, não de leitura
       corrida. */
    QTableWidget {{
        font-size: 13px;
        background: {p["PAPER_RAISED"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 6px;
        gridline-color: {p["HAIRLINE"]};
        alternate-background-color: {p["ALT_ROW"]};
    }}

    QHeaderView::section {{
        font-size: 13px;
        background: {p["INK"]};
        color: {p["PAPER_RAISED"]};
        padding: 9px 8px;
        border: none;
        font-weight: 600;
    }}

    /* O fio embaixo de cada célula substitui a grade quadriculada (ver
       common.TabelaLista): separa um registro do outro sem desenhar trilhos
       verticais que descem até o último e param no ar. */
    QTableWidget::item {{
        padding: 6px 8px;
        border: none;
        border-bottom: 1px solid {p["HAIRLINE"]};
    }}

    QTableWidget::item:selected {{
        background: {p["ENTROU_BG"]};
        color: {p["INK"]};
    }}

    /* Barra de progresso na paleta do programa: o azul padrão do Qt é a única
       coisa na tela que não pertence ao conjunto. */
    QProgressBar {{
        background: {p["PAPER"]};
        border: 1px solid {p["HAIRLINE"]};
        border-radius: 5px;
        text-align: center;
        font-size: 11px;
        color: {p["INK_MUTED"]};
    }}

    QProgressBar::chunk {{
        background: {p["BRASS"]};
        border-radius: 4px;
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
