"""A conexão com o PostgreSQL do escritório.

O que se testa aqui é o que quebra em silêncio ou só no escritório, com
vários PCs: onde fica a configuração de cada máquina, o que um PC enxerga do
outro, o que acontece depois de um erro no meio de uma gravação ou de uma
queda de rede, e se as mensagens de erro dizem o que fazer.
"""
import datetime as dt
import json
import os
import pathlib
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import psycopg
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from controle_lucros import db, preferencias, repositories as repo
from controle_lucros.models import Empresa
from controle_lucros.ui import local_banco

PROJETO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture()
def pc(monkeypatch, tmp_path):
    """Um PC recém-instalado: pasta local vazia e sem conexão configurada."""
    monkeypatch.setenv("CONTROLE_LUCROS_DADOS", str(tmp_path / "pc"))
    monkeypatch.delenv("CONTROLE_LUCROS_PG")
    return tmp_path / "pc"


@pytest.fixture()
def parametros_de_teste():
    return db.conexao_configurada()


# ------------------------------------------------------ pasta local --


def test_empacotado_a_pasta_local_e_a_da_maquina(monkeypatch, tmp_path):
    monkeypatch.delenv("CONTROLE_LUCROS_DADOS")
    monkeypatch.setattr(db.sys, "frozen", True, raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    assert db.pasta_local() == tmp_path / "ProgramData" / "ControleDeLucros" / "data"


def test_rodando_do_codigo_a_pasta_local_fica_ao_lado_do_projeto(monkeypatch):
    monkeypatch.delenv("CONTROLE_LUCROS_DADOS")
    monkeypatch.delattr(db.sys, "frozen", raising=False)
    assert db.pasta_local() == PROJETO / "data"


# ---------------------------------------------- conexão configurada --


def test_instalacao_nova_pergunta_a_conexao(pc):
    assert db.precisa_configurar()
    assert db.conexao_configurada() is None


def test_conexao_escolhida_fica_neste_pc(pc):
    db.definir_conexao(db.ParametrosConexao(servidor="192.168.0.10", senha="x"))

    assert not db.precisa_configurar()
    guardado = json.loads((pc / db.ARQUIVO_CONFIG_LOCAL).read_text(encoding="utf-8"))
    assert guardado["conexao"]["servidor"] == "192.168.0.10"
    assert db.conexao_configurada() == db.ParametrosConexao(servidor="192.168.0.10", senha="x")


def test_configuracao_com_bom_do_bloco_de_notas_e_lida(pc):
    pc.mkdir(parents=True)
    (pc / db.ARQUIVO_CONFIG_LOCAL).write_text(
        json.dumps({"conexao": {"servidor": "srv", "porta": 5433}}), encoding="utf-8-sig"
    )
    parametros = db.conexao_configurada()
    assert (parametros.servidor, parametros.porta, parametros.banco) == ("srv", 5433, "controle_lucros")


def test_configuracao_estragada_pergunta_de_novo(pc):
    pc.mkdir(parents=True)
    (pc / db.ARQUIVO_CONFIG_LOCAL).write_text("{nao é json", encoding="utf-8")
    assert db.precisa_configurar()


def test_sem_conexao_configurada_nao_tenta_conectar(pc):
    with pytest.raises(db.ConexaoNaoConfigurada):
        db.connect()


def test_preferencias_ficam_em_cada_computador(pc):
    preferencias.salvar_chave("modo", "escuro")
    assert json.loads((pc / "preferencias.json").read_text(encoding="utf-8"))["modo"] == "escuro"


# ------------------------------------------------ vários computadores --


def test_um_pc_ve_o_que_o_outro_gravou(conn):
    outro_pc = db.connect()
    try:
        repo.salvar_empresa(outro_pc, Empresa(None, "001", "ACME LTDA", "", 1000, 100))
        assert [e.nome for e in repo.listar_empresas(conn)] == ["ACME LTDA"]
    finally:
        outro_pc.close()


def test_gravacao_so_aparece_pros_outros_depois_do_commit(conn):
    outro_pc = db.connect()
    try:
        conn.execute(
            "INSERT INTO empresa (numero_chamada, nome) VALUES ('001', 'PENDENTE LTDA')"
        )
        assert repo.listar_empresas(outro_pc) == []
        conn.commit()
        assert [e.nome for e in repo.listar_empresas(outro_pc)] == ["PENDENTE LTDA"]
    finally:
        outro_pc.close()


def test_leitura_nao_deixa_transacao_aberta(conn):
    """Uma tela parada mostrando dados não pode segurar nada no servidor."""
    repo.listar_empresas(conn)
    assert not conn.em_transacao


def test_dois_pcs_abrindo_pela_primeira_vez_ao_mesmo_tempo(parametros_de_teste):
    """Os dois criam o schema; a trava faz um esperar o outro em vez de um
    deles falhar com "duplicate key" no catálogo do PostgreSQL."""
    erros = []

    def abrir():
        try:
            c = db.connect(parametros_de_teste)
            db.init_schema(c)
            c.close()
        except Exception as erro:  # noqa: BLE001
            erros.append(erro)

    threads = [threading.Thread(target=abrir) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert erros == []


def test_gravacao_travada_por_outro_pc_desiste_com_aviso(conn, monkeypatch):
    monkeypatch.setattr(db, "ESPERA_DE_BLOQUEIO_MS", 200)
    repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 1000, 100))
    outro_pc = db.connect()
    try:
        outro_pc.execute("UPDATE empresa SET nome = 'TRAVADA LTDA'")  # sem commit
        esperando = db.connect()
        try:
            with pytest.raises(psycopg.errors.LockNotAvailable) as erro:
                esperando.execute("UPDATE empresa SET nome = 'OUTRA LTDA'")
            assert "Outro computador está gravando" in db.explicar_erro(erro.value)
            assert not esperando.em_transacao
        finally:
            esperando.close()
    finally:
        outro_pc.rollback()
        outro_pc.close()


