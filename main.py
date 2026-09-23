import atexit
import faulthandler
import sys

import psycopg

from PySide6.QtWidgets import QApplication, QDialog

from controle_lucros import backup, db, relatorio_erro, repositories as repo, sessao, traducao
from controle_lucros.ui.icones import icone_app
from controle_lucros.ui.local_banco import DialogoBancoInacessivel, DialogoConexao
from controle_lucros.ui.login import DialogoLogin, DialogoPrimeiroUsuario
from controle_lucros.ui.main_window import MainWindow
from controle_lucros.ui.reportar_erro import CapturaDeErros, abrir_para_fechamento
from controle_lucros.ui.theme import build_stylesheet


def _preparar_registro_de_falhas(pasta) -> str:
    """Liga o registro de falhas e devolve o que sobrou da sessão anterior.

    Falha de segmentação não levanta exceção: quando ela acontece não há
    código Python rodando pra capturar nada. O faulthandler escreve a pilha
    direto no arquivo, no momento do tombo, e a marca de sessão diz na
    abertura seguinte que a anterior não terminou pelo caminho normal.

    Nada aqui pode impedir o programa de abrir — é registro de problema, não
    função do sistema."""
    detalhes = ""
    try:
        if relatorio_erro.sessao_anterior_caiu(pasta):
            detalhes = relatorio_erro.detalhes_do_fechamento(pasta)
        relatorio_erro.limpar_falha(pasta)

        # Mantido aberto pelo resto da execução de propósito: fechar o arquivo
        # deixaria o faulthandler sem pra onde escrever justamente na hora do
        # tombo, que é a única hora em que ele serve.
        destino = open(relatorio_erro.caminho_falha(pasta), "w", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(file=destino)

        relatorio_erro.marcar_sessao_aberta(pasta)
        atexit.register(relatorio_erro.encerrar_sessao, pasta)
    except OSError:
        pass
    return detalhes


def _abrir_banco() -> db.Conexao:
    """Conecta e prepara o banco, insistindo enquanto a pessoa quiser.

    Com o banco no servidor, não abrir é coisa do dia a dia — servidor
    reiniciando, PC que ainda não entrou na rede. Em vez de o programa cair
    com erro técnico, a pessoa tenta de novo ou corrige a conexão."""
    while True:
        conn = None
        try:
            conn = db.connect()
            db.init_schema(conn)
            return conn
        except psycopg.Error as erro:
            if conn is not None:
                conn.close()
            if DialogoBancoInacessivel(erro).exec() == QDialog.Rejected:
                sys.exit(0)


def main() -> None:
    # Na pasta deste PC: cada computador tem a sua marca de sessão.
    fechamento_anterior = _preparar_registro_de_falhas(db.pasta_local())

    app = QApplication(sys.argv)
    traducao.instalar(app)
    app.setWindowIcon(icone_app())
    app.setStyleSheet(build_stylesheet())

    captura = CapturaDeErros()
    captura.instalar()

    # Instalação nova: antes de tudo, saber em que servidor está o banco.
    if db.precisa_configurar() and DialogoConexao(primeira_vez=True).exec() != QDialog.Accepted:
        sys.exit(0)

    conn = _abrir_banco()

    while True:
        if not repo.existe_algum_usuario(conn):
            dialogo = DialogoPrimeiroUsuario(conn)
        else:
            dialogo = DialogoLogin(conn)

        if dialogo.exec() != QDialog.Accepted:
            if getattr(dialogo, "trocou_banco", False):
                # PC que estava no banco errado, apontado pro do escritório:
                # os usuários estão lá, então volta pro começo já com o login.
                conn.close()
                conn = _abrir_banco()
                continue
            sys.exit(0)

        usuario = dialogo.usuario_autenticado
        sessao.definir_usuario_atual(usuario)

        try:
            backup.backup_automatico_se_necessario(conn)
        except (OSError, psycopg.Error):
            pass

        janela = MainWindow(conn, usuario)
        captura.janela_principal = janela
        janela.show()

        # Depois da janela aberta, não antes: perguntar sobre o tombo da vez
        # passada por cima da tela de login seria pedir explicação a quem
        # ainda nem entrou. Uma vez por execução.
        if fechamento_anterior:
            abrir_para_fechamento(fechamento_anterior, parent=janela)
            fechamento_anterior = ""

        app.exec()

        sessao.definir_usuario_atual(None)
        if not janela.logout_solicitado:
            sys.exit(0)


if __name__ == "__main__":
    main()
