"""Janela de conferência e emissão do informe de rendimentos de um sócio.

Abre a partir da aba de Sócios. Como cada empresa é uma fonte pagadora
distinta e emite o seu próprio comprovante, a lista da esquerda traz uma
caixa de seleção por empresa: dá pra conferir uma a uma e emitir todas de uma
vez, cada uma no seu PDF.

Os valores vêm sugeridos do que o sistema já controla (pró-labore, IRRF,
lucro distribuído e saldo de empréstimo do ano). O que ele não controla —
INSS, 13º, pensão alimentícia — é digitado aqui, conferido contra a folha, e
fica guardado pra reemissão não precisar de tudo de novo.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import preferencias, repositories as repo
from ..fiscal import cpf_valido, de_centavos, formatar_cpf, para_centavos
from ..informe_rendimentos import (
    APELIDOS_CAMPOS,
    CAMPOS_SUGERIDOS,
    QUADRO_3_LINHAS,
    QUADRO_4_LINHAS,
    QUADRO_5_LINHAS,
    TITULO_QUADRO_3,
    TITULO_QUADRO_4,
    TITULO_QUADRO_5,
    montar_html,
    nome_arquivo_sugerido,
)
from ..models import InformeRendimento, Socio
from .icones import icone_app
from .informe_pdf import gerar_pdfs

# O modelo do comprovante vale a partir do ano-calendário de 1996 (é o ano em
# que os lucros passaram a ser isentos — a linha 5 do Quadro 4 diz isso).
PRIMEIRO_ANO = 1996


class CampoDinheiro(QLineEdit):
    """Campo de valor em reais: mostra sempre no formato do informe
    ("1.234,56") e devolve centavos, pro resto do fluxo nunca ver float."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignRight)
        self.setPlaceholderText("0,00")
        self.setProperty("role", "mono")
        self.setMaximumWidth(140)
        self.editingFinished.connect(self._reformatar)

    def definir_centavos(self, centavos: int) -> None:
        self.setText(de_centavos(centavos))

    def centavos(self) -> int:
        return para_centavos(self.text())

    def _reformatar(self) -> None:
        try:
            self.setText(de_centavos(self.centavos()))
        except ValueError:
            pass  # deixa como está; a validação de verdade é ao salvar/emitir


