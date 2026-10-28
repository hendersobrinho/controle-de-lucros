"""Cartão de participação: a ficha de um sócio numa empresa, na aba Sócios.

Substitui a tabela de vínculos, que espremia oito colunas lado a lado — dois
percentuais com nomes parecidos ("% registrado", "% atual"), datas em ISO,
números sem unidade — e obrigava a ler a linha inteira pra entender uma
participação. Aqui cada empresa é uma ficha com os campos rotulados, na
ordem em que se pergunta: quanto ele tem, em cotas e em reais, desde quando,
e por qual alteração contratual.

A faixa de participação é o desenho do quadro societário visto da fatia
deste sócio: a barra inteira é o capital da empresa, a parte em latão é a
dele. Lê-se de relance quem pesa e quem é simbólico.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import AlteracaoContratual, Empresa, VinculoSocietario
from .common import formatar_data_br, formatar_percentual, formatar_valor_br, pintura_segura
from .theme import BRASS, HAIRLINE, INK_MUTED
from .theme import estado as tema_estado

# Diferença a partir da qual o percentual pelas cotas é mostrado ao lado do
# registrado: abaixo disso é arredondamento, e repetir o mesmo número duas
# vezes só confunde.
_TOLERANCIA_PERCENTUAL = 0.005


class FaixaParticipacao(QWidget):
    """A fatia do sócio no capital: trilho inteiro = 100% da empresa."""

    def __init__(self, percentual: float, ativo: bool, parent=None):
        super().__init__(parent)
        self._percentual = max(0.0, min(100.0, float(percentual or 0.0)))
        self._ativo = ativo
        self.setFixedHeight(8)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(f"{formatar_percentual(self._percentual)} do capital da empresa")
        tema_estado().mudou.connect(self.update)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        with pintura_segura(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            raio = self.height() / 2
            trilho = QRectF(0, 0, self.width(), self.height())
            painter.setBrush(QBrush(QColor(HAIRLINE())))
            painter.drawRoundedRect(trilho, raio, raio)
            if self._percentual <= 0:
                return
            # Participação simbólica (0,01%) ainda aparece como um traço: a
            # barra vazia diria "zero", que é outra coisa.
            largura = max(self.height(), self.width() * self._percentual / 100)
            # Participação encerrada recua: a mesma fatia, num tom que não
            # disputa atenção com quem está na sociedade hoje.
            cor = QColor(BRASS() if self._ativo else INK_MUTED())
            if not self._ativo:
                cor.setAlphaF(0.45)
            painter.setBrush(QBrush(cor))
            painter.drawRoundedRect(QRectF(0, 0, largura, self.height()), raio, raio)


def _rotulo(texto: str) -> QLabel:
    rotulo = QLabel(texto.upper())
    rotulo.setProperty("role", "rotuloCampo")
    fonte = rotulo.font()
    fonte.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
    rotulo.setFont(fonte)
    return rotulo


def _valor(texto: str, dica: str = "") -> QLabel:
    valor = QLabel(texto)
    valor.setProperty("role", "valorCampo")
    valor.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if dica:
        valor.setToolTip(dica)
    return valor


def _texto_alteracao(alteracao: AlteracaoContratual | None, verbo: str, movimento: str) -> str:
    if alteracao is None:
        return f"{movimento} sem alteração contratual associada"
    return f"{verbo} pela alteração Nº {alteracao.numero}, de {formatar_data_br(alteracao.data)}"


class CartaoParticipacao(QFrame):
    """A ficha de UM vínculo. Dois cliques, ou o botão, pedem a edição —
    quem abre a tela de edição é a aba, que é quem sabe recarregar depois."""

    editar = Signal(int)

    def __init__(
        self,
        vinculo: VinculoSocietario,
        empresa: Empresa | None,
        total_cotas_empresa: float,
        capital_calculado: float | None,
        alteracoes: dict[int, AlteracaoContratual],
        parent=None,
        valor_cota_informado: bool = False,
        refeita: bool = False,
        na_empresa_desde: str | None = None,
    ):
        super().__init__(parent)
        self.vinculo = vinculo
        ativo = vinculo.data_saida is None
        self.setProperty("role", "cartaoParticipacao")
        self.setProperty("encerrado", "false" if ativo else "true")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Dois cliques para editar esta participação")

        # ---- cabeçalho: empresa e situação
        nome = QLabel(empresa.nome if empresa else "Empresa não encontrada")
        nome.setProperty("role", "nomeEmpresaCartao")
        nome.setWordWrap(True)
        numero = QLabel(f"nº {empresa.numero_chamada}" if empresa and empresa.numero_chamada else "")
        numero.setProperty("role", "subtitulo")

        # Participação refeita fecha este vínculo e abre outro na mesma data:
        # o sócio não saiu, e a etiqueta não pode dizer que saiu.
        if ativo:
            texto_etiqueta, tom = "Ativo", "ativo"
        elif refeita:
            texto_etiqueta, tom = f"Refeita em {formatar_data_br(vinculo.data_saida)}", "mudou"
        else:
            texto_etiqueta, tom = f"Saiu em {formatar_data_br(vinculo.data_saida)}", "saiu"
        self.etiqueta = QLabel(texto_etiqueta)
        self.etiqueta.setProperty("role", "etiquetaSituacao")
        self.etiqueta.setProperty("tom", tom)

        cabecalho = QHBoxLayout()
        cabecalho.setSpacing(8)
        cabecalho.addWidget(nome, 1)
        cabecalho.addWidget(numero, 0, Qt.AlignVCenter)
        cabecalho.addWidget(self.etiqueta, 0, Qt.AlignVCenter)

        # ---- participação: o número grande e a faixa
        self.percentual = QLabel(formatar_percentual(vinculo.percentual_capital))
        self.percentual.setProperty("role", "destaqueParticipacao")
        do_capital = QLabel("do capital social")
        do_capital.setProperty("role", "subtitulo")

        linha_percentual = QHBoxLayout()
        linha_percentual.setSpacing(6)
        linha_percentual.addWidget(self.percentual, 0, Qt.AlignBaseline)
        linha_percentual.addWidget(do_capital, 0, Qt.AlignBaseline)
        linha_percentual.addStretch()

        cotas = vinculo.quantidade_cotas or 0
        if ativo and cotas and total_cotas_empresa:
            pelas_cotas = 100 * cotas / total_cotas_empresa
            if abs(pelas_cotas - vinculo.percentual_capital) > _TOLERANCIA_PERCENTUAL:
                divergente = QLabel(f"Pelas cotas, hoje: {formatar_percentual(pelas_cotas)}")
                divergente.setProperty("role", "subtitulo")
                divergente.setToolTip(
                    "Cotas do sócio ÷ total de cotas da empresa na alteração mais recente. "
                    "Não bate com o percentual registrado: confira se as cotas ou o "
                    "percentual estão desatualizados."
                )
                linha_percentual.addWidget(divergente, 0, Qt.AlignBaseline)

        faixa = FaixaParticipacao(vinculo.percentual_capital, ativo)

        # ---- os números, cada um com o seu rótulo
        if cotas and total_cotas_empresa:
            texto_cotas = f"{formatar_valor_br(cotas, 0)} de {formatar_valor_br(total_cotas_empresa, 0)}"
        elif cotas:
            texto_cotas = formatar_valor_br(cotas, 0)
        else:
            texto_cotas = "—"

        if vinculo.valor_capital is not None:
            self.capital = _valor(f"R$ {formatar_valor_br(vinculo.valor_capital)}")
        elif capital_calculado is not None and valor_cota_informado:
            # Com o valor da cota informado na empresa, cotas × valor É o
            # capital do sócio — não uma estimativa.
            self.capital = _valor(
                f"R$ {formatar_valor_br(capital_calculado)}",
                "Cotas do sócio × valor da cota informado no cadastro da empresa.",
            )
        elif capital_calculado is not None:
            self.capital = _valor(
                f"≈ R$ {formatar_valor_br(capital_calculado)}",
                "Estimativa pelas cotas (capital social ÷ cotas da empresa × cotas do sócio). "
                "Informe o valor da cota em \"Editar participação\" para o valor exato.",
            )
            self.capital.setProperty("role", "subtitulo")
        else:
            self.capital = _valor("Não informado")
            self.capital.setProperty("role", "subtitulo")

        # Com a participação refeita, o vínculo atual começa na data da
        # mudança — mas o sócio está na empresa desde a primeira entrada.
        if ativo:
            periodo = f"desde {formatar_data_br(na_empresa_desde or vinculo.data_entrada)}"
        else:
            periodo = f"{formatar_data_br(vinculo.data_entrada)} a {formatar_data_br(vinculo.data_saida)}"

        numeros = QGridLayout()
        numeros.setHorizontalSpacing(28)
        numeros.setVerticalSpacing(2)
        for coluna, (rotulo, valor) in enumerate(
            (
                ("Cotas", _valor(texto_cotas)),
                ("Capital do sócio", self.capital),
                ("Na sociedade", _valor(periodo)),
            )
        ):
            numeros.addWidget(_rotulo(rotulo), 0, coluna)
            numeros.addWidget(valor, 1, coluna)
            numeros.setColumnStretch(coluna, 1)

        # ---- alterações contratuais e observação
        detalhes = QVBoxLayout()
        detalhes.setSpacing(2)
        if na_empresa_desde and na_empresa_desde != vinculo.data_entrada:
            alteracao = alteracoes.get(vinculo.alteracao_entrada_id)
            texto_entrada = (
                f"Participação nova pela alteração Nº {alteracao.numero}, de {formatar_data_br(alteracao.data)}"
                if alteracao else f"Participação nova em {formatar_data_br(vinculo.data_entrada)}"
            )
        else:
            texto_entrada = _texto_alteracao(alteracoes.get(vinculo.alteracao_entrada_id), "Entrou", "Entrada")
        entrada = QLabel(texto_entrada)
        entrada.setProperty("role", "subtitulo")
        detalhes.addWidget(entrada)
        if not ativo:
            saida = QLabel(
                _texto_alteracao(alteracoes.get(vinculo.alteracao_saida_id), "Refeita", "Mudança")
                if refeita else _texto_alteracao(alteracoes.get(vinculo.alteracao_saida_id), "Saiu", "Saída")
            )
            saida.setProperty("role", "subtitulo")
            detalhes.addWidget(saida)
        if vinculo.observacao:
            observacao = QLabel(f"Observação: {vinculo.observacao}")
            observacao.setProperty("role", "subtitulo")
            observacao.setWordWrap(True)
            detalhes.addWidget(observacao)

        self.btn_editar = QPushButton("Editar participação")
        self.btn_editar.setCursor(Qt.PointingHandCursor)
        self.btn_editar.clicked.connect(lambda: self.editar.emit(self.vinculo.id))

        rodape = QHBoxLayout()
        rodape.addLayout(detalhes, 1)
        rodape.addWidget(self.btn_editar, 0, Qt.AlignBottom)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        layout.addLayout(cabecalho)
        layout.addLayout(linha_percentual)
        layout.addWidget(faixa)
        layout.addSpacing(4)
        layout.addLayout(numeros)
        layout.addSpacing(2)
        layout.addLayout(rodape)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.editar.emit(self.vinculo.id)
        event.accept()
