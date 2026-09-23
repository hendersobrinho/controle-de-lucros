"""O banco numa pasta do servidor, usado por vários PCs.

O programa roda instalado em cada PC e todos apontam pro mesmo arquivo no
servidor. O que quebra silencioso aqui: o modo de journal (WAL na rede
corrompe o banco), o caminho que cada PC guarda pra achar o banco, e o que
fica em cada PC em vez de ir pro servidor (o tema de um não pode virar o
de todos).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest

from controle_lucros import db, preferencias, repositories as repo
from controle_lucros.models import Empresa


@pytest.fixture()
def pc(monkeypatch, tmp_path):
    """Um PC com a configuração local numa pasta temporária — sem a
    CONTROLE_LUCROS_DB dos testes, que passaria por cima do banco escolhido."""
    monkeypatch.delenv("CONTROLE_LUCROS_DB", raising=False)
    monkeypatch.setattr(db, "_pasta_dados_padrao", lambda: tmp_path / "local")
    monkeypatch.setattr(db, "DEFAULT_DB_PATH", tmp_path / "local" / "controle_lucros.db")
    return tmp_path


@pytest.fixture()
def como_se_fosse_rede(monkeypatch):
    """Não dá pra montar um \\\\SERVIDOR de verdade no teste: finge que toda
    pasta é de rede, que é o que decide o modo de journal."""
    monkeypatch.setattr(db, "banco_em_rede", lambda caminho: True)


def _modo(conn) -> str:
    return str(conn.execute("PRAGMA journal_mode;").fetchone()[0]).lower()


# ---------------------------------------------------- o que é rede --


@pytest.mark.parametrize("caminho", [
    r"\\SERVIDOR\ControleDeLucros\controle_lucros.db",
    "//SERVIDOR/ControleDeLucros/controle_lucros.db",
    r"\\?\UNC\SERVIDOR\ControleDeLucros\controle_lucros.db",
])
def test_caminho_de_servidor_e_rede(caminho):
    assert db.banco_em_rede(caminho)


@pytest.mark.parametrize("caminho", [
    r"\\?\C:\ProgramData\ControleDeLucros\data\controle_lucros.db",
    "/home/fulano/controle_lucros.db",
])
def test_caminho_local_nao_e_rede(caminho):
    assert not db.banco_em_rede(caminho)


# ------------------------------------------------ modo de journal --


def test_no_servidor_o_banco_nao_usa_wal(tmp_path, como_se_fosse_rede):
    """WAL coordena os programas por memória compartilhada, que só existe
    dentro de uma máquina. Na rede, dois PCs gravando assim corrompem o
    banco."""
    conn = db.connect(tmp_path / "controle_lucros.db")
    assert _modo(conn) == "delete"
    conn.close()


def test_neste_computador_continua_em_wal(tmp_path):
    conn = db.connect(tmp_path / "controle_lucros.db")
    assert _modo(conn) == "wal"
    conn.close()


def test_banco_copiado_em_wal_pro_servidor_e_convertido(tmp_path, como_se_fosse_rede):
    """Alguém copiou à mão o banco de um PC (em WAL) pra pasta do servidor."""
    caminho = tmp_path / "controle_lucros.db"
    em_wal = sqlite3.connect(caminho)
    em_wal.execute("PRAGMA journal_mode = WAL;")
    em_wal.execute("CREATE TABLE marca (id INTEGER PRIMARY KEY)")
    em_wal.commit()
    em_wal.close()

    conn = db.connect(caminho)
    assert _modo(conn) == "delete"
    conn.close()


def test_banco_em_wal_aberto_por_outro_pc_nao_abre(tmp_path, como_se_fosse_rede):
    """Se não dá pra tirar do WAL porque outro PC está com ele aberto assim,
    abrir mesmo assim é o caso que corrompe — melhor recusar e explicar."""
    caminho = tmp_path / "controle_lucros.db"
    outro_pc = sqlite3.connect(caminho)
    outro_pc.execute("PRAGMA journal_mode = WAL;")
    outro_pc.execute("CREATE TABLE marca (id INTEGER PRIMARY KEY)")
    outro_pc.commit()
    outro_pc.execute("BEGIN")
    outro_pc.execute("SELECT * FROM marca").fetchall()

    with pytest.raises(db.BancoEmWalNaRede):
        db.connect(caminho)

    outro_pc.rollback()
    outro_pc.close()


def test_dois_pcs_gravam_no_banco_do_servidor(tmp_path, como_se_fosse_rede):
    caminho = tmp_path / "controle_lucros.db"
    primeiro = db.connect(caminho)
    db.init_schema(primeiro)
    segundo = db.connect(caminho)

    repo.salvar_empresa(primeiro, Empresa(None, "91", "ENDOGASTRO LTDA", "", 1000, 1000))
    repo.salvar_empresa(segundo, Empresa(None, "148", "RENAL NEFRON LTDA", "", 2000, 2000))

    esperado = ["ENDOGASTRO LTDA", "RENAL NEFRON LTDA"]
    assert [e.nome for e in repo.listar_empresas(primeiro)] == esperado
    assert [e.nome for e in repo.listar_empresas(segundo)] == esperado
    primeiro.close()
    segundo.close()


# ------------------------------------------- onde cada PC acha o banco --


def test_sem_escolha_usa_o_banco_deste_computador(pc):
    assert db.get_db_path() == pc / "local" / "controle_lucros.db"


def test_banco_escolhido_vale_pras_proximas_aberturas(pc):
    servidor = pc / "servidor" / "controle_lucros.db"
    db.definir_banco(servidor)
    assert db.get_db_path() == servidor

    db.definir_banco(None)
    assert db.get_db_path() == pc / "local" / "controle_lucros.db"


def test_a_escolha_fica_neste_pc_e_nao_junto_do_banco(pc):
    """O caminho até o servidor precisa ser lido ANTES de abrir o banco —
    guardado lá, não teria como achá-lo."""
    db.definir_banco(pc / "servidor" / "controle_lucros.db")
    assert (pc / "local" / db.ARQUIVO_CONFIG_LOCAL).exists()
    assert not (pc / "servidor").exists()


def test_configuracao_local_estragada_volta_ao_padrao(pc):
    (pc / "local").mkdir()
    (pc / "local" / db.ARQUIVO_CONFIG_LOCAL).write_text("{nao é json", encoding="utf-8")
    assert db.get_db_path() == pc / "local" / "controle_lucros.db"


def test_nao_migra_o_banco_antigo_pra_dentro_do_servidor(pc, monkeypatch):
    """Servidor fora do ar faz o banco parecer inexistente — não é hora de
    criar um lá com o cadastro velho de uma conta só."""
    monkeypatch.setattr(db, "banco_em_rede", lambda caminho: True)
    assert db.migrar_banco_por_usuario(pc / "servidor" / "controle_lucros.db") is None


# ------------------------------------------------ levar pro servidor --


def test_levar_o_banco_pro_servidor_leva_tudo(tmp_path):
    local = db.connect(tmp_path / "local.db")
    db.init_schema(local)
    # Fica no -wal, sem checkpoint: a cópia tem que trazer mesmo assim.
    repo.salvar_empresa(local, Empresa(None, "91", "ENDOGASTRO LTDA", "", 1000, 1000))

    destino = db.levar_banco_para(local, tmp_path / "servidor")
    local.close()

    assert destino == tmp_path / "servidor" / db.NOME_DO_ARQUIVO
    copia = sqlite3.connect(destino)
    assert _modo(copia) == "delete"
    assert [r[0] for r in copia.execute("SELECT nome FROM empresa")] == ["ENDOGASTRO LTDA"]
    copia.close()


def test_levar_nao_sobrescreve_o_banco_que_ja_esta_no_servidor(tmp_path):
    """O que está lá pode ser o trabalho do escritório inteiro."""
    (tmp_path / "servidor").mkdir()
    existente = tmp_path / "servidor" / db.NOME_DO_ARQUIVO
    existente.write_bytes(b"banco do escritorio")
    local = db.connect(tmp_path / "local.db")
    db.init_schema(local)

    with pytest.raises(FileExistsError):
        db.levar_banco_para(local, tmp_path / "servidor")

    local.close()
    assert existente.read_bytes() == b"banco do escritorio"


def test_reconhece_o_banco_do_sistema(tmp_path):
    conn = db.connect(tmp_path / "controle_lucros.db")
    db.init_schema(conn)
    conn.close()
    qualquer = tmp_path / "qualquer.db"
    sqlite3.connect(qualquer).close()
    lixo = tmp_path / "lixo.db"
    lixo.write_bytes(b"nao sou banco")

    assert db.e_banco_do_sistema(tmp_path / "controle_lucros.db")
    assert not db.e_banco_do_sistema(qualquer)
    assert not db.e_banco_do_sistema(lixo)
    assert not db.e_banco_do_sistema(tmp_path / "nao_existe.db")
    assert not (tmp_path / "nao_existe.db").exists()


# ------------------------------------------ preferências de cada PC --


def test_tema_fica_em_cada_computador(pc):
    """Com o banco no servidor, o tema escuro de um virava o de todos."""
    preferencias.salvar_chave("modo", "escuro")
    assert preferencias.obter("modo") == "escuro"
    assert "modo" not in preferencias.carregar()
    assert db.ler_config_local()["modo"] == "escuro"


def test_responsavel_do_informe_vale_pra_todos(pc):
    preferencias.guardar_responsavel_informe("FULANO DE TAL")
    assert preferencias.carregar()[preferencias.CHAVE_RESPONSAVEL_INFORME] == "FULANO DE TAL"
    assert preferencias.CHAVE_RESPONSAVEL_INFORME not in db.ler_config_local()


def test_tema_de_quem_atualizou_continua_o_mesmo(pc):
    """Até esta versão o tema ficava junto do banco."""
    arquivo = db.get_db_path().parent / "preferencias.json"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text('{"modo": "escuro"}', encoding="utf-8")
    assert preferencias.obter("modo") == "escuro"


# ------------------------------------------------- mensagens de erro --


def test_rede_caida_vira_mensagem_que_diz_o_que_fazer():
    texto = db.explicar_erro(sqlite3.OperationalError("disk I/O error"))
    assert "rede" in texto
    assert "disk I/O" not in texto


def test_banco_ocupado_vira_mensagem_que_diz_o_que_fazer():
    texto = db.explicar_erro(sqlite3.OperationalError("database is locked"))
    assert "outro computador" in texto


def test_outros_erros_passam_como_estao():
    assert db.explicar_erro(ValueError("CNPJ inválido")) == "CNPJ inválido"
    assert db.explicar_erro(sqlite3.OperationalError("no such table: x")) == "no such table: x"


# ------------------------------------------------ tela de primeiro acesso --


def test_pc_novo_pode_apontar_pro_banco_do_servidor(monkeypatch, tmp_path):
    """A primeira tela de um PC novo é a de criar usuário (o banco local está
    vazio). Dali ele precisa conseguir ir pro banco do servidor."""
    from PySide6.QtWidgets import QApplication

    from controle_lucros.ui import login

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(login, "escolher_banco_existente", lambda parent: tmp_path / "x.db")
    conn = db.connect(tmp_path / "vazio.db")
    db.init_schema(conn)

    dialogo = login.DialogoPrimeiroUsuario(conn)
    dialogo._usar_banco_do_servidor()

    assert dialogo.trocou_banco
    assert dialogo.result() == login.QDialog.Rejected
    conn.close()


# ------------------------------------------- primeira abertura do PC --


def test_instalacao_nova_pergunta_onde_fica_o_banco(pc):
    assert db.precisa_configurar()


def test_pc_que_ja_escolheu_nao_pergunta_de_novo(pc):
    db.definir_banco(pc / "servidor" / "controle_lucros.db")
    assert not db.precisa_configurar()


def test_pc_que_ja_tinha_banco_local_nao_pergunta(pc):
    """Quem atualiza o programa não é instalação nova."""
    db.connect(db.DEFAULT_DB_PATH).close()
    assert not db.precisa_configurar()


def test_criar_banco_novo_na_pasta(tmp_path):
    caminho = db.criar_banco_em(tmp_path / "servidor")
    assert caminho == tmp_path / "servidor" / db.NOME_DO_ARQUIVO
    assert db.e_banco_do_sistema(caminho)


def test_criar_nao_passa_por_cima_do_banco_de_outro_pc(tmp_path):
    existente = db.criar_banco_em(tmp_path / "servidor")
    conn = db.connect(existente)
    repo.salvar_empresa(conn, Empresa(None, "91", "ENDOGASTRO LTDA", "", 1000, 1000))
    conn.close()

    with pytest.raises(FileExistsError):
        db.criar_banco_em(tmp_path / "servidor")

    conn = db.connect(existente)
    assert [e.nome for e in repo.listar_empresas(conn)] == ["ENDOGASTRO LTDA"]
    conn.close()


@pytest.fixture()
def tela(monkeypatch):
    """Diálogos do Qt respondidos pelo teste: a pasta escolhida e a resposta
    às perguntas (guardadas pra conferir o que foi perguntado)."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from controle_lucros.ui import local_banco

    QApplication.instance() or QApplication([])
    estado = {"pasta": "", "resposta": QMessageBox.Yes, "perguntas": [], "avisos": []}
    monkeypatch.setattr(local_banco.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: estado["pasta"]))

    def perguntar(parent, titulo, *a, **k):
        estado["perguntas"].append(titulo)
        return estado["resposta"]

    monkeypatch.setattr(local_banco.QMessageBox, "question", staticmethod(perguntar))
    monkeypatch.setattr(local_banco.QMessageBox, "warning",
                        staticmethod(lambda parent, titulo, *a, **k: estado["avisos"].append(titulo)))
    estado["modulo"] = local_banco
    return estado


