import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from controle_lucros import repositories as repo
from controle_lucros.models import Socio
from controle_lucros.ui import importacao_cadastro_view as vista
from controle_lucros.ui.importacao_cadastro_view import DialogoRevisaoCadastro


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


def _linha(numero_chamada, empresa_nome, **overrides):
    dados = dict(
        numero_chamada=numero_chamada, empresa_nome=empresa_nome, cnpj="",
        capital_social=1000, quantidade_cotas=100,
        socio_nome="Carlos Mendes", socio_cpf="555.555.555-55", tipo_pessoa="fisica",
        percentual_capital=100.0, cotas_socio=100, data_entrada="2025-01-01",
    )
    dados.update(overrides)
    return dados


def test_mesmo_socio_novo_em_varias_empresas_vira_um_cartao_so(conn, monkeypatch):
    """O ponto central: sócio novo que aparece em N linhas (N empresas) da
    mesma planilha não pode virar N pendências independentes — resolver uma
    vez (criar o cadastro) precisa valer pras outras empresas dele também,
    sem duplicar o sócio."""
    linhas_planilha = [
        _linha("101", "Empresa A LTDA", percentual_capital=100.0),
        _linha("102", "Empresa B LTDA", percentual_capital=50.0),
        _linha("103", "Empresa C LTDA", percentual_capital=30.0),
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas_planilha)
    assert resultado["prontas"] == []
    assert len(resultado["pendencias"]) == 3

    dialogo = DialogoRevisaoCadastro(conn, resultado["pendencias"])
    assert len(dialogo._grupos_ui) == 1

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    linhas_grupo, combo, botao = dialogo._grupos_ui[0]
    dialogo._cadastrar_novo(linhas_grupo, combo, botao)

    socios = repo.listar_socios(conn)
    assert len(socios) == 1

    resolvidos = dialogo.resolvidos()
    assert len(resolvidos) == 3
    assert {r["socio_id"] for r in resolvidos} == {socios[0].id}

    aplicado = repo.aplicar_importacao_cadastro(conn, resultado["prontas"] + resolvidos)
    assert aplicado == {"empresas_criadas": 3, "vinculos_criados": 3, "vinculos_ja_existentes": 0, "vinculos_encerrados": 0, "participacoes_atualizadas": 0, "participacoes_nao_atualizadas": 0, "distribuicoes_lancadas": 0, "alteracoes_criadas": 0}

    for empresa in repo.listar_empresas(conn):
        (vinculo,) = repo.listar_vinculos_empresa(conn, empresa.id)
        assert vinculo.socio_id == socios[0].id


def test_socios_diferentes_ficam_em_cartoes_separados(conn):
    linhas_planilha = [
        _linha("101", "Empresa A LTDA", socio_nome="Carlos Mendes", socio_cpf="555.555.555-55"),
        _linha("102", "Empresa B LTDA", socio_nome="Ana Paula", socio_cpf="666.666.666-66"),
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas_planilha)
    dialogo = DialogoRevisaoCadastro(conn, resultado["pendencias"])
    assert len(dialogo._grupos_ui) == 2


def test_agrupa_por_nome_quando_cpf_esta_vazio(conn):
    linhas_planilha = [
        _linha("101", "Empresa A LTDA", socio_nome="Carlos Mendes", socio_cpf=""),
        _linha("102", "Empresa B LTDA", socio_nome="Carlos Mendes", socio_cpf=""),
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas_planilha)
    dialogo = DialogoRevisaoCadastro(conn, resultado["pendencias"])
    assert len(dialogo._grupos_ui) == 1


def test_cadastrar_todos_resolve_o_quadro_inteiro_de_uma_vez(conn, monkeypatch):
    """Importar o quadro societário de uma empresa nova cai no diálogo com
    todo mundo pendente; a ação em lote existe pra isso não virar dezenas de
    cliques idênticos."""
    linhas_arquivo = [
        _linha("91", "Endogastro LTDA", socio_nome=f"Socio {i}", socio_cpf=f"{i:03d}.000.000-00")
        for i in range(1, 8)
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas_arquivo)
    dialogo = DialogoRevisaoCadastro(conn, resultado["pendencias"])
    assert len(dialogo._pendentes()) == 7

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    dialogo._cadastrar_todos()

    assert len(repo.listar_socios(conn)) == 7
    assert dialogo._pendentes() == []
    assert len(dialogo.resolvidos()) == 7
    # Cada cartão aponta pro sócio que acabou de ser criado, não pro de outro.
    cpfs = {s.id: s.cpf for s in repo.listar_socios(conn)}
    for linhas, combo, botao in dialogo._grupos_ui:
        assert not botao.isEnabled()
        assert cpfs[combo.currentData()] == linhas[0]["socio_cpf"]


