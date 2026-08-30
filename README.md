# Controle de Distribuição de Lucros

Sistema local (desktop) para controle de distribuição de lucros entre sócios,
substituindo a planilha de controle. Feito em Python + PySide6, com banco de
dados SQLite local — sem servidor, sem nuvem, cada instalação guarda seus
próprios dados.

## Rodar a partir do código-fonte

Requer Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

No primeiro uso, o sistema pede pra criar o primeiro usuário (administrador).

## Empacotar para Windows (gerar o .exe)

Isso empacota o programa inteiro (Python + PySide6 + tudo) numa pasta que
roda em qualquer Windows sem precisar instalar Python nela.

1. Crie e ative o ambiente virtual, e instale as dependências de
   desenvolvimento (inclui o PyInstaller):

   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements-dev.txt
   ```

2. Gere o pacote:

   ```bat
   pyinstaller controle_lucros.spec
   ```

3. O resultado fica em `dist\ControleDeLucros\` — uma pasta com
   `ControleDeLucros.exe` e todos os arquivos que ele precisa. **É essa
   pasta inteira** que deve ser copiada/distribuída (zipar e mandar, ou
   copiar direto) — não só o `.exe` sozinho, ele não roda fora da pasta.

4. Pra testar, dê duplo-clique em `dist\ControleDeLucros\ControleDeLucros.exe`.

Pra gerar de novo do zero (depois de mudar código), limpe o build anterior:

```bat
pyinstaller --clean controle_lucros.spec
```

### Onde ficam os dados depois de empacotado

Rodando o `.exe`, o banco de dados, backups e preferências (tema
claro/escuro) ficam em `%LOCALAPPDATA%\ControleDeLucros\` — não dentro da
pasta do programa. Isso significa que dá pra atualizar o programa (trocar os
arquivos em `dist\ControleDeLucros\` por uma versão nova) sem perder os
dados: eles moram em outro lugar, específico do usuário do Windows logado.

### Se o build falhar reclamando de gráficos (QtCharts) ou exportação em PDF

Em builds mais antigas de PyInstaller isso pode não detectar esses módulos
do Qt sozinho. Se acontecer, gere de novo assim:

```bat
pyinstaller --clean --hidden-import PySide6.QtCharts --hidden-import PySide6.QtPrintSupport --hidden-import PySide6.QtSvgWidgets controle_lucros.spec
```

## Rodar os testes

```bash
pip install -r requirements-dev.txt
pytest
```
