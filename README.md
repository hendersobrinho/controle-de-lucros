# Controle de Distribuição de Lucros

Sistema local (desktop) para controle de distribuição de lucros entre sócios,
substituindo a planilha de controle. Feito em Python + PySide6, com banco de
dados SQLite local — sem servidor, sem nuvem, cada instalação guarda seus
próprios dados.

## Como funcionam as telas de cadastro

Nas telas de **Empresas · Cadastro** e **Sócios**, o formulário da direita tem
três estados, sinalizados pelo aviso acima dos campos e pelo botão em destaque:

| Estado | Como aparece |
|---|---|
| Bloqueado | Campos e rótulos apagados; **Novo** em destaque. Nada foi selecionado ainda. |
| Novo registro | Campos liberados com o cursor no primeiro deles; **Salvar** em destaque. |
| Editando *fulano* | Campos preenchidos com o registro selecionado; **Salvar** e **Excluir** liberados. |

O destaque de botão primário acompanha a próxima ação esperada, e o aviso do
modo de edição diz de quem é o registro e que salvar **substitui** aquele
registro — para cadastrar outro é preciso clicar em **Novo** antes.

O botão **Cancelar** aparece sempre que o formulário está aberto: descarta o
que foi digitado e volta ao estado bloqueado, sem alterar nada do que já
estava salvo.

## Modelos de planilha

A importação em massa (**Empresas · Importação em massa**) tem três modelos, e
o combo **Modelo** vale tanto para exportar a planilha em branco quanto para
exportar o cadastro atual:

| Modelo | Colunas | Para quê |
|---|---|---|
| Completo | 16 | Empresas, sócios, saída e distribuição de uma vez |
| Empresas e sócios | 11 | Só o quadro societário |
| Só empresas | 5 | Uma linha por empresa, sem sócios |

Todos são lidos pelo mesmo importador — as colunas são identificadas pelo nome
no cabeçalho, então um modelo menor é só uma planilha com menos colunas.
Importar por um modelo enxuto **não apaga** o que ele não contém.

Toda planilha exportada (inclusive a de distribuição) sai com uma segunda aba
**Exemplo**, preenchida com dados fictícios, mostrando como repetir a empresa
para cada sócio, que o mesmo sócio se repete em empresas diferentes sem
duplicar cadastro, e que sócio pode ser pessoa jurídica. O exemplo fica em aba
separada de propósito: junto dos dados, quem esquecesse de apagar importaria
empresas fictícias.

## Distribuição trimestral

Além da aba de **Distribuição anual**, há a de **Distribuição trimestral**, para
as empresas que deliberam por trimestre em vez de uma vez no fim do ano. Cada
trimestre registra, por sócio, o valor distribuído, o pró-labore e o IRRF.

A cada lançamento, a distribuição **anual** daquele sócio passa a ser a soma dos
trimestres já lançados — o anual vai acumulando sozinho, sem ninguém somar à
mão, e o informe de rendimentos (que lê o anual) acompanha. A coluna **Origem**
na aba anual mostra de onde veio cada valor:

- `trimestres` — o valor é o somatório dos trimestres lançados;
- `editado à mão (trimestres: R$ …)` — alguém digitou outro valor na aba anual;
  ele prevalece **até o próximo lançamento trimestral**, que volta a escrever a
  soma por cima;
- `—` — a empresa não usa controle trimestral, e nada mudou pra ela.

Trancar o período na aba anual tranca os lançamentos trimestrais do mesmo ano.

A aba trimestral também exporta e importa planilha, no mesmo formato da anual
(CPF, Sócio, Valor Distribuído, Pró-labore, IRRF). Os valores entram no
trimestre selecionado no topo da tela — que aparece no título da janela de
escolha do arquivo. Substituir lançamento já existente pede confirmação;
trimestre em branco importa direto.

## Informe de rendimentos

A aba **Sócios** emite o Comprovante de Rendimentos Pagos e de Imposto sobre a
Renda Retido na Fonte no modelo da Instrução Normativa RFB nº 2.060/2021 —
selecione o sócio e clique em **Informe de rendimentos**.

É um comprovante por empresa (cada uma é uma fonte pagadora, com o seu próprio
CNPJ), e dá pra emitir todos de uma vez, um PDF por empresa. O exercício é
sempre o ano seguinte ao ano-calendário escolhido.

O sistema já preenche o que ele controla — pró-labore e IRRF no Quadro 3,
lucro distribuído no Quadro 4 e o saldo de empréstimo da empresa ao sócio no
Quadro 7. O que ele não controla (INSS, 13º, pensão alimentícia, diárias) é
digitado na tela, conferido contra a folha e fica guardado por sócio, empresa
e ano — reemitir depois não exige digitar tudo de novo.

O botão **Visualizar** mostra o mesmo HTML que vai pro PDF, então conferir na
tela é conferir o documento impresso.

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

### Gerar um instalador (Inno Setup)

Opcional — empacota a pasta `dist\ControleDeLucros\` num instalador único
(`.exe`) com atalho no menu Iniciar, atalho na Área de Trabalho (opcional) e
desinstalador. Requer o [Inno Setup](https://jrsoftware.org/isinfo.php)
instalado no Windows, e que o passo anterior (`pyinstaller controle_lucros.spec`)
já tenha rodado.

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" controle_lucros.iss
```

O instalador final fica em `installer\ControleDeLucros_Setup_<versão>.exe`.
Os dados do usuário (banco, backups, preferências) ficam em
`%LOCALAPPDATA%\ControleDeLucros\`, fora da pasta de instalação — então
desinstalar ou reinstalar/atualizar o programa nunca apaga os dados.

Pra lançar uma nova versão, atualize `MyAppVersion` no topo do
`controle_lucros.iss` antes de gerar o instalador de novo.

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
