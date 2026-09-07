import sys

from PySide6.QtWidgets import QApplication, QDialog

from controle_lucros import backup, db, preferencias, repositories as repo, sessao, traducao
from controle_lucros.ui.icones import icone_app
from controle_lucros.ui.login import DialogoLogin, DialogoPrimeiroUsuario
from controle_lucros.ui.main_window import MainWindow
from controle_lucros.ui.theme import build_stylesheet


def _entrar_com_sessao_salva(conn):
    """Entra direto quando existe um "continuar conectado" válido nesta
    máquina. O token guardado localmente é conferido contra o hash no banco;
    qualquer coisa fora do lugar (vencido, conta desativada, senha trocada,
    banco trocado) devolve None e cai na tela de login normal."""
    salva = preferencias.sessao_salva()
    if salva is None:
        return None
    usuario = repo.usuario_de_sessao_salva(conn, *salva)
    if usuario is None:
        preferencias.esquecer_sessao()
    return usuario


def main() -> None:
    conn = db.connect()
    db.init_schema(conn)

    app = QApplication(sys.argv)
    traducao.instalar(app)
    app.setWindowIcon(icone_app())
    app.setStyleSheet(build_stylesheet())

    while True:
        usuario = _entrar_com_sessao_salva(conn)
        if usuario is None:
            if not repo.existe_algum_usuario(conn):
                dialogo = DialogoPrimeiroUsuario(conn)
            else:
                dialogo = DialogoLogin(conn)

            if dialogo.exec() != QDialog.Accepted:
                sys.exit(0)
            usuario = dialogo.usuario_autenticado

        sessao.definir_usuario_atual(usuario)

        try:
            backup.backup_automatico_se_necessario(conn)
        except OSError:
            pass

        janela = MainWindow(conn, usuario)
        janela.show()
        app.exec()

        sessao.definir_usuario_atual(None)
        if not janela.logout_solicitado:
            sys.exit(0)


if __name__ == "__main__":
    main()
