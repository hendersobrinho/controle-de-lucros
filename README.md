# Controle de Distribuição de Lucros

Sistema desktop para controle de distribuição de lucros entre sócios,
substituindo a planilha de controle. Feito em Python + PySide6, com o banco de
dados num servidor PostgreSQL do escritório — o programa é instalado em cada
PC e todos se conectam no mesmo banco. Sem nuvem.

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

### A tela de entrada

É a primeira coisa que se vê do programa todo dia, e por isso tem uma coluna
só, centrada: marca, um **Seja bem-vindo**, os campos e o botão de entrar,
tudo dentro do mesmo cartão usado no resto do sistema. O primeiro acesso
(quando ainda não há usuário) usa o mesmo desenho, com o texto explicando que
a conta criada ali será a administradora.

### A tipografia

Uma família só, sem serifa, com a **Segoe UI** à frente da lista: no Windows,
onde o programa roda instalado, ela é a fonte do próprio sistema — a mais
comum que existe por lá, e a que faz o programa parecer parte do ambiente. As
seguintes (Inter, Noto Sans, Cantarell) cobrem Linux e macOS sem depender de
fonte empacotada junto. Os títulos usavam serifa (Constantia/Cambria), o que
dava ao programa um ar de documento antigo; a mistura das duas famílias era o
que mais pesava. O corpo subiu de 13 para 14px.

### Os botões e a espera

Os botões têm três níveis, e é o contorno que os separa: o **primário** (tinta
cheia) é a próxima ação esperada, o secundário tem contorno fino — antes era
contorno grosso em tinta cheia, o que fazia toda barra de ações parecer uma
fileira de botões primários competindo entre si —, e o de **perigo** (excluir,
encerrar) é o único vermelho. Cantos mais arredondados, mais respiro interno e
foco visível pelo teclado, que o retângulo pontilhado do Qt não dava.

Operação demorada agora avisa ([ocupado.py](controle_lucros/ui/ocupado.py)). O
trabalho roda na mesma linha de execução que desenha a tela, então durante
alguns segundos a janela não responde — sem sinal nenhum, a leitura é de
programa travado, e a reação natural é clicar de novo. Há duas formas: quando
dá para contar os passos (gravar a importação linha a linha, emitir um informe
por empresa), a barra anda de verdade com "84 de 160"; quando é uma chamada só
(ler o PDF, gravar a planilha), fica a janelinha dizendo o que está
acontecendo, com o cursor de espera.

A contagem vem de baixo: `aplicar_importacao_cadastro` e `gerar_pdfs` aceitam
um callback opcional `progresso(feitos, total)`. Assim o repositório não
precisa saber que existe uma tela, e continua chamável sem callback nenhum — é
como os testes o usam.

### As tabelas

Todas as listas do sistema usam a `TabelaLista`
([common.py](controle_lucros/ui/common.py)), que troca a grade quadriculada do
Qt por linhas de lista. A grade desenha trilhos verticais que descem até o
último registro e param no ar: com quatro empresas numa tela alta, a tabela
parece cortada no meio. Sem os trilhos, cada registro é uma linha separada da
seguinte, e onde a lista acaba é só onde ela acaba.

A largura também tem dono. Sobrando espaço, ele vai para uma coluna escolhida
por tela (o nome da empresa, o sócio, os detalhes do log) e o vão morto à
direita desaparece; faltando, é dessa mesma coluna que sai — até um mínimo, e
só quando isso realmente evita a barra de rolagem. Quem cede é sempre uma só
porque a largura que o Qt calcula é a exata do conteúdo, e tirar um pixel de
uma coluna de data já corta o `2010-01-05` no meio. A regra é uma função pura,
`larguras_ajustadas`, testada sem abrir janela. Texto que não coube inteiro
ganha o conteúdo completo como dica, e tabela vazia diz que está vazia em vez
de parecer tela que não carregou.

## Formatos de planilha

A tela **Sistema · Importação e exportação** gira em torno de um conceito só, o
**formato**, e ele vale para os dois lados: exporta no mesmo desenho em que
importa. São dois tipos — os *modelos do sistema*, lidos pelo nome no
cabeçalho, e os *layouts* configurados pelo usuário, lidos pela posição da
coluna (adiante).

Os três modelos do sistema:

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

## Layouts de coluna: importar planilha de qualquer origem