class _DialogoVisualizar(QDialog):
    """Pré-visualização com o MESMO HTML que vai pro PDF — conferir aqui é
    conferir o documento, não uma aproximação dele. Fundo branco fixo mesmo
    no tema escuro, porque o informe é impresso preto sobre branco."""

    def __init__(self, html: str, titulo: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setWindowIcon(icone_app())
        self.resize(880, 900)

        visualizador = QTextBrowser()
        visualizador.setStyleSheet("QTextBrowser { background: #FFFFFF; color: #000000; }")
        fonte = QFont()
        fonte.setFamilies(["Segoe UI", "DejaVu Sans", "Arial"])
        fonte.setPointSizeF(7.0)
        visualizador.document().setDefaultFont(fonte)
        visualizador.setHtml(html)

        botoes = QDialogButtonBox(QDialogButtonBox.Close)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(visualizador, 1)
        layout.addWidget(botoes)


class InformeRendimentosDialog(QDialog):
    def __init__(self, conn, socio: Socio, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.socio = socio
        self._empresas: list = []
        # Valores em edição por empresa. Ficam em memória enquanto a janela
        # está aberta pra dar pra ir e voltar entre as empresas conferindo,
        # sem gravar nada até apertar Salvar ou Emitir.
        self._informes: dict[int, InformeRendimento] = {}
        self._salvos: dict[int, bool] = {}
        self._empresa_atual: int | None = None
        self._ano_carregado: int | None = None
        self._carregando = False
        self._alterado = False

        self.setWindowTitle(f"Informe de rendimentos — {socio.nome}")
        self.setWindowIcon(icone_app())
        self.resize(1180, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self._montar_cabecalho())
        layout.addWidget(self._montar_corpo(), 1)
        layout.addLayout(self._montar_acoes())

        self._recarregar_empresas()

    # ---------------------------------------------------------- montagem --
    def _montar_cabecalho(self) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        linha = QHBoxLayout(card)
        linha.setContentsMargins(18, 14, 18, 14)
        linha.setSpacing(16)

        self.identificacao = QLabel()
        cpf = formatar_cpf(self.socio.cpf)
        if self.socio.tipo_pessoa != "fisica":
            aviso = "— o comprovante é da pessoa física beneficiária"
        elif not cpf_valido(self.socio.cpf):
            # CPF errado aqui trava a declaração do sócio e só aparece meses
            # depois, então o aviso é na cara antes de emitir.
            aviso = "— CPF inválido ou não cadastrado; corrija no cadastro do sócio"
        else:
            aviso = ""
        self.identificacao.setText(f"<b>{self.socio.nome}</b><br>CPF {cpf or '—'} {aviso}")
        self.identificacao.setTextFormat(Qt.RichText)
        self.identificacao.setWordWrap(True)
        linha.addWidget(self.identificacao)
        linha.addStretch(1)

        linha.addWidget(QLabel("Ano-calendário"))
        self.ano = QSpinBox()
        self.ano.setRange(PRIMEIRO_ANO, dt.date.today().year + 1)
        self.ano.setValue(dt.date.today().year - 1)
        self.ano.setToolTip(
            "Ano em que os rendimentos foram pagos. O exercício da declaração é sempre "
            "o ano seguinte (pago em 2025 = exercício 2026)."
        )
        self.ano.valueChanged.connect(self._ao_trocar_ano)
        linha.addWidget(self.ano)

        self.exercicio = QLabel()
        self.exercicio.setProperty("role", "subtitulo")
        linha.addWidget(self.exercicio)

        linha.addWidget(QLabel("Emitido em"))
        self.data_emissao = QDateEdit(calendarPopup=True)
        self.data_emissao.setDisplayFormat("dd/MM/yyyy")
        self.data_emissao.setDate(dt.date.today())
        linha.addWidget(self.data_emissao)

        return card

    def _montar_corpo(self) -> QWidget:
        divisor = QSplitter(Qt.Horizontal)
        divisor.setChildrenCollapsible(False)
        divisor.addWidget(self._montar_lista_empresas())
        divisor.addWidget(self._montar_formulario())
        divisor.setStretchFactor(0, 1)
        divisor.setStretchFactor(1, 2)
        divisor.setSizes([390, 770])
        return divisor

    def _montar_lista_empresas(self) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        col = QVBoxLayout(card)
        col.setContentsMargins(18, 14, 18, 16)
        col.setSpacing(8)

        titulo = QLabel("Fontes pagadoras")
        titulo.setProperty("role", "secao")
        ajuda = QLabel(
            "Um comprovante por empresa. Marque as que devem ser emitidas e clique em cada "
            "uma pra conferir os valores dela."
        )
        ajuda.setProperty("role", "subtitulo")
        ajuda.setWordWrap(True)
        col.addWidget(titulo)
        col.addWidget(ajuda)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lista.currentRowChanged.connect(self._ao_trocar_empresa)
        self.lista.itemChanged.connect(lambda _item: self._atualizar_botoes())
        col.addWidget(self.lista, 1)
        return card

    def _montar_formulario(self) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        col = QVBoxLayout(card)
        col.setContentsMargins(18, 14, 18, 16)
        col.setSpacing(8)

        self.titulo_form = QLabel("Valores do informe")
        self.titulo_form.setProperty("role", "secao")
        self.origem_valores = QLabel()
        self.origem_valores.setProperty("role", "subtitulo")
        self.origem_valores.setWordWrap(True)
        col.addWidget(self.titulo_form)
        col.addWidget(self.origem_valores)

        interno = QWidget()
        form = QVBoxLayout(interno)
        form.setContentsMargins(0, 0, 12, 0)
        form.setSpacing(6)

        self.campos: dict[str, CampoDinheiro] = {}
        self.campos_texto: dict[str, QWidget] = {}

        identificacao = QFormLayout()
        identificacao.setSpacing(8)
        self.campos_texto["codigo_beneficiario"] = QLineEdit()
        self.campos_texto["codigo_beneficiario"].setMaximumWidth(140)
        self.campos_texto["codigo_beneficiario"].setPlaceholderText("000001")
        self.campos_texto["natureza_rendimento"] = QLineEdit()
        identificacao.addRow("Código do beneficiário", self.campos_texto["codigo_beneficiario"])
        identificacao.addRow("Natureza do rendimento", self.campos_texto["natureza_rendimento"])
        form.addLayout(identificacao)

        for titulo, linhas in (
            (TITULO_QUADRO_3, QUADRO_3_LINHAS),
            (TITULO_QUADRO_4, QUADRO_4_LINHAS),
            (TITULO_QUADRO_5, QUADRO_5_LINHAS),
        ):
            form.addWidget(self._hairline())
            rotulo = QLabel(titulo)
            rotulo.setProperty("role", "secao")
            rotulo.setWordWrap(True)
            form.addWidget(rotulo)
            for campo, numero, descricao in linhas:
                form.addLayout(self._linha_valor(campo, numero, descricao))

        form.addWidget(self._hairline())
        rotulo_q7 = QLabel("7. Informações Complementares")
        rotulo_q7.setProperty("role", "secao")
        form.addWidget(rotulo_q7)
        form.addLayout(
            self._linha_valor(
                "emprestimo_saldo",
                "",
                "Empréstimo da empresa ao sócio — saldo em 31/12. Não é rendimento: sai no "
                "Quadro 7 pro sócio declarar em Dívidas e Ônus Reais.",
            )
        )
        self.campos_texto["informacoes_complementares"] = QPlainTextEdit()
        self.campos_texto["informacoes_complementares"].setPlaceholderText(
            "Texto livre, impresso depois do bloco do empréstimo."
        )
        self.campos_texto["informacoes_complementares"].setFixedHeight(70)
        form.addWidget(self.campos_texto["informacoes_complementares"])

        form.addWidget(self._hairline())
        rotulo_q8 = QLabel("8. Responsável pelas Informações")
        rotulo_q8.setProperty("role", "secao")
        form.addWidget(rotulo_q8)
        self.campos_texto["responsavel_nome"] = QLineEdit()
        self.campos_texto["responsavel_nome"].setPlaceholderText("Quem assina o comprovante")
        form.addWidget(self.campos_texto["responsavel_nome"])

        # É quase sempre a mesma pessoa em todos os informes do escritório;
        # guardar como padrão evita redigitar em cada sócio e cada empresa.
        self.responsavel_padrao = QCheckBox("Usar como responsável padrão dos próximos informes")
        self.responsavel_padrao.setToolTip(
            "Guarda este nome neste computador e já traz preenchido nos informes que "
            "ainda não foram salvos."
        )
        form.addWidget(self.responsavel_padrao)
        form.addStretch()

        for widget in self.campos_texto.values():
            sinal = widget.textChanged if hasattr(widget, "textChanged") else None
            if sinal is not None:
                sinal.connect(self._marcar_alterado)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(interno)
        col.addWidget(area, 1)
        return card

    def _linha_valor(self, campo: str, numero: str, descricao: str) -> QHBoxLayout:
        apelido = APELIDOS_CAMPOS.get(campo)
        prefixo = f"{numero}. " if numero else ""
        texto = f"{prefixo}{descricao}"
        if apelido:
            # O apelido do escritório em negrito na frente do texto oficial:
            # é assim que quem preenche sabe que pró-labore é a linha 1 do
            # Quadro 3 sem ter que decorar o modelo.
            texto = f"{prefixo}<b>{apelido}</b> — {descricao}"
        rotulo = QLabel(texto)
        rotulo.setTextFormat(Qt.RichText)
        rotulo.setWordWrap(True)

        entrada = CampoDinheiro()
        entrada.textEdited.connect(self._marcar_alterado)
        self.campos[campo] = entrada

        linha = QHBoxLayout()
        linha.setSpacing(10)
        linha.addWidget(rotulo, 1)
        linha.addWidget(entrada)
        return linha

    def _hairline(self) -> QFrame:
        linha = QFrame()
        linha.setProperty("role", "hairline")
        return linha

    def _montar_acoes(self) -> QHBoxLayout:
        self.btn_visualizar = QPushButton("Visualizar")
        self.btn_visualizar.clicked.connect(self._visualizar)
        self.btn_salvar = QPushButton("Salvar valores")
        self.btn_salvar.clicked.connect(self._salvar)
        self.btn_emitir = QPushButton("Emitir PDF")
        self.btn_emitir.setProperty("role", "primario")
        self.btn_emitir.clicked.connect(self._emitir)
        btn_fechar = QPushButton("Fechar")
        btn_fechar.clicked.connect(self.reject)

        acoes = QHBoxLayout()
        acoes.addStretch()
        acoes.addWidget(self.btn_visualizar)
        acoes.addWidget(self.btn_salvar)
        acoes.addWidget(self.btn_emitir)
        acoes.addWidget(btn_fechar)
        return acoes

    # ------------------------------------------------------------- dados --
    def _recarregar_empresas(self) -> None:
        ano = self.ano.value()
        self._ano_carregado = ano
        self.exercicio.setText(f"exercício {ano + 1}")
        self._empresas = repo.empresas_do_socio_no_ano(self.conn, self.socio.id, ano)
        self._informes = {}
        self._salvos = {}
        for empresa in self._empresas:
            informe, salvo = repo.carregar_informe(self.conn, empresa.id, ano, self.socio.id)
            self._informes[empresa.id] = informe
            self._salvos[empresa.id] = salvo

        self._carregando = True
        self.lista.clear()
        for empresa in self._empresas:
            item = QListWidgetItem(f"{empresa.nome} (nº {empresa.numero_chamada})")
            # Razão social costuma ser longa demais pra caber no painel; o nome
            # inteiro fica na dica, pra não precisar arrastar o divisor.
            item.setToolTip(item.text())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, empresa.id)
            self.lista.addItem(item)
        self._carregando = False

        self._empresa_atual = None
        self._alterado = False
        if self._empresas:
            self.lista.setCurrentRow(0)
        else:
            self._limpar_formulario()
        self._atualizar_botoes()

    def _ao_trocar_ano(self) -> None:
        if self._alterado:
            resposta = QMessageBox.question(
                self,
                "Trocar de ano",
                "Há valores digitados que ainda não foram salvos. Trocar o ano-calendário "
                "descarta essas alterações. Continuar?",
            )
            if resposta != QMessageBox.Yes:
                self.ano.blockSignals(True)
                self.ano.setValue(self._ano_carregado)
                self.ano.blockSignals(False)
                return
        self._recarregar_empresas()

    def _ao_trocar_empresa(self, linha: int) -> None:
        if self._carregando:
            return
        self._recolher_formulario()
        self._empresa_atual = self._empresas[linha].id if 0 <= linha < len(self._empresas) else None
        self._preencher_formulario()
        self._atualizar_botoes()

    def _preencher_formulario(self) -> None:
        if self._empresa_atual is None:
            self._limpar_formulario()
            return
        informe = self._informes[self._empresa_atual]
        empresa = next(e for e in self._empresas if e.id == self._empresa_atual)
        self.titulo_form.setText(f"Valores do informe — {empresa.nome}")
        self.origem_valores.setText(
            "Valores já conferidos e salvos para este ano."
            if self._salvos[self._empresa_atual]
            else "Pró-labore, IRRF, lucro distribuído e saldo de empréstimo vieram dos lançamentos "
            "do ano; o resto (INSS, 13º, pensão) o sistema não controla e precisa ser digitado. "
            "Confira tudo antes de emitir."
        )

        self._carregando = True
        for campo, entrada in self.campos.items():
            entrada.definir_centavos(getattr(informe, campo))
            sugerido = not self._salvos[self._empresa_atual] and campo in CAMPOS_SUGERIDOS
            entrada.setToolTip("Sugerido a partir dos lançamentos do ano." if sugerido else "")
        self.campos_texto["codigo_beneficiario"].setText(informe.codigo_beneficiario)
        self.campos_texto["natureza_rendimento"].setText(informe.natureza_rendimento)
        self.campos_texto["informacoes_complementares"].setPlainText(informe.informacoes_complementares)
        # Informe já conferido mantém quem assinou de fato; o que ainda não
        # foi salvo herda o padrão, que é o caso do primeiro do ano.
        responsavel = informe.responsavel_nome
        if not responsavel and not self._salvos[self._empresa_atual]:
            responsavel = preferencias.responsavel_informe()
        self.campos_texto["responsavel_nome"].setText(responsavel)
        self._carregando = False

    def _limpar_formulario(self) -> None:
        self._carregando = True
        self.titulo_form.setText("Valores do informe")
        self.origem_valores.setText(
            f"O sócio não foi fonte pagadora de nenhuma empresa em {self.ano.value()} — "
            "sem vínculo no ano e sem lançamento, não há informe a emitir."
        )
        for entrada in self.campos.values():
            entrada.clear()
        for widget in self.campos_texto.values():
            widget.clear()
        self._carregando = False

    def _recolher_formulario(self) -> None:
        """Guarda o que está na tela no informe da empresa que estava aberta,
        pra ir e voltar entre empresas sem perder o que foi digitado."""
        if self._empresa_atual is None:
            return
        informe = self._informes[self._empresa_atual]
        for campo, entrada in self.campos.items():
            try:
                setattr(informe, campo, entrada.centavos())
            except ValueError:
                pass  # texto inválido fica como está; _ler_formulario reclama na hora de salvar
        informe.codigo_beneficiario = self.campos_texto["codigo_beneficiario"].text().strip()
        informe.natureza_rendimento = self.campos_texto["natureza_rendimento"].text().strip()
        informe.informacoes_complementares = self.campos_texto["informacoes_complementares"].toPlainText().strip()
        informe.responsavel_nome = self.campos_texto["responsavel_nome"].text().strip()

    def _validar_formulario(self) -> bool:
        """Um valor mal digitado não pode virar 0,00 silenciosamente num
        documento fiscal — melhor barrar e dizer qual campo está errado."""
        if self._empresa_atual is None:
            return True
        for campo, entrada in self.campos.items():
            try:
                entrada.centavos()
            except ValueError:
                QMessageBox.warning(
                    self, "Valor inválido", f'"{entrada.text()}" não é um valor em reais válido.'
                )
                entrada.setFocus()
                return False
        return True

    def _marcar_alterado(self, *_args) -> None:
        if not self._carregando:
            self._alterado = True

    # ------------------------------------------------------------- ações --
    def _empresas_marcadas(self) -> list:
        marcadas = []
        for linha in range(self.lista.count()):
            item = self.lista.item(linha)
            if item.checkState() == Qt.Checked:
                marcadas.append(self._empresas[linha])
        return marcadas

    def _atualizar_botoes(self) -> None:
        tem_atual = self._empresa_atual is not None
        self.btn_visualizar.setEnabled(tem_atual)
        self.btn_salvar.setEnabled(bool(self._empresas))
        self.btn_emitir.setEnabled(bool(self._empresas_marcadas()))

    def _html_do(self, empresa) -> str:
        return montar_html(
            self._informes[empresa.id],
            empresa_nome=empresa.nome,
            empresa_cnpj=empresa.cnpj or "",
            socio_nome=self.socio.nome,
            socio_cpf=self.socio.cpf or "",
            data_emissao=self.data_emissao.date().toString("dd/MM/yyyy"),
        )

    def _visualizar(self) -> None:
        if not self._validar_formulario():
            return
        self._recolher_formulario()
        empresa = next(e for e in self._empresas if e.id == self._empresa_atual)
        _DialogoVisualizar(self._html_do(empresa), f"Informe — {empresa.nome}", self).exec()

    def _salvar(self) -> bool:
        if not self._validar_formulario():
            return False
        self._recolher_formulario()
        try:
            for empresa in self._empresas:
                repo.salvar_informe(self.conn, self._informes[empresa.id])
                self._salvos[empresa.id] = True
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao salvar", str(exc))
            return False
        if self.responsavel_padrao.isChecked():
            preferencias.guardar_responsavel_informe(
                self.campos_texto["responsavel_nome"].text()
            )
        self._alterado = False
        self._preencher_formulario()
        return True

    def _emitir(self) -> None:
        empresas = self._empresas_marcadas()
        if not empresas:
            return
        if not self._validar_formulario():
            return
        self._recolher_formulario()

        if not cpf_valido(self.socio.cpf):
            resposta = QMessageBox.question(
                self,
                "CPF inválido",
                f'O CPF cadastrado para "{self.socio.nome}" não é válido. Um informe com CPF '
                "errado impede o sócio de importar os dados na declaração. Emitir mesmo assim?",
            )
            if resposta != QMessageBox.Yes:
                return

        pasta = QFileDialog.getExistingDirectory(self, "Onde salvar os informes")
        if not pasta:
            return

        # Emitir grava também: o papel que saiu tem que ser o que ficou no
        # banco, senão a reemissão no ano que vem sai diferente do entregue.
        if not self._salvar():
            return

        paginas = [
            (nome_arquivo_sugerido(self._informes[e.id], self.socio.nome, e.nome), self._html_do(e))
            for e in empresas
        ]
        try:
            gerados = gerar_pdfs(paginas, Path(pasta))
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao emitir", f"Não foi possível gravar os PDFs: {exc}")
            return

        for empresa, caminho in zip(empresas, gerados):
            repo.registrar_emissao_informe(
                self.conn, empresa.id, self.ano.value(), self.socio.id, str(caminho)
            )

        QMessageBox.information(
            self,
            "Informes emitidos",
            f"{len(gerados)} informe(s) gravado(s) em:\n{pasta}\n\n"
            + "\n".join(c.name for c in gerados),
        )