def test_cadastrar_todos_nao_mexe_em_quem_ja_foi_resolvido(conn, monkeypatch):
    # O sócio existente está cadastrado com o nome de casada; a linha do
    # arquivo veio com o de solteira, então não casa sozinho.
    existente = repo.salvar_socio(conn, Socio(id=None, nome="CARLA SOUZA LIMA", cpf="777.777.777-77"))
    linhas_arquivo = [
        _linha("101", "Empresa A LTDA", socio_nome="Carla Souza", socio_cpf=""),
        _linha("102", "Empresa B LTDA", socio_nome="Ana Paula", socio_cpf="666.666.666-66"),
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas_arquivo)
    dialogo = DialogoRevisaoCadastro(conn, resultado["pendencias"])
    assert len(dialogo._pendentes()) == 2

    # A pessoa resolve um cartão à mão, apontando pro sócio existente.
    combo_carla = next(
        combo for linhas, combo, _b in dialogo._grupos_ui if linhas[0]["socio_nome"] == "Carla Souza"
    )
    combo_carla.setCurrentIndex(combo_carla.findData(existente))
    assert len(dialogo._pendentes()) == 1

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    dialogo._cadastrar_todos()

    assert len(repo.listar_socios(conn)) == 2  # só a Ana foi criada
    assert combo_carla.currentData() == existente


def test_cadastrar_todos_recusado_nao_cria_ninguem(conn, monkeypatch):
    resultado = repo.preparar_importacao_cadastro(conn, [_linha("101", "Empresa A LTDA")])
    dialogo = DialogoRevisaoCadastro(conn, resultado["pendencias"])

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    dialogo._cadastrar_todos()

    assert repo.listar_socios(conn) == []
    assert len(dialogo._pendentes()) == 1


def test_importar_relatorio_pdf_alimenta_o_cadastro(conn, monkeypatch, tmp_path):
    """Caminho completo da tela: PDF escolhido → texto extraído → layout casado
    → revisão → cadastro gravado. Só a leitura do PDF é substituída."""
    texto = (
        "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA Data do quadro societário: 20/05/2026\n"
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94\n"
        "707 LUIZA DIAS TORRES 103.285.827-35 02/03/2023 20/05/2026 0\n"
        "1041 CAIO GUIMARAES ARAUJO 142.575.367-13 16/02/2024 53,06\n"
    )
    arquivo = tmp_path / "relatorio.pdf"
    arquivo.write_bytes(b"%PDF-falso")

    view = vista.ImportacaoCadastroView(conn)
    monkeypatch.setattr(vista, "extrair_texto", lambda caminho: texto)
    monkeypatch.setattr(
        vista.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(arquivo), ""))
    )
    monkeypatch.setattr(vista.QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(vista.QMessageBox, "information", staticmethod(lambda *a, **k: None))

    # No diálogo de revisão, cadastra todo mundo de uma vez e aplica.
    def revisar(self_dialogo):
        self_dialogo._cadastrar_todos()
        return vista.QDialog.Accepted

    monkeypatch.setattr(vista.DialogoRevisaoCadastro, "exec", revisar)
    view._importar_relatorio()

    (empresa,) = repo.listar_empresas(conn)
    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    socios = {s.nome: s for s in repo.listar_socios(conn)}
    assert set(socios) == {"ANDRE FRANZOTTI CARDOSO", "LUIZA DIAS TORRES", "CAIO GUIMARAES ARAUJO"}
    assert socios["ANDRE FRANZOTTI CARDOSO"].cpf == "076.925.727-55"

    vinculos = {v.socio_id: v for v in repo.listar_vinculos_empresa(conn, empresa.id)}
    andre = vinculos[socios["ANDRE FRANZOTTI CARDOSO"].id]
    assert andre.percentual_capital == 46.94
    assert andre.data_entrada == "2007-03-23"
    assert andre.data_saida in (None, "")
    # Quem saiu entra já com a saída registrada, que é o ponto do relatório.
    assert vinculos[socios["LUIZA DIAS TORRES"].id].data_saida == "2026-05-20"

    # Movimentação de sócio é alteração contratual: a empresa tocada pelo
    # relatório ganha uma automática, e todo vínculo criado/encerrado por
    # ele fica amarrado a ela.
    (alteracao,) = repo.listar_alteracoes(conn, empresa.id)
    assert all(v.alteracao_entrada_id == alteracao.id for v in vinculos.values())
    assert vinculos[socios["LUIZA DIAS TORRES"].id].alteracao_saida_id == alteracao.id


def test_importar_relatorio_pdf_recusado_na_confirmacao_nao_grava(conn, monkeypatch, tmp_path):
    arquivo = tmp_path / "relatorio.pdf"
    arquivo.write_bytes(b"%PDF-falso")
    view = vista.ImportacaoCadastroView(conn)
    monkeypatch.setattr(
        vista, "extrair_texto",
        lambda caminho: "Empresa: 91 - X LTDA\n75 ANDRE 076.925.727-55 23/03/2007 100\n",
    )
    monkeypatch.setattr(
        vista.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(arquivo), ""))
    )
    monkeypatch.setattr(vista.QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))

    view._importar_relatorio()

    assert repo.listar_empresas(conn) == []
    assert repo.listar_socios(conn) == []