def test_segundo_pc_escolhe_a_mesma_pasta_e_usa_o_mesmo_banco(pc, tela):
    """O primeiro PC criou; o segundo aponta pra mesma pasta. Os dois ficam
    no MESMO arquivo — é o que faz todos verem o mesmo cadastro."""
    existente = db.criar_banco_em(pc / "servidor")
    tela["pasta"] = str(pc / "servidor")

    assert tela["modulo"].escolher_banco_existente() == existente
    assert db.get_db_path() == existente


def test_usar_pasta_sem_banco_avisa_e_nao_cria_nada(pc, tela):
    (pc / "servidor").mkdir()
    tela["pasta"] = str(pc / "servidor")

    assert tela["modulo"].escolher_banco_existente() is None
    assert tela["avisos"] == ["Não há banco nesta pasta"]
    assert db.banco_configurado() is None
    assert not (pc / "servidor" / db.NOME_DO_ARQUIVO).exists()


def test_criar_onde_ja_ha_banco_oferece_usar_o_que_esta_la(pc, tela, monkeypatch):
    """O engano mais provável: escolher "criar" no segundo PC. Em vez de dar
    erro ou criar outro cadastro, oferece usar o que já existe."""
    existente = db.criar_banco_em(pc / "servidor")
    tela["pasta"] = str(pc / "servidor")

    assert tela["modulo"].criar_banco_novo() == existente
    assert tela["perguntas"] == ["Já existe um banco nesta pasta"]
    assert db.get_db_path() == existente


