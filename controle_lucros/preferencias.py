"""Preferências persistidas em JSON — cada funcionalidade lê/grava sua
própria chave sem apagar as outras, porque salvar sempre relê o arquivo
inteiro antes de escrever de volta.

São dois arquivos. O preferencias.json fica ao lado do banco e vale pra todo
mundo que usa aquele banco (pasta de backup, quem assina o informe). As
chaves em CHAVES_DO_COMPUTADOR ficam na configuração local de cada PC: com o
banco no servidor, o tema escuro de um virava o tema de todos."""
from __future__ import annotations

import json
from pathlib import Path

from . import db


def _arquivo() -> Path:
    """Recalculado a cada chamada (não guardado em constante de módulo) pra
    respeitar CONTROLE_LUCROS_DB mesmo se definido depois do import — o
    mesmo comportamento de db.get_db_path()."""
    return db.get_db_path().parent / "preferencias.json"


# Gosto de quem está sentado naquele PC, não regra do escritório.
CHAVES_DO_COMPUTADOR = {"modo", "importacao_formato"}


def carregar() -> dict:
    try:
        return json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def obter(chave: str, padrao=None):
    if chave in CHAVES_DO_COMPUTADOR:
        local = db.ler_config_local()
        if chave in local:
            return local[chave]
        # Quem atualiza de uma versão que guardava tudo junto do banco
        # continua com o tema que tinha, até trocar de novo.
    return carregar().get(chave, padrao)


def salvar_chave(chave: str, valor) -> None:
    if chave in CHAVES_DO_COMPUTADOR:
        try:
            db.gravar_config_local(chave, valor)
        except OSError:
            pass
        return
    dados = carregar()
    dados[chave] = valor
    arquivo = _arquivo()
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


CHAVE_RESPONSAVEL_INFORME = "responsavel_informe"


def responsavel_informe() -> str:
    """Quem assina o informe de rendimentos (Quadro 8). É quase sempre a
    mesma pessoa em todos os informes do escritório, então fica guardado e
    vem preenchido — sem impedir de trocar num informe específico."""
    return str(obter(CHAVE_RESPONSAVEL_INFORME) or "")


def guardar_responsavel_informe(nome: str) -> None:
    salvar_chave(CHAVE_RESPONSAVEL_INFORME, nome.strip())
