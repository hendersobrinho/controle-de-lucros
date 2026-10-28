"""Alteração contratual como documento: cada uma com os seus movimentos.

Os casos que motivaram a mudança: dez sócios entrando juntos viravam dez
alterações, e mexer na participação por uma alteração mudava o que a outra
registrou.
"""
import pytest

from controle_lucros import repositories as repo
from controle_lucros.models import AlteracaoContratual, Empresa, Socio, VinculoSocietario


@pytest.fixture()
def ano_2025(monkeypatch):
    monkeypatch.setattr(repo, "_ano_corrente", lambda: 2025)


@pytest.fixture()
def empresa(conn):
    return repo.salvar_empresa(conn, Empresa(None, "001", "ACME", "", 100_000, 100_000))


def _socio(conn, nome, cpf=""):
    return repo.salvar_socio(conn, Socio(None, nome, cpf))


def _alteracao(conn, empresa, numero, data, capital=100_000, cotas=100_000):
    return repo.salvar_alteracao(conn, AlteracaoContratual(None, empresa, numero, data, "ACME", capital, cotas, ""))


def _ativos(conn, empresa, data):
    return {
        v.socio_id: v for v in repo.listar_vinculos_empresa(conn, empresa)
        if v.data_entrada <= data and (v.data_saida is None or v.data_saida > data)
    }


# ------------------------------------------------- uma alteração, vários sócios --


def test_varios_socios_no_mesmo_dia_sao_uma_alteracao(conn, empresa, ano_2025):
    socios = [_socio(conn, f"SOCIO {i}") for i in range(10)]
    for socio in socios:
        repo.associar_socio_a_empresa(conn, empresa, socio, 10, 10_000, "2025-03-01")
    (alteracao,) = repo.listar_alteracoes(conn, empresa)
    assert len(repo.listar_movimentos(conn, alteracao.id)) == 10
    # Saída e mudança no mesmo dia, em outro momento, também caem nela.
    ativo = _ativos(conn, empresa, "2025-03-01")
    repo.encerrar_vinculo_registrando_alteracao(conn, ativo[socios[0]], "2025-06-01")
    repo.atualizar_cotas_vinculo(conn, ativo[socios[1]], 20, 20_000, "2025-06-01")
    junho = [a for a in repo.listar_alteracoes(conn, empresa) if a.data == "2025-06-01"]
    assert len(junho) == 1
    assert {m["tipo"] for m in repo.listar_movimentos(conn, junho[0].id)} == {"saida", "participacao"}


# ---------------------------------------- cada alteração com o que registrou --


@pytest.fixture()
def duas_alteracoes(conn, empresa):
    """Nº 1 (2023): X entra com 10%. Nº 2 (2024): X passa a 20% e Y entra."""
    x, y = _socio(conn, "XAVIER"), _socio(conn, "YARA")
    a1 = _alteracao(conn, empresa, 1, "2023-01-01")
    a2 = _alteracao(conn, empresa, 2, "2024-01-01")
    repo.salvar_movimento(conn, a1, x, "entrada", percentual=10, cotas=10_000)
    repo.salvar_movimento(conn, a2, x, "participacao", percentual=20, cotas=20_000)
    repo.salvar_movimento(conn, a2, y, "entrada", percentual=30, cotas=30_000)
    return {"x": x, "y": y, "a1": a1, "a2": a2}


