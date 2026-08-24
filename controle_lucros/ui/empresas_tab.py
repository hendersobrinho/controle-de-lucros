from __future__ import annotations

from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QLineEdit

from .. import repositories as repo
from ..models import Empresa
from .common import CrudTab, cnpj_valido_ou_vazio, configurar_campo_cnpj, formatar_numero, formatar_valor_br


class EmpresasTab(CrudTab):
    colunas = [
        ("Nº chamada", "numero_chamada"),
        ("Nome", "nome"),
        ("CNPJ", "cnpj"),
        ("Capital social", "capital_social"),
        ("Cotas", "quantidade_cotas"),
    ]

    def montar_formulario(self, form_layout: QFormLayout) -> None:
        self.numero_chamada = QLineEdit()
        self.numero_chamada.setProperty("role", "mono")
        self.numero_chamada.setPlaceholderText("ex.: 042")

        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Razão social")

        self.cnpj = QLineEdit()
        self.cnpj.setProperty("role", "mono")
        configurar_campo_cnpj(self.cnpj)
        self.cnpj.setPlaceholderText("AA.AAA.AAA/AAAA-DV")

        self.capital = QDoubleSpinBox()
        self.capital.setMaximum(1_000_000_000)
        self.capital.setDecimals(2)
        self.capital.setPrefix("R$ ")
        formatar_numero(self.capital)

        self.cotas = QDoubleSpinBox()
        self.cotas.setMaximum(1_000_000_000)
        self.cotas.setDecimals(0)
        formatar_numero(self.cotas)

        form_layout.addRow("Nº de chamada", self.numero_chamada)
        form_layout.addRow("Nome da empresa", self.nome)
        form_layout.addRow("CNPJ", self.cnpj)
        form_layout.addRow("Capital social (fundação)", self.capital)
        form_layout.addRow("Quantidade de cotas (fundação)", self.cotas)

    def listar(self):
        return repo.listar_empresas(self.conn)

    def placeholder_busca(self) -> str:
        return "Buscar por nome ou nº de chamada…"

    def corresponde_busca(self, registro: Empresa, termo: str) -> bool:
        return termo in registro.nome.lower() or termo in (registro.numero_chamada or "").lower()

    def valor_coluna(self, registro: Empresa, attr: str):
        if attr == "capital_social":
            return f"R$ {formatar_valor_br(registro.capital_social)}"
        if attr == "quantidade_cotas":
            return formatar_valor_br(registro.quantidade_cotas, 0)
        return getattr(registro, attr, None)

    def carregar_form(self, e: Empresa) -> None:
        self.numero_chamada.setText(e.numero_chamada or "")
        self.nome.setText(e.nome)
        self.cnpj.setText(e.cnpj or "")
        self.capital.setValue(e.capital_social)
        self.cotas.setValue(e.quantidade_cotas)

    def ler_form(self, id_atual):
        return Empresa(
            id=id_atual,
            numero_chamada=self.numero_chamada.text().strip(),
            nome=self.nome.text().strip(),
            cnpj=cnpj_valido_ou_vazio(self.cnpj),
            capital_social=self.capital.value(),
            quantidade_cotas=self.cotas.value(),
        )

    def limpar_form(self) -> None:
        self.numero_chamada.clear()
        self.nome.clear()
        self.cnpj.clear()
        self.capital.setValue(0)
        self.cotas.setValue(0)

    def salvar_registro(self, registro: Empresa) -> None:
        if not registro.nome:
            raise ValueError("Informe o nome da empresa.")
        if not registro.numero_chamada:
            raise ValueError("Informe o número de chamada.")
        repo.salvar_empresa(self.conn, registro)

    def excluir_registro(self, id_) -> None:
        repo.excluir_empresa(self.conn, id_)
