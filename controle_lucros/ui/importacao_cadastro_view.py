"""Tela de importação em massa de cadastro: sobe uma planilha com empresa +
sócio + vínculo numa linha só e aplica tudo de uma vez — pensada pra dar
conta de uma base grande (~160+ empresas) sem digitar registro por registro
nas abas de Cadastro. Empresa é reconhecida por nº de chamada/CNPJ/nome e
resolve sozinha (baixo risco de duplicata); sócio é reconhecido por CPF/nome
e nunca criado sem confirmação — o mesmo sócio costuma aparecer em várias
empresas, e duplicar cadastro dele bagunçaria o histórico em todas elas."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..models import Socio
from ..planilha import exportar_modelo_cadastro, importar_cadastro
from .common import formatar_valor_br
from .theme import SAIU_FG


class _DialogoRevisaoCadastro(QDialog):
    """Uma pendência por sócio que não bateu com segurança contra o cadastro
    existente (CPF ausente ou nome ambíguo) — escolher um sócio já
    cadastrado ou criar um novo, sempre com confirmação humana antes de
    aplicar qualquer coisa. Quando o mesmo sócio novo aparece em várias
    linhas (várias empresas) da mesma planilha, agrupamos num cartão só —
    resolver uma vez já aplica a todas as empresas dele, em vez de pedir
    confirmação repetida pra "a mesma pessoa"."""

    def __init__(self, conn, pendencias: list[dict], parent=None):
        super().__init__(parent)
        self.conn = conn
        self._socios = repo.listar_socios(conn)
        self._grupos_ui: list[tuple[list[dict], QComboBox]] = []

        grupos: dict[str, list[dict]] = {}
        ordem: list[str] = []
        for pendencia in pendencias:
            cpf = pendencia["socio_cpf"].strip()
            chave = cpf if cpf else f"nome::{pendencia['socio_nome'].strip().lower()}"
            if chave not in grupos:
                grupos[chave] = []
                ordem.append(chave)
            grupos[chave].append(pendencia)

        self.setWindowTitle("Revisar sócios da planilha")
        self.setMinimumSize(700, 480)

        plural_socio = "sócio(s)" if len(ordem) != 1 else "sócio"
        aviso = QLabel(
            f"{len(ordem)} {plural_socio} da planilha ({len(pendencias)} linha(s) no total) não puderam ser "
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

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Aplicar selecionados")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(aviso)
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

        self._grupos_ui.append((linhas, combo))
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

    def resolvidos(self) -> list[dict]:
        """Pendências que a pessoa confirmou, já com socio_id definido —
        prontas pra passar direto pra repo.aplicar_importacao_cadastro. Cada
        grupo resolvido expande de volta pra uma entrada por linha/empresa."""
        resultado = []
        for linhas, combo in self._grupos_ui:
            socio_id = combo.currentData()
            if socio_id is None:
                continue
            for pendencia in linhas:
                resultado.append({**pendencia, "socio_id": socio_id})
        return resultado


class ImportacaoCadastroView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        titulo = QLabel("Importação em massa de cadastro")
        titulo.setProperty("role", "secao")

        explicacao = QLabel(
            "Cadastre empresas, sócios, vínculos e distribuição de uma vez a partir de uma planilha — uma "
            "linha por (empresa, sócio). A empresa é reconhecida pelo nº de chamada, CNPJ ou nome e é "
            "criada automaticamente se ainda não existir; o sócio é reconhecido pelo CPF ou nome e nunca é "
            "criado sem confirmação, pra nunca duplicar cadastro. Capital, cotas, percentual e data de "
            "entrada são obrigatórios; data de saída, ano base, valor distribuído, pró-labore e IRRF são "
            "opcionais — preencha só quem tiver saído da sociedade ou tiver uma distribuição daquele ano "
            "pra lançar junto. Comece exportando o modelo, preencha e importe de volta."
        )
        explicacao.setWordWrap(True)
        explicacao.setProperty("role", "subtitulo")

        self.btn_exportar_modelo = QPushButton("Exportar modelo (planilha em branco)")
        self.btn_exportar_modelo.clicked.connect(self._exportar_modelo)

        self.btn_exportar_atual = QPushButton("Exportar cadastro atual")
        self.btn_exportar_atual.clicked.connect(self._exportar_atual)

        self.btn_importar = QPushButton("Importar planilha")
        self.btn_importar.setProperty("role", "primario")
        self.btn_importar.clicked.connect(self._importar_planilha)

        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_exportar_modelo)
        botoes.addWidget(self.btn_exportar_atual)
        botoes.addWidget(self.btn_importar)
        botoes.addStretch()

        self.resultado = QLabel("")
        self.resultado.setWordWrap(True)
        self.resultado.setProperty("role", "subtitulo")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(titulo)
        layout.addWidget(explicacao)
        layout.addLayout(botoes)
        layout.addWidget(self.resultado)
        layout.addStretch()

    def atualizar(self) -> None:
        pass

    def _exportar_modelo(self) -> None:
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar modelo de cadastro", "modelo_cadastro.xlsx", "Planilha Excel (*.xlsx)"
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".xlsx"):
            caminho += ".xlsx"
        exportar_modelo_cadastro(Path(caminho))
        QMessageBox.information(self, "Modelo exportado", f"Modelo salvo em:\n{caminho}")

    def _exportar_atual(self) -> None:
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar cadastro atual", "cadastro_atual.xlsx", "Planilha Excel (*.xlsx)"
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".xlsx"):
            caminho += ".xlsx"

        socios_por_id = {s.id: s for s in repo.listar_socios(self.conn)}
        linhas = []
        for empresa in repo.listar_empresas(self.conn):
            vinculos = [v for v in repo.listar_vinculos_empresa(self.conn, empresa.id) if v.data_saida is None]
            if not vinculos:
                linhas.append(
                    {
                        "numero_chamada": empresa.numero_chamada,
                        "empresa_nome": empresa.nome,
                        "cnpj": empresa.cnpj,
                        "capital_social": empresa.capital_social,
                        "quantidade_cotas": empresa.quantidade_cotas,
                    }
                )
                continue
            for v in vinculos:
                socio = socios_por_id.get(v.socio_id)
                linhas.append(
                    {
                        "numero_chamada": empresa.numero_chamada,
                        "empresa_nome": empresa.nome,
                        "cnpj": empresa.cnpj,
                        "capital_social": empresa.capital_social,
                        "quantidade_cotas": empresa.quantidade_cotas,
                        "socio_nome": socio.nome if socio else "",
                        "socio_cpf": socio.cpf if socio else "",
                        "tipo_pessoa": socio.tipo_pessoa if socio else "fisica",
                        "percentual_capital": v.percentual_capital,
                        "cotas_socio": v.quantidade_cotas,
                        "data_entrada": v.data_entrada,
                    }
                )
        exportar_modelo_cadastro(Path(caminho), linhas)
        QMessageBox.information(self, "Cadastro exportado", f"{len(linhas)} linha(s) salvas em:\n{caminho}")

    def _importar_planilha(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Importar planilha de cadastro", "", "Planilhas (*.xlsx *.csv)"
        )
        if not caminho:
            return
        try:
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

        resultado = repo.preparar_importacao_cadastro(self.conn, linhas_importadas)
        prontas = list(resultado["prontas"])
        pendencias = resultado["pendencias"]

        if pendencias:
            dialogo = _DialogoRevisaoCadastro(self.conn, pendencias, self)
            if dialogo.exec() == QDialog.Accepted:
                prontas.extend(dialogo.resolvidos())

        if not prontas:
            QMessageBox.information(self, "Importar planilha", "Nenhuma linha foi aplicada.")
            return

        try:
            aplicado = repo.aplicar_importacao_cadastro(self.conn, prontas)
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
        if nao_aplicadas > 0:
            resumo += f"\n{nao_aplicadas} linha(s) não foram aplicadas."
        self.resultado.setText(resumo)
        QMessageBox.information(self, "Importação concluída", resumo)
