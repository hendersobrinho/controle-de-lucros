"""Preferências persistidas localmente num JSON só (tema, pasta de backup,
etc.) — cada funcionalidade lê/grava sua própria chave sem apagar as outras,
porque salvar sempre relê o arquivo inteiro antes de escrever de volta."""
from __future__ import annotations

import json
from pathlib import Path

from . import db


def _arquivo() -> Path:
    """Recalculado a cada chamada (não guardado em constante de módulo) pra
    respeitar CONTROLE_LUCROS_DB mesmo se definido depois do import — o
    mesmo comportamento de db.get_db_path()."""
    return db.get_db_path().parent / "preferencias.json"


def carregar() -> dict:
    try:
        return json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def obter(chave: str, padrao=None):
    return carregar().get(chave, padrao)


def salvar_chave(chave: str, valor) -> None:
    dados = carregar()
    dados[chave] = valor
    arquivo = _arquivo()
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


CHAVE_ULTIMO_LOGIN = "ultimo_login"
CHAVE_SESSAO = "sessao_salva"


def ultimo_login() -> str:
    """Último login que entrou com sucesso, pra já vir preenchido na tela.
    Só o nome de usuário — senha não é guardada em lugar nenhum."""
    return str(obter(CHAVE_ULTIMO_LOGIN) or "")


def guardar_ultimo_login(login: str) -> None:
    salvar_chave(CHAVE_ULTIMO_LOGIN, login)


def sessao_salva() -> tuple[int, str] | None:
    """(usuario_id, token) do "continuar conectado", ou None. O token vale
    só nesta máquina: o que o banco guarda é o hash dele."""
    dados = obter(CHAVE_SESSAO)
    if not isinstance(dados, dict):
        return None
    usuario_id, token = dados.get("usuario_id"), dados.get("token")
    if not isinstance(usuario_id, int) or not isinstance(token, str) or not token:
        return None
    return usuario_id, token


def guardar_sessao(usuario_id: int, token: str) -> None:
    salvar_chave(CHAVE_SESSAO, {"usuario_id": usuario_id, "token": token})


def esquecer_sessao() -> None:
    salvar_chave(CHAVE_SESSAO, None)
