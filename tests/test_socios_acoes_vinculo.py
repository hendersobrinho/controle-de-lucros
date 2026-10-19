"""As participações do sócio na aba Sócios: fichas por empresa e a edição.

As quatro ações que existiam (editar datas, atualizar cotas, encerrar,
excluir) viraram uma tela só, com todos os campos do vínculo e o botão de
excluir. O que estes testes prendem é que a tela grava o que mostra, que o
capital do sócio aparece, e que os rótulos continuam cabendo na janela.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from controle_lucros import repositories as repo
from controle_lucros.models import AlteracaoContratual, Empresa, Socio
from controle_lucros.ui import socios_tab as mod
from controle_lucros.ui.socios_tab import SociosTab


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture()
def cenario(conn):
    empresa_id = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 100000, 1000))
    socio_id = repo.salvar_socio(conn, Socio(None, "FULANO DE TAL", "005.169.717-35"))
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100.0, 1000, "2020-01-01")
    (vinculo,) = repo.listar_vinculos_socio(conn, socio_id)
    return {"empresa": empresa_id, "socio": socio_id, "vinculo": vinculo}


def _aba(conn) -> SociosTab:
    aba = SociosTab(conn)
    aba.lista.selectRow(0)
    return aba


def _dialogo(conn, cenario) -> mod._DialogoEditarVinculo:
    vinculo = repo.buscar_vinculo(conn, cenario["vinculo"].id)
    return mod._DialogoEditarVinculo(conn, vinculo, "ACME LTDA")


# ------------------------------------------------------ as fichas --


def _textos(widget) -> str:
    from PySide6.QtWidgets import QLabel

    return " | ".join(r.text() for r in widget.findChildren(QLabel))


def test_ficha_mostra_a_participacao_com_unidades_e_datas_legiveis(conn, cenario):
    aba = _aba(conn)
    (cartao,) = aba.cartoes
    textos = _textos(cartao)
    assert "ACME LTDA" in textos
    assert "100,0000%" in textos                # percentual com o símbolo
    assert "1.000 de 1.000" in textos           # cotas com a régua da empresa
    assert "desde 01/01/2020" in textos         # data no formato de quem lê
    assert "2020-01-01" not in textos
    assert cartao.etiqueta.text() == "Ativo"


def test_ficha_mostra_capital_informado_ou_a_estimativa(conn, cenario):
    aba = _aba(conn)
    (cartao,) = aba.cartoes
    # 1000 cotas de uma empresa de R$ 100.000 em 1000 cotas.
    assert cartao.capital.text() == "≈ R$ 100.000,00"
    assert "Estimativa" in cartao.capital.toolTip()

    vinculo = repo.buscar_vinculo(conn, cenario["vinculo"].id)
    vinculo.valor_capital = 75000
    repo.salvar_vinculo(conn, vinculo)
    (cartao,) = _aba(conn).cartoes
    assert cartao.capital.text() == "R$ 75.000,00"


def test_ativas_vem_antes_das_encerradas_e_da_maior_pra_menor(conn, cenario):
    from controle_lucros.models import VinculoSocietario

    beta = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 1000, 100))
    gama = repo.salvar_empresa(conn, Empresa(None, "003", "GAMA LTDA", "", 1000, 100))
    repo.salvar_vinculo(conn, VinculoSocietario(None, beta, cenario["socio"], 30, 30, "2021-01-01", "2023-06-30"))
    repo.salvar_vinculo(conn, VinculoSocietario(None, gama, cenario["socio"], 40, 40, "2022-01-01", None))

    aba = _aba(conn)
    nomes = [c.vinculo.empresa_id for c in aba.cartoes]
    assert nomes == [cenario["empresa"], gama, beta]
    assert aba.cartoes[-1].etiqueta.text() == "Saiu em 30/06/2023"
    assert aba.resumo_socio.text().startswith("2 empresas ativas · saiu de 1 empresa")


def test_lista_de_socios_conta_as_empresas_ativas(conn, cenario):
    repo.salvar_socio(conn, Socio(None, "SEM EMPRESA NENHUMA", ""))
    aba = SociosTab(conn)
    from controle_lucros.ui.lista_fichas import PAPEL_DETALHE, PAPEL_MARCADOR

    linhas = {aba.lista.item(r).text(): aba.lista.item(r) for r in range(aba.lista.count())}
    assert linhas["FULANO DE TAL"].data(PAPEL_MARCADOR) == "1 empresa"
    assert linhas["SEM EMPRESA NENHUMA"].data(PAPEL_MARCADOR) == "sem empresa"
    assert linhas["FULANO DE TAL"].data(PAPEL_DETALHE) == "CPF 005.169.717-35"
    assert aba.contagem.text() == "2 sócios"


def test_busca_acha_por_nome_ou_documento_sem_pontuacao(conn, cenario):
    repo.salvar_socio(conn, Socio(None, "BEATRIZ LIMA", "111.444.777-35"))
    aba = SociosTab(conn)
    aba.busca.setText("beatriz")
    assert [aba.lista.item(r).text() for r in range(aba.lista.count())] == ["BEATRIZ LIMA"]
    aba.busca.setText("11144477")
    assert [aba.lista.item(r).text() for r in range(aba.lista.count())] == ["BEATRIZ LIMA"]
    assert aba.contagem.text() == "1 de 2 sócios"


# ------------------------------------------------- telas vazias --


def test_sem_socio_selecionado_convida_a_escolher(conn, cenario):
    aba = SociosTab(conn)
    assert aba.cabecalho_socio.isHidden()
    assert not aba.painel_vazio.isHidden()
    assert "Nenhum sócio selecionado" in aba.vazio_titulo.text()
    assert not aba.btn_associar.isEnabled()


def test_socio_sem_empresa_convida_a_associar(conn, cenario):
    repo.salvar_socio(conn, Socio(None, "BEATRIZ LIMA", ""))
    aba = SociosTab(conn)
    aba.lista.selectRow(0)  # "BEATRIZ LIMA" vem antes por nome
    assert aba.cartoes == []
    assert "ainda não participa de nenhuma empresa" in aba.vazio_titulo.text()
    assert "Associar empresa" in aba.vazio_texto.text()
    assert aba.btn_associar.isEnabled()


# ---------------------------------------------- cadastro do sócio --


def test_novo_socio_salvar_e_associar_emenda_a_associacao(conn, cenario, monkeypatch):
    """O cadastro inicial do sócio só fica completo com a participação: o
    botão principal do cadastro novo já abre a associação."""
    associacoes = []

    def preencher_e_salvar(dialogo):
        dialogo.nome.setText("NOVA SÓCIA")
        dialogo._salvar(associar=True)
        return dialogo.result()

    monkeypatch.setattr(mod.DialogoSocio, "exec", preencher_e_salvar)
    monkeypatch.setattr(mod._DialogoAssociarEmpresa, "exec", lambda self: associacoes.append(self) or QDialog.Rejected)
    aba = SociosTab(conn)
    aba._novo_socio()

    nova = next(s for s in repo.listar_socios(conn) if s.nome == "NOVA SÓCIA")
    assert aba._socio_atual_id == nova.id
    assert len(associacoes) == 1


def test_novo_socio_so_salvar_nao_abre_a_associacao(conn, cenario, monkeypatch):
    associacoes = []

    def preencher_e_salvar(dialogo):
        dialogo.nome.setText("NOVA SÓCIA")
        dialogo._salvar(associar=False)
        return dialogo.result()

    monkeypatch.setattr(mod.DialogoSocio, "exec", preencher_e_salvar)
    monkeypatch.setattr(mod._DialogoAssociarEmpresa, "exec", lambda self: associacoes.append(self) or QDialog.Rejected)
    aba = SociosTab(conn)
    aba._novo_socio()

    assert associacoes == []
    assert "ainda não participa de nenhuma empresa" in aba.vazio_titulo.text()


def test_cadastro_sem_nome_avisa_e_nao_fecha(conn, cenario, monkeypatch):
    avisos = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    dialogo = mod.DialogoSocio(conn)
    dialogo._salvar(associar=False)
    assert avisos == ["Informe o nome do sócio."]
    assert dialogo.result() != QDialog.Accepted


def test_editar_dados_do_socio(conn, cenario, monkeypatch):
    def renomear(dialogo):
        assert dialogo.nome.text() == "FULANO DE TAL"
        assert dialogo.cpf.text() == "005.169.717-35"
        dialogo.nome.setText("FULANO DE TAL JUNIOR")
        dialogo._salvar(associar=False)
        return dialogo.result()

    monkeypatch.setattr(mod.DialogoSocio, "exec", renomear)
    aba = _aba(conn)
    aba.btn_editar_socio.click()
    assert aba.titulo_socio.text() == "FULANO DE TAL JUNIOR"
    assert aba.lista.item(0).text() == "FULANO DE TAL JUNIOR"


def test_excluir_socio_com_participacao_explica_e_nao_exclui(conn, cenario, monkeypatch):
    avisos = []
    monkeypatch.setattr(mod.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    socio = next(s for s in repo.listar_socios(conn) if s.id == cenario["socio"])
    dialogo = mod.DialogoSocio(conn, socio)
    dialogo._excluir()
    assert "Não é possível excluir" in avisos[0]
    assert any(s.id == cenario["socio"] for s in repo.listar_socios(conn))


def test_excluir_socio_sem_participacao(conn, cenario, monkeypatch):
    monkeypatch.setattr(mod.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    socio_id = repo.salvar_socio(conn, Socio(None, "Sem Nada", ""))
    dialogo = mod.DialogoSocio(conn, next(s for s in repo.listar_socios(conn) if s.id == socio_id))
    dialogo._excluir()
    assert dialogo.result() == mod.DialogoSocio.EXCLUIDO
    assert all(s.id != socio_id for s in repo.listar_socios(conn))


# ------------------------------------------------ abrir a edição --


def test_botao_e_dois_cliques_na_ficha_abrem_a_edicao(conn, cenario, monkeypatch):
    abertos = []
    monkeypatch.setattr(mod._DialogoEditarVinculo, "exec", lambda self: abertos.append(self.vinculo.id) or QDialog.Rejected)
    aba = _aba(conn)
    (cartao,) = aba.cartoes

    cartao.btn_editar.click()
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    cartao.mouseDoubleClickEvent(QMouseEvent(
        QEvent.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    assert abertos == [cenario["vinculo"].id, cenario["vinculo"].id]


# ------------------------------------------------------- a edição --


def test_edicao_grava_todos_os_campos(conn, cenario):
    alteracao_id = repo.salvar_alteracao(conn, AlteracaoContratual(
        None, cenario["empresa"], 7, "2019-12-15", "ACME LTDA", 100000, 1000, "Contrato antigo"))
    dialogo = _dialogo(conn, cenario)

    dialogo.percentual.setValue(60.0)
    dialogo.cotas.setValue(600)
    dialogo.capital.setValue(60000)
    dialogo.observacao.setText("corrigido pelo contrato")
    dialogo.alteracao_entrada.setCurrentIndex(dialogo.alteracao_entrada.findData(alteracao_id))
    dialogo._salvar()

    assert dialogo.result() == QDialog.Accepted
    vinculo = repo.buscar_vinculo(conn, cenario["vinculo"].id)
    assert (vinculo.percentual_capital, vinculo.quantidade_cotas, vinculo.valor_capital) == (60.0, 600, 60000)
    assert vinculo.observacao == "corrigido pelo contrato"
    assert vinculo.alteracao_entrada_id == alteracao_id
    # Corrigir não é movimentar: nada de vínculo novo nem alteração nova.
    assert len(repo.listar_vinculos_socio(conn, cenario["socio"])) == 1
    assert [a.id for a in repo.listar_alteracoes(conn, cenario["empresa"])] == [alteracao_id]


def test_marcar_saida_encerra_o_vinculo(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    assert not dialogo.data_saida.isEnabled()

    dialogo.saiu.setChecked(True)
    assert dialogo.data_saida.isEnabled()
    dialogo.data_saida.setDate(dialogo.data_saida.date().fromString("2024-06-30", "yyyy-MM-dd"))
    dialogo._salvar()

    assert repo.buscar_vinculo(conn, cenario["vinculo"].id).data_saida == "2024-06-30"


def test_desmarcar_saida_reabre_o_vinculo(conn, cenario):
    repo.encerrar_vinculo(conn, cenario["vinculo"].id, "2024-06-30", None)
    dialogo = _dialogo(conn, cenario)
    assert dialogo.saiu.isChecked()

    dialogo.saiu.setChecked(False)
    dialogo._salvar()

    assert repo.buscar_vinculo(conn, cenario["vinculo"].id).data_saida is None


def test_capital_em_branco_fica_sem_valor_informado(conn, cenario):
    """Zero no campo é "não informado": a tabela volta a mostrar a estimativa."""
    dialogo = _dialogo(conn, cenario)
    dialogo.capital.setValue(0)
    dialogo._salvar()
    assert repo.buscar_vinculo(conn, cenario["vinculo"].id).valor_capital is None


def test_erro_ao_salvar_mantem_a_tela_aberta(conn, cenario, monkeypatch):
    """Com erro a pessoa corrige na tela, em vez de perder o que digitou."""
    avisos = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    dialogo = _dialogo(conn, cenario)
    dialogo.saiu.setChecked(True)
    dialogo.data_saida.setDate(dialogo.data_saida.date().fromString("2010-01-01", "yyyy-MM-dd"))

    dialogo._salvar()

    assert dialogo.result() != QDialog.Accepted
    assert "anterior à data de entrada" in avisos[0]


def test_excluir_pela_tela_de_edicao_pede_confirmacao(conn, cenario, monkeypatch):
    monkeypatch.setattr(mod.QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    dialogo = _dialogo(conn, cenario)
    dialogo._excluir()
    assert repo.buscar_vinculo(conn, cenario["vinculo"].id) is not None

    monkeypatch.setattr(mod.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dialogo._excluir()
    assert dialogo.result() == mod._DialogoEditarVinculo.EXCLUIDO
    assert repo.buscar_vinculo(conn, cenario["vinculo"].id) is None


def test_alteracoes_da_empresa_aparecem_para_associar(conn, cenario):
    repo.salvar_alteracao(conn, AlteracaoContratual(
        None, cenario["empresa"], 3, "2018-05-10", "ACME LTDA", 100000, 1000, "Entrada do Fulano"))
    dialogo = _dialogo(conn, cenario)
    rotulos = [dialogo.alteracao_entrada.itemText(i) for i in range(dialogo.alteracao_entrada.count())]
    assert rotulos[0] == "Nenhuma (associar depois)"
    assert "Nº 3 — 10/05/2018 — Entrada do Fulano" in rotulos


# ------------------------------------- valor da cota e capital --


def _associar_beatriz(conn, empresa_id):
    repo.salvar_socio(conn, Socio(None, "BEATRIZ LIMA", ""))
    beatriz = next(s for s in repo.listar_socios(conn) if s.nome == "BEATRIZ LIMA")
    dialogo = mod._DialogoAssociarEmpresa(conn, beatriz.id)
    dialogo.empresa.setCurrentIndex(dialogo.empresa.findData(empresa_id))
    return dialogo


def test_capital_do_socio_e_cotas_vezes_valor_da_cota(conn, cenario):
    """O relatório não traz o capital: cotas × valor da cota chega nele."""
    outra = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 0, 0))
    dialogo = _associar_beatriz(conn, outra)
    assert dialogo.valor_cota.value() == 1.0           # sem informação: R$ 1,00, o comum
    assert "ainda não tem o valor da cota" in dialogo.campos.dica_valor_cota.text()

    dialogo.cotas.setValue(250_000)
    assert dialogo.capital.value() == 250_000.0
    dialogo.valor_cota.atalhos[1].click()              # R$ 0,01
    assert dialogo.capital.value() == 2_500.0
    assert "250.000 cotas × R$ 0,01 = R$ 2.500,00" in dialogo.campos.conta_capital.text()


def test_valor_da_cota_vem_da_empresa(conn, cenario):
    outra = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 50000, 500))
    dialogo = _associar_beatriz(conn, outra)
    assert dialogo.valor_cota.value() == 100.0         # capital ÷ cotas
    repo.definir_valor_da_cota(conn, outra, 0.01)
    dialogo.campos.carregar_empresa()
    assert dialogo.valor_cota.value() == 0.01
    assert "informado no cadastro da empresa" in dialogo.campos.dica_valor_cota.text()


def test_associar_grava_o_valor_da_cota_na_empresa(conn, cenario, monkeypatch):
    outra = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 0, 0))
    repo.salvar_socio(conn, Socio(None, "BEATRIZ LIMA", ""))

    def associar(dialogo):
        dialogo.empresa.setCurrentIndex(dialogo.empresa.findData(outra))
        dialogo.cotas.setValue(1000)
        dialogo.valor_cota.setValue(0.01)
        return QDialog.Accepted

    monkeypatch.setattr(mod._DialogoAssociarEmpresa, "exec", associar)
    aba = SociosTab(conn)
    aba.lista.selectRow(0)  # Beatriz Lima
    aba._associar_empresa()

    assert repo.buscar_empresa(conn, outra).valor_cota == 0.01
    (vinculo,) = repo.listar_vinculos_empresa(conn, outra)
    assert vinculo.valor_capital == 10.0


def test_percentual_em_branco_acompanha_as_cotas(conn, cenario):
    outra = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 50000, 500))
    dialogo = _associar_beatriz(conn, outra)
    dialogo.cotas.setValue(120)
    assert dialogo.percentual.value() == 24.0
    assert "de 500 cotas da empresa" in dialogo.campos.total_cotas.text()


def test_percentual_informado_so_muda_pelo_botao(conn, cenario):
    """O percentual do contrato pode ser outro: depois de digitado, as cotas
    não mexem mais nele."""
    dialogo = _dialogo(conn, cenario)
    dialogo.percentual.setValue(60.0)
    dialogo.cotas.setValue(200)
    assert dialogo.percentual.value() == 60.0
    dialogo.campos.btn_percentual.click()
    assert dialogo.percentual.value() == 20.0


def test_abrir_a_edicao_nao_troca_o_capital_informado(conn, cenario):
    vinculo = repo.buscar_vinculo(conn, cenario["vinculo"].id)
    vinculo.valor_capital = 12345.0
    repo.salvar_vinculo(conn, vinculo)
    dialogo = _dialogo(conn, cenario)
    assert dialogo.capital.value() == 12345.0


def test_campos_mostram_a_unidade_sem_zeros_sobrando(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    dialogo.percentual.setValue(46.94)
    dialogo.cotas.setValue(469)
    assert dialogo.percentual.text() == "46,9400 %"
    assert dialogo.cotas.text() == "469"
    assert dialogo.capital.prefix() == "R$ "

    dialogo.percentual.setValue(33.3333)
    assert dialogo.percentual.text() == "33,3333 %"


def test_associar_com_entrada_antiga_avisa_que_nao_cria_alteracao(conn, cenario, monkeypatch):
    monkeypatch.setattr(repo, "_ano_corrente", lambda: 2026)
    outra = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 1000, 100))
    dialogo = mod._DialogoAssociarEmpresa(conn, cenario["socio"])
    dialogo.empresa.setCurrentIndex(dialogo.empresa.findData(outra))

    dialogo.data_entrada.setDate(dialogo.data_entrada.date().fromString("2015-03-01", "yyyy-MM-dd"))
    assert not dialogo.aviso_alteracao.isHidden()
    assert "associe depois" in dialogo.aviso_alteracao.text()
    assert not dialogo.descricao.isEnabled()

    dialogo.data_entrada.setDate(dialogo.data_entrada.date().fromString("2026-03-01", "yyyy-MM-dd"))
    assert dialogo.aviso_alteracao.isHidden()
    assert dialogo.descricao.isEnabled()


# --------------------------------------------------- larguras --


def test_nenhum_botao_trunca_na_largura_minima_da_janela(conn, cenario):
    """A régua é a janela no seu tamanho mínimo: se couber ali, cabe em
    qualquer uso real. Foi assim que "Cancelar" virou "ancel" antes.

    O estilo do programa é aplicado de propósito: é ele que dá padding aos
    botões, então sem ele a medida sai menor do que a real."""
    from controle_lucros.ui.main_window import MainWindow
    from controle_lucros.ui.theme import build_stylesheet

    QApplication.instance().setStyleSheet(build_stylesheet())
    repo.criar_usuario(conn, "Admin", "admin", "senha123", True)
    janela = MainWindow(conn, repo.listar_usuarios(conn)[0])
    janela.resize(janela.minimumSizeHint().width(), 720)
    janela._ir_para("socios")
    janela.show()

    aba = janela.socios_tab
    aba.lista.selectRow(0)
    janela.layout().activate()

    botoes = {
        "Novo sócio": aba.btn_novo, "Editar dados": aba.btn_editar_socio,
        "Associar": aba.btn_associar, "Informe": aba.btn_informe, "Mapa de vínculos": aba.btn_mapa,
        "Editar participação": aba.cartoes[0].btn_editar,
    }
    truncados = [nome for nome, b in botoes.items() if b.width() < b.sizeHint().width()]
    assert truncados == [], f"rótulos cortados: {truncados}"


def test_tipo_de_pessoa_em_botoes_troca_a_mascara(conn):
    dialogo = mod.DialogoSocio(conn)
    assert dialogo._rotulo_documento.text() == "CPF"
    dialogo.tipo_pessoa.setCurrentIndex(dialogo.tipo_pessoa.findData("juridica"))
    assert dialogo._rotulo_documento.text() == "CNPJ"


def test_campos_da_saida_so_aparecem_quando_o_socio_saiu(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    assert dialogo.campos_saida.isHidden()
    dialogo.saiu.setChecked(True)
    assert not dialogo.campos_saida.isHidden()
