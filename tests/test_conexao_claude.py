"""Conectar ao Claude: grava a configuração sem estragar a que já existe."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros import conexao_claude as claude


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config(tmp_path, monkeypatch):
    arquivo = tmp_path / "Claude" / "claude_desktop_config.json"
    monkeypatch.setattr(claude, "arquivos_claude_desktop", lambda: [arquivo])
    return arquivo


def test_conectar_cria_o_arquivo_apontando_para_o_servidor(config):
    assert claude.situacao_claude_desktop() == "desconectado"
    claude.conectar_claude_desktop()
    entrada = json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["controle-de-lucros"]
    comando, argumentos = claude.comando_do_servidor()
    assert entrada == {"command": comando, "args": argumentos}
    assert argumentos[0].endswith("servidor_mcp.py") and claude.servidor_disponivel()
    assert claude.situacao_claude_desktop() == "conectado"


def test_conectar_preserva_o_resto_e_guarda_copia(config):
    config.parent.mkdir(parents=True)
    original = {"preferencias": {"tema": "escuro"}, "mcpServers": {"outro": {"command": "x"}}}
    config.write_text(json.dumps(original), encoding="utf-8")
    claude.conectar_claude_desktop(cpf_completo=True)
    dados = json.loads(config.read_text(encoding="utf-8"))
    assert dados["preferencias"] == {"tema": "escuro"}
    assert dados["mcpServers"]["outro"] == {"command": "x"}
    assert dados["mcpServers"]["controle-de-lucros"]["env"] == {"CONTROLE_LUCROS_MCP_DOCUMENTOS": "completos"}
    assert json.loads(config.with_name(config.name + ".bak").read_text(encoding="utf-8")) == original


def test_json_invalido_nao_e_sobrescrito(config):
    config.parent.mkdir(parents=True)
    config.write_text("{ isto não é json", encoding="utf-8")
    with pytest.raises(ValueError, match="não é um JSON válido"):
        claude.conectar_claude_desktop()
    assert config.read_text(encoding="utf-8") == "{ isto não é json"


def test_programa_em_outra_pasta_aparece_como_outro_e_desconectar_remove(config):
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"mcpServers": {"controle-de-lucros": {"command": "C:\\velho.exe", "args": []}}}),
                      encoding="utf-8")
    assert claude.situacao_claude_desktop() == "outro"
    claude.desconectar_claude_desktop()
    assert json.loads(config.read_text(encoding="utf-8")) == {"mcpServers": {}}
    assert claude.situacao_claude_desktop() == "desconectado"


def test_empacotado_usa_o_exe_ao_lado_do_programa(monkeypatch, tmp_path):
    monkeypatch.setattr(claude.sys, "frozen", True, raising=False)
    monkeypatch.setattr(claude.sys, "executable", str(tmp_path / "ControleDeLucros.exe"))
    comando, argumentos = claude.comando_do_servidor()
    assert argumentos == [] and comando.startswith(str(tmp_path)) and "ControleDeLucrosMCP" in comando
    assert not claude.servidor_disponivel()


def test_claude_code_sem_o_comando_explica(monkeypatch):
    monkeypatch.setattr(claude.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="não está instalado"):
        claude.conectar_claude_code()


def test_claude_code_remove_e_registra_para_o_usuario(monkeypatch):
    chamadas = []
    monkeypatch.setattr(claude.shutil, "which", lambda _: "/bin/claude")
    monkeypatch.setattr(claude.subprocess, "run",
                        lambda args, **kw: chamadas.append(args) or claude.subprocess.CompletedProcess(args, 0, "", ""))
    claude.conectar_claude_code()
    assert chamadas[0][1:] == ["mcp", "remove", "--scope", "user", "controle-de-lucros"]
    comando, argumentos = claude.comando_do_servidor()
    assert chamadas[1][1:] == ["mcp", "add", "--scope", "user", "controle-de-lucros", "--", comando, *argumentos]


def test_janela_mostra_a_situacao_e_conecta(config, monkeypatch):
    from controle_lucros.ui.conectar_claude import DialogoConectarClaude
    monkeypatch.setattr(claude.shutil, "which", lambda _: None)
    monkeypatch.setattr("controle_lucros.ui.conectar_claude.QMessageBox.information", lambda *a: None)
    janela = DialogoConectarClaude()
    assert janela.desktop["situacao"].text() == "não conectado"
    assert janela.code["situacao"].text() == "não instalado" and not janela.code["conectar"].isEnabled()
    janela.desktop["conectar"].click()
    assert janela.desktop["situacao"].text() == "✓ conectado"
    assert claude.situacao_claude_desktop() == "conectado"


def test_botao_na_tela_de_entrada(conn):
    from PySide6.QtWidgets import QPushButton
    from controle_lucros.ui.login import DialogoLogin, DialogoPrimeiroUsuario
    for dialogo in (DialogoLogin(conn), DialogoPrimeiroUsuario(conn)):
        assert "Conectar ao Claude…" in [b.text() for b in dialogo.findChildren(QPushButton)]