def test_pdf_que_nao_e_o_relatorio_avisa_e_nao_grava(conn, monkeypatch, tmp_path):
    arquivo = tmp_path / "outro.pdf"
    arquivo.write_bytes(b"%PDF-falso")
    view = vista.ImportacaoCadastroView(conn)
    avisos = []
    monkeypatch.setattr(vista, "extrair_texto", lambda caminho: "Balancete de verificação")
    monkeypatch.setattr(
        vista.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(arquivo), ""))
    )
    monkeypatch.setattr(
        vista.QMessageBox, "warning", staticmethod(lambda parent, titulo, texto, *a: avisos.append(texto))
    )

    view._importar_relatorio()

    assert avisos and "Cadastro de Sócios" in avisos[0]
    assert repo.listar_empresas(conn) == []


def test_confirmacao_do_pdf_avisa_quando_alguma_linha_nao_foi_lida(conn, monkeypatch, tmp_path):
    """Importar 1 de 2 sócios sem dizer nada é o pior desfecho: a falta só
    apareceria muito depois, se aparecesse."""
    arquivo = tmp_path / "relatorio.pdf"
    arquivo.write_bytes(b"%PDF-falso")
    texto = (
        "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA\n"
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94\n"
        "7 A 103.285.827-35 02/03/2023 53,06\n"   # nome ilegível: linha perdida
    )
    perguntas = []
    view = vista.ImportacaoCadastroView(conn)
    monkeypatch.setattr(vista, "extrair_texto", lambda caminho: texto)
    monkeypatch.setattr(
        vista.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(arquivo), ""))
    )
    monkeypatch.setattr(
        vista.QMessageBox, "question",
        staticmethod(lambda parent, titulo, texto, *a, **k: perguntas.append(texto) or QMessageBox.No),
    )

    view._importar_relatorio()

    assert perguntas
    assert "1 linha(s) com cara de sócio não foram reconhecidas" in perguntas[0]
    assert "103.285.827-35" in perguntas[0]


