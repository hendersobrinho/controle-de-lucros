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
