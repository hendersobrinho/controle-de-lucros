"""Tela de Empresas: a lista, a ficha só de leitura e a janela de cadastro.

O problema que o desenho antigo tinha, e que estes testes prendem: um
formulário sempre aberto ao lado da tabela, em que digitar por cima de um
registro selecionado ALTERAVA aquele registro em vez de criar outro. Agora
ver e editar são separados — a ficha só mostra, e mudar abre uma janela.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

from controle_lucros import repositories as repo
from controle_lucros.models import Empresa, Socio, VinculoSocietario
from controle_lucros.ui import empresas_tab as mod
from controle_lucros.ui.empresas_tab import DialogoEmpresa, EmpresasTab
from controle_lucros.ui.lista_fichas import PAPEL_DETALHE, PAPEL_MARCADOR


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture(autouse=True)
def avisos(monkeypatch):
    """QMessageBox.warning é modal: sem interceptar, um erro de validação
    dentro do teste trava a suíte inteira esperando um clique."""
    capturados = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: capturados.append(args[2]))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    return capturados


@pytest.fixture()
def empresas(conn):
    acme = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "11.222.333/0001-81", 100000, 1000))
    repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 50000, 500))
    fulano = repo.salvar_socio(conn, Socio(None, "FULANO DE TAL", "005.169.717-35"))
    repo.salvar_vinculo(conn, VinculoSocietario(None, acme, fulano, 60, 600, "2020-01-01", None, valor_capital=60000))
    return EmpresasTab(conn)


def _textos(widget) -> str:
    return " | ".join(r.text() for r in widget.findChildren(QLabel) if r.isVisibleTo(widget))


def _acme(empresas):
    return next(e for e in repo.listar_empresas(empresas.conn) if e.nome == "ACME LTDA")


# ------------------------------------------------------------- lista --


def test_lista_mostra_nome_numero_cnpj_e_socios(empresas):
    linhas = {empresas.lista.item(r).text(): empresas.lista.item(r) for r in range(empresas.lista.count())}
    assert linhas["ACME LTDA"].data(PAPEL_DETALHE) == "nº 001 · CNPJ 11.222.333/0001-81"
    assert linhas["ACME LTDA"].data(PAPEL_MARCADOR) == "1 sócio"
    assert linhas["BETA LTDA"].data(PAPEL_MARCADOR) == "sem sócios"
    assert empresas.contagem.text() == "2 empresas"


def test_busca_por_nome_numero_ou_cnpj(empresas):
    for termo in ("acme", "001", "11222333"):
        empresas.busca.setText(termo)
        assert [empresas.lista.item(r).text() for r in range(empresas.lista.count())] == ["ACME LTDA"], termo
    assert empresas.contagem.text() == "1 de 2 empresas"


# ------------------------------------------------------------- ficha --


def test_abre_sem_empresa_selecionada_e_convida_a_escolher(empresas):
    assert not empresas.painel_vazio.isHidden()
    assert empresas.rolagem.isHidden()
    assert not empresas.btn_editar.isEnabled()
    assert not empresas.btn_quadro.isEnabled()


def test_ficha_mostra_capital_valor_da_cota_e_quadro(empresas):
    empresas.lista.selectRow(0)  # ACME
    textos = _textos(empresas)
    assert "ACME LTDA" in textos
    assert "nº 001 · CNPJ 11.222.333/0001-81" in textos
    assert "R$ 100.000,00" in textos            # capital social
    assert "R$ 100,00" in textos                # valor da cota (capital ÷ cotas)
    assert "capital ÷ cotas" in textos
    assert "FULANO DE TAL" in textos
    assert "60,0000%" in textos
    assert "As participações somam 60,0000%, não 100%" in textos


def test_ficha_nao_deixa_editar_por_cima(empresas):
    """A ficha é só leitura: não há campo de texto nela."""
    from PySide6.QtWidgets import QLineEdit

    empresas.lista.selectRow(0)
    campos = [c for c in empresas.findChildren(QLineEdit) if c.isVisibleTo(empresas) and c is not empresas.busca]
    assert campos == []


def test_ficha_mostra_o_estado_vigente_e_a_fundacao(empresas):
    from controle_lucros.models import AlteracaoContratual

    acme = _acme(empresas)
    repo.salvar_alteracao(empresas.conn, AlteracaoContratual(
        None, acme.id, 1, "2024-05-01", "ACME LTDA", 200000, 2000, "Aumento de capital"))
    empresas.atualizar()
    empresas.selecionar_empresa(acme.id)
    textos = _textos(empresas)
    assert "R$ 200.000,00" in textos
    assert "Na fundação: R$ 100.000,00 em 1.000 cotas" in textos


def test_selecionar_avisa_a_tela_de_alteracoes(empresas):
    escolhidas = []
    empresas.definir_callback_selecao(lambda empresa: escolhidas.append(empresa.nome))
    empresas.lista.selectRow(1)
    assert escolhidas == ["BETA LTDA"]


# ---------------------------------------------- cadastro e edição --


def test_nova_empresa_pela_janela_de_cadastro(empresas, monkeypatch):
    def cadastrar(dialogo):
        dialogo.numero_chamada.setText("003")
        dialogo.nome.setText("GAMA LTDA")
        dialogo.capital.setValue(2_500)
        dialogo.cotas.setValue(250_000)  # cada cota: R$ 0,01
        dialogo._salvar()
        return dialogo.result()

    monkeypatch.setattr(DialogoEmpresa, "exec", cadastrar)
    empresas._nova_empresa()

    gama = next(e for e in repo.listar_empresas(empresas.conn) if e.nome == "GAMA LTDA")
    assert (gama.quantidade_cotas, gama.valor_cota, gama.capital_social) == (250_000, 0.01, 2_500)
    assert empresas._empresa_atual_id == gama.id  # já fica selecionada


def test_capital_e_digitado_direto_e_as_cotas_nao_o_apagam(empresas):
    """O capital digitado fica: informar as cotas depois só calcula o valor
    de cada cota (antes, refazia o capital por cima)."""
    dialogo = DialogoEmpresa(empresas.conn)
    dialogo.capital.setValue(5000)
    assert "cotas podem ficar em branco" in dialogo.conta.text()
    dialogo.cotas.setValue(1000)
    assert dialogo.capital.value() == 5000.0
    assert dialogo.valor_da_cota() == 5.0
    assert "Cada cota vale R$ 5,00" in dialogo.conta.text()


def test_cadastro_sem_numero_ou_nome_avisa(empresas, avisos):
    dialogo = DialogoEmpresa(empresas.conn)
    dialogo._salvar()
    assert avisos == ["Informe o nº da empresa."]
    dialogo.numero_chamada.setText("009")
    dialogo._salvar()
    assert avisos[-1] == "Informe a razão social da empresa."
    assert dialogo.result() != QDialog.Accepted


def test_editar_abre_com_os_dados_e_grava(empresas, monkeypatch):
    def renomear(dialogo):
        assert dialogo.nome.text() == "ACME LTDA"
        assert dialogo.cotas.text() == "1.000"
        dialogo.nome.setText("ACME COMERCIO LTDA")
        dialogo._salvar()
        return dialogo.result()

    monkeypatch.setattr(DialogoEmpresa, "exec", renomear)
    empresas.lista.selectRow(0)
    empresas.btn_editar.click()
    assert empresas.titulo_empresa.text() == "ACME COMERCIO LTDA"


def test_empresa_so_com_capital_grava_sem_valor_da_cota(empresas):
    """Sem cotas não há conta: o valor da cota fica em branco, em vez de um
    número inventado."""
    dialogo = DialogoEmpresa(empresas.conn)
    dialogo.numero_chamada.setText("004")
    dialogo.nome.setText("DELTA LTDA")
    dialogo.capital.setValue(80_000)
    empresa = dialogo.empresa_editada()
    assert (empresa.capital_social, empresa.quantidade_cotas, empresa.valor_cota) == (80_000, 0, None)


def test_excluir_empresa_diz_o_que_vai_junto_e_ja_vem_em_nao(empresas, monkeypatch):
    """A empresa leva junto tudo o que é dela: a pergunta diz o quê, e
    responder "Não" (o padrão) não apaga nada."""
    perguntas = []

    def responder(parent, titulo, texto, botoes=None, padrao=None):
        perguntas.append((texto, padrao))
        return QMessageBox.No

    monkeypatch.setattr(mod.QMessageBox, "warning", responder)
    acme = _acme(empresas)
    dialogo = DialogoEmpresa(empresas.conn, acme)
    dialogo._excluir()

    texto, padrao = perguntas[0]
    assert "1 vínculo(s) de sócio" in texto
    assert "sócios continuam cadastrados" in texto
    assert padrao == QMessageBox.No
    assert any(e.id == acme.id for e in repo.listar_empresas(empresas.conn))


def test_excluir_empresa_confirmado_some_da_lista(empresas, monkeypatch):
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)

    def excluir(dialogo):
        dialogo._excluir()
        return dialogo.result()

    monkeypatch.setattr(DialogoEmpresa, "exec", excluir)
    empresas.lista.selectRow(0)
    empresas._editar_empresa()

    assert [empresas.lista.item(r).text() for r in range(empresas.lista.count())] == ["BETA LTDA"]
    assert empresas._empresa_atual_id is None
    assert not empresas.painel_vazio.isHidden()


# ------------------------------------------------------- navegação --


def test_dois_cliques_no_socio_do_quadro_abre_o_socio(empresas):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    abertos = []
    empresas.ao_abrir_socio = abertos.append
    empresas.atualizar()
    empresas.lista.selectRow(0)
    (linha,) = empresas.findChildren(mod._LinhaQuadro)
    linha.mouseDoubleClickEvent(QMouseEvent(
        QEvent.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    fulano = next(s for s in repo.listar_socios(empresas.conn) if s.nome == "FULANO DE TAL")
    assert abertos == [fulano.id]


def test_botao_de_alteracoes_leva_a_empresa_junto(empresas):
    abertas = []
    empresas.ao_abrir_alteracoes = abertas.append
    empresas.lista.selectRow(0)
    empresas.btn_alteracoes.click()
    assert abertas == [_acme(empresas).id]
