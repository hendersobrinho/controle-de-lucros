"""Testes do informe de rendimentos: o que o sistema sugere a partir dos
lançamentos, o que fica guardado, e a redação/mapeamento do documento."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from controle_lucros import repositories as repo
from controle_lucros.informe_rendimentos import (
    APELIDOS_CAMPOS,
    QUADRO_3_LINHAS,
    QUADRO_4_LINHAS,
    QUADRO_5_LINHAS,
    RODAPE_LEGAL,
    bloco_emprestimo,
    bloco_saida_sociedade,
    bloco_variacao_cotas,
    informacoes_complementares,
    montar_html,
    nome_arquivo_sugerido,
)
from controle_lucros.models import (
    CAMPOS_COTAS_INFORME,
    CAMPOS_VALOR_INFORME,
    Empresa,
    InformeRendimento,
    Movimentacao,
    Socio,
)


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


def test_bloco_de_saida_da_sociedade_tem_a_redacao_do_modelo():
    assert bloco_saida_sociedade("2025-08-29") == (
        "SAÍDA DE SOCIEDADE DE DIREITO PRIVADO (Ficha de Dívidas e Ônus Reais):\n"
        "Data da saída 29/08/2025"
    )


def test_bloco_de_variacao_descreve_a_alienacao_como_no_comprovante_de_verdade():
    """Redação conferida contra o comprovante emitido pela contabilidade para
    um sócio que vendeu as 12.000 cotas dele e saiu."""
    informe = _informe(cotas_inicio=12000, cotas_fim=0, cota_valor_nominal=100)
    assert bloco_variacao_cotas(informe) == (
        "VARIAÇÃO DE COTAS (por alteração contratual) (Ficha de Bens e Direitos):\n"
        "Alienação de 12.000 Cotas Societárias, no valor nominal de R$ 1,00 cada uma, "
        "totalizando R$ 12.000,00. Saldo em 31/12/2025: 0 Cotas = R$ 0,00"
    )


def test_comprar_cotas_sai_como_aquisicao_com_o_saldo_que_ficou():
    informe = _informe(cotas_inicio=500, cotas_fim=1500, cota_valor_nominal=250)
    texto = bloco_variacao_cotas(informe)
    assert "Aquisição de 1.000 Cotas Societárias" in texto
    assert "no valor nominal de R$ 2,50 cada uma, totalizando R$ 2.500,00" in texto
    assert "Saldo em 31/12/2025: 1.500 Cotas = R$ 3.750,00" in texto


def test_cotas_iguais_no_comeco_e_no_fim_do_ano_nao_geram_bloco():
    """Quem não mexeu na participação repete a declaração do ano anterior —
    imprimir "variação de 0 cotas" só confundiria quem declara."""
    assert bloco_variacao_cotas(_informe(cotas_inicio=1000, cotas_fim=1000)) == ""


def test_quadro_7_ordena_emprestimo_saida_variacao_e_texto_livre():
    informe = _informe(
        emprestimo_saldo=78551616,
        saida_sociedade_data="2025-08-29",
        cotas_inicio=12000,
        cotas_fim=0,
        cota_valor_nominal=100,
        informacoes_complementares="Observação do escritório.",
    )
    blocos = informacoes_complementares(informe).split("\n\n")
    assert [b.split("\n")[0] for b in blocos] == [
        "EMPRÉSTIMO A SÓCIOS (Ficha de Dívidas e Ônus Reais):",
        "SAÍDA DE SOCIEDADE DE DIREITO PRIVADO (Ficha de Dívidas e Ônus Reais):",
        "VARIAÇÃO DE COTAS (por alteração contratual) (Ficha de Bens e Direitos):",
        "Observação do escritório.",
    ]


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
    campos = set(CAMPOS_VALOR_INFORME) | {"emprestimo_saldo"} | set(CAMPOS_COTAS_INFORME)
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


def test_html_imprime_a_variacao_de_cotas_no_quadro_7():
    html = _html_roselene(
        saida_sociedade_data="2025-08-29", cotas_inicio=12000, cotas_fim=0, cota_valor_nominal=100
    )
    corpo_q7 = html.split("7. Informações Complementares")[1]
    assert "Data da saída 29/08/2025" in corpo_q7
    assert "Alienação de 12.000 Cotas Societárias" in corpo_q7
    # Cota não é rendimento: nada disso pode subir pros quadros de valores.
    assert "Cotas Societárias" not in html.split("7. Informações Complementares")[0]


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


def test_sugestao_traz_a_saida_e_a_alienacao_de_cotas_do_ano(conn):
    """O caso que motivou o recurso: o sócio vendeu as cotas e saiu em agosto.
    O comprovante do ano tem que mandar ele baixar a participação."""
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 10, 100, "2010-01-01", "Inclusão")
    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2025-08-29", "Saída")

    informe = repo.informe_sugerido(conn, empresa_id, 2025, socio_id)
    assert informe.saida_sociedade_data == "2025-08-29"
    assert informe.cotas_inicio == 100
    assert informe.cotas_fim == 0
    assert informe.cota_valor_nominal == 1000  # capital 10.000 / 1.000 cotas
    assert "Alienação de 100 Cotas Societárias" in informacoes_complementares(informe)


def test_reduzir_participacao_nao_vira_saida_da_sociedade(conn):
    """Reduzir cotas fecha um vínculo e abre outro na mesma data — ler isso
    como saída faria o informe mandar o sócio baixar uma participação que
    ele ainda tem."""
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 10, 100, "2010-01-01", "Inclusão")
    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    repo.atualizar_cotas_vinculo(conn, vinculo, 4.0, 40, "2025-08-29")

    informe = repo.informe_sugerido(conn, empresa_id, 2025, socio_id)
    assert informe.saida_sociedade_data == ""
    assert (informe.cotas_inicio, informe.cotas_fim) == (100, 40)
    texto = informacoes_complementares(informe)
    assert "SAÍDA DE SOCIEDADE" not in texto
    assert "Alienação de 60 Cotas Societárias" in texto
    assert "Saldo em 31/12/2025: 40 Cotas" in texto


def test_entrar_na_sociedade_no_ano_sugere_aquisicao(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 10, 100, "2025-04-01", "Inclusão")

    informe = repo.informe_sugerido(conn, empresa_id, 2025, socio_id)
    assert (informe.cotas_inicio, informe.cotas_fim) == (0, 100)
    assert "Aquisição de 100 Cotas Societárias" in informacoes_complementares(informe)


def test_quem_saiu_em_ano_anterior_nao_repete_a_saida_todo_ano(conn):
    """Sem isso, o informe emitido por causa de um empréstimo antigo mandaria
    o sócio baixar de novo, todo ano, uma participação que ele já baixou."""
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 10, 100, "2010-01-01", "Inclusão")
    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2024-08-29", "Saída")

    informe = repo.informe_sugerido(conn, empresa_id, 2025, socio_id)
    assert informe.saida_sociedade_data == ""
    assert (informe.cotas_inicio, informe.cotas_fim) == (0, 0)
    assert informacoes_complementares(informe) == ""


def test_variacao_de_cotas_conferida_na_tela_fica_guardada(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    informe = _informe(
        empresa_id=empresa_id,
        socio_id=socio_id,
        saida_sociedade_data="2025-08-29",
        cotas_inicio=12000,
        cotas_fim=0,
        cota_valor_nominal=100,
    )
    repo.salvar_informe(conn, informe)

    recarregado = repo.buscar_informe(conn, empresa_id, 2025, socio_id)
    assert recarregado.saida_sociedade_data == "2025-08-29"
    assert recarregado.cotas_inicio == 12000
    assert recarregado.cotas_fim == 0
    assert recarregado.cota_valor_nominal == 100


def test_salvar_recusa_quantidade_de_cotas_negativa(conn):
    empresa_id, socio_id = _empresa(conn), _socio(conn)
    with pytest.raises(ValueError, match="cotas"):
        repo.salvar_informe(conn, _informe(empresa_id=empresa_id, socio_id=socio_id, cotas_fim=-1))


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