Planilha que já existe — vinda de outro sistema contábil, do banco, de um
relatório antigo — não precisa ser remontada no modelo daqui. Um **layout**
descreve a planilha que o usuário já tem: para cada campo do cadastro, a
**letra da coluna** onde ele está (`A`, `B`, `AC`…) e a linha em que os dados
começam. Campo sem letra é informação que aquela origem não traz.

Salvo com um nome, o layout vira o formato daquela origem: configura-se uma vez
e depois é só apontar o arquivo. Na tela, **Novo layout** começa do zero e
**Duplicar como layout** já vem preenchido a partir do formato selecionado.

A grade de letras fica recolhida fora dessas horas. Ela abre ao criar ou
duplicar um layout e ao clicar em **Editar layout**; salvar recolhe de volta.
O uso diário é escolher o formato e apontar o arquivo, e dezesseis caixinhas
de letra permanentes na tela só atrapalhariam isso.

**Conferir com uma planilha…** abre um arquivo e mostra as primeiras linhas já
lidas pelo layout, sem importar nada — a mesma prévia aparece como confirmação
antes de qualquer importação. É o que separa configurar as letras no escuro de
conferir antes de gravar, porque uma letra errada só apareceria muito depois.

A validação recusa o que falharia em silêncio: nome da empresa é obrigatório,
layout com dados de sócio exige a coluna do nome do sócio (sem ela toda linha
seria descartada), e a mesma letra não pode estar em dois campos. Daí em
diante o caminho é o de sempre — CPF identifica o sócio, empresa nova é criada,
sócio novo espera confirmação, e vínculo que já existe é ignorado.

## Importar o relatório de sócios (PDF ou planilha)

Na mesma tela, o botão **Importar relatório de sócios** lê o relatório *Cadastro
de Sócios* emitido por outro sistema contábil e traz, de cada empresa listada, os
sócios com CPF/CNPJ, participação e datas de entrada e saída — quem está
migrando de sistema alimenta o cadastro sem redigitar o quadro societário.

Daí em diante é o mesmo caminho da planilha: empresa reconhecida ou criada,
sócio reconhecido pelo CPF, e o que não bater vai para a revisão — onde
**Cadastrar todos como novos sócios** resolve o quadro inteiro de uma empresa
nova com uma confirmação só, em vez de uma por pessoa.

O relatório não traz CNPJ da empresa, capital social nem quantidade de cotas:
empresa criada por aí nasce com esses campos em branco, e a tela avisa isso
antes de aplicar. A leitura usa o QtPdf, que já vem no PySide6 — nenhuma
dependência nova; só PDF com camada de texto (gerado por sistema, não
escaneado).

A leitura não casa o layout inteiro com uma expressão regular, porque cada
sistema imprime esse relatório de um jeito e recusar o arquivo é o pior
resultado possível — a pessoa não tem como saber o que desagradou. Em vez
disso, [relatorio_socios.py](controle_lucros/relatorio_socios.py) **ancora no
CPF/CNPJ**, o único campo de formato inconfundível, e lê o resto em relação a
ele: antes vêm código e nome, depois as datas e o percentual, em qualquer ordem
e com colunas extras no meio. São aceitos cabeçalho com ou sem dois-pontos,
travessão no lugar do hífen, data do quadro em linha separada, linha sem coluna
de código, percentual com `%`, CPF sem pontuação, datas em quatro formatos e o
cabeçalho da empresa repetido a cada página (as páginas viram um quadro só).
No cabeçalho, também `Cliente:`/`Estabelecimento:`, número e nome em colunas
separadas, empresa sem número (quando o arquivo não tem nenhuma numerada) e
empresa identificada por CNPJ — que nesse caso é aproveitado.

O outro lado é igualmente testado: o cabeçalho e o rodapé com o CNPJ do
escritório emissor, linhas de total e cabeçalhos de coluna **não** viram
sócios — uma linha de sócio precisa ter nome, documento e data. E o que tinha
cara de sócio mas não foi entendido é contado e mostrado na confirmação, para
que nunca se importe parte do quadro em silêncio.

O mesmo relatório costuma sair também em planilha, e ela é aceita: **.xls** (o
BIFF do Excel 97-2003, que é o que esses sistemas exportam), .xlsx e .csv. Como
nenhuma biblioteca instalada lê .xls — e a usual, `xlrd`, recusa o arquivo real
que motivou o recurso, por causa de registros fora de ordem que o exportador
grava —, [leitor_xls.py](controle_lucros/leitor_xls.py) faz essa leitura com a
biblioteca padrão do Python: abre o container OLE, percorre os registros BIFF
sem confiar na estrutura declarada e recolhe as células onde estiverem,
convertendo data (que no Excel é número com formato de data) e texto
compartilhado. Continua sem dependência nova.

