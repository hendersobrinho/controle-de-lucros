"""O relatório de problema: o texto que a pessoa manda quando algo dá errado.

O que se testa aqui é o que decide se o relatório serve ou não: se ele diz de
onde veio (erro, fechamento sozinho ou relato à mão), se a pilha do erro
chega inteira, se cabe num mailto sem cortar no meio em silêncio, e se a
marca de sessão realmente distingue fechamento normal de tombo.
"""
import datetime as dt
import urllib.parse

from controle_lucros import relatorio_erro


def _erro_com_pilha(mensagem="deu ruim") -> Exception:
    """Um erro de verdade, já levantado: sem passar pelo raise não há
    traceback, e o traceback é metade do relatório."""
    try:
        raise ValueError(mensagem)
    except ValueError as erro:
        return erro


def test_relatorio_de_erro_leva_a_pilha_e_o_que_a_pessoa_escreveu():
    relatorio = relatorio_erro.montar(
        _erro_com_pilha("coluna X não existe"),
        o_que_fazia="importei o relatório de sócios do mês",
        tela="Alterações contratuais",
    )

    assert "ValueError" in relatorio.assunto
    assert "importei o relatório de sócios do mês" in relatorio.corpo
    assert "Alterações contratuais" in relatorio.corpo
    # A pilha é o que diz ONDE quebrou.
    assert "Traceback" in relatorio.corpo
    assert "coluna X não existe" in relatorio.corpo


def test_sem_descricao_o_relatorio_diz_que_nao_foi_informado():
    """Campo em branco não pode virar um vazio ambíguo no meio do texto —
    quem recebe precisa saber que a pergunta foi feita e não respondida."""
    relatorio = relatorio_erro.montar(_erro_com_pilha())
    assert "(não informado)" in relatorio.corpo


def test_as_tres_origens_se_distinguem_no_assunto():
    """Quem recebe precisa separar de relance um programa que fechou sozinho
    de uma dúvida enviada à mão."""
    erro = relatorio_erro.montar(_erro_com_pilha(), origem="erro")
    fechou = relatorio_erro.montar(origem="fechamento")
    mao = relatorio_erro.montar(origem="manual")

    assert "Erro" in erro.assunto
    assert "fechou sozinho" in fechou.assunto.lower()
    assert "Relato" in mao.assunto
    assert len({erro.assunto, fechou.assunto, mao.assunto}) == 3


def test_relatorio_sempre_traz_versao_e_sistema():
    """Sem versão, um relatório não diz se o problema já foi corrigido."""
    from controle_lucros import __version__

    corpo = relatorio_erro.montar(origem="manual").corpo
    assert __version__ in corpo
    assert "Sistema:" in corpo
    assert "Python:" in corpo


def test_o_registro_do_fechamento_entra_no_corpo():
    relatorio = relatorio_erro.montar(
        origem="fechamento",
        detalhes_extras="Current thread 0x00007f (most recent call first):\n  File ...",
    )
    assert "Current thread" in relatorio.corpo


# ------------------------------------------------------------- mailto --


def test_mailto_leva_destino_assunto_e_corpo():
    relatorio = relatorio_erro.montar(_erro_com_pilha(), o_que_fazia="cliquei em salvar")
    url = relatorio_erro.url_mailto(relatorio)

    assert url.startswith(f"mailto:{relatorio_erro.DESTINO}?")
    partes = urllib.parse.parse_qs(url.split("?", 1)[1])
    assert partes["subject"][0] == relatorio.assunto
    assert "cliquei em salvar" in partes["body"][0]


def test_mailto_escapa_acento_e_e_comercial():
    """Sem escapar, o corpo chega cortado no primeiro "&" e ninguém percebe —
    o e-mail abre com metade do relatório e parece completo."""
    relatorio = relatorio_erro.montar(
        origem="manual", o_que_fazia="a empresa F&F não apareceu na relação"
    )
    url = relatorio_erro.url_mailto(relatorio)
    corpo = urllib.parse.parse_qs(url.split("?", 1)[1])["body"][0]
    assert "F&F não apareceu" in corpo


def test_corpo_grande_e_encurtado_avisando_que_foi():
    """O mailto tem limite de tamanho que varia por programa de e-mail.
    Cortar é inevitável; cortar calado não — quem recebe leria um relatório
    terminado no meio sem saber que falta coisa."""
    relatorio = relatorio_erro.montar(
        origem="manual", o_que_fazia="detalhe. " * 2000
    )
    assert len(relatorio.corpo) > relatorio_erro.LIMITE_CORPO_MAILTO

    encurtado = relatorio.corpo_para_mailto()
    assert len(encurtado) < len(relatorio.corpo)
    assert "não coube" in encurtado
    assert "Copiar mensagem" in encurtado


def test_corpo_pequeno_vai_inteiro():
    relatorio = relatorio_erro.montar(origem="manual", o_que_fazia="nada demais")
    assert relatorio.corpo_para_mailto() == relatorio.corpo


def test_nome_de_arquivo_diz_a_origem_e_a_data():
    relatorio = relatorio_erro.montar(origem="fechamento")
    nome = relatorio_erro.nome_de_arquivo(relatorio, dt.datetime(2026, 9, 17, 14, 30, 5))
    assert nome == "problema_fechamento_20260917_143005.txt"


# ------------------------------------------------- marca de sessão --


def test_sessao_encerrada_pelo_caminho_normal_nao_acusa_tombo(tmp_path):
    relatorio_erro.marcar_sessao_aberta(tmp_path)
    assert relatorio_erro.sessao_anterior_caiu(tmp_path)

    relatorio_erro.encerrar_sessao(tmp_path)
    assert not relatorio_erro.sessao_anterior_caiu(tmp_path)


def test_marca_que_sobrou_denuncia_o_fechamento_inesperado(tmp_path):
    """É assim que uma falha de segmentação é descoberta: ela não levanta
    exceção nenhuma, então o que resta é a marca que ninguém apagou."""
    relatorio_erro.marcar_sessao_aberta(tmp_path, dt.datetime(2026, 9, 17, 9, 0))

    # A sessão morre sem passar pelo encerramento — nada é chamado aqui.
    assert relatorio_erro.sessao_anterior_caiu(tmp_path)
    detalhes = relatorio_erro.detalhes_do_fechamento(tmp_path)
    assert "2026-09-17T09:00" in detalhes


def test_detalhes_do_fechamento_incluem_a_pilha_do_faulthandler(tmp_path):
    relatorio_erro.marcar_sessao_aberta(tmp_path)
    relatorio_erro.caminho_falha(tmp_path).write_text(
        "Fatal Python error: Segmentation fault\n\nCurrent thread:\n  File \"x.py\", line 1\n",
        encoding="utf-8",
    )
    detalhes = relatorio_erro.detalhes_do_fechamento(tmp_path)
    assert "Segmentation fault" in detalhes


def test_encerrar_sessao_que_nunca_abriu_nao_quebra(tmp_path):
    """Roda no atexit: levantar aqui sujaria a saída de um programa que
    terminou bem."""
    relatorio_erro.encerrar_sessao(tmp_path)
    relatorio_erro.limpar_falha(tmp_path)