# ------------------------------------------------- erros e quedas --


def test_erro_no_meio_da_gravacao_nao_trava_a_conexao(conn):
    """No PostgreSQL, erro dentro da transação a invalida: sem desfazer na
    hora, todo comando seguinte falharia com "transaction is aborted"."""
    empresa_id = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 1000, 100))
    repo.salvar_socio(conn, repo.Socio(id=None, nome="Fulano", cpf=""))
    conn.execute(
        "INSERT INTO vinculo_societario (empresa_id, socio_id, percentual_capital, data_entrada) "
        "VALUES (%s, 1, 100, '2024-01-01')", (empresa_id,)
    )
    conn.commit()

    with pytest.raises(ValueError, match="Não é possível excluir"):
        repo.excluir_empresa(conn, empresa_id)

    assert [e.nome for e in repo.listar_empresas(conn)] == ["ACME LTDA"]
    repo.salvar_empresa(conn, Empresa(None, "002", "OUTRA LTDA", "", 1, 1))
    assert len(repo.listar_empresas(conn)) == 2


def test_conexao_que_caiu_e_refeita_no_proximo_comando(conn, parametros_de_teste):
    """Servidor reiniciado ou rede que piscou: a próxima ação reconecta, em
    vez de o programa precisar ser fechado."""
    repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 1000, 100))
    pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]
    administrador = db.connect(parametros_de_teste)
    try:
        administrador.execute("SELECT pg_terminate_backend(%s)", (pid,))
    finally:
        administrador.close()

    with pytest.raises(psycopg.OperationalError) as erro:
        repo.listar_empresas(conn)
    assert "falhou ou caiu" in db.explicar_erro(erro.value)

    assert [e.nome for e in repo.listar_empresas(conn)] == ["ACME LTDA"]


# ---------------------------------------------- jeito do sqlite3 --


def test_linha_se_le_por_nome_por_posicao_e_vira_dicionario(conn):
    linha = conn.execute("SELECT 1 AS um, 'dois' AS dois").fetchone()
    assert (linha["um"], linha[1]) == (1, "dois")
    assert dict(linha) == {"um": 1, "dois": "dois"}
    assert tuple(linha) == (1, "dois")


def test_data_vai_como_texto_iso(conn):
    """As datas moram em colunas TEXT; passar um date tem que funcionar
    como no sqlite3, e não virar erro de tipo."""
    empresa_id = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 1000, 100))
    conn.execute(
        "INSERT INTO movimentacao (empresa_id, socio_id, tipo, valor, data) "
        "SELECT %s, id, 'adiantamento_lucro', 10, %s FROM socio",
        (empresa_id, dt.date(2024, 3, 31)),
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM alteracao_contratual WHERE data <= %s", (dt.date(2024, 1, 1),)
    ).fetchone()[0] == 0


def test_booleano_vai_como_inteiro(conn):
    repo.criar_usuario(conn, "Admin", "admin", "senha123", admin=True)
    assert conn.execute("SELECT admin FROM usuario").fetchone()[0] == 1


# ------------------------------------------------- testar conexão --


def test_testar_conexao_devolve_a_versao(parametros_de_teste):
    assert db.testar_conexao(parametros_de_teste)[:2].isdigit()


def test_banco_que_nao_existe_diz_o_que_fazer(parametros_de_teste):
    errado = db.ParametrosConexao(**{**parametros_de_teste.__dict__, "banco": "nao_existe"})
    with pytest.raises(psycopg.Error) as erro:
        db.testar_conexao(errado)
    assert "banco com esse nome não existe" in db.explicar_erro(erro.value)