def test_criar_na_pasta_do_servidor(pc, tela, monkeypatch):
    monkeypatch.setattr(db, "banco_em_rede", lambda caminho: True)
    tela["pasta"] = str(pc / "servidor")

    caminho = tela["modulo"].criar_banco_novo()

    assert caminho == pc / "servidor" / db.NOME_DO_ARQUIVO
    assert tela["perguntas"] == []
    assert db.get_db_path() == caminho


def test_criar_numa_pasta_local_confirma_antes(pc, tela):
    """Os outros PCs não enxergariam — vale perguntar."""
    tela["pasta"] = str(pc / "pasta_local")
    tela["resposta"] = tela["modulo"].QMessageBox.No

    assert tela["modulo"].criar_banco_novo() is None
    assert tela["perguntas"] == ["Pasta deste computador"]
    assert not (pc / "pasta_local" / db.NOME_DO_ARQUIVO).exists()


def test_so_neste_computador_nao_pergunta_mais(pc, tela):
    dialogo = tela["modulo"].DialogoConfigurarBanco()
    dialogo._so_neste()
    assert dialogo.result() == tela["modulo"].QDialog.Accepted
    db.connect(db.get_db_path()).close()
    assert not db.precisa_configurar()


# ------------------------------------------- escolha feita no instalador --


