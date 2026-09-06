"""Testes do informe de rendimentos: o que o sistema sugere a partir dos
lançamentos, o que fica guardado, e a redação/mapeamento do documento."""
import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from controle_lucros import db, repositories as repo
from controle_lucros.informe_rendimentos import (
    APELIDOS_CAMPOS,
    QUADRO_3_LINHAS,
    QUADRO_4_LINHAS,
    QUADRO_5_LINHAS,
    RODAPE_LEGAL,
    bloco_emprestimo,
    informacoes_complementares,
    montar_html,
    nome_arquivo_sugerido,
)
from controle_lucros.models import CAMPOS_VALOR_INFORME, Empresa, InformeRendimento, Movimentacao, Socio


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()


def _empresa(conn, nome="CSI - CENTRO DE SOLUCOES EM INFORMATICA", numero="001", cnpj="36415149000189") -> int:
    return repo.salvar_empresa(
        conn,
        Empresa(id=None, numero_chamada=numero, nome=nome, cnpj=cnpj, capital_social=10000, quantidade_cotas=1000),
    )


def _socio(conn, nome="ROSELENE CARONE", cpf="005.169.717-35") -> int:
    return repo.salvar_socio(conn, Socio(id=None, nome=nome, cpf=cpf))


def _informe(**overrides) -> InformeRendimento:
    dados = dict(id=None, empresa_id=1, socio_id=1, ano_base=2025)
    dados.update(overrides)
    return InformeRendimento(**dados)


# ------------------------------------------------- regras do documento --


def test_exercicio_e_o_ano_seguinte_ao_ano_calendario():
    assert _informe(ano_base=2025).exercicio == 2026
    assert _informe(ano_base=1996).exercicio == 1997


def test_bloco_de_emprestimo_tem_a_redacao_exata_do_modelo():
    assert bloco_emprestimo(78551616, 2025) == (
        "EMPRÉSTIMO A SÓCIOS (Ficha de Dívidas e Ônus Reais):\n"
        "Empréstimo da Empresa para o Sócio - Saldo em 31/12/2025 R$ 785.516,16"
    )


def test_quadro_7_junta_emprestimo_e_texto_livre():
    informe = _informe(emprestimo_saldo=78551616, informacoes_complementares="Observação do escritório.")
    texto = informacoes_complementares(informe)
    assert texto.startswith("EMPRÉSTIMO A SÓCIOS")
    assert texto.endswith("Observação do escritório.")
    assert "\n\n" in texto  # linha em branco separando os blocos


def test_quadro_7_vazio_quando_nao_ha_emprestimo_nem_texto():
    assert informacoes_complementares(_informe()) == ""


def test_sem_emprestimo_o_quadro_7_nao_traz_o_bloco():
    informe = _informe(emprestimo_saldo=0, informacoes_complementares="Só isso.")
    assert informacoes_complementares(informe) == "Só isso."


# ------------------------------------------------- mapeamento dos valores --


def test_pro_labore_inss_e_irrf_caem_nas_linhas_certas_do_quadro_3():
    campos = {campo: numero for campo, numero, _ in QUADRO_3_LINHAS}
    assert campos["q3_total_rendimentos"] == "1"  # pró-labore
    assert campos["q3_previdencia_oficial"] == "2"  # INSS
    assert campos["q3_irrf"] == "5"


def test_lucros_distribuidos_caem_na_linha_5_do_quadro_4():
    campos = {campo: numero for campo, numero, _ in QUADRO_4_LINHAS}
    assert campos["q4_lucros_dividendos"] == "5"


def test_todo_campo_de_valor_aparece_em_algum_quadro():
    """Sem isso dá pra adicionar um campo no banco, preenchê-lo na tela e ele
    nunca ser impresso — o valor sumiria do documento sem ninguém notar.
    emprestimo_saldo fica fora de propósito: não é rendimento, vai no Quadro 7."""
    impressos = {campo for campo, _, _ in QUADRO_3_LINHAS + QUADRO_4_LINHAS + QUADRO_5_LINHAS}
    assert impressos == set(CAMPOS_VALOR_INFORME)
    assert "emprestimo_saldo" not in impressos


