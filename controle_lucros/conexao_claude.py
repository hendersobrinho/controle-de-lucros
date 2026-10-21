"""Liga o Claude (Desktop e Code) ao servidor MCP deste PC, sem ninguém
precisar editar JSON à mão.

Claude Desktop: acrescenta o servidor em claude_desktop_config.json,
preservando o que já estiver lá (outros servidores, preferências) e
guardando uma cópia .bak do arquivo antes. Claude Code: pelo próprio
comando "claude mcp add", quando ele está instalado.

O servidor que o Claude abre é o ControleDeLucrosMCP.exe ao lado do
programa, quando instalado; rodando do código-fonte, o servidor_mcp.py da
raiz com o mesmo Python.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

NOME = "controle-de-lucros"
VARIAVEL_DOCUMENTOS = "CONTROLE_LUCROS_MCP_DOCUMENTOS"


def comando_do_servidor() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        pasta = Path(sys.executable).resolve().parent
        nome = "ControleDeLucrosMCP.exe" if sys.platform == "win32" else "ControleDeLucrosMCP"
        return str(pasta / nome), []
    raiz = Path(__file__).resolve().parent.parent
    return sys.executable, [str(raiz / "servidor_mcp.py")]


def servidor_disponivel() -> bool:
    comando, argumentos = comando_do_servidor()
    return Path(argumentos[0] if argumentos else comando).exists()


# ------------------------------------------------------------ Claude Desktop --


def arquivos_claude_desktop() -> list[Path]:
    """Onde o Claude Desktop lê a configuração. No Windows, a versão da
    Microsoft Store guarda numa pasta própria do pacote; se ela existir,
    grava-se nas duas, porque não há como saber qual das duas está em uso."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        caminhos = [base / "Claude" / "claude_desktop_config.json"]
        locais = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        caminhos += sorted(
            p / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"
            for p in (locais / "Packages").glob("Claude_*") if p.is_dir()
        )
        return caminhos
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]
    return [Path.home() / ".config" / "Claude" / "claude_desktop_config.json"]


def _ler(arquivo: Path) -> dict:
    if not arquivo.exists() or not arquivo.read_text(encoding="utf-8").strip():
        return {}
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erro:
        # Sobrescrever um arquivo que não se entendeu apagaria a configuração
        # de outra coisa: melhor parar e dizer.
        raise ValueError(f"O arquivo {arquivo} não é um JSON válido (linha {erro.lineno}). "
                         "Corrija ou apague o arquivo e tente de novo.") from erro
    if not isinstance(dados, dict):
        raise ValueError(f"O arquivo {arquivo} não tem o formato esperado.")
    return dados


def _gravar(arquivo: Path, dados: dict) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if arquivo.exists():
        shutil.copy2(arquivo, arquivo.with_name(arquivo.name + ".bak"))
    temporario = arquivo.with_name(arquivo.name + ".tmp")
    temporario.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporario, arquivo)


def entrada_do_servidor(cpf_completo: bool = False) -> dict:
    comando, argumentos = comando_do_servidor()
    entrada: dict = {"command": comando, "args": argumentos}
    if cpf_completo:
        entrada["env"] = {VARIAVEL_DOCUMENTOS: "completos"}
    return entrada


def situacao_claude_desktop() -> str:
    """"conectado" (aponta para o servidor deste programa), "outro" (há uma
    entrada com o nosso nome, mas para outro caminho — programa movido ou
    reinstalado em outro lugar) ou "desconectado"."""
    esperado = comando_do_servidor()
    achou_outro = False
    for arquivo in arquivos_claude_desktop():
        try:
            entrada = _ler(arquivo).get("mcpServers", {}).get(NOME)
        except ValueError:
            continue
        if entrada:
            if (entrada.get("command"), entrada.get("args", [])) == (esperado[0], esperado[1]):
                return "conectado"
            achou_outro = True
    return "outro" if achou_outro else "desconectado"


def conectar_claude_desktop(cpf_completo: bool = False) -> list[Path]:
    """Grava o servidor na configuração do Claude Desktop e devolve os
    arquivos alterados. Só passa a valer depois de fechar e abrir o Claude."""
    gravados = []
    for arquivo in arquivos_claude_desktop():
        dados = _ler(arquivo)
        servidores = dados.get("mcpServers")
        if not isinstance(servidores, dict):
            servidores = {}
        servidores[NOME] = entrada_do_servidor(cpf_completo)
        dados["mcpServers"] = servidores
        _gravar(arquivo, dados)
        gravados.append(arquivo)
    return gravados


def desconectar_claude_desktop() -> list[Path]:
    gravados = []
    for arquivo in arquivos_claude_desktop():
        dados = _ler(arquivo)
        if NOME in dados.get("mcpServers", {}):
            del dados["mcpServers"][NOME]
            _gravar(arquivo, dados)
            gravados.append(arquivo)
    return gravados


# --------------------------------------------------------------- Claude Code --


def comando_claude_code() -> str | None:
    return shutil.which("claude")


def _rodar_claude(*argumentos: str) -> subprocess.CompletedProcess:
    sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run([comando_claude_code(), *argumentos], capture_output=True, text=True,
                          timeout=60, creationflags=sem_janela)


def conectar_claude_code(cpf_completo: bool = False) -> None:
    """Registra para o usuário do Windows (vale em qualquer pasta). Remove
    antes o registro anterior, se houver — o "add" não substitui."""
    if comando_claude_code() is None:
        raise ValueError("O Claude Code não está instalado neste computador (não achei o comando \"claude\").")
    _rodar_claude("mcp", "remove", "--scope", "user", NOME)
    comando, argumentos = comando_do_servidor()
    ambiente = ["-e", f"{VARIAVEL_DOCUMENTOS}=completos"] if cpf_completo else []
    resultado = _rodar_claude("mcp", "add", "--scope", "user", *ambiente, NOME, "--", comando, *argumentos)
    if resultado.returncode != 0:
        raise ValueError((resultado.stderr or resultado.stdout or "o comando falhou").strip())


def desconectar_claude_code() -> None:
    if comando_claude_code() is not None:
        _rodar_claude("mcp", "remove", "--scope", "user", NOME)
