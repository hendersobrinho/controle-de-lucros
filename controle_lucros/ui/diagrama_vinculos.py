"""Desenho do mapa de vínculos, na tela e nos arquivos exportados.

Uma função de pintura só — desenhar() — serve aos três destinos: a tela, o PDF
e o SVG. Todos são um QPainter sobre um dispositivo diferente, então duplicar o
desenho por destino seria garantir que o PDF um dia deixasse de ser igual ao
que a pessoa viu antes de exportar.

As medidas vêm em pixels de controle_lucros.mapa_vinculos e todas as fontes são
definidas em pixel (não em ponto) pelo mesmo motivo: a página do PDF tem outra
resolução, e um tamanho em ponto mudaria de proporção lá. Assim o desenho é um
só, e cada destino apenas escala.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..mapa_vinculos import MapaVinculos, montar_mapa, nome_de_arquivo
from . import theme
from .common import formatar_valor_br

RAIO_CAIXA = 8
RAIO_COTOVELO = 10


def _paleta_da_tela() -> dict:
    return theme.estado().paleta()


def _paleta_para_arquivo() -> dict:
    """Arquivo exportado sai sempre no tema claro. O PDF vai para o papel e o
    SVG para dentro de um documento — os dois com fundo branco. Exportar o
    tema escuro daria uma página preta que ninguém quer imprimir."""
    return theme.PALETA_CLARA


def _fonte(tamanho: int, negrito: bool = False) -> QFont:
    fonte = QFont()
    fonte.setFamilies(["Segoe UI", "Noto Sans", "DejaVu Sans", "sans-serif"])
    fonte.setPixelSize(tamanho)
    fonte.setBold(negrito)
    return fonte


def _texto_que_cabe(texto: str, fonte: QFont, largura: float) -> str:
    return QFontMetricsF(fonte).elidedText(texto, Qt.ElideRight, largura)


def desenhar(painter: QPainter, mapa: MapaVinculos, paleta: dict) -> None:
    """Pinta o mapa inteiro no sistema de coordenadas do próprio mapa."""
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

    tinta = QColor(paleta["INK"])
    suave = QColor(paleta["INK_MUTED"])
    papel = QColor(paleta["PAPER"])
    papel_alto = QColor(paleta["PAPER_RAISED"])
    fio = QColor(paleta["HAIRLINE"])
    latao = QColor(paleta["BRASS"])
    saiu_fundo = QColor(paleta["SAIU_BG"])
    saiu_tinta = QColor(paleta["SAIU_FG"])

    painter.fillRect(QRectF(0, 0, mapa.largura, mapa.altura), papel)

    _desenhar_cabecalho(painter, mapa, tinta, suave)
    # Os traços primeiro: assim eles passam por baixo das caixas, e a ponta do
    # traço não aparece cortando o texto do nome da empresa.
    for empresa in mapa.empresas:
        _desenhar_ligacao(painter, mapa, empresa, latao, saiu_tinta, papel_alto, suave, fio)
    _desenhar_hub(painter, mapa, papel_alto, latao, tinta, suave)
    for empresa in mapa.empresas:
        _desenhar_empresa(painter, empresa, papel_alto, fio, tinta, suave, saiu_fundo, saiu_tinta)
    _desenhar_rodape(painter, mapa, suave)


def _desenhar_cabecalho(painter: QPainter, mapa: MapaVinculos, tinta: QColor, suave: QColor) -> None:
    painter.setPen(QPen(tinta))
    painter.setFont(_fonte(20, negrito=True))
    painter.drawText(QRectF(28, 18, mapa.largura - 56, 26), Qt.AlignLeft | Qt.AlignVCenter,
                     "Mapa de vínculos societários")

    painter.setPen(QPen(suave))
    painter.setFont(_fonte(12))
    documento = f" · CPF/CNPJ {mapa.socio_documento}" if mapa.socio_documento else ""
    painter.drawText(QRectF(28, 44, mapa.largura - 56, 20), Qt.AlignLeft | Qt.AlignVCenter,
                     f"{mapa.socio_nome}{documento} — {mapa.resumo()}")


def _desenhar_rodape(painter: QPainter, mapa: MapaVinculos, suave: QColor) -> None:
    linhas = []
    if mapa.empresas_omitidas:
        linhas.append(
            f"{mapa.empresas_omitidas} vínculo(s) de menor participação ficaram fora do desenho — "
            "a lista completa está na aba Sócios."
        )
    if mapa.gerado_em:
        linhas.append(f"Gerado em {mapa.gerado_em}")
    if not linhas:
        return
    painter.setPen(QPen(suave))
    painter.setFont(_fonte(11))
    painter.drawText(
        QRectF(28, mapa.altura - 28, mapa.largura - 56, 20),
        Qt.AlignLeft | Qt.AlignVCenter,
        "  ·  ".join(linhas),
    )


def _desenhar_hub(painter: QPainter, mapa: MapaVinculos, fundo: QColor, borda: QColor,
                  tinta: QColor, suave: QColor) -> None:
    caixa = mapa.hub
    retangulo = QRectF(caixa.x, caixa.y, caixa.largura, caixa.altura)
    painter.setBrush(QBrush(fundo))
    painter.setPen(QPen(borda, 2))
    painter.drawRoundedRect(retangulo, RAIO_CAIXA + 2, RAIO_CAIXA + 2)

    fonte_nome = _fonte(15, negrito=True)
    painter.setFont(fonte_nome)
    painter.setPen(QPen(tinta))
    painter.drawText(
        QRectF(caixa.x + 14, caixa.y + 16, caixa.largura - 28, 22),
        Qt.AlignCenter,
        _texto_que_cabe(mapa.socio_nome, fonte_nome, caixa.largura - 28),
    )

    painter.setFont(_fonte(11))
    painter.setPen(QPen(suave))
    painter.drawText(
        QRectF(caixa.x + 14, caixa.y + 40, caixa.largura - 28, 18),
        Qt.AlignCenter,
        mapa.socio_documento or "sem CPF/CNPJ cadastrado",
    )
    painter.setFont(_fonte(10))
    painter.drawText(
        QRectF(caixa.x + 14, caixa.y + 58, caixa.largura - 28, 16),
        Qt.AlignCenter,
        "sócio",
    )


def _desenhar_ligacao(painter: QPainter, mapa: MapaVinculos, empresa, latao: QColor,
                      saiu: QColor, fundo_etiqueta: QColor, suave: QColor, fio: QColor) -> None:
    """Liga a caixa ao hub com um cotovelo: um trecho reto na altura da caixa,
    uma curva, e a descida até o hub.

    Com curva em S de ponta a ponta, o meio de todos os traços caía quase na
    mesma altura (a do hub) — e a etiqueta do percentual de um sócio com muitas
    empresas ficava empilhada uma por cima da outra. No cotovelo, o trecho reto
    fica na altura da própria caixa, e cada etiqueta tem a linha só pra ela."""
    hub, caixa = mapa.hub, empresa.caixa
    if empresa.lado == "esquerda":
        saida = QPointF(caixa.direita, caixa.centro_y)
        chegada = QPointF(hub.x, hub.centro_y)
    else:
        saida = QPointF(caixa.x, caixa.centro_y)
        chegada = QPointF(hub.direita, hub.centro_y)

    dobra = (saida.x() + chegada.x()) / 2
    caminho = _caminho_cotovelo(saida, chegada, dobra)
    sentido = 1 if chegada.x() > saida.x() else -1

    cor = latao if empresa.ativo else saiu
    caneta = QPen(cor, 1.6)
    if not empresa.ativo:
        # Vínculo encerrado com traço pontilhado: a diferença se enxerga mesmo
        # impresso em preto e branco, onde a cor some.
        caneta.setStyle(Qt.DashLine)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(caneta)
    painter.drawPath(caminho)

    # No meio do trecho reto — não do traço inteiro: o reto vai da caixa até
    # a dobra, e centrar ali deixa a etiqueta sobre a linha, longe da caixa e
    # longe do canto arredondado.
    centro = QPointF((saida.x() + dobra - sentido * RAIO_COTOVELO) / 2, saida.y())
    _desenhar_etiqueta_percentual(painter, empresa, centro, fundo_etiqueta, fio, cor)


def _caminho_cotovelo(saida: QPointF, chegada: QPointF, dobra: float,
                      raio: float = RAIO_COTOVELO) -> QPainterPath:
    """Reto até a dobra, canto arredondado, vertical, outro canto, e entra no
    hub. Quando a caixa está quase na altura do hub não há espaço para os dois
    cantos, e aí uma curva suave fica melhor do que um degrau minúsculo."""
    caminho = QPainterPath(saida)
    desnivel = chegada.y() - saida.y()
    if abs(desnivel) < 2 * raio + 1:
        meio = (saida.x() + chegada.x()) / 2
        caminho.cubicTo(QPointF(meio, saida.y()), QPointF(meio, chegada.y()), chegada)
        return caminho

    sinal_x = 1 if chegada.x() > saida.x() else -1
    sinal_y = 1 if desnivel > 0 else -1
    caminho.lineTo(dobra - sinal_x * raio, saida.y())
    caminho.quadTo(QPointF(dobra, saida.y()), QPointF(dobra, saida.y() + sinal_y * raio))
    caminho.lineTo(dobra, chegada.y() - sinal_y * raio)
    caminho.quadTo(QPointF(dobra, chegada.y()), QPointF(dobra + sinal_x * raio, chegada.y()))
    caminho.lineTo(chegada)
    return caminho


def _desenhar_etiqueta_percentual(painter: QPainter, empresa, centro: QPointF,
                                  fundo: QColor, fio: QColor, cor_texto: QColor) -> None:
    """A participação em cima da linha, numa pastilha com fundo, pra ficar
    legível mesmo quando passa por cima do traço."""
    texto = f"{formatar_valor_br(empresa.percentual, 2)}%"
    fonte = _fonte(10, negrito=True)
    largura = QFontMetricsF(fonte).horizontalAdvance(texto) + 12
    altura = 18
    retangulo = QRectF(centro.x() - largura / 2, centro.y() - altura / 2, largura, altura)

    painter.setBrush(QBrush(fundo))
    painter.setPen(QPen(fio, 1))
    painter.drawRoundedRect(retangulo, altura / 2, altura / 2)
    painter.setPen(QPen(cor_texto))
    painter.setFont(fonte)
    painter.drawText(retangulo, Qt.AlignCenter, texto)


def _desenhar_empresa(painter: QPainter, empresa, fundo: QColor, fio: QColor, tinta: QColor,
                      suave: QColor, saiu_fundo: QColor, saiu_tinta: QColor) -> None:
    caixa = empresa.caixa
    retangulo = QRectF(caixa.x, caixa.y, caixa.largura, caixa.altura)

    painter.setBrush(QBrush(fundo if empresa.ativo else saiu_fundo))
    painter.setPen(QPen(fio if empresa.ativo else saiu_tinta, 1))
    painter.drawRoundedRect(retangulo, RAIO_CAIXA, RAIO_CAIXA)

    fonte_nome = _fonte(13, negrito=True)
    painter.setFont(fonte_nome)
    painter.setPen(QPen(tinta if empresa.ativo else saiu_tinta))
    painter.drawText(
        QRectF(caixa.x + 12, caixa.y + 9, caixa.largura - 24, 20),
        Qt.AlignLeft | Qt.AlignVCenter,
        _texto_que_cabe(empresa.nome, fonte_nome, caixa.largura - 24),
    )

    painter.setFont(_fonte(11))
    painter.setPen(QPen(suave if empresa.ativo else saiu_tinta))
    situacao = "" if empresa.ativo else "encerrado · "
    painter.drawText(
        QRectF(caixa.x + 12, caixa.y + 30, caixa.largura - 24, 18),
        Qt.AlignLeft | Qt.AlignVCenter,
        f"{situacao}{empresa.periodo}",
    )


class DiagramaVinculos(QWidget):
    """O mapa na tela. Só desenha — quem monta os dados é a tela que abre."""

    def __init__(self, mapa: MapaVinculos, parent=None):
        super().__init__(parent)
        self._mapa = mapa
        self.setMinimumSize(int(mapa.largura), int(mapa.altura))
        theme.estado().mudou.connect(self.update)

    def definir_mapa(self, mapa: MapaVinculos) -> None:
        self._mapa = mapa
        self.setMinimumSize(int(mapa.largura), int(mapa.altura))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(int(self._mapa.largura), int(self._mapa.altura))

    # Até onde o desenho pode crescer quando sobra espaço. Sem teto, o mapa de
    # um sócio com uma empresa só viraria uma caixa gigante no meio da tela.
    ESCALA_MAXIMA = 1.6

    def paintEvent(self, evento) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(_paleta_da_tela()["PAPER"]))
        escala = min(self.width() / self._mapa.largura, self.height() / self._mapa.altura)
        escala = max(1.0, min(escala, self.ESCALA_MAXIMA))
        # Centralizado: encostado no canto, o mapa curto parecia um pedaço de
        # tela que não carregou.
        painter.translate(
            max(0.0, (self.width() - self._mapa.largura * escala) / 2),
            max(0.0, (self.height() - self._mapa.altura * escala) / 2),
        )
        painter.scale(escala, escala)
        desenhar(painter, self._mapa, _paleta_da_tela())
        painter.end()


def exportar_svg(caminho: Path, mapa: MapaVinculos) -> Path:
    """SVG é vetorial e editável: entra em slide, em laudo, no editor de quem
    for arrumar o layout depois."""
    from PySide6.QtSvg import QSvgGenerator

    caminho = Path(caminho)
    gerador = QSvgGenerator()
    gerador.setFileName(str(caminho))
    gerador.setSize(QSize(int(mapa.largura), int(mapa.altura)))
    gerador.setViewBox(QRectF(0, 0, mapa.largura, mapa.altura))
    gerador.setTitle(f"Mapa de vínculos — {mapa.socio_nome}")
    gerador.setDescription(mapa.resumo())

    painter = QPainter(gerador)
    desenhar(painter, mapa, _paleta_para_arquivo())
    painter.end()
    return caminho


def orientacao_da_pagina(mapa: MapaVinculos):
    """Paisagem ou retrato, conforme a forma do mapa.

    Com o teto de empresas que montar_mapa aplica, o desenho sai sempre mais
    largo do que alto, e na prática isto devolve paisagem. A conta fica aqui
    mesmo assim porque quem mexer naquele teto (ou nas medidas das caixas)
    muda a forma do desenho sem passar por este arquivo — e aí a página
    acompanha sozinha, em vez de espremer um mapa alto numa folha deitada."""
    return QPageLayout.Portrait if mapa.altura > mapa.largura else QPageLayout.Landscape


def exportar_pdf(caminho: Path, mapa: MapaVinculos) -> Path:
    """Uma página só, com o desenho inteiro centralizado nela."""
    from PySide6.QtGui import QPdfWriter

    caminho = Path(caminho)
    escritor = QPdfWriter(str(caminho))
    escritor.setResolution(300)
    escritor.setPageSize(QPageSize(QPageSize.A4))
    escritor.setPageOrientation(orientacao_da_pagina(mapa))
    escritor.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Millimeter)
    escritor.setTitle(f"Mapa de vínculos — {mapa.socio_nome}")

    painter = QPainter(escritor)
    escala = min(escritor.width() / mapa.largura, escritor.height() / mapa.altura)
    painter.translate(
        (escritor.width() - mapa.largura * escala) / 2,
        (escritor.height() - mapa.altura * escala) / 2,
    )
    painter.scale(escala, escala)
    desenhar(painter, mapa, _paleta_para_arquivo())
    painter.end()
    return caminho


class DialogoMapaVinculos(QDialog):
    """A tela do mapa: o desenho e os dois jeitos de levá-lo para fora.

    Recebe os vínculos já em forma de dicionário, não os objetos do banco —
    assim esta tela não depende do repositório e dá pra abri-la com dados de
    teste."""

    def __init__(self, socio_nome: str, socio_documento: str, vinculos: list[dict], parent=None):
        super().__init__(parent)
        self._socio_nome = socio_nome
        self._socio_documento = socio_documento
        self._vinculos = list(vinculos)

        self.setWindowTitle(f"Mapa de vínculos — {socio_nome}")
        self.setMinimumSize(1000, 620)

        self.incluir_encerrados = QCheckBox("Incluir vínculos encerrados")
        self.incluir_encerrados.setChecked(True)
        self.incluir_encerrados.setToolTip(
            "Desmarque para ver só onde o sócio participa hoje — útil quando o histórico "
            "é longo e o desenho fica cheio."
        )
        self.incluir_encerrados.toggled.connect(self._remontar)

        self.diagrama = DiagramaVinculos(self._montar())
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(self.diagrama)

        self.btn_pdf = QPushButton("Exportar PDF")
        self.btn_pdf.setProperty("role", "primario")
        self.btn_pdf.clicked.connect(self._exportar_pdf)

        self.btn_svg = QPushButton("Exportar SVG")
        self.btn_svg.setToolTip(
            "Formato vetorial, que abre em editor de imagem e entra em slide ou laudo "
            "sem perder qualidade."
        )
        self.btn_svg.clicked.connect(self._exportar_svg)

        btn_fechar = QPushButton("Fechar")
        btn_fechar.clicked.connect(self.reject)

        self.aviso = QLabel()
        self.aviso.setProperty("role", "subtitulo")
        self.aviso.setWordWrap(True)

        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.addWidget(self.incluir_encerrados)
        acoes.addWidget(self.aviso, 1)
        acoes.addWidget(self.btn_pdf)
        acoes.addWidget(self.btn_svg)
        acoes.addWidget(btn_fechar)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 14, 14, 14)
        coluna.setSpacing(10)
        coluna.addWidget(area, 1)
        coluna.addLayout(acoes)

    # ---------------------------------------------------------------- dados --
    def _montar(self) -> MapaVinculos:
        vinculos = self._vinculos
        if not self.incluir_encerrados.isChecked():
            vinculos = [v for v in vinculos if not v.get("data_saida")]
        return montar_mapa(
            self._socio_nome,
            self._socio_documento,
            vinculos,
            gerado_em=dt.datetime.now().strftime("%d/%m/%Y às %H:%M"),
        )

    def _remontar(self, *_args) -> None:
        self.diagrama.definir_mapa(self._montar())

    def mapa(self) -> MapaVinculos:
        return self._montar()

    # ------------------------------------------------------------ exportar --
    def _exportar_pdf(self) -> None:
        self._exportar("pdf", "PDF (*.pdf)", exportar_pdf)

    def _exportar_svg(self) -> None:
        self._exportar("svg", "Imagem vetorial (*.svg)", exportar_svg)

    def _exportar(self, extensao: str, filtro: str, funcao) -> None:
        sugestao = nome_de_arquivo(self._socio_nome, extensao)
        caminho, _ = QFileDialog.getSaveFileName(self, f"Exportar mapa em {extensao.upper()}", sugestao, filtro)
        if not caminho:
            return
        if not caminho.lower().endswith(f".{extensao}"):
            caminho += f".{extensao}"
        try:
            funcao(Path(caminho), self._montar())
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao salvar o arquivo", str(exc))
            return
        self.aviso.setText(f"Salvo em {caminho}")
        QMessageBox.information(self, "Mapa exportado", f"Mapa salvo em:\n{caminho}")