def _instalador_gravou(pc, texto: str) -> None:
    """Como o Inno Setup grava: UTF-8 com BOM."""
    (pc / "local").mkdir(exist_ok=True)
    (pc / "local" / db.ARQUIVO_CONFIG_LOCAL).write_bytes(b"\xef\xbb\xbf" + texto.encode("utf-8"))


def _json(caminho) -> str:
    return str(caminho).replace("\\", "\\\\")


def test_le_o_banco_escolhido_no_instalador(pc):
    servidor = pc / "servidor" / "controle_lucros.db"
    _instalador_gravou(pc, '{"banco": "%s"}' % _json(servidor))
    assert db.get_db_path() == servidor
    assert not db.precisa_configurar()


def test_so_neste_computador_escolhido_no_instalador_nao_pergunta_de_novo(pc):
    _instalador_gravou(pc, '{"banco": ""}')
    assert not db.precisa_configurar()
    assert db.get_db_path() == pc / "local" / "controle_lucros.db"


def test_banco_configurado_que_sumiu_nao_vira_banco_novo(pc):
    """Caminho errado ou arquivo movido: o SQLite criaria um banco vazio e o
    PC pediria um primeiro usuário como se o escritório nunca tivesse usado
    o sistema."""
    servidor = pc / "servidor"
    servidor.mkdir()
    db.definir_banco(servidor / "controle_lucros.db")

    with pytest.raises(db.BancoNaoEncontrado):
        db.verificar_banco_configurado()
    assert not (servidor / "controle_lucros.db").exists()