def test_apelidos_apontam_para_campos_que_existem():
    campos = set(CAMPOS_VALOR_INFORME) | {"emprestimo_saldo"}
    assert set(APELIDOS_CAMPOS) <= campos


# ------------------------------------------------------------------ HTML --


def _html_roselene(**overrides) -> str:
    informe = _informe(
        codigo_beneficiario="000001",
        natureza_rendimento="RENDIMENTO DO TRABALHO ASSALARIADO",
        q4_lucros_dividendos=56061985,
        emprestimo_saldo=78551616,
        responsavel_nome="ELLEN SCHNEIDER EWALD",
        **overrides,
    )
    return montar_html(
        informe,
        empresa_nome="CSI - CENTRO DE SOLUCOES EM INFORMATICA",
        empresa_cnpj="36415149000189",
        socio_nome="ROSELENE CARONE",
        socio_cpf="00516971735",
        data_emissao="06/05/2026",
        brasao=None,
    )


def test_html_tem_os_oito_quadros_o_cabecalho_e_o_rodape():
    html = _html_roselene()
    for titulo in (
        "1. Fonte Pagadora",
        "2. Pessoa Física Beneficiária dos Rendimentos",
        "3. Rendimentos Tributáveis",
        "4. Rendimentos Isentos e Não Tributáveis",
        "5. Rendimentos Sujeitos a Tributação Exclusiva",
        "6. Rendimentos Recebidos Acumuladamente",
        "7. Informações Complementares",
        "8. Responsável pelas Informações",
    ):
        assert titulo in html
    assert "MINISTÉRIO DA ECONOMIA" in html
    assert "SECRETARIA DA RECEITA FEDERAL DO BRASIL" in html
    assert RODAPE_LEGAL in html


def test_html_traz_exercicio_ano_calendario_e_identificacao_formatados():
    html = _html_roselene()
    assert "<b>2026</b>" in html  # exercício
    assert "<b>2025</b>" in html  # ano-calendário
    assert "36.415.149/0001-89" in html
    assert "005.169.717-35" in html
    assert "ROSELENE CARONE" in html
    assert "000001" in html


def test_html_imprime_todas_as_linhas_dos_quadros_com_a_redacao_oficial():
    html = _html_roselene()
    for campo, numero, descricao in QUADRO_3_LINHAS + QUADRO_4_LINHAS + QUADRO_5_LINHAS:
        assert f"{numero}. {descricao}" in html, campo


def test_html_zera_as_linhas_nao_preenchidas():
    html = _html_roselene()
    assert "560.619,85" in html
    assert html.count("0,00") == len(CAMPOS_VALOR_INFORME) - 1  # todas menos os lucros


def test_html_poe_o_emprestimo_so_no_quadro_7():
    html = _html_roselene()
    corpo_q7 = html.split("7. Informações Complementares")[1]
    assert "785.516,16" in corpo_q7
    # O saldo não pode vazar pra nenhum quadro de valores, senão vira
    # rendimento tributável de mentira na declaração do sócio.
    assert "785.516,16" not in html.split("7. Informações Complementares")[0]


def test_html_escapa_texto_do_usuario():
    html = _html_roselene(informacoes_complementares="Acerto <b>especial</b> & cia")
    assert "&lt;b&gt;especial&lt;/b&gt; &amp; cia" in html


def test_nome_do_arquivo_separa_socio_empresa_e_ano():
    nome = nome_arquivo_sugerido(_informe(), "ROSELENE CARONE", "CSI / INFORMATICA")
    assert nome == "Informe 2025 - ROSELENE CARONE - CSI - INFORMATICA.pdf"
    assert "/" not in nome


# ------------------------------------------------ valores vindos do banco --