Lida a planilha, cada linha vira uma linha de texto e segue pelo **mesmo**
leitor do PDF — manter duas listas de regras de layout garantiria que uma
ficasse para trás. Como a leitura se ancora no CPF/CNPJ, as colunas podem estar
em outra ordem, e estão: na planilha a participação vem antes das datas. O
arquivo real foi conferido dos dois jeitos e produz exatamente o mesmo quadro
societário.

**Reimportar é seguro:** o relatório do mês seguinte traz o histórico inteiro
de novo, e o importador reconhece o que já existe — inclusive os vínculos já
encerrados, que antes eram recriados a cada importação.

## Mapa de vínculos do sócio

Na aba **Sócios**, o botão **Mapa de vínculos** (no alto do painel de vínculos)
abre um diagrama do que a tabela mostra em linhas: o sócio no centro e as
empresas ao redor, ligadas por um traço com o percentual e as datas. Vínculo
encerrado sai com traço pontilhado e caixa em vermelho, de modo que a diferença
sobrevive à impressão em preto e branco.

O desenho é exportável em **PDF** (uma página, pronta para anexar) e em **SVG**
(vetorial, para slide ou laudo). A geometria vive em
[mapa_vinculos.py](controle_lucros/mapa_vinculos.py), sem Qt — é lá que se testa
que caixa não fica por cima de caixa —, e uma única função de pintura serve à
tela, ao PDF e ao SVG, para que o arquivo exportado nunca divirja do que se viu
antes de exportar. Tudo com QtSvg/QPdfWriter, que já vêm no PySide6: nenhuma
dependência nova.

## O que os dashboards apontam

Os gráficos respondiam "quanto" e "como ficou dividido" — descrição, não
diagnóstico. Duas leituras novas ([analise.py](controle_lucros/analise.py),
módulo puro, sem banco e sem Qt) usam dados que já estavam gravados lado a lado
e nunca eram cruzados:

- **Distribuição sem pró-labore** — sócio pessoa física que recebeu lucros e
  nenhum pró-labore no ano, somado por (sócio, empresa) e com os anos em que a
  situação se repetiu. Pessoa jurídica é excluída: holding sócia não tem
  pró-labore, e listá-la encheria o painel de casos que não são caso — o aviso
  que grita sempre deixa de ser lido.
- **Desvio em relação à participação** — quanto cada sócio recebeu além ou
  aquém, em reais, do que a participação daria. O esperado sai do total
  distribuído *daquele ano*, porque é ele que a participação divide; misturar
  anos daria um esperado que nunca existiu. O gráfico é de barras divergentes e
  não usa verde: receber aquém é tão fora do eixo quanto receber além.

As duas substituíram as pizzas que havia — a de proporcional × desproporcional
repetia em desenho os dois cartões logo acima, e a de classificações dizia
quantos sócios estavam fora do eixo sem dizer por quanto.

O programa aponta o fato e não dá o veredito: se o pró-labore é compatível com
o trabalho, ou se a desproporção está amparada no contrato social, é análise de
quem entende do caso. E fica registrado o que **não** dá para fazer: a leitura
mais forte seria distribuição acima do lucro apurado, mas o sistema não guarda
resultado do exercício — precisaria de um campo novo por empresa e por ano.

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

O Quadro 7 também informa a **variação de cotas** do ano, que o sistema deduz
do histórico de vínculos: quantas cotas o sócio tinha em 31/12 do ano anterior
e em 31/12 do ano-base, o valor nominal de cada uma (capital social ÷ total de
cotas da empresa) e, quando ele terminou o ano fora da sociedade, a data da
saída. Sai impresso como alienação ou aquisição de cotas, com o saldo que
ficou — é o que o sócio lança nas fichas de *Bens e Direitos* e de *Dívidas e
Ônus Reais*. Reduzir participação sem sair não é lido como saída, e ano sem
mudança de cotas não imprime nada disso.

O botão **Visualizar** mostra o mesmo HTML que vai pro PDF, então conferir na
tela é conferir o documento impresso.

## Rodar a partir do código-fonte

Requer Python 3.11+ e um PostgreSQL acessível (15 ou mais novo — pra
desenvolver, o da própria máquina serve).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

