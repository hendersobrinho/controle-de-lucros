"""Isolamento dos testes do ambiente real.

Sem isto, qualquer teste que construa uma tela acaba gravando no
data/preferencias.json de verdade — o mesmo arquivo que guarda o tema, a pasta
de backup e o último formato de importação de quem usa o sistema. Rodar a
suíte não pode mexer na configuração de ninguém.

CONTROLE_LUCROS_DB é o que db.get_db_path() consulta, e preferencias._arquivo()
deriva dele, então apontar essa variável para uma pasta temporária redireciona
os dois de uma vez.
"""
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def dados_isolados(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("dados")
    anterior = os.environ.get("CONTROLE_LUCROS_DB")
    os.environ["CONTROLE_LUCROS_DB"] = str(pasta / "controle_lucros.db")
    yield pasta
    if anterior is None:
        os.environ.pop("CONTROLE_LUCROS_DB", None)
    else:
        os.environ["CONTROLE_LUCROS_DB"] = anterior
