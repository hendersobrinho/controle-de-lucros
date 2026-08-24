import sys

from PySide6.QtWidgets import QApplication, QDialog

from controle_lucros import backup, db, repositories as repo, sessao
from controle_lucros.ui.icones import icone_app
from controle_lucros.ui.login import DialogoLogin, DialogoPrimeiroUsuario
from controle_lucros.ui.main_window import MainWindow
from controle_lucros.ui.theme import build_stylesheet


def main() -> None:
    conn = db.connect()
    db.init_schema(conn)

    app = QApplication(sys.argv)
    app.setWindowIcon(icone_app())
    app.setStyleSheet(build_stylesheet())

    while True:
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