def test_banco_novo_pedido_no_instalador_e_criado_uma_vez(pc):
    servidor = pc / "servidor" / "controle_lucros.db"
    _instalador_gravou(pc, '{"banco": "%s", "criar_banco": true}' % _json(servidor))

    db.verificar_banco_configurado()  # pedido de criar: não reclama
    conn = db.connect()
    db.init_schema(conn)
    db.banco_aberto_com_sucesso()
    conn.close()

    assert db.e_banco_do_sistema(servidor)
    # Criado, o pedido acaba: se o arquivo sumir depois, é erro, não banco novo.
    assert db.CHAVE_CRIAR not in db.ler_config_local()
    servidor.unlink()
    with pytest.raises(db.BancoNaoEncontrado):
        db.verificar_banco_configurado()


def test_mensagem_de_banco_nao_encontrado_diz_o_caminho(pc):
    db.definir_banco(pc / "servidor" / "controle_lucros.db")
    with pytest.raises(db.BancoNaoEncontrado) as erro:
        db.verificar_banco_configurado()
    assert str(pc / "servidor" / "controle_lucros.db") in db.explicar_erro(erro.value)


# ----------------------------------------- tutorial do caminho do servidor --


def test_letra_mapeada_vira_caminho_de_rede(monkeypatch):
    """Z: é de cada conta do Windows; guardado assim, o caminho só funciona
    pra quem escolheu."""
    monkeypatch.setattr(db.sys, "platform", "win32")
    monkeypatch.setattr(db, "_destino_da_unidade",
                        lambda unidade: r"\\SRV-ESCRITORIO\ControleDeLucros" if unidade == "Z:" else None)

    assert str(db.caminho_de_rede(r"Z:\banco")) == str(db.Path(r"\\SRV-ESCRITORIO\ControleDeLucros\banco"))
    assert str(db.caminho_de_rede(r"C:\ProgramData")) == str(db.Path(r"C:\ProgramData"))
    assert str(db.caminho_de_rede(r"\\SRV\pasta")) == str(db.Path(r"\\SRV\pasta"))