Na primeira abertura, o sistema pergunta a conexão com o PostgreSQL (servidor,
porta, banco, usuário, senha) e, com o banco vazio, pede pra criar o primeiro
usuário (administrador). O banco e o usuário precisam existir antes — veja
[Servidor PostgreSQL](#servidor-postgresql).

## Ícone do programa

`controle_lucros/ui/assets/logo.svg` é a fonte; `logo.png` e `logo.ico` são
gerados a partir dele. Depois de mexer no SVG:

```bash
python tools/gerar_icones.py
```

O `.ico` sai com dez resoluções (16 a 256), cada uma desenhada direto do vetor
em vez de reduzida de um PNG grande — reduzir borra os traços nos tamanhos
pequenos, que são justamente os da barra de tarefas e da lista de arquivos.

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
   python -m PyInstaller --clean controle_lucros.spec
   ```

3. O resultado fica em `dist\ControleDeLucros\` — uma pasta com
   `ControleDeLucros.exe` e todos os arquivos que ele precisa. **É essa
   pasta inteira** que deve ser copiada/distribuída (zipar e mandar, ou
   copiar direto) — não só o `.exe` sozinho, ele não roda fora da pasta.

4. Pra testar, dê duplo-clique em `dist\ControleDeLucros\ControleDeLucros.exe`.

Pra gerar de novo do zero (depois de mudar código), limpe o build anterior:

```bat
python -m PyInstaller --clean controle_lucros.spec
```

> **Por que `python -m PyInstaller` e não só `pyinstaller`?** O `pip` instala
> os executáveis numa pasta `Scripts` que muitas vezes não está no PATH do
> Windows — aí `pyinstaller` dá "não é reconhecido como um comando interno ou
> externo" mesmo estando instalado. Chamando como módulo, quem resolve é o
> próprio Python. Vale o mesmo pro `pytest`: `python -m pytest`.

### Onde ficam os dados depois de empacotado

O cadastro inteiro (empresas, sócios, lançamentos, usuários) fica no
**PostgreSQL**, no servidor. Em cada PC, fica só o que é daquela máquina, em
`%PROGRAMDATA%\ControleDeLucros\data\` (normalmente
`C:\ProgramData\ControleDeLucros\data\`), fora da pasta do programa:

- `configuracao_local.json` — a conexão com o servidor (`db.definir_conexao`),
  com a senha do banco em texto: legível por quem usa aquele PC;
- `preferencias.json` — tema, pasta dos backups, responsável do informe,
  último formato de importação;
- `backups\` — os backups feitos por este PC (pasta padrão, configurável);
- o registro de falhas (`relatorio_erro`).

`%PROGRAMDATA%` é a pasta da **máquina**, não a de cada conta do Windows: a
conexão configurada uma vez vale pra todos os usuários daquele PC.

> A permissão de escrita dessa pasta pra usuário comum é o instalador que
> abre (seção `[Dirs]` do `controle_lucros.iss`). Copiando a pasta
> `dist\ControleDeLucros\` na mão, sem instalador, é preciso liberar
> `C:\ProgramData\ControleDeLucros` pro grupo Usuários.

### Servidor PostgreSQL

O banco roda num **PostgreSQL 15**: é a versão mais nova cujo instalador
(EDB) é testado no Windows Server 2016, o servidor do escritório — que não
roda o próprio programa, porque o Qt 6 exige Windows 10 1809 / Server 2019.
O SQL do sistema não usa nada posterior ao 15. O passo a passo pra quem cuida
do servidor (instalar, criar o banco, liberar a rede, firewall, backup com
`pg_dump`) está no manual do programa, tópico **Servidor PostgreSQL**
(`ui/manual.py`, `_SERVIDOR`). Em resumo:

```sql
CREATE ROLE controle_lucros LOGIN PASSWORD '...';
CREATE DATABASE controle_lucros OWNER controle_lucros ENCODING 'UTF8';
```

mais uma linha no `pg_hba.conf` liberando a rede do escritório e a porta 5432
no firewall. O **OWNER** é obrigatório: no PostgreSQL 15 só o dono cria
tabelas no schema `public`, e o programa cria as dele na primeira conexão
(`db.init_schema`, protegido por uma trava pra dois PCs abrindo ao mesmo tempo
não disputarem).

Como o código conversa com o banco (`db.Conexao`):

- **Mesmo jeito do sqlite3**, de onde o sistema veio: `conn.execute(...)`
  devolve o cursor, linhas se leem por nome ou posição (`db.Linha`), e
  gravações ficam pendentes até `conn.commit()`. Parâmetros são `%s`.
- **Leitura não abre transação.** Só INSERT/UPDATE/DELETE/DDL abrem; assim uma
  tela parada não segura travas no servidor.
- **Erro no meio de uma gravação desfaz a transação na hora** — no PostgreSQL,
  sem isso, todo comando seguinte falharia com "transaction is aborted".
- **Conexão que caiu é refeita no próximo comando** (servidor reiniciado, rede
  que piscou), e a ação que falhou vira mensagem explicando o que fazer
  (`db.explicar_erro`, que reconhece as mensagens do servidor em inglês e em
  português).
- **Gravação travada por outro PC** espera até 10 s (`lock_timeout`) e então
  vira aviso de "tente de novo".
- Datas continuam como texto ISO (`'2024-03-31'`) em colunas `TEXT`; um
  `date` do Python é convertido pra texto ao gravar, como o sqlite3 fazia.
  Valores do informe são `BIGINT` de centavos.

**Backup** (`backup.py`): arquivo `.json` com todas as tabelas, lidas numa
transação `REPEATABLE READ` (uma foto só, mesmo com outro PC gravando).
Restaurar é uma transação única — `TRUNCATE` de tudo, inserção e ajuste das
sequências de id —, então ou o banco inteiro vira o do backup, ou nada muda.
Não depende do `pg_dump` estar nos PCs; o backup do próprio servidor (com
`pg_dump`, agendado) é recomendado à parte, no manual.

### Gerar um instalador (Inno Setup)

Opcional — empacota a pasta `dist\ControleDeLucros\` num instalador único
(`.exe`) com atalho no menu Iniciar, atalho na Área de Trabalho (opcional) e
desinstalador. Requer o [Inno Setup 6](https://jrsoftware.org/isinfo.php)
instalado no Windows, e que o passo anterior (`python -m PyInstaller --clean controle_lucros.spec`)
já tenha rodado — se não tiver, a compilação para com uma mensagem dizendo
isso, em vez de gerar um instalador vazio.

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" controle_lucros.iss
```

O instalador final fica em `installer\ControleDeLucros_Setup_<versão>.exe`.
Ele instala em Arquivos de Programas (pede elevação) e cria
`C:\ProgramData\ControleDeLucros\` já com escrita liberada pro grupo
Usuários. A conexão com o servidor **não** é perguntada no instalador: ele
roda como administrador, que não enxerga a rede como quem usa o PC. O
programa pergunta na primeira abertura, já como o usuário. Desinstalar ou
atualizar nunca toca no banco, que está no servidor.

### Lançar uma nova versão

A versão fica num lugar só: `__version__` em `controle_lucros/__init__.py`.
Dali ela vai pras propriedades do `.exe` (aba Detalhes, no Windows), pro nome
do instalador, pra tela **Sobre**, e pro registro de programas instalados.

1. Edite `__version__` em `controle_lucros/__init__.py`.
2. `python -m PyInstaller --clean controle_lucros.spec`
3. `"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" controle_lucros.iss`

Nessa ordem: o instalador se recusa a compilar sem o pacote pronto, e a
versão que ele usa é escrita pelo passo 2.

Como o `AppId` não muda entre versões, instalar por cima é reconhecido pelo
Windows como **atualização** — a entrada em "Aplicativos instalados" continua
sendo uma só, e os dados do usuário não são tocados.

### Se o build falhar reclamando de gráficos (QtCharts) ou exportação em PDF

Em builds mais antigas de PyInstaller isso pode não detectar esses módulos
do Qt sozinho. Se acontecer, gere de novo assim:

```bat
python -m PyInstaller --clean --hidden-import PySide6.QtCharts --hidden-import PySide6.QtPrintSupport --hidden-import PySide6.QtSvgWidgets controle_lucros.spec
```

## Rodar os testes

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Os testes precisam dos binários do PostgreSQL na máquina (`initdb`, `pg_ctl`
— no Ubuntu, o pacote `postgresql`; no Windows, o instalador da EDB): o
`tests/conftest.py` cria um PostgreSQL descartável numa pasta temporária,
numa porta livre, e o desliga no fim. Nenhum servidor de verdade é tocado.
Pra usar um servidor de teste que já existe, aponte
`CONTROLE_LUCROS_TESTE_PG` pra ele (`"host=... dbname=... user=..."`) —
**todas as tabelas do sistema nesse banco são apagadas a cada teste**.