def test_importa_o_relatorio_em_xls_pela_mesma_tela(conn, monkeypatch, tmp_path):
    """O mesmo relatório, agora em planilha .xls — o botão é o mesmo e o
    resultado precisa ser o mesmo."""
    import datetime as data
    from apoio_xls import escrever_xls

    caminho = escrever_xls(tmp_path / "socios.xls", [
        ["Empresa:", "METODOS SERVICOS CONTABEIS LTDA", "Página:", "1/1"],
        ["C.N.P.J.:", "02294442000113", "Emissão:", data.date(2026, 9, 9)],
        ["Código", "Nome", "Inscrição", "Participação(%)", "Data de ingresso", "Data saída"],
        ["Empresa:", "91 - ENDOGASTRO CLINICA MEDICA LTDA", "Data do quadro societário:",
         data.date(2026, 5, 20)],
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, data.date(2007, 3, 23), ""],
        [707, "LUIZA DIAS TORRES", "10328582735", 0.0, data.date(2023, 3, 2), data.date(2026, 5, 20)],
    ])

    view = vista.ImportacaoCadastroView(conn)
    monkeypatch.setattr(
        vista.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(caminho), ""))
    )
    monkeypatch.setattr(vista.QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(vista.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        vista.DialogoRevisaoCadastro, "exec",
        lambda self: (self._cadastrar_todos(), vista.QDialog.Accepted)[1],
    )

    view._importar_relatorio()

    (empresa,) = repo.listar_empresas(conn)
    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    socios = {s.nome: s for s in repo.listar_socios(conn)}
    assert set(socios) == {"ANDRE FRANZOTTI CARDOSO", "LUIZA DIAS TORRES"}
    assert socios["ANDRE FRANZOTTI CARDOSO"].cpf == "076.925.727-55"

    vinculos = {v.socio_id: v for v in repo.listar_vinculos_empresa(conn, empresa.id)}
    assert vinculos[socios["ANDRE FRANZOTTI CARDOSO"].id].percentual_capital == 46.94
    assert vinculos[socios["LUIZA DIAS TORRES"].id].data_saida == "2026-05-20"


def test_relatorio_em_xlsx_tambem_e_aceito(conn, monkeypatch, tmp_path):
    """Quem reabre o .xls e salva de novo acaba com um .xlsx — e não deveria
    precisar saber disso."""
    import datetime as data

    import openpyxl

    caminho = tmp_path / "socios.xlsx"
    livro = openpyxl.Workbook()
    aba = livro.active
    for linha in [
        ["Empresa:", "91 - ENDOGASTRO CLINICA MEDICA LTDA", "Data do quadro societário:",
         data.date(2026, 5, 20)],
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, data.date(2007, 3, 23), None],
    ]:
        aba.append(linha)
    livro.save(caminho)

    view = vista.ImportacaoCadastroView(conn)
    monkeypatch.setattr(
        vista.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(caminho), ""))
    )
    monkeypatch.setattr(vista.QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(vista.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        vista.DialogoRevisaoCadastro, "exec",
        lambda self: (self._cadastrar_todos(), vista.QDialog.Accepted)[1],
    )

    view._importar_relatorio()

    (empresa,) = repo.listar_empresas(conn)
    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert [s.nome for s in repo.listar_socios(conn)] == ["ANDRE FRANZOTTI CARDOSO"]


def test_empresa_ja_cadastrada_pergunta_onde_lancar_a_movimentacao(conn, monkeypatch, tmp_path):
    """Relatório de uma empresa só que já está no cadastro: dá pra perguntar
    em qual alteração contratual a movimentação entra, em vez de abrir uma
    automática sem avisar. Com várias empresas no arquivo não há o que
    escolher, e o caminho automático continua."""
    from controle_lucros.models import Empresa

    empresa_id = repo.salvar_empresa(
        conn, Empresa(None, "91", "ENDOGASTRO CLINICA MEDICA LTDA", "", 10000, 1000)
    )
    repo.salvar_socio(conn, Socio(None, "ANDRE FRANZOTTI CARDOSO", "076.925.727-55"))

    arquivo = tmp_path / "relatorio.pdf"
    arquivo.write_bytes(b"%PDF-falso")
    monkeypatch.setattr(
        vista, "extrair_texto",
        lambda caminho: (
            "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA Data do quadro societário: 20/05/2026\n"
            "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94\n"
        ),
    )
    monkeypatch.setattr(
        vista.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(arquivo), ""))
    )
    monkeypatch.setattr(vista.QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(vista.QMessageBox, "information", staticmethod(lambda *a, **k: None))

    telas = []
    monkeypatch.setattr(
        vista.DialogoDestinoAlteracao, "exec",
        lambda self: (telas.append(self), vista.QDialog.Accepted)[1],
    )

    view = vista.ImportacaoCadastroView(conn)
    view._importar_relatorio()

    (destino,) = telas
    assert destino.empresa_id == empresa_id
    # Sem alteração aberta ainda, a escolha cai em cadastrar uma nova, já com
    # a data do quadro societário do relatório.
    assert destino.opcao_nova.isChecked()
    assert destino.data.date().toString("yyyy-MM-dd") == "2026-05-20"

    (alteracao,) = repo.listar_alteracoes(conn, empresa_id)
    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa_id)
    assert vinculo.alteracao_entrada_id == alteracao.id