def test_fora_do_windows_o_caminho_volta_como_veio():
    assert db.caminho_de_rede("/mnt/servidor") == db.Path("/mnt/servidor")


def test_manual_ensina_a_montar_o_caminho_do_servidor():
    from controle_lucros.ui import manual

    topico = next(t for t in manual.TOPICOS if t.id == "sistema.servidor")
    for trecho in (r"\\SRV-ESCRITORIO\ControleDeLucros", "Compartilhamento Avançado",
                   "hostname", "net use", "barra de endereço", "Segurança"):
        assert trecho in topico.corpo


@pytest.mark.parametrize("montar", [
    lambda lb: lb.DialogoConfigurarBanco(),
    lambda lb: lb.DialogoBancoInacessivel(sqlite3.OperationalError("disk I/O error")),
])
def test_telas_de_escolher_o_banco_levam_ao_tutorial(tela, monkeypatch, montar):
    from PySide6.QtWidgets import QPushButton

    from controle_lucros.ui import manual

    abertos = []
    monkeypatch.setattr(manual.DialogoManual, "exec", lambda self: abertos.append(
        self.lista.currentItem().text()))
    dialogo = montar(tela["modulo"])
    botao = next(b for b in dialogo.findChildren(QPushButton)
                 if b.text() == "Como configurar o caminho do servidor?")
    botao.click()
    assert abertos == ["Caminho do servidor"]


# ------------------------------------------------------ regressões --


def test_reconhecer_banco_nao_usa_uri(tmp_path, monkeypatch):
    """Pra \\\\SERVIDOR\\pasta, a URI "file:...?mode=ro" vira
    file://SERVIDOR/..., que o SQLite recusa: todo banco do servidor era dado
    como "não reconhecido". Não dá pra montar um \\\\SERVIDOR aqui, então
    o teste garante que a URI não volta."""
    caminho = db.criar_banco_em(tmp_path)
    original = sqlite3.connect

    def sem_uri(*args, **kwargs):
        assert not kwargs.get("uri"), "URI quebra com caminho de servidor"
        return original(*args, **kwargs)

    monkeypatch.setattr(db.sqlite3, "connect", sem_uri)
    assert db.e_banco_do_sistema(caminho)


def test_backup_nao_fica_em_wal(tmp_path):
    """A cópia herdaria o WAL do banco local — e levaria o WAL junto ao ser
    restaurada no servidor."""
    from controle_lucros import backup

    local = db.connect(tmp_path / "local.db")
    db.init_schema(local)
    copia = backup.criar_backup(local, tmp_path / "backups")
    local.close()

    conn = sqlite3.connect(copia)
    assert _modo(conn) == "delete"
    conn.close()


def test_restaurar_backup_antigo_em_wal_no_servidor_nao_liga_o_wal(tmp_path, como_se_fosse_rede):
    """Backup feito por versão anterior está em WAL. Restaurado no banco do
    servidor com outro PC usando, o WAL chegaria junto — o modo que corrompe."""
    from controle_lucros import backup

    em_wal = sqlite3.connect(tmp_path / "backup_antigo.db")
    em_wal.execute("PRAGMA journal_mode = WAL;")
    em_wal.close()
    conn_antigo = sqlite3.connect(tmp_path / "backup_antigo.db")
    conn_antigo.row_factory = sqlite3.Row
    db.init_schema(conn_antigo)
    conn_antigo.close()

    servidor = db.criar_banco_em(tmp_path / "servidor")
    outro_pc = db.connect(servidor)

    backup.restaurar_backup(tmp_path / "backup_antigo.db", servidor)

    assert _modo(outro_pc) == "delete"
    novo = sqlite3.connect(servidor)
    assert _modo(novo) == "delete"
    novo.close()
    outro_pc.close()
