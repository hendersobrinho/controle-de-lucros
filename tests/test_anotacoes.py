"""Os quatro itens do ANOTAÇÕES.TXT.

1. sugestão de sócio já cadastrado na hora de cadastrar
2. normalização de nomes na importação (coberta em test_planilha.py)
3. responsável padrão do informe de rendimentos
4. tela de busca ao incluir sócio na alteração contratual
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from controle_lucros import db, preferencias, repositories as repo
from controle_lucros.models import Empresa, Socio
from controle_lucros.ui.common import MODO_CANCELADO, MODO_VAZIO
from controle_lucros.ui.socios_tab import SociosTab


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()


# ================================ 1. sugestão de sócio já cadastrado =======


def test_acha_pelo_documento_mesmo_com_nome_diferente(conn):
    """CPF é o indício mais forte: nome digitado diferente não deve esconder
    que a pessoa já existe."""
    repo.salvar_socio(conn, Socio(None, "João da Silva", "005.169.717-35"))
    (achado, motivo), = repo.socios_semelhantes(conn, "Outro Nome", "005.169.717-35")
    assert achado.nome == "João da Silva"
    assert motivo == "mesmo CPF/CNPJ"


def test_acha_ignorando_acento_caixa_e_espaco(conn):
    repo.salvar_socio(conn, Socio(None, "João da Silva", ""))
    for digitado in ("JOAO DA SILVA", "joão  da  silva", "  João da Silva "):
        achados = repo.socios_semelhantes(conn, digitado, "")
        assert [m for _, m in achados] == ["mesmo nome"], digitado


def test_nome_parcial_vira_parecido_e_nao_igual(conn):
    repo.salvar_socio(conn, Socio(None, "João da Silva", ""))
    (_, motivo), = repo.socios_semelhantes(conn, "João", "")
    assert motivo == "nome parecido"


def test_nao_sugere_nada_com_pouca_coisa_digitada(conn):
    """Duas letras casariam com meio cadastro e o aviso viraria ruído."""
    repo.salvar_socio(conn, Socio(None, "João da Silva", ""))
    assert repo.socios_semelhantes(conn, "Jo", "") == []
    assert repo.socios_semelhantes(conn, "", "") == []


def test_editar_um_socio_nao_sugere_ele_mesmo(conn):
    socio_id = repo.salvar_socio(conn, Socio(None, "João da Silva", "005.169.717-35"))
    assert repo.socios_semelhantes(conn, "João da Silva", "005.169.717-35", ignorar_id=socio_id) == []


def test_documento_vem_antes_de_nome_parecido(conn):
    repo.salvar_socio(conn, Socio(None, "Zulmira Pereira", "005.169.717-35"))
    repo.salvar_socio(conn, Socio(None, "Ana Paula", ""))
    achados = repo.socios_semelhantes(conn, "Ana", "005.169.717-35")
    assert [m for _, m in achados] == ["mesmo CPF/CNPJ", "nome parecido"]


def test_aviso_aparece_ao_digitar_nome_ja_cadastrado(conn):
    repo.salvar_socio(conn, Socio(None, "João da Silva", "005.169.717-35"))
    aba = SociosTab(conn)
    assert not aba.aviso_duplicado.isVisibleTo(aba)

    aba._novo_socio()
    aba.nome.setText("JOAO DA SILVA")
    assert aba.aviso_duplicado.isVisibleTo(aba)
    assert "João da Silva" in aba.aviso_duplicado.text()
    # Cadastrando um novo, dá pra pular direto pro cadastro que já existe.
    assert aba.btn_abrir_semelhante.isVisibleTo(aba)


def test_aviso_some_quando_o_nome_deixa_de_bater(conn):
    repo.salvar_socio(conn, Socio(None, "João da Silva", ""))
    aba = SociosTab(conn)
    aba._novo_socio()
    aba.nome.setText("João da Silva")
    assert aba.aviso_duplicado.isVisibleTo(aba)
    aba.nome.setText("Carlos Andrade")
    assert not aba.aviso_duplicado.isVisibleTo(aba)


def test_aviso_nao_aparece_com_o_formulario_bloqueado(conn):
    """Sem nada sendo digitado não há o que avisar."""
    repo.salvar_socio(conn, Socio(None, "João da Silva", ""))
    aba = SociosTab(conn)
    aba._novo_socio()
    aba.nome.setText("João da Silva")
    aba._cancelar_socio()
    assert aba._modo == MODO_CANCELADO
    assert not aba.aviso_duplicado.isVisibleTo(aba)


def test_abrir_o_semelhante_leva_pro_cadastro_existente(conn):
    socio_id = repo.salvar_socio(conn, Socio(None, "João da Silva", ""))
    aba = SociosTab(conn)
    aba._novo_socio()
    aba.nome.setText("João da Silva")
    aba._abrir_semelhante()
    assert aba._socio_atual_id == socio_id


def test_o_aviso_nao_impede_cadastrar_homonimo(conn):
    """Homônimo existe; o aviso informa, não bloqueia."""
    repo.salvar_socio(conn, Socio(None, "João da Silva", "005.169.717-35"))
    aba = SociosTab(conn)
    aba._novo_socio()
    aba.nome.setText("João da Silva")
    aba.cpf.setText("072.525.437-81")
    aba._salvar_socio()
    assert len([s for s in repo.listar_socios(conn) if s.nome == "João da Silva"]) == 2


# ==================================== 3. responsável padrão do informe =====


@pytest.fixture()
def prefs(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTROLE_LUCROS_DB", str(tmp_path / "teste.db"))
    return tmp_path


def _dialogo_informe(conn):
    """Reaproveita o cadastro se já existir — os testes que reabrem o informe
    chamam isto duas vezes no mesmo banco."""
    from controle_lucros.ui.informe_rendimentos_view import InformeRendimentosDialog

    socios = repo.listar_socios(conn)
    if socios:
        socio = socios[0]
    else:
        empresa = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 1000, 100))
        socio_id = repo.salvar_socio(conn, Socio(None, "ROSELENE CARONE", "005.169.717-35"))
        repo.associar_socio_a_empresa(conn, empresa, socio_id, 100.0, 100, "2020-01-01")
        socio = next(s for s in repo.listar_socios(conn) if s.id == socio_id)

    dialogo = InformeRendimentosDialog(conn, socio)
    dialogo.ano.setValue(2025)
    return dialogo


def test_responsavel_padrao_e_guardado_e_relido(prefs):
    assert preferencias.responsavel_informe() == ""
    preferencias.guardar_responsavel_informe("  ELLEN SCHNEIDER EWALD  ")
    assert preferencias.responsavel_informe() == "ELLEN SCHNEIDER EWALD"


def test_informe_novo_ja_vem_com_o_responsavel_padrao(conn, prefs):
    preferencias.guardar_responsavel_informe("ELLEN SCHNEIDER EWALD")
    dialogo = _dialogo_informe(conn)
    assert dialogo.campos_texto["responsavel_nome"].text() == "ELLEN SCHNEIDER EWALD"


def test_marcar_como_padrao_guarda_ao_salvar(conn, prefs):
    dialogo = _dialogo_informe(conn)
    dialogo.campos_texto["responsavel_nome"].setText("ELLEN SCHNEIDER EWALD")
    dialogo.responsavel_padrao.setChecked(True)
    assert dialogo._salvar() is True
    assert preferencias.responsavel_informe() == "ELLEN SCHNEIDER EWALD"


def test_sem_marcar_nao_mexe_no_padrao(conn, prefs):
    preferencias.guardar_responsavel_informe("QUEM ASSINA SEMPRE")
    dialogo = _dialogo_informe(conn)
    dialogo.campos_texto["responsavel_nome"].setText("SUBSTITUTO EVENTUAL")
    dialogo._salvar()
    assert preferencias.responsavel_informe() == "QUEM ASSINA SEMPRE"


def test_informe_ja_salvo_mantem_quem_assinou(conn, prefs):
    """O padrão só preenche o que ainda está em branco — informe já conferido
    guarda quem assinou de fato, mesmo que o padrão mude depois."""
    dialogo = _dialogo_informe(conn)
    dialogo.campos_texto["responsavel_nome"].setText("QUEM ASSINOU NA EPOCA")
    dialogo._salvar()

    preferencias.guardar_responsavel_informe("OUTRO RESPONSAVEL")
    outro = _dialogo_informe(conn)
    assert outro.campos_texto["responsavel_nome"].text() == "QUEM ASSINOU NA EPOCA"


# ============================ 4. busca de sócio na alteração contratual ====


@pytest.fixture()
def cenario_alteracao(conn):
    from controle_lucros.models import AlteracaoContratual

    empresa = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 100000, 1000))
    dentro = repo.salvar_socio(conn, Socio(None, "JA VINCULADO", "005.169.717-35"))
    fora = repo.salvar_socio(conn, Socio(None, "MARIA EXEMPLO", "072.525.437-81"))
    repo.salvar_socio(conn, Socio(None, "HOLDING XYZ", "12.345.678/0001-90", "juridica"))
    repo.associar_socio_a_empresa(conn, empresa, dentro, 100.0, 1000, "2020-01-01")
    alteracao = repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa, 9, "2025-01-01", "ACME LTDA", 100000, 1000, "")
    )
    return {"empresa": empresa, "dentro": dentro, "fora": fora, "alteracao": alteracao}


def _dialogo_incluir(conn, cenario):
    from controle_lucros.ui.alteracao_card import _DialogoIncluirSocio

    return _DialogoIncluirSocio(conn, cenario["empresa"], {cenario["dentro"]})


def test_lista_so_quem_ainda_nao_esta_na_empresa(conn, cenario_alteracao):
    dialogo = _dialogo_incluir(conn, cenario_alteracao)
    nomes = [s.nome for s in dialogo._socios]
    assert "JA VINCULADO" not in nomes
    assert {"MARIA EXEMPLO", "HOLDING XYZ"} <= set(nomes)


def test_busca_filtra_por_nome_e_por_documento(conn, cenario_alteracao):
    dialogo = _dialogo_incluir(conn, cenario_alteracao)

    dialogo.busca.setText("maria")
    assert [s.nome for s in dialogo._socios] == ["MARIA EXEMPLO"]

    # Só os dígitos: quem digita CPF raramente repete a pontuação exata.
    dialogo.busca.setText("07252543781")
    assert [s.nome for s in dialogo._socios] == ["MARIA EXEMPLO"]

    dialogo.busca.setText("12.345.678")
    assert [s.nome for s in dialogo._socios] == ["HOLDING XYZ"]


def test_busca_sem_resultado_explica_em_vez_de_lista_vazia(conn, cenario_alteracao):
    dialogo = _dialogo_incluir(conn, cenario_alteracao)
    dialogo.busca.setText("xyzabc")
    assert dialogo._socios == []
    assert dialogo.vazio.isVisibleTo(dialogo)
    assert "Nenhum sócio encontrado" in dialogo.vazio.text()


def test_incluir_so_libera_com_socio_escolhido(conn, cenario_alteracao):
    """Sem isto o diálogo aceitaria e devolveria None pro chamador."""
    dialogo = _dialogo_incluir(conn, cenario_alteracao)
    ok = dialogo.botoes.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled()

    dialogo.busca.setText("maria")
    dialogo.tabela.selectRow(0)
    assert ok.isEnabled()
    assert dialogo.dados()[0] == cenario_alteracao["fora"]


def test_cadastrar_socio_novo_ali_dentro_e_ja_seleciona(conn, cenario_alteracao, monkeypatch):
    """Quem monta alteração contratual quase sempre inclui alguém que ainda
    não existe; antes era preciso sair pra aba Sócios e voltar."""
    from controle_lucros.ui import alteracao_card as mod

    dialogo = _dialogo_incluir(conn, cenario_alteracao)
    dialogo.busca.setText("filtro que esconde tudo")

    class _Falso:
        def exec(self):
            return mod.QDialog.Accepted

        def socio(self):
            return Socio(None, "RECEM CADASTRADO", "")

    monkeypatch.setattr(mod, "_DialogoNovoSocio", lambda parent=None: _Falso())
    dialogo._cadastrar_socio()

    assert any(s.nome == "RECEM CADASTRADO" for s in repo.listar_socios(conn))
    # A busca é limpa, senão o recém-cadastrado ficaria escondido pelo filtro.
    assert dialogo.busca.text() == ""
    selecionado = dialogo._socio_selecionado()
    assert selecionado is not None and selecionado.nome == "RECEM CADASTRADO"


def test_montar_a_tela_nao_dispara_erro_no_aviso(conn):
    """Os campos ficam ligados ao aviso de duplicata, e o textChanged dispara
    já na construção (o ajuste da máscara limpa o documento). Como o Qt engole
    exceção dentro de slot, um erro aqui passaria despercebido — este teste
    chama o handler direto, sem a rede de proteção do Qt."""
    repo.salvar_socio(conn, Socio(None, "João da Silva", "005.169.717-35"))
    aba = SociosTab(conn)
    aba._procurar_semelhantes()  # não pode levantar
    assert aba._modo == MODO_VAZIO
    assert not aba.aviso_duplicado.isVisibleTo(aba)