def test_porta_sem_postgres_diz_o_que_fazer(parametros_de_teste):
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta_livre = s.getsockname()[1]
    errado = db.ParametrosConexao(**{**parametros_de_teste.__dict__, "porta": porta_livre})
    with pytest.raises(psycopg.OperationalError) as erro:
        db.testar_conexao(errado)
    assert "PostgreSQL não atendeu" in db.explicar_erro(erro.value)


def test_usuario_que_nao_e_dono_do_banco_e_avisado(conn, parametros_de_teste):
    """PostgreSQL 15: só o dono do banco cria tabelas. Banco criado sem o
    OWNER certo tem que ser pego no teste de conexão, não na primeira
    abertura."""
    eh_superusuario = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    if not eh_superusuario.fetchone()[0]:
        pytest.skip("precisa de superusuário no banco de teste")
    conn.execute("DROP ROLE IF EXISTS so_leitura")
    conn.execute("CREATE ROLE so_leitura LOGIN")
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    conn.commit()
    try:
        so_leitura = db.ParametrosConexao(**{**parametros_de_teste.__dict__, "usuario": "so_leitura"})
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as erro:
            db.testar_conexao(so_leitura)
        assert "OWNER" in db.explicar_erro(erro.value)
    finally:
        conn.execute("DROP ROLE so_leitura")
        conn.commit()


@pytest.mark.parametrize("mensagem, esperado", [
    ('FATAL:  password authentication failed for user "x"', "usuário ou a senha"),
    ('FATAL:  autenticação do tipo senha falhou para o usuário "x"', "usuário ou a senha"),
    ('FATAL:  role "x" does not exist', "usuário ou a senha"),
    ('FATAL:  banco de dados "x" não existe', "banco com esse nome não existe"),
    ('FATAL:  no pg_hba.conf entry for host "192.168.0.5"', "não aceita conexões"),
    ('FATAL:  nenhuma entrada no pg_hba.conf para máquina "192.168.0.5"', "não aceita conexões"),
    ("connection timeout expired", "não respondeu"),
    ("Connection refused", "PostgreSQL não atendeu"),
    ("Conexão recusada", "PostgreSQL não atendeu"),
    ('could not translate host name "srv" to address', "Não encontrei o servidor"),
])
def test_erro_ao_conectar_em_ingles_ou_portugues(mensagem, esperado):
    """O servidor instalado num Windows em português responde em português."""
    assert esperado in db.explicar_erro(psycopg.OperationalError(mensagem))


def test_erro_que_nao_e_do_banco_passa_como_esta():
    assert db.explicar_erro(ValueError("outra coisa")) == "outra coisa"


# ----------------------------------------------------------- telas --


@pytest.fixture()
def app():
    return QApplication.instance() or QApplication([])


def test_primeira_abertura_salva_a_conexao_que_funciona(app, parametros_de_teste, pc, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(a[2]))
    tela = local_banco.DialogoConexao(primeira_vez=True)
    tela.servidor.setText(parametros_de_teste.servidor)
    tela.porta.setValue(parametros_de_teste.porta)
    tela.banco.setText(parametros_de_teste.banco)
    tela.usuario.setText(parametros_de_teste.usuario)

    tela._salvar()

    assert tela.result() == QDialog.Accepted
    assert db.conexao_configurada().servidor == parametros_de_teste.servidor


def test_sem_servidor_nao_salva(app, pc, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    tela = local_banco.DialogoConexao(primeira_vez=True)

    tela._salvar()

    assert avisos == ["Preencha o servidor."]
    assert db.precisa_configurar()


def test_conexao_que_nao_funciona_so_salva_se_confirmar(app, pc, monkeypatch):
    perguntas = []

    def responder(*a, **k):
        perguntas.append(a[2])
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", responder)
    tela = local_banco.DialogoConexao(primeira_vez=True)
    tela.servidor.setText("127.0.0.1")
    tela.porta.setValue(1)

    tela._salvar()

    assert "Salvar esses dados assim mesmo?" in perguntas[0]
    assert db.precisa_configurar()


def test_banco_inacessivel_explica_e_mostra_a_conexao(app, parametros_de_teste):
    erro = psycopg.OperationalError("connection timeout expired")
    tela = local_banco.DialogoBancoInacessivel(erro)
    textos = " ".join(w.text() for w in tela.findChildren(local_banco.QLabel))
    assert "não respondeu" in textos
    assert parametros_de_teste.servidor in textos


def test_manual_ensina_a_preparar_o_servidor():
    from controle_lucros.ui.manual import TOPICOS

    (topico,) = [t for t in TOPICOS if t.id == "sistema.servidor"]
    for trecho in ("PostgreSQL 15", "Windows Server", "OWNER", "pg_hba.conf", "5432"):
        assert trecho in topico.corpo