def test_sugestao_puxa_pro_labore_irrf_e_lucros_da_distribuicao(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.salvar_distribuicao(conn, empresa_id, 2025, socio_id, 387649.46, pro_labore=24500.00, irrf=562.51)

    informe = repo.informe_sugerido(conn, empresa_id, 2025, socio_id)
    assert informe.q3_total_rendimentos == 2450000
    assert informe.q3_irrf == 56251
    assert informe.q4_lucros_dividendos == 38764946
    # O que o sistema não controla continua zerado, pra ser digitado na tela.
    assert informe.q3_previdencia_oficial == 0


def test_sugestao_de_emprestimo_acumula_ate_31_12_do_ano(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    for data, valor in (("2024-06-01", 100000.00), ("2025-03-10", 685516.16), ("2026-01-05", 50000.00)):
        repo.salvar_movimentacao(
            conn,
            Movimentacao(None, empresa_id, socio_id, "emprestimo_empresa_para_socio", valor, data),
        )
    # Empréstimo do sócio PARA a empresa é dívida da empresa, não pagamento
    # desta: não pode abater o saldo que vai pro Quadro 7.
    repo.salvar_movimentacao(
        conn, Movimentacao(None, empresa_id, socio_id, "emprestimo_socio_para_empresa", 300000.00, "2025-05-01")
    )

    assert repo.saldo_emprestimo_em(conn, empresa_id, socio_id, 2025) == pytest.approx(785516.16)
    assert repo.informe_sugerido(conn, empresa_id, 2025, socio_id).emprestimo_saldo == 78551616
    assert repo.saldo_emprestimo_em(conn, empresa_id, socio_id, 2024) == pytest.approx(100000.00)


def test_salvar_e_recarregar_mantem_os_valores_conferidos(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.salvar_distribuicao(conn, empresa_id, 2025, socio_id, 387649.46)

    informe = repo.informe_sugerido(conn, empresa_id, 2025, socio_id)
    informe.q3_previdencia_oficial = 269500  # INSS, digitado na tela
    informe.responsavel_nome = "ELLEN SCHNEIDER EWALD"
    repo.salvar_informe(conn, informe)

    recarregado, salvo = repo.carregar_informe(conn, empresa_id, 2025, socio_id)
    assert salvo is True
    assert recarregado.q3_previdencia_oficial == 269500
    assert recarregado.q4_lucros_dividendos == 38764946
    assert recarregado.responsavel_nome == "ELLEN SCHNEIDER EWALD"


def test_carregar_sem_registro_devolve_a_sugestao_marcada_como_nao_salva(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    _, salvo = repo.carregar_informe(conn, empresa_id, 2025, socio_id)
    assert salvo is False


def test_salvar_duas_vezes_substitui_em_vez_de_duplicar(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    informe = _informe(empresa_id=empresa_id, socio_id=socio_id, q3_irrf=100)
    primeiro = repo.salvar_informe(conn, informe)
    informe.q3_irrf = 200
    assert repo.salvar_informe(conn, informe) == primeiro
    assert conn.execute("SELECT COUNT(*) AS n FROM informe_rendimento").fetchone()["n"] == 1
    assert repo.buscar_informe(conn, empresa_id, 2025, socio_id).q3_irrf == 200


def test_valores_sao_isolados_por_ano(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.salvar_informe(conn, _informe(empresa_id=empresa_id, socio_id=socio_id, ano_base=2024, q3_irrf=100))
    repo.salvar_informe(conn, _informe(empresa_id=empresa_id, socio_id=socio_id, ano_base=2025, q3_irrf=999))
    assert repo.buscar_informe(conn, empresa_id, 2024, socio_id).q3_irrf == 100
    assert repo.buscar_informe(conn, empresa_id, 2025, socio_id).q3_irrf == 999


def test_valores_sao_isolados_por_empresa(conn):
    """Cada empresa é uma fonte pagadora com o seu próprio comprovante — os
    valores de uma não podem aparecer no informe da outra."""
    csi, clinirim = _empresa(conn), _empresa(conn, nome="CLINIRIM LTDA", numero="002", cnpj="00317100000146")
    socio_id = _socio(conn)
    repo.salvar_informe(conn, _informe(empresa_id=csi, socio_id=socio_id, q4_lucros_dividendos=56061985))
    repo.salvar_informe(conn, _informe(empresa_id=clinirim, socio_id=socio_id, q4_lucros_dividendos=38764946))
    assert repo.buscar_informe(conn, csi, 2025, socio_id).q4_lucros_dividendos == 56061985
    assert repo.buscar_informe(conn, clinirim, 2025, socio_id).q4_lucros_dividendos == 38764946


def test_salvar_recusa_valor_negativo(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    with pytest.raises(ValueError, match="negativos"):
        repo.salvar_informe(conn, _informe(empresa_id=empresa_id, socio_id=socio_id, q3_irrf=-1))


def test_salvar_recusa_ano_anterior_ao_modelo(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    with pytest.raises(ValueError, match="Ano-calendário"):
        repo.salvar_informe(conn, _informe(empresa_id=empresa_id, socio_id=socio_id, ano_base=1995))


def test_salvar_registra_no_log_de_atividades(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.salvar_informe(conn, _informe(empresa_id=empresa_id, socio_id=socio_id))
    repo.registrar_emissao_informe(conn, empresa_id, 2025, socio_id, "/tmp/informe.pdf")
    acoes = [
        (linha.acao, linha.entidade)
        for linha in repo.listar_log_atividade(conn)
        if linha.entidade == "informe_rendimento"
    ]
    assert ("criar", "informe_rendimento") in acoes
    assert ("emitir", "informe_rendimento") in acoes


# --------------------------------------------- quais empresas têm informe --


def test_empresas_do_socio_no_ano_traz_vinculo_ativo(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100, 1000, "2020-01-01", "Inclusão")
    assert [e.id for e in repo.empresas_do_socio_no_ano(conn, socio_id, 2025)] == [empresa_id]


def test_empresas_do_socio_no_ano_ignora_ano_anterior_a_entrada(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100, 1000, "2025-03-01", "Inclusão")
    assert repo.empresas_do_socio_no_ano(conn, socio_id, 2024) == []
    # Entrou em março: o ano inteiro de 2025 continua tendo informe.
    assert [e.id for e in repo.empresas_do_socio_no_ano(conn, socio_id, 2025)] == [empresa_id]


def test_empresas_do_socio_no_ano_inclui_quem_ja_saiu_mas_teve_lancamento(conn):
    """Lucro deliberado depois da saída ainda é rendimento pago pela empresa.
    Sem isso o informe sumiria justamente no ano em que o sócio precisa dele."""
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100, 1000, "2018-01-01", "Inclusão")
    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2024-06-30", "Saída")
    assert repo.empresas_do_socio_no_ano(conn, socio_id, 2025) == []

    repo.salvar_distribuicao(conn, empresa_id, 2025, socio_id, 10000.00)
    assert [e.id for e in repo.empresas_do_socio_no_ano(conn, socio_id, 2025)] == [empresa_id]


def test_empresas_do_socio_no_ano_nao_repete_empresa_com_varios_vinculos(conn):
    """Sair e voltar na mesma empresa no mesmo ano é um comprovante só."""
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 50, 500, "2025-01-01", "Inclusão")
    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2025-05-31", "Saída")
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 60, 600, "2025-09-01", "Reingresso")
    assert [e.id for e in repo.empresas_do_socio_no_ano(conn, socio_id, 2025)] == [empresa_id]


def test_empresas_do_socio_no_ano_lista_uma_por_fonte_pagadora(conn):
    csi, clinirim = _empresa(conn), _empresa(conn, nome="CLINIRIM LTDA", numero="002", cnpj="00317100000146")
    socio_id = _socio(conn)
    repo.associar_socio_a_empresa(conn, csi, socio_id, 100, 1000, "2020-01-01", "Inclusão")
    repo.associar_socio_a_empresa(conn, clinirim, socio_id, 50, 500, "2020-01-01", "Inclusão")
    assert len(repo.empresas_do_socio_no_ano(conn, socio_id, 2025)) == 2


def test_empresas_do_socio_no_ano_inclui_saldo_de_emprestimo_de_anos_anteriores(conn):
    """Empréstimo tomado antes da saída continua sendo saldo em 31/12 até ser
    quitado — o sócio precisa do comprovante pra ficha de Dívidas e Ônus Reais
    mesmo num ano em que não recebeu nada da empresa."""
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100, 1000, "2018-01-01", "Inclusão")
    repo.salvar_movimentacao(
        conn,
        Movimentacao(None, empresa_id, socio_id, "emprestimo_empresa_para_socio", 785516.16, "2019-03-10"),
    )
    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2020-06-30", "Saída")

    assert [e.id for e in repo.empresas_do_socio_no_ano(conn, socio_id, 2025)] == [empresa_id]
    informe = repo.informe_sugerido(conn, empresa_id, 2025, socio_id)
    assert informe.emprestimo_saldo == 78551616
    assert informe.q4_lucros_dividendos == 0
