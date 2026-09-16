"""Tela de importação em massa de cadastro: sobe uma planilha com empresa +
sócio + vínculo numa linha só e aplica tudo de uma vez — pensada pra dar
conta de uma base grande (~160+ empresas) sem digitar registro por registro
nas abas de Cadastro. Empresa é reconhecida por nº da empresa/CNPJ/nome e
resolve sozinha (baixo risco de duplicata); sócio é reconhecido por CPF/nome
e nunca criado sem confirmação — o mesmo sócio costuma aparecer em várias
empresas, e duplicar cadastro dele bagunçaria o histórico em todas elas."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import preferencias, repositories as repo
from ..layout_importacao import (
    ROTULOS_CAMPOS,
    LayoutImportacao,
    LayoutInvalido,
    exportar_com_layout,
    importar_com_layout,
    layout_do_modelo,
    previa,
    validar as validar_layout,
)
from ..models import Socio
from ..planilha import (
    MODELO_CADASTRO_PADRAO,
    MODELOS_CADASTRO,
    exportar_modelo_cadastro,
    importar_cadastro,
    ler_linhas_brutas,
    modelo_cadastro,
)
from ..leitor_xls import XlsIlegivel, e_xls_antigo, ler_xls
from ..relatorio_socios import (
    RelatorioInvalido,
    ler_relatorio_de_planilha,
    ler_relatorio_socios,
    linhas_para_importacao,
    resumo as resumo_do_relatorio,
)
from .common import TabelaLista
from .destino_alteracao import DialogoDestinoAlteracao
from .ocupado import Progresso, ocupado
from .layout_editor import EditorLayout
from .leitor_pdf import PdfIlegivel, extrair_texto
from .theme import SAIU_FG

# Último formato escolhido, guardado entre execuções.
_CHAVE_FORMATO = "importacao_formato"


def ler_relatorio_arquivo(caminho: Path):
    """Lê o relatório "Cadastro de Sócios" de outro sistema contábil, em PDF
    ou em planilha, escolhendo como extrair pelo conteúdo do arquivo e não
    pela extensão.

    Relatório salvo como ".xls" por um sistema e reaberto/salvo por outro
    vira .xlsx ou HTML sem mudar de nome — conferir a assinatura evita
    recusar um arquivo que dá perfeitamente para ler. Módulo nível, e não
    método: usado tanto por esta tela quanto pelo import direto de dentro de
    um card da aba Alterações."""
    if caminho.suffix.lower() == ".pdf":
        return ler_relatorio_socios(extrair_texto(caminho))
    if e_xls_antigo(caminho):
        return ler_relatorio_de_planilha(ler_xls(caminho))
    # .xlsx e .csv: as linhas vêm sem descartar as vazias, porque aqui a
    # posição não importa e uma linha em branco no meio não atrapalha.
    return ler_relatorio_de_planilha(ler_linhas_brutas(caminho, descartar_vazias=False))


class DialogoRevisaoCadastro(QDialog):
    """Uma pendência por sócio que não bateu com segurança contra o cadastro
    existente (CPF ausente ou nome ambíguo) — escolher um sócio já
    cadastrado ou criar um novo, sempre com confirmação humana antes de
    aplicar qualquer coisa. Quando o mesmo sócio novo aparece em várias
    linhas (várias empresas) do mesmo arquivo, agrupamos num cartão só —
    resolver uma vez já aplica a todas as empresas dele, em vez de pedir
    confirmação repetida pra "a mesma pessoa"."""

    def __init__(self, conn, pendencias: list[dict], parent=None):
        super().__init__(parent)
        self.conn = conn
        self._socios = repo.listar_socios(conn)
        self._grupos_ui: list[tuple[list[dict], QComboBox, QPushButton]] = []

        grupos: dict[str, list[dict]] = {}
        ordem: list[str] = []
        for pendencia in pendencias:
            cpf = pendencia["socio_cpf"].strip()
            chave = cpf if cpf else f"nome::{pendencia['socio_nome'].strip().lower()}"
            if chave not in grupos:
                grupos[chave] = []
                ordem.append(chave)
            grupos[chave].append(pendencia)

        self.setWindowTitle("Revisar sócios importados")
        self.setMinimumSize(700, 480)

        plural_socio = "sócio(s)" if len(ordem) != 1 else "sócio"
        aviso = QLabel(
            f"{len(ordem)} {plural_socio} do arquivo ({len(pendencias)} linha(s) no total) não puderam ser "
            "associados automaticamente a um cadastro já existente. Confira cada um abaixo — resolver um "
            "sócio que aparece em várias empresas já vale pra todas elas. Nada é aplicado sem sua confirmação."
        )
        aviso.setWordWrap(True)
        aviso.setProperty("role", "subtitulo")

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setSpacing(10)
        for chave in ordem:
            coluna.addWidget(self._montar_grupo(grupos[chave]))
        coluna.addStretch()
        area.setWidget(conteudo)

        # Importar o quadro societário inteiro de uma empresa nova cai aqui
        # com todo mundo pendente — sem uma ação em lote seriam dezenas de
        # cliques idênticos. Continua sendo confirmação explícita, só que uma
        # vez em vez de uma por pessoa.
        self.btn_cadastrar_todos = QPushButton("Cadastrar todos como novos sócios")
        self.btn_cadastrar_todos.clicked.connect(self._cadastrar_todos)

        linha_lote = QHBoxLayout()
        linha_lote.addWidget(self.btn_cadastrar_todos)
        linha_lote.addStretch()

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Aplicar selecionados")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(aviso)
        layout.addLayout(linha_lote)
        layout.addWidget(area, 1)
        layout.addWidget(botoes)

    def _montar_grupo(self, linhas: list[dict]) -> QWidget:
        representante = linhas[0]
        caixa = QFrame()
        caixa.setProperty("role", "card")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(6)

        cpf_texto = representante["socio_cpf"] or "não informado"
        nomes_empresas = list(dict.fromkeys(l["empresa_nome"] for l in linhas))
        plural_empresa = "empresas" if len(nomes_empresas) != 1 else "empresa"
        titulo = QLabel(
            f"<b>{representante['socio_nome']}</b> — CPF/CNPJ: {cpf_texto} — "
            f"{len(nomes_empresas)} {plural_empresa}: {', '.join(nomes_empresas)}"
        )
        titulo.setWordWrap(True)
        col.addWidget(titulo)

        rotulo_aviso = QLabel(f"⚠ {representante['aviso']}")
        rotulo_aviso.setWordWrap(True)
        rotulo_aviso.setStyleSheet(f"color: {SAIU_FG()}; font-size: 11px;")
        col.addWidget(rotulo_aviso)

        linha_acoes = QHBoxLayout()
        combo = QComboBox()
        self._preencher_combo_socios(combo)
        sugestao = representante.get("socio_sugestao")
        if sugestao is not None:
            idx = combo.findData(sugestao.id)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        rotulo_tipo = "jurídico" if representante.get("tipo_pessoa") == "juridica" else "físico"
        btn_cadastrar = QPushButton(f"Cadastrar como novo sócio ({rotulo_tipo})")
        btn_cadastrar.clicked.connect(lambda: self._cadastrar_novo(linhas, combo, btn_cadastrar))

        linha_acoes.addWidget(QLabel("Vincular a:"))
        linha_acoes.addWidget(combo, 1)
        linha_acoes.addWidget(btn_cadastrar)
        col.addLayout(linha_acoes)

        self._grupos_ui.append((linhas, combo, btn_cadastrar))
        return caixa

    def _preencher_combo_socios(self, combo: QComboBox) -> None:
        combo.clear()
        combo.addItem("— não importar estas linhas —", None)
        for s in self._socios:
            combo.addItem(f"{s.nome} ({s.cpf or 'sem CPF'})", s.id)

    def _cadastrar_novo(self, linhas: list[dict], combo: QComboBox, botao: QPushButton) -> None:
        representante = linhas[0]
        tipo_pessoa = representante.get("tipo_pessoa", "fisica")
        rotulo_tipo = "jurídico" if tipo_pessoa == "juridica" else "físico"
        nomes_empresas = list(dict.fromkeys(l["empresa_nome"] for l in linhas))
        plural_empresa = "empresas" if len(nomes_empresas) != 1 else "empresa"
        resposta = QMessageBox.question(
            self,
            "Cadastrar novo sócio",
            f'Cadastrar "{representante["socio_nome"]}" (CPF/CNPJ: {representante["socio_cpf"] or "não informado"}) '
            f"como sócio {rotulo_tipo} novo, e vincular {'à' if len(nomes_empresas) == 1 else 'às'} "
            f"{len(nomes_empresas)} {plural_empresa}: {', '.join(nomes_empresas)}?",
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            novo_id = repo.salvar_socio(
                self.conn,
                Socio(id=None, nome=representante["socio_nome"], cpf=representante["socio_cpf"] or "", tipo_pessoa=tipo_pessoa),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao cadastrar sócio", str(exc))
            return
        self._socios = repo.listar_socios(self.conn)
        self._preencher_combo_socios(combo)
        idx = combo.findData(novo_id)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        botao.setEnabled(False)
        botao.setText("Sócio cadastrado ✓")

    def _pendentes(self) -> list[tuple[list[dict], QComboBox, QPushButton]]:
        """Grupos que ainda não foram resolvidos — nem cadastrados como novos,
        nem apontados para um sócio existente."""
        return [
            grupo for grupo in self._grupos_ui
            if grupo[2].isEnabled() and grupo[1].currentData() is None
        ]

    def _recarregar_combos(self) -> None:
        """Repõe a lista de sócios em todos os combos preservando o que já
        estava escolhido — sem isso, quem foi cadastrado no lote não apareceria
        como opção nos cartões seguintes."""
        self._socios = repo.listar_socios(self.conn)
        for _linhas, combo, _botao in self._grupos_ui:
            escolhido = combo.currentData()
            self._preencher_combo_socios(combo)
            indice = combo.findData(escolhido) if escolhido is not None else -1
            combo.setCurrentIndex(indice if indice >= 0 else 0)

    def _cadastrar_todos(self) -> None:
        pendentes = self._pendentes()
        if not pendentes:
            QMessageBox.information(
                self, "Cadastrar todos",
                "Todos os sócios desta lista já foram resolvidos — cadastrados ou "
                "vinculados a um cadastro existente.",
            )
            return

        resposta = QMessageBox.question(
            self,
            "Cadastrar todos como novos sócios",
            f"Cadastrar {len(pendentes)} sócio(s) novo(s) de uma vez, com o nome e o "
            "CPF/CNPJ que vieram no arquivo, e vinculá-los às empresas indicadas?\n\n"
            "Os que você já resolveu à mão não são tocados.",
        )
        if resposta != QMessageBox.Yes:
            return

        criados: list[tuple[QComboBox, QPushButton, int]] = []
        erros: list[str] = []
        for linhas, combo, botao in pendentes:
            representante = linhas[0]
            try:
                novo_id = repo.salvar_socio(
                    self.conn,
                    Socio(
                        id=None,
                        nome=representante["socio_nome"],
                        cpf=representante["socio_cpf"] or "",
                        tipo_pessoa=representante.get("tipo_pessoa", "fisica"),
                    ),
                )
            except ValueError as exc:
                # Um CPF repetido no arquivo não pode abortar o lote inteiro:
                # anota, segue, e mostra tudo junto no fim.
                erros.append(f"{representante['socio_nome']}: {exc}")
                continue
            criados.append((combo, botao, novo_id))

        self._recarregar_combos()
        for combo, botao, novo_id in criados:
            indice = combo.findData(novo_id)
            combo.setCurrentIndex(indice if indice >= 0 else 0)
            botao.setEnabled(False)
            botao.setText("Sócio cadastrado ✓")

        if erros:
            detalhe = "\n".join(erros[:8])
            if len(erros) > 8:
                detalhe += f"\n(e mais {len(erros) - 8})"
            QMessageBox.warning(
                self, "Alguns sócios não foram cadastrados",
                f"{len(criados)} cadastrado(s). {len(erros)} não deu(ram) certo:\n\n{detalhe}",
            )

    def resolvidos(self) -> list[dict]:
        """Pendências que a pessoa confirmou, já com socio_id definido —
        prontas pra passar direto pra repo.aplicar_importacao_cadastro. Cada
        grupo resolvido expande de volta pra uma entrada por linha/empresa."""
        resultado = []
        for linhas, combo, _botao in self._grupos_ui:
            socio_id = combo.currentData()
            if socio_id is None:
                continue
            for pendencia in linhas:
                resultado.append({**pendencia, "socio_id": socio_id})
        return resultado


class _DialogoPrevia(QDialog):
    """As primeiras linhas já lidas pelo layout, como o sistema as entendeu.

    Trocar uma letra é fácil, e o estrago aparece tarde — o CNPJ gravado no
    lugar do capital social só chama atenção meses depois. Ver a primeira
    linha interpretada custa um instante e é a diferença entre configurar o
    layout no escuro e conferir antes de aplicar."""

    def __init__(self, cabecalhos: list[str], linhas: list[list[str]], total: int,
                 somente_conferir: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conferir leitura da planilha" if somente_conferir else "Confirmar importação")
        self.setMinimumSize(820, 420)

        if total:
            resumo = (
                f"{total} linha(s) reconhecidas. Abaixo, as {len(linhas)} primeiras, "
                "já com cada coluna no campo em que vai entrar."
            )
        else:
            resumo = (
                "Nenhuma linha foi reconhecida. Confira a linha em que os dados começam "
                "e a letra da coluna do nome da empresa — sem ela, a linha é ignorada."
            )
        aviso = QLabel(resumo)
        aviso.setWordWrap(True)
        aviso.setProperty("role", "subtitulo")

        tabela = TabelaLista(len(linhas), len(cabecalhos), coluna_flexivel=1)
        tabela.setHorizontalHeaderLabels(cabecalhos)
        tabela.verticalHeader().setVisible(False)
        tabela.setEditTriggers(QTableWidget.NoEditTriggers)
        tabela.setSelectionMode(QTableWidget.NoSelection)
        # Sem foco: a tabela é só para ler, e a moldura de célula atual faria
        # parecer que dá para editar o que está ali.
        tabela.setFocusPolicy(Qt.NoFocus)
        for i, linha in enumerate(linhas):
            for j, valor in enumerate(linha):
                tabela.setItem(i, j, QTableWidgetItem(valor))
        tabela.ajustar_colunas()

        if somente_conferir:
            botoes = QDialogButtonBox(QDialogButtonBox.Close)
            botoes.rejected.connect(self.reject)
        else:
            botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            ok = botoes.button(QDialogButtonBox.Ok)
            ok.setText("Importar estas linhas")
            ok.setEnabled(bool(total))
            botoes.accepted.connect(self.accept)
            botoes.rejected.connect(self.reject)

        coluna = QVBoxLayout(self)
        coluna.addWidget(aviso)
        coluna.addWidget(tabela, 1)
        coluna.addWidget(botoes)


class ImportacaoCadastroView(QWidget):
    """Importação e exportação de cadastro em massa.

    A tela gira em torno de um conceito só, o <b>formato</b>: ou um modelo do
    sistema, cujas colunas são reconhecidas pelo cabeçalho, ou um layout
    configurado pela pessoa, que diz por letra onde está cada informação na
    planilha daquela origem. O formato escolhido vale para os dois lados —
    exporta no mesmo desenho em que importa —, porque o caso real é um ciclo:
    o arquivo sai do outro sistema, entra aqui, e às vezes precisa voltar."""

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        self.editor = EditorLayout()
        self.editor.alterado.connect(self._ao_editar_layout)

        corpo = QWidget()
        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(0, 0, 8, 0)
        coluna.setSpacing(14)
        coluna.addWidget(self._montar_cabecalho())
        coluna.addWidget(self._montar_card_formato())
        coluna.addWidget(self._montar_card_layout())
        coluna.addWidget(self._montar_card_acoes())
        coluna.addStretch()

        # A grade de colunas é alta; sem rolagem a tela fica inutilizável em
        # notebook de tela baixa, que é onde ela vai ser usada.
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(corpo)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.addWidget(area)

        self._recarregar_formatos(selecionar=preferencias.obter(_CHAVE_FORMATO))

    # ------------------------------------------------------------ montagem --
    def _montar_cabecalho(self) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        col = QVBoxLayout(card)
        col.setContentsMargins(18, 14, 18, 16)
        col.setSpacing(6)

        titulo = QLabel("Importação e exportação de cadastro")
        titulo.setProperty("role", "secao")
        explicacao = QLabel(
            "Cadastre empresas, sócios, vínculos e distribuição de uma vez, a partir de uma "
            "planilha sua ou do relatório de sócios de outro sistema — em PDF ou em Excel. "
            "A empresa é reconhecida pelo nº, "
            "CNPJ ou nome e é criada se ainda não existir; o sócio é reconhecido pelo CPF e "
            "<b>nunca é criado sem sua confirmação</b>. O que já está cadastrado não é duplicado: "
            "vínculo que já existe é ignorado, e só entra o que é novo."
        )
        explicacao.setWordWrap(True)
        explicacao.setProperty("role", "subtitulo")
        col.addWidget(titulo)
        col.addWidget(explicacao)
        return card

    def _montar_card_formato(self) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        col = QVBoxLayout(card)
        col.setContentsMargins(18, 14, 18, 16)
        col.setSpacing(8)

        titulo = QLabel("Formato da planilha")
        titulo.setProperty("role", "secao")
        col.addWidget(titulo)

        self.formato = QComboBox()
        self.formato.setMinimumWidth(320)
        self.formato.currentIndexChanged.connect(self._ao_trocar_formato)

        self.btn_novo_layout = QPushButton("Novo layout")
        self.btn_novo_layout.setToolTip("Configurar do zero o desenho de uma planilha de outra origem.")
        self.btn_novo_layout.clicked.connect(self._novo_layout)

        self.btn_duplicar = QPushButton("Duplicar como layout")
        self.btn_duplicar.setToolTip(
            "Cria um layout já preenchido a partir do formato selecionado — mais rápido do que "
            "digitar as dezesseis letras."
        )
        self.btn_duplicar.clicked.connect(self._duplicar_como_layout)

        self.btn_excluir_layout = QPushButton("Excluir layout")
        self.btn_excluir_layout.setProperty("role", "perigo")
        self.btn_excluir_layout.clicked.connect(self._excluir_layout)

        linha = QHBoxLayout()
        linha.setSpacing(8)
        linha.addWidget(QLabel("Formato:"))
        linha.addWidget(self.formato, 1)
        linha.addWidget(self.btn_novo_layout)
        linha.addWidget(self.btn_duplicar)
        linha.addWidget(self.btn_excluir_layout)
        col.addLayout(linha)

        self.descricao_formato = QLabel()
        self.descricao_formato.setWordWrap(True)
        self.descricao_formato.setProperty("role", "subtitulo")
        col.addWidget(self.descricao_formato)
        return card

    def _montar_card_layout(self) -> QWidget:
        self.card_layout = QFrame()
        self.card_layout.setProperty("role", "card")
        col = QVBoxLayout(self.card_layout)
        col.setContentsMargins(18, 14, 18, 16)
        col.setSpacing(10)

        titulo = QLabel("Colunas deste layout")
        titulo.setProperty("role", "secao")
        col.addWidget(titulo)
        col.addWidget(self.editor)

        self.btn_salvar_layout = QPushButton("Salvar layout")
        self.btn_salvar_layout.setProperty("role", "primario")
        self.btn_salvar_layout.clicked.connect(self._salvar_layout)

        self.btn_conferir = QPushButton("Conferir com uma planilha…")
        self.btn_conferir.setToolTip(
            "Abre uma planilha e mostra como o sistema leria as primeiras linhas com este "
            "layout — sem importar nada."
        )
        self.btn_conferir.clicked.connect(self._conferir_layout)

        self.aviso_layout = QLabel()
        self.aviso_layout.setWordWrap(True)
        self.aviso_layout.setProperty("role", "subtitulo")

        linha = QHBoxLayout()
        linha.setSpacing(8)
        linha.addWidget(self.btn_salvar_layout)
        linha.addWidget(self.btn_conferir)
        linha.addWidget(self.aviso_layout, 1)
        col.addLayout(linha)
        return self.card_layout

    def _montar_card_acoes(self) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        col = QVBoxLayout(card)
        col.setContentsMargins(18, 14, 18, 16)
        col.setSpacing(10)

        titulo = QLabel("Exportar e importar")
        titulo.setProperty("role", "secao")
        col.addWidget(titulo)

        self.btn_exportar_modelo = QPushButton("Exportar planilha em branco")
        self.btn_exportar_modelo.clicked.connect(self._exportar_modelo)

        self.btn_exportar_atual = QPushButton("Exportar cadastro atual")
        self.btn_exportar_atual.clicked.connect(self._exportar_atual)

        self.btn_importar = QPushButton("Importar planilha")
        self.btn_importar.setProperty("role", "primario")
        self.btn_importar.clicked.connect(self._importar_planilha)

        self.btn_importar_relatorio = QPushButton("Importar relatório de sócios")
        self.btn_importar_relatorio.setToolTip(
            "Lê o relatório \"Cadastro de Sócios\" emitido por outro sistema contábil — em "
            "PDF ou em planilha (.xls, .xlsx, .csv) — e traz empresas, sócios, participação "
            "e datas de entrada/saída. Cada empresa tocada ganha uma alteração contratual "
            "automática registrando a movimentação; pra lançar direto numa alteração já aberta "
            "de uma empresa só, use o botão de importar dentro do card dela, na aba Alterações."
        )
        self.btn_importar_relatorio.clicked.connect(self._importar_relatorio)

        linha = QHBoxLayout()
        linha.setSpacing(8)
        linha.addWidget(self.btn_exportar_modelo)
        linha.addWidget(self.btn_exportar_atual)
        linha.addSpacing(16)
        linha.addWidget(self.btn_importar)
        linha.addWidget(self.btn_importar_relatorio)
        linha.addStretch()
        col.addLayout(linha)

        self.resultado = QLabel("")
        self.resultado.setWordWrap(True)
        self.resultado.setProperty("role", "subtitulo")
        col.addWidget(self.resultado)
        return card

    # -------------------------------------------------------------- formato --
    def _recarregar_formatos(self, selecionar: str | None = None) -> None:
        """Modelos do sistema e layouts salvos na mesma lista: pra quem usa, os
        dois são "o formato do arquivo" — o que muda por dentro (cabeçalho ou
        posição da coluna) não é decisão de quem importa."""
        # A chave crua do combo, não o par (tipo, id) de _formato_atual: é ela
        # que o findData compara lá embaixo.
        anterior = selecionar or self.formato.currentData()
        self.formato.blockSignals(True)
        self.formato.clear()
        for modelo in MODELOS_CADASTRO:
            self.formato.addItem(f"Modelo do sistema · {modelo.nome}", f"modelo:{modelo.id}")
        layouts = repo.listar_layouts_importacao(self.conn)
        if layouts:
            self.formato.insertSeparator(self.formato.count())
            for layout in layouts:
                self.formato.addItem(f"Layout · {layout.nome}", f"layout:{layout.id}")
        self._layouts_salvos = {layout.id: layout for layout in layouts}

        indice = self.formato.findData(anterior) if anterior else -1
        self.formato.setCurrentIndex(indice if indice >= 0 else 0)
        self.formato.blockSignals(False)
        self._ao_trocar_formato()

    def atualizar(self) -> None:
        """Repõe a lista ao voltar pra tela — layout salvo noutra sessão (ou um
        banco restaurado de backup) não pode deixar a lista velha na frente de
        quem vai importar."""
        self._recarregar_formatos()

    def _formato_atual(self) -> tuple[str, str]:
        """(tipo, identificador) do que está selecionado — "modelo"/"layout"/"novo"."""
        chave = self.formato.currentData() or f"modelo:{MODELO_CADASTRO_PADRAO.id}"
        tipo, _, identificador = str(chave).partition(":")
        return tipo, identificador

    def _modo_layout(self) -> bool:
        return self._formato_atual()[0] in ("layout", "novo")

    def _modelo_escolhido(self):
        tipo, identificador = self._formato_atual()
        if tipo == "modelo":
            return modelo_cadastro(identificador)
        return MODELO_CADASTRO_PADRAO

    def _layout_escolhido(self) -> LayoutImportacao:
        """O que está na tela, não o que está gravado: se a pessoa mexeu numa
        letra e importou sem salvar, tem que valer o que ela está vendo."""
        return self.editor.layout_atual()

    def _ao_trocar_formato(self, *_args) -> None:
        tipo, identificador = self._formato_atual()
        if tipo != "novo":
            # Lembrar a escolha é mais do que conveniência: quem importa da
            # mesma origem todo mês encontraria a tela sempre no modelo
            # completo, e importar com o formato errado é silencioso.
            preferencias.salvar_chave(_CHAVE_FORMATO, f"{tipo}:{identificador}")
        if tipo == "layout":
            self.editor.carregar(self._layouts_salvos.get(int(identificador)))
        elif tipo != "novo":
            self.editor.limpar()

        e_layout = self._modo_layout()
        self.card_layout.setVisible(e_layout)
        self.btn_excluir_layout.setEnabled(tipo == "layout")
        self.btn_duplicar.setEnabled(tipo != "novo")

        if e_layout:
            layout = self._layout_escolhido()
            self.descricao_formato.setText(
                "Layout configurado por você: as colunas são lidas pela <b>posição</b> "
                f"(letra), não pelo cabeçalho. {layout.resumo()}."
            )
        else:
            modelo = self._modelo_escolhido()
            self.descricao_formato.setText(
                f"{modelo.descricao}  ({len(modelo.colunas)} colunas, reconhecidas pelo "
                "cabeçalho da planilha.)"
            )
        self._atualizar_aviso_layout()

    def _ao_editar_layout(self) -> None:
        self._atualizar_aviso_layout()

    def _atualizar_aviso_layout(self) -> None:
        if not self._modo_layout():
            return
        layout = self._layout_escolhido()
        erros = validar_layout(layout)
        if erros:
            self.aviso_layout.setText("⚠ " + erros[0])
        elif layout.id is None:
            self.aviso_layout.setText("Layout novo — salve para reaproveitá-lo depois.")
        else:
            salvo = self._layouts_salvos.get(layout.id)
            alterado = salvo is not None and (
                salvo.colunas != layout.colunas
                or salvo.linha_inicial != layout.linha_inicial
                or salvo.nome != layout.nome
            )
            self.aviso_layout.setText(
                "Há alterações não salvas — elas já valem para importar e exportar agora."
                if alterado else f"Salvo · {layout.resumo()}."
            )

    # --------------------------------------------------------- ações layout --
    def _novo_layout(self) -> None:
        self.formato.blockSignals(True)
        self.formato.addItem("Layout novo (não salvo)", "novo:")
        self.formato.setCurrentIndex(self.formato.count() - 1)
        self.formato.blockSignals(False)
        self.editor.limpar()
        self._ao_trocar_formato()
        self.editor.primeiro_campo().setFocus()

    def _duplicar_como_layout(self) -> None:
        tipo, _identificador = self._formato_atual()
        if tipo == "modelo":
            base = layout_do_modelo(self._modelo_escolhido())
        else:
            base = self._layout_escolhido()
            base = LayoutImportacao(
                nome=f"Cópia de {base.nome}", colunas=dict(base.colunas), linha_inicial=base.linha_inicial
            )
        base.id = None
        self.formato.blockSignals(True)
        self.formato.addItem("Layout novo (não salvo)", "novo:")
        self.formato.setCurrentIndex(self.formato.count() - 1)
        self.formato.blockSignals(False)
        self.editor.carregar(base)
        self._ao_trocar_formato()
        self.editor.primeiro_campo().setFocus()

    def _salvar_layout(self) -> None:
        layout = self._layout_escolhido()
        try:
            novo_id = repo.salvar_layout_importacao(self.conn, layout)
        except (LayoutInvalido, ValueError) as exc:
            QMessageBox.warning(self, "Layout incompleto", str(exc))
            return
        self.editor.definir_id(novo_id)
        self._recarregar_formatos(selecionar=f"layout:{novo_id}")
        self.resultado.setText(f'Layout "{layout.nome}" salvo.')

    def _excluir_layout(self) -> None:
        tipo, identificador = self._formato_atual()
        if tipo != "layout":
            return
        layout = self._layouts_salvos.get(int(identificador))
        if layout is None:
            return
        resposta = QMessageBox.question(
            self,
            "Excluir layout",
            f'Excluir o layout "{layout.nome}"?\n\nO que já foi importado com ele continua '
            "no cadastro — só a configuração de colunas é apagada.",
        )
        if resposta != QMessageBox.Yes:
            return
        repo.excluir_layout_importacao(self.conn, layout.id)
        self._recarregar_formatos(selecionar=f"modelo:{MODELO_CADASTRO_PADRAO.id}")
        self.resultado.setText(f'Layout "{layout.nome}" excluído.')

    def _conferir_layout(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Conferir leitura da planilha", "", "Planilhas (*.xlsx *.csv)"
        )
        if not caminho:
            return
        self._mostrar_previa(Path(caminho), somente_conferir=True)

    def _mostrar_previa(self, caminho: Path, somente_conferir: bool) -> bool:
        """Devolve True quando a pessoa confirmou a importação."""
        layout = self._layout_escolhido()
        try:
            with ocupado(self, "Lendo a planilha", f"Lendo {caminho.name} pelo layout…"):
                linhas = importar_com_layout(caminho, layout)
                amostra = previa(caminho, layout)
        except LayoutInvalido as exc:
            QMessageBox.warning(self, "Layout incompleto", str(exc))
            return False
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao ler a planilha", str(exc))
            return False
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao abrir arquivo", str(exc))
            return False

        cabecalhos = [ROTULOS_CAMPOS[campo] for campo in layout.campos_mapeados()]
        dialogo = _DialogoPrevia(cabecalhos, amostra, len(linhas), somente_conferir, self)
        aceitou = dialogo.exec() == QDialog.Accepted
        if aceitou and not somente_conferir:
            self._aplicar_linhas(linhas, "Importar planilha")
        return aceitou

    # ------------------------------------------------------------- exportar --
    def _nome_sugerido(self, prefixo: str) -> str:
        if self._modo_layout():
            apelido = "".join(c if c.isalnum() else "_" for c in self._layout_escolhido().nome).strip("_")
            return f"{prefixo}_{apelido.lower() or 'layout'}.xlsx"
        return f"{prefixo}_{self._formato_atual()[1]}.xlsx"

    def _escolher_destino(self, titulo: str, sugestao: str) -> Path | None:
        caminho, _ = QFileDialog.getSaveFileName(self, titulo, sugestao, "Planilha Excel (*.xlsx)")
        if not caminho:
            return None
        if not caminho.lower().endswith(".xlsx"):
            caminho += ".xlsx"
        return Path(caminho)

    def _exportar_modelo(self) -> None:
        destino = self._escolher_destino("Exportar planilha em branco", self._nome_sugerido("modelo"))
        if destino is None:
            return
        if self._modo_layout():
            if not self._exportar_no_layout(destino, []):
                return
            QMessageBox.information(
                self,
                "Planilha exportada",
                f"Planilha em branco no seu layout, salva em:\n{destino}\n\n"
                "Cada campo já está na coluna que você configurou.",
            )
            return
        modelo = self._modelo_escolhido()
        with ocupado(self, "Exportar modelo", f"Gerando {destino.name}…"):
            exportar_modelo_cadastro(destino, modelo=modelo)
        QMessageBox.information(
            self,
            "Modelo exportado",
            f"Modelo \"{modelo.nome}\" salvo em:\n{destino}\n\n"
            "A aba \"Exemplo\" da planilha mostra o preenchimento com dados fictícios.",
        )

    def _exportar_atual(self) -> None:
        destino = self._escolher_destino("Exportar cadastro atual", self._nome_sugerido("cadastro_atual"))
        if destino is None:
            return
        so_empresas = (
            not self._layout_escolhido().colunas.get("socio_nome")
            if self._modo_layout()
            else self._modelo_escolhido().uma_linha_por_empresa
        )
        with ocupado(self, "Exportar cadastro", "Reunindo empresas e sócios…") as espera:
            linhas = self._linhas_do_cadastro(so_empresas)
            espera.dizer(f"Gravando {len(linhas)} linha(s) em {destino.name}…")
            QApplication.processEvents()
            if self._modo_layout():
                if not self._exportar_no_layout(destino, linhas):
                    return
            else:
                exportar_modelo_cadastro(destino, linhas, modelo=self._modelo_escolhido())
        QMessageBox.information(self, "Cadastro exportado", f"{len(linhas)} linha(s) salvas em:\n{destino}")

    def _exportar_no_layout(self, destino: Path, linhas: list[dict]) -> bool:
        try:
            exportar_com_layout(destino, linhas, self._layout_escolhido())
        except LayoutInvalido as exc:
            QMessageBox.warning(self, "Layout incompleto", str(exc))
            return False
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao salvar arquivo", str(exc))
            return False
        return True

    def _linhas_do_cadastro(self, so_empresas: bool) -> list[dict]:
        """O cadastro de hoje no formato de linha da importação — empresa
        repetida uma vez por sócio ativo. Empresa sem nenhum sócio ativo entra
        assim mesmo: ela existe, e some do arquivo seria pior."""
        socios_por_id = {s.id: s for s in repo.listar_socios(self.conn)}
        linhas = []
        for empresa in repo.listar_empresas(self.conn):
            dados_empresa = {
                "numero_chamada": empresa.numero_chamada,
                "empresa_nome": empresa.nome,
                "cnpj": empresa.cnpj,
                "capital_social": empresa.capital_social,
                "quantidade_cotas": empresa.quantidade_cotas,
            }
            vinculos = [v for v in repo.listar_vinculos_empresa(self.conn, empresa.id) if v.data_saida is None]
            if not vinculos or so_empresas:
                # Sem coluna de sócio, uma linha por vínculo viraria a mesma
                # empresa repetida sem nada que as diferencie.
                linhas.append(dados_empresa)
                continue
            for v in vinculos:
                socio = socios_por_id.get(v.socio_id)
                linhas.append(
                    {
                        **dados_empresa,
                        "socio_nome": socio.nome if socio else "",
                        "socio_cpf": socio.cpf if socio else "",
                        "tipo_pessoa": socio.tipo_pessoa if socio else "fisica",
                        "percentual_capital": v.percentual_capital,
                        "cotas_socio": v.quantidade_cotas,
                        "data_entrada": v.data_entrada,
                    }
                )
        return linhas

    # ------------------------------------------------------------- importar --
    def _importar_planilha(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Importar planilha de cadastro", "", "Planilhas (*.xlsx *.csv)"
        )
        if not caminho:
            return

        # Com layout, a prévia é parte do caminho: ela é a confirmação, e é
        # onde um erro de letra aparece antes de virar dado gravado.
        if self._modo_layout():
            self._mostrar_previa(Path(caminho), somente_conferir=False)
            return

        try:
            with ocupado(self, "Importar planilha", f"Lendo {Path(caminho).name}…"):
                linhas_importadas = importar_cadastro(Path(caminho))
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao importar", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao abrir arquivo", str(exc))
            return

        if not linhas_importadas:
            QMessageBox.information(self, "Importar planilha", "A planilha não tem nenhuma linha com dados.")
            return

        self._aplicar_linhas(linhas_importadas, "Importar planilha")

    def _importar_relatorio(self) -> None:
        """Importa o relatório "Cadastro de Sócios" de outro sistema contábil,
        em PDF ou em planilha.

        Não usa layout de colunas: o relatório tem forma própria, e lê-lo é
        trabalho de reconhecer o texto, não de apontar coluna. Só a extração
        muda conforme o arquivo — daí pra frente as linhas seguem pelo mesmo
        caminho de sempre."""
        # O primeiro filtro é o que abre por padrão e mostra os quatro tipos
        # juntos — quem não sabe em que formato o relatório foi salvo acha o
        # arquivo assim mesmo. Os outros ficam na lista para quem quiser
        # separar PDF de planilha numa pasta cheia.
        caminho, _ = QFileDialog.getOpenFileName(
            self,
            "Importar relatório de sócios",
            "",
            "Relatório de sócios — PDF ou Excel (*.pdf *.xls *.xlsx *.csv);;"
            "Relatório em PDF (*.pdf);;"
            "Planilha do Excel (*.xls *.xlsx);;"
            "Texto separado por ponto e vírgula (*.csv);;"
            "Todos os arquivos (*)",
        )
        if not caminho:
            return
        try:
            with ocupado(self, "Importar relatório", f"Lendo {Path(caminho).name}…"):
                leitura = ler_relatorio_arquivo(Path(caminho))
        except (PdfIlegivel, XlsIlegivel, RelatorioInvalido) as exc:
            QMessageBox.warning(self, "Não consegui ler o relatório", str(exc))
            return
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao ler o relatório", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao abrir arquivo", str(exc))
            return

        empresas = leitura.empresas
        linhas_importadas = linhas_para_importacao(empresas)
        if not linhas_importadas:
            QMessageBox.information(
                self,
                "Importar relatório de sócios",
                "Li o relatório, mas ele não tem nenhum sócio listado.",
            )
            return

        # O relatório é um retrato do quadro societário, não do cadastro
        # inteiro: dizer isso antes evita a surpresa de abrir a empresa
        # importada e achar os campos fiscais em branco.
        nomes = "\n".join(f"• {e.numero} - {e.nome}" for e in empresas[:8])
        if len(empresas) > 8:
            nomes += f"\n• (e mais {len(empresas) - 8} empresa(s))"

        # Linha que parecia sócio e não foi entendida é dita na cara: importar
        # 17 de 19 sem avisar é o pior desfecho possível, porque o que falta
        # só apareceria muito depois, se aparecesse.
        alerta = ""
        if leitura.ignoradas:
            exemplos = "\n".join(f"   {linha[:90]}" for linha in leitura.ignoradas[:3])
            if len(leitura.ignoradas) > 3:
                exemplos += f"\n   (e mais {len(leitura.ignoradas) - 3})"
            alerta = (
                f"\n\n⚠ {len(leitura.ignoradas)} linha(s) com cara de sócio não foram "
                f"reconhecidas e ficarão de fora:\n{exemplos}"
            )

        confirmar = QMessageBox.question(
            self,
            "Importar relatório de sócios",
            f"Li {resumo_do_relatorio(empresas)}:\n\n{nomes}\n\n"
            "O relatório traz sócio, CPF/CNPJ, participação e datas de entrada e saída. "
            "Ele não traz CNPJ da empresa, capital social nem quantidade de cotas — "
            "empresa criada por aqui nasce com esses campos em branco, para você "
            f"completar depois no cadastro.{alerta}\n\nSeguir com a importação?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirmar != QMessageBox.Yes:
            return

        # Relatório de uma empresa só que já está no cadastro é o caso em que
        # dá pra perguntar onde a movimentação entra — e é o caso comum, o
        # relatório tirado de uma empresa específica. Com várias empresas no
        # arquivo (ou com empresa que ainda vai ser criada) não há o que
        # escolher: cada uma ganha a sua alteração automática.
        alteracao_id = None
        dar_baixa = False
        documentos = {
            repo.normalizar_documento(l["socio_cpf"]) for l in linhas_importadas if l.get("socio_cpf")
        }
        empresa_unica = self._empresa_cadastrada_unica(empresas)
        if empresa_unica is not None:
            data_provavel = empresas[0].data_quadro or dt.date.today().isoformat()
            destino = DialogoDestinoAlteracao(
                self.conn,
                empresa_unica.id,
                f'Li {resumo_do_relatorio(empresas)} para "{empresa_unica.nome}".',
                data_sugerida=empresas[0].data_quadro,
                ausentes=[
                    socio.nome
                    for _v, socio in repo.vinculos_ativos_fora_da_lista(
                        self.conn, empresa_unica.id, documentos, data_provavel
                    )
                ],
                parent=self,
            )
            if destino.exec() != QDialog.Accepted:
                return
            try:
                alteracao_id = destino.resolver()
            except ValueError as exc:
                QMessageBox.warning(self, "Não foi possível abrir a alteração", str(exc))
                return
            dar_baixa = destino.dar_baixa_ausentes.isChecked()

        self._aplicar_linhas(
            linhas_importadas,
            "Importar relatório de sócios",
            alteracao_id=alteracao_id,
            criar_alteracao_por_empresa=alteracao_id is None,
            atualizar_participacao=True,
        )

        if dar_baixa and alteracao_id is not None:
            alteracao = repo.buscar_alteracao(self.conn, alteracao_id)
            try:
                baixas = repo.encerrar_vinculos_fora_da_lista(
                    self.conn, empresa_unica.id, documentos, alteracao.data, alteracao_id
                )
            except ValueError as exc:
                QMessageBox.warning(self, "Erro ao dar baixa nos ausentes", str(exc))
                return
            if baixas:
                QMessageBox.information(
                    self,
                    "Saídas registradas",
                    f"{len(baixas)} sócio(s) não apareciam no relatório e receberam "
                    f"saída em {alteracao.data}:\n\n" + ", ".join(baixas),
                )

    def _empresa_cadastrada_unica(self, empresas: list):
        """A empresa do cadastro quando o relatório traz uma só e ela já
        existe aqui — senão None, e o caminho segue sem escolha de destino."""
        if len(empresas) != 1:
            return None
        do_relatorio = empresas[0]
        for empresa in repo.listar_empresas(self.conn):
            numero_bate = (
                do_relatorio.numero
                and empresa.numero_chamada
                and do_relatorio.numero.strip() == empresa.numero_chamada.strip()
            )
            cnpj_bate = (
                do_relatorio.cnpj
                and empresa.cnpj
                and repo.normalizar_documento(do_relatorio.cnpj) == repo.normalizar_documento(empresa.cnpj)
            )
            if numero_bate or cnpj_bate or do_relatorio.nome.strip().lower() == empresa.nome.strip().lower():
                return empresa
        return None

    def _aplicar_linhas(
        self,
        linhas_importadas: list[dict],
        titulo: str,
        *,
        alteracao_id: int | None = None,
        criar_alteracao_por_empresa: bool = False,
        atualizar_participacao: bool = False,
    ) -> None:
        """Casa as linhas contra o cadastro, resolve pendências com a pessoa e
        aplica. É o mesmo caminho para planilha, layout e relatório em PDF — o
        que muda entre eles é só de onde as linhas vieram.

        `criar_alteracao_por_empresa` só vale pro relatório de sócios: é
        movimentação de quadro societário, então cada empresa tocada ganha
        sua alteração contratual automática. Planilha de cadastro comum não
        passa por aqui como movimentação — fica como estava."""
        resultado = repo.preparar_importacao_cadastro(self.conn, linhas_importadas)
        prontas = list(resultado["prontas"])
        pendencias = resultado["pendencias"]
        conflitos = resultado["conflitos"]

        # Conflito é o arquivo se contradizendo (nº da empresa e CNPJ de
        # empresas diferentes) — não é escolha a fazer, é erro a corrigir,
        # então é avisado antes de aplicar o resto.
        if conflitos:
            detalhe = "\n\n".join(
                f'Linha de "{c["empresa_nome"]}" / "{c["socio_nome"]}":\n{c["aviso"]}' for c in conflitos[:5]
            )
            if len(conflitos) > 5:
                detalhe += f"\n\n(e mais {len(conflitos) - 5} linha(s) com o mesmo tipo de problema)"
            QMessageBox.warning(
                self,
                "Linhas com dados contraditórios",
                f"{len(conflitos)} linha(s) não serão importadas:\n\n{detalhe}",
            )

        if pendencias:
            dialogo = DialogoRevisaoCadastro(self.conn, pendencias, self)
            if dialogo.exec() == QDialog.Accepted:
                prontas.extend(dialogo.resolvidos())

        if not prontas:
            QMessageBox.information(
                self,
                titulo,
                "Nenhuma linha foi aplicada."
                + (" Corrija os dados contraditórios apontados acima." if conflitos else ""),
            )
            return

        try:
            with Progresso(self, titulo, len(prontas), "Gravando o que foi importado…") as barra:
                aplicado = repo.aplicar_importacao_cadastro(
                    self.conn,
                    prontas,
                    progresso=lambda feitas, total: barra.passo(
                        feitas, total, f"Gravando linha {feitas} de {total}…"
                    ),
                    alteracao_id=alteracao_id,
                    criar_alteracao_por_empresa=criar_alteracao_por_empresa,
                    atualizar_participacao=atualizar_participacao,
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao importar", str(exc))
            return

        nao_aplicadas = len(linhas_importadas) - len(prontas)
        resumo = (
            f"{aplicado['empresas_criadas']} empresa(s) nova(s) · "
            f"{aplicado['vinculos_criados']} vínculo(s) criado(s) · "
            f"{aplicado['vinculos_ja_existentes']} já existiam (ignorados) · "
            f"{aplicado['vinculos_encerrados']} vínculo(s) com saída registrada · "
            f"{aplicado['distribuicoes_lancadas']} distribuição(ões) lançada(s)."
        )
        if aplicado.get("participacoes_atualizadas"):
            resumo += f"\n{aplicado['participacoes_atualizadas']} participação(ões) atualizada(s) pelo relatório."
        if aplicado.get("participacoes_nao_atualizadas"):
            resumo += (
                f"\n⚠ {aplicado['participacoes_nao_atualizadas']} participação(ões) não foram atualizadas: "
                "a data da alteração é anterior à entrada desses sócios."
            )
        if aplicado.get("alteracoes_criadas"):
            qtd = aplicado["alteracoes_criadas"]
            resumo += (
                "\n1 alteração contratual criada automaticamente pra registrar a movimentação."
                if qtd == 1
                else f"\n{qtd} alterações contratuais criadas automaticamente pra registrar a movimentação."
            )
        if nao_aplicadas > 0:
            resumo += f"\n{nao_aplicadas} linha(s) não foram aplicadas"
            resumo += f" ({len(conflitos)} por dados contraditórios)." if conflitos else "."
        self.resultado.setText(resumo)
        QMessageBox.information(self, "Importação concluída", resumo)