def test_quadro_sai_dos_movimentos_na_ordem(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    em_2023 = _ativos(conn, empresa, "2023-06-01")
    em_2024 = _ativos(conn, empresa, "2024-06-01")
    assert set(em_2023) == {d["x"]} and em_2023[d["x"]].percentual_capital == 10
    assert em_2024[d["x"]].percentual_capital == 20 and em_2024[d["y"]].percentual_capital == 30
    ficha = repo.ficha_alteracao(conn, d["a2"])
    assert ficha["mudancas"] == ["XAVIER"] and ficha["entradas"] == ["YARA"]


def test_corrigir_a_primeira_nao_muda_a_segunda(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    repo.salvar_movimento(conn, d["a1"], d["x"], "entrada", percentual=15, cotas=15_000)
    (movimento_a2,) = [m for m in repo.listar_movimentos(conn, d["a2"]) if m["socio_id"] == d["x"]]
    assert movimento_a2["percentual_capital"] == 20  # a Nº 2 continua com o que registrou
    assert _ativos(conn, empresa, "2023-06-01")[d["x"]].percentual_capital == 15
    assert _ativos(conn, empresa, "2024-06-01")[d["x"]].percentual_capital == 20


def test_corrigir_pela_aba_socios_mexe_so_na_alteracao_da_participacao(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    vinculo_2023 = _ativos(conn, empresa, "2023-06-01")[d["x"]]
    vinculo_2023.percentual_capital = 12
    repo.salvar_vinculo(conn, vinculo_2023)
    movimentos = {m["alteracao_id"]: m for a in (d["a1"], d["a2"])
                  for m in repo.listar_movimentos(conn, a) if m["socio_id"] == d["x"]}
    assert movimentos[d["a1"]]["percentual_capital"] == 12
    assert movimentos[d["a2"]]["percentual_capital"] == 20


def test_data_de_saida_que_e_da_outra_alteracao_nao_muda_por_aqui(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    vinculo_2023 = _ativos(conn, empresa, "2023-06-01")[d["x"]]
    vinculo_2023.data_saida = "2023-09-01"
    with pytest.raises(ValueError, match="alteração Nº 2"):
        repo.salvar_vinculo(conn, vinculo_2023)


def test_mudar_a_data_da_alteracao_leva_os_movimentos(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    a2 = repo.buscar_alteracao(conn, d["a2"])
    a2.data = "2024-07-01"
    repo.salvar_alteracao(conn, a2)
    assert _ativos(conn, empresa, "2024-03-01")[d["x"]].percentual_capital == 10
    assert d["y"] not in _ativos(conn, empresa, "2024-03-01")
    assert _ativos(conn, empresa, "2024-08-01")[d["x"]].percentual_capital == 20


def test_excluir_a_segunda_volta_ao_quadro_da_primeira(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    repo.excluir_alteracao(conn, d["a2"])
    ativos = _ativos(conn, empresa, "2025-01-01")
    assert set(ativos) == {d["x"]} and ativos[d["x"]].percentual_capital == 10
    assert ativos[d["x"]].data_saida is None


def test_saida_e_participacao_so_de_quem_era_socio(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    z = _socio(conn, "ZECA")
    with pytest.raises(ValueError, match="não é sócio"):
        repo.salvar_movimento(conn, d["a2"], z, "saida")
    with pytest.raises(ValueError, match="já é sócio"):
        repo.salvar_movimento(conn, d["a2"], d["x"], "entrada", percentual=1)


def test_periodo_trancado_barra_e_nao_deixa_nada_pela_metade(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    repo.fechar_periodo(conn, empresa, 2023)
    with pytest.raises(ValueError, match="trancado"):
        repo.salvar_movimento(conn, d["a1"], d["x"], "entrada", percentual=99)
    (movimento,) = repo.listar_movimentos(conn, d["a1"])
    assert movimento["percentual_capital"] == 10


def test_capital_de_cada_alteracao_fica_nela(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    a2 = repo.buscar_alteracao(conn, d["a2"])
    a2.capital_social = 250_000
    repo.salvar_alteracao(conn, a2)
    assert repo.buscar_alteracao(conn, d["a1"]).capital_social == 100_000
    assert repo.estado_atual_empresa(conn, empresa)["capital_social"] == 250_000


# ------------------------------------------------ dados gravados pela versão antiga --


def _alteracao_antiga(conn, empresa, numero, data, descricao):
    """Como a versão anterior gravava: alteração e vínculos, sem movimentos."""
    return conn.execute(
        """INSERT INTO alteracao_contratual (empresa_id, numero, data, nome_empresa, capital_social,
           quantidade_cotas, descricao) VALUES (%s, %s, %s, 'ACME', 1000, 1000, %s) RETURNING id""",
        (empresa, numero, data, descricao),
    ).fetchone()[0]


def _vinculo_antigo(conn, empresa, socio, entrada, entrada_id, saida=None, saida_id=None, pct=10):
    conn.execute(
        """INSERT INTO vinculo_societario (empresa_id, socio_id, percentual_capital, quantidade_cotas,
           data_entrada, data_saida, alteracao_entrada_id, alteracao_saida_id)
           VALUES (%s, %s, %s, 100, %s, %s, %s, %s)""",
        (empresa, socio, pct, entrada, saida, entrada_id, saida_id),
    )


def test_alteracoes_antigas_ganham_movimentos_sem_mudar_o_quadro(conn, empresa):
    x, y = _socio(conn, "XAVIER"), _socio(conn, "YARA")
    a1 = _alteracao_antiga(conn, empresa, 1, "2023-01-01", "Contrato")
    a2 = _alteracao_antiga(conn, empresa, 2, "2024-01-01", "Mudança")
    _vinculo_antigo(conn, empresa, x, "2023-01-01", a1, "2024-01-01", a2, pct=10)
    _vinculo_antigo(conn, empresa, x, "2024-01-01", a2, pct=20)
    _vinculo_antigo(conn, empresa, y, "2023-01-01", a1, "2024-01-01", a2, pct=90)
    conn.commit()
    antes = sorted(tuple(r) for r in conn.execute("SELECT * FROM vinculo_societario").fetchall())

    repo.arrumar_alteracoes(conn)

    tipos = {(m["alteracao_id"], m["socio_nome"]): m["tipo"]
             for a in (a1, a2) for m in repo.listar_movimentos(conn, a)}
    assert tipos == {(a1, "XAVIER"): "entrada", (a1, "YARA"): "entrada",
                     (a2, "XAVIER"): "participacao", (a2, "YARA"): "saida"}
    assert repo.recompor_quadro(conn, empresa) == 0  # os movimentos dão o mesmo quadro
    assert sorted(tuple(r) for r in conn.execute("SELECT * FROM vinculo_societario").fetchall()) == antes


def test_alteracoes_repetidas_do_mesmo_dia_viram_uma(conn, empresa):
    socios = [_socio(conn, f"SOCIO {i}") for i in range(3)]
    for i, socio in enumerate(socios):
        a = _alteracao_antiga(conn, empresa, i + 1, "2025-05-10", "Inclusão de sócio (registrada pelo Claude)")
        _vinculo_antigo(conn, empresa, socio, "2025-05-10", a)
    manual = _alteracao_antiga(conn, empresa, 9, "2025-08-01", "Aumento de capital")
    conn.commit()

    repo.arrumar_alteracoes(conn)

    alteracoes = repo.listar_alteracoes(conn, empresa)
    assert [a.numero for a in alteracoes] == [1, 9]
    assert len(repo.listar_movimentos(conn, alteracoes[0].id)) == 3
    assert {v.alteracao_entrada_id for v in repo.listar_vinculos_empresa(conn, empresa)} == {alteracoes[0].id}
    assert manual in {a.id for a in alteracoes}
    repo.arrumar_alteracoes(conn)  # de novo, nada a fazer
    assert len(repo.listar_alteracoes(conn, empresa)) == 2


def test_duas_alteracoes_cadastradas_a_mao_no_mesmo_dia_ficam(conn, empresa):
    _alteracao_antiga(conn, empresa, 1, "2025-05-10", "Contrato A")
    _alteracao_antiga(conn, empresa, 2, "2025-05-10", "Contrato B")
    conn.commit()
    repo.arrumar_alteracoes(conn)
    assert len(repo.listar_alteracoes(conn, empresa)) == 2


def test_historia_sem_alteracao_continua_e_a_alteracao_segue_dela(conn, empresa):
    x = _socio(conn, "XAVIER")
    repo.salvar_vinculo(conn, VinculoSocietario(None, empresa, x, 50, 500, "2019-01-01", None))
    a = _alteracao(conn, empresa, 3, "2024-01-01")
    repo.salvar_movimento(conn, a, x, "saida")
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    assert (vinculo.data_entrada, vinculo.data_saida, vinculo.alteracao_entrada_id) == ("2019-01-01", "2024-01-01", None)
    repo.remover_movimento(conn, a, x)
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    assert vinculo.data_saida is None


# ------------------------------------------------------ casos do code review --


def test_quadro_antes_da_alteracao_respeita_a_data_dela(conn, empresa):
    """Saída marcada depois (fim do movimento, história com data de saída)
    ainda não aconteceu na data da alteração; entrada futura também não."""
    x, y, z = _socio(conn, "XAVIER"), _socio(conn, "YARA"), _socio(conn, "ZECA")
    repo.salvar_vinculo(conn, VinculoSocietario(None, empresa, y, 30, 300, "2019-01-01", "2025-01-01"))
    repo.salvar_vinculo(conn, VinculoSocietario(None, empresa, z, 10, 100, "2025-03-01", None))
    a1 = _alteracao(conn, empresa, 1, "2023-01-01")
    a2 = _alteracao(conn, empresa, 2, "2024-01-01")
    repo.salvar_movimento(conn, a1, x, "entrada", percentual=10, fim="2025-06-01")

    antes = repo.quadro_antes_da_alteracao(conn, a2)
    assert set(antes) == {x, y}
    repo.salvar_movimento(conn, a2, x, "participacao", percentual=20)
    repo.salvar_movimento(conn, a2, y, "saida")
    assert _ativos(conn, empresa, "2024-06-01")[x].percentual_capital == 20
    assert y not in _ativos(conn, empresa, "2024-06-01")


@pytest.fixture()
def entrou_e_saiu(conn, empresa):
    x = _socio(conn, "XAVIER")
    a1 = _alteracao(conn, empresa, 1, "2023-01-01")
    repo.salvar_movimento(conn, a1, x, "entrada", percentual=10)
    repo.salvar_movimento(conn, a1, x, "saida", data="2023-06-01")
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    assert (vinculo.data_saida, vinculo.alteracao_saida_id) == ("2023-06-01", a1)
    return x, a1, vinculo


def test_editar_quem_entrou_e_saiu_na_mesma_alteracao_mantem_a_saida(conn, empresa, entrou_e_saiu):
    x, a1, vinculo = entrou_e_saiu
    vinculo.observacao = "conferido"
    repo.salvar_vinculo(conn, vinculo)
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    assert (vinculo.data_saida, vinculo.alteracao_saida_id, vinculo.observacao) == ("2023-06-01", a1, "conferido")

    vinculo.data_saida = "2023-09-01"
    repo.salvar_vinculo(conn, vinculo)
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    assert (vinculo.data_saida, vinculo.alteracao_saida_id) == ("2023-09-01", a1)


def test_corrigir_quem_entrou_e_saiu_com_data_errada_nao_perde_a_saida(conn, empresa, entrou_e_saiu):
    x, a1, _ = entrou_e_saiu
    with pytest.raises(ValueError, match="anterior"):
        repo.salvar_movimento(conn, a1, x, "entrada", data="2023-08-01", percentual=10,
                              fim="2023-06-01", saida_nesta=True)
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    assert (vinculo.data_saida, vinculo.alteracao_saida_id) == ("2023-06-01", a1)
    repo.salvar_movimento(conn, a1, x, "entrada", data="2023-02-01", percentual=15,
                          fim="2023-06-01", saida_nesta=True)
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    assert (vinculo.percentual_capital, vinculo.data_saida, vinculo.alteracao_saida_id) == (15, "2023-06-01", a1)


def test_mudar_cotas_no_dia_em_que_o_socio_entrou(conn, empresa, ano_2025):
    x = _socio(conn, "XAVIER")
    repo.associar_socio_a_empresa(conn, empresa, x, 10, 10_000, "2025-03-01")
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    repo.atualizar_cotas_vinculo(conn, vinculo, 20, 20_000, "2025-03-01")
    (alteracao,) = repo.listar_alteracoes(conn, empresa)
    (movimento,) = repo.listar_movimentos(conn, alteracao.id)
    assert (movimento["tipo"], movimento["percentual_capital"], movimento["quantidade_cotas"]) == (
        "entrada", 20, 20_000)
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa)
    assert vinculo.percentual_capital == 20 and vinculo.data_saida is None


def test_desfazer_a_saida_pela_aba_socios(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    a3 = _alteracao(conn, empresa, 3, "2025-01-01")
    repo.salvar_movimento(conn, a3, d["y"], "saida")
    vinculo = next(v for v in repo.listar_vinculos_empresa(conn, empresa) if v.socio_id == d["y"])
    vinculo.data_saida, vinculo.alteracao_saida_id = None, None
    repo.salvar_vinculo(conn, vinculo)
    assert d["y"] in _ativos(conn, empresa, "2026-01-01")
    assert repo.listar_movimentos(conn, a3) == []


def test_desfazer_saida_que_e_participacao_nova_de_outra_e_barrado(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    vinculo = next(v for v in repo.listar_vinculos_empresa(conn, empresa)
                   if v.socio_id == d["x"] and v.alteracao_entrada_id == d["a1"])
    vinculo.data_saida, vinculo.alteracao_saida_id = None, None
    with pytest.raises(ValueError, match="participação nova"):
        repo.salvar_vinculo(conn, vinculo)


def test_excluir_vinculo_de_alteracao_sem_movimento_nao_deixa_nada_pela_metade(conn, empresa, duas_alteracoes):
    d = duas_alteracoes
    w = _socio(conn, "WILSON")
    _vinculo_antigo(conn, empresa, w, "2023-01-01", d["a1"], "2024-01-01", d["a2"])
    conn.commit()
    (vinculo,) = [v for v in repo.listar_vinculos_empresa(conn, empresa) if v.socio_id == w]
    repo.excluir_vinculo(conn, vinculo.id)
    conn.rollback()  # nada pendente: o que foi feito já está gravado
    assert w not in {v.socio_id for v in repo.listar_vinculos_empresa(conn, empresa)}
    assert {v.socio_id for v in repo.listar_vinculos_empresa(conn, empresa)} == {d["x"], d["y"]}


def test_alteracoes_da_distribuicao_anual_do_mesmo_dia_viram_uma(conn, empresa):
    x, y = _socio(conn, "XAVIER"), _socio(conn, "YARA")
    a = _alteracao_antiga(conn, empresa, 1, "2025-05-10", "Atualização de cotas (editado na Distribuição anual)")
    b = _alteracao_antiga(conn, empresa, 2, "2025-05-10", "Saída de sócio (editado na Distribuição anual)")
    _vinculo_antigo(conn, empresa, x, "2025-05-10", a)
    _vinculo_antigo(conn, empresa, y, "2025-05-10", b)
    conn.commit()
    repo.arrumar_alteracoes(conn)
    assert len(repo.listar_alteracoes(conn, empresa)) == 1


def test_erro_na_arrumacao_nao_impede_de_abrir(conn, empresa, monkeypatch):
    x = _socio(conn, "XAVIER")
    a = _alteracao_antiga(conn, empresa, 1, "2025-05-10", "Contrato")
    _vinculo_antigo(conn, empresa, x, "2025-05-10", a)
    conn.commit()

    def quebra(*_args, **_kwargs):
        raise RuntimeError("dado antigo que não fecha")

    monkeypatch.setattr(repo, "_movimentos_tirados_dos_vinculos", quebra)
    monkeypatch.setattr(repo, "recompor_quadro", quebra)
    repo.arrumar_alteracoes(conn)  # não levanta
    assert len(repo.listar_vinculos_empresa(conn, empresa)) == 1
