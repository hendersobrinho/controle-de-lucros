"""Manual do sistema, aberto com F1 em qualquer tela.

O conteúdo fica aqui, em texto, e não num PDF ou site à parte de propósito: o
programa roda em máquina sem internet garantida, e manual que mora fora do
sistema é manual que ninguém acha na hora da dúvida. F1 abre já no tópico da
tela em que a pessoa está — a dúvida quase sempre é sobre o que está na
frente dela.

Cada tópico descreve o que a tela faz e as regras que valem ali. Quando o
comportamento do código mudar, o texto correspondente muda junto: manual
desatualizado é pior que manual nenhum, porque ensina errado.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .icones import icone_app
from . import theme


@dataclass(frozen=True)
class Topico:
    id: str
    titulo: str
    corpo: str


_INICIO = """
<h2>Como o sistema se organiza</h2>
<p>O sistema guarda o histórico societário das empresas e a distribuição de
lucros entre os sócios. Tudo gira em torno de quatro coisas:</p>
<ul>
<li><b>Empresa</b> — o cadastro base (nome, CNPJ, capital, cotas de fundação).</li>
<li><b>Sócio</b> — a pessoa (ou holding), cadastrada uma vez só e reaproveitada
em todas as empresas de que participa.</li>
<li><b>Vínculo</b> — a participação de um sócio numa empresa, com data de
entrada e (quando houver) de saída. É o vínculo que diz quem era sócio de quê
e quando.</li>
<li><b>Distribuição</b> — quanto cada sócio recebeu num ano (e, se a empresa
usar, em cada trimestre).</li>
</ul>

<h3>A regra que vale para o sistema inteiro</h3>
<p><b>Nada é apagado do histórico.</b> Sócio que sai não é excluído: o vínculo
dele ganha uma data de saída e continua aparecendo nos anos em que ele
participou. É isso que permite emitir um informe de 2023 hoje, ou explicar
uma distribuição de três anos atrás.</p>

<h3>Onde ficam os dados</h3>
<p>Tudo num arquivo local, nesta máquina — não há servidor nem nuvem. Por isso
o <b>backup é responsabilidade de quem usa</b>: veja o tópico
<i>Backup</i>.</p>

<p><i>Aperte F1 em qualquer tela para abrir este manual já no tópico dela.</i></p>
"""

_EMPRESAS = """
<h2>Empresas · Cadastro</h2>
<p>O cadastro base da empresa. Nome, CNPJ, capital social e quantidade de cotas
aqui são os valores <b>de fundação</b> — o estado atual de uma empresa que já
teve alterações contratuais vem da alteração mais recente, não daqui.</p>

<h3>Como usar o formulário</h3>
<p>O formulário da direita tem três estados, e o aviso acima dos campos sempre
diz em qual você está:</p>
<ul>
<li><b>Bloqueado</b> — campos apagados, botão <b>Novo</b> em destaque. É o
estado inicial.</li>
<li><b>Novo registro</b> — depois de clicar em <b>Novo</b>. Os campos liberam e
o cursor vai para o primeiro deles.</li>
<li><b>Editando <i>fulano</i></b> — depois de clicar numa linha da tabela. O que
você salvar <b>substitui aquele registro</b>.</li>
</ul>
<p><b>Atenção:</b> com uma linha selecionada, digitar por cima e salvar altera
aquela empresa. Para cadastrar outra, clique em <b>Novo</b> antes.</p>
<p>O botão <b>Cancelar</b> aparece sempre que o formulário está aberto e é a
saída sem gravar nada: descarta o que foi digitado e volta ao estado
bloqueado. Nada do que estava salvo é alterado.</p>

<h3>Nº da empresa</h3>
<p>É o código interno do escritório. Serve para achar a empresa rápido na busca
e é um dos campos usados para reconhecer a empresa na importação em massa —
por isso vale manter único e sem repetição.</p>

<h3>Excluir</h3>
<p>Só é possível excluir uma empresa que não tenha nada pendurada nela — sem
sócios vinculados, alterações contratuais, distribuições ou movimentações. Se
tiver, o sistema recusa e explica o motivo. Isso é proposital: apagar a
empresa apagaria o histórico junto.</p>
"""

_ALTERACOES = """
<h2>Empresas · Alterações contratuais</h2>
<p>Cada alteração contratual é uma <b>fotografia do contrato social</b> num
momento: nome, capital, quantidade de cotas e a movimentação de sócios daquele
evento. É esse histórico que permite saber qual era o capital da empresa em
2022 sem depender do valor de hoje.</p>

<h3>Aberta e fechada</h3>
<p>O selo ao lado de cada alteração mostra a situação:</p>
<ul>
<li><b>Aberta</b> (cadeado dourado) — ainda dá para editar.</li>
<li><b>Fechada</b> (selo vinho) — travada. Nem ela nem os vínculos de sócio
criados por ela podem ser alterados enquanto não for reaberta.</li>
</ul>
<p>Feche a alteração quando o documento estiver registrado. Reabrir é possível
a qualquer momento, e fica no log de atividades.</p>

<h3>Alterações criadas automaticamente</h3>
<p>Mexer nos sócios pela aba <b>Sócios</b> (associar a uma empresa, atualizar
cotas, encerrar vínculo) <b>gera uma alteração contratual sozinha</b>, com a
data que você informar. Por isso o histórico da empresa reflete o que foi feito
na tela de Sócios, e vice-versa — não são dois cadastros separados.</p>
"""

_IMPORTACAO = """
<h2>Importação em massa</h2>
<p>Cadastra empresas, sócios, vínculos e (opcionalmente) distribuição de uma
vez, a partir de uma planilha. <b>Uma linha por (empresa, sócio)</b> — a mesma
empresa aparece repetida em várias linhas, uma para cada sócio dela.</p>

<h3>O caminho recomendado</h3>
<ol>
<li>Escolher o <b>modelo</b> (veja abaixo).</li>
<li><b>Exportar modelo</b> — planilha em branco com as colunas daquele modelo.</li>
<li>Abrir a aba <b>Exemplo</b> da planilha, ver como se organiza, e preencher a
aba <b>Cadastro</b>.</li>
<li><b>Importar planilha</b> e revisar o que o sistema não conseguiu resolver
sozinho.</li>
</ol>
<p>O botão <b>Exportar cadastro atual</b> traz o que já está no sistema, no
modelo escolhido — útil para conferir ou para corrigir em massa.</p>

<h3>Os três modelos</h3>
<p>Todos são lidos do mesmo jeito: as colunas são reconhecidas pelo nome no
cabeçalho, então um modelo menor é só uma planilha com menos colunas — não um
formato diferente. Escolha pelo que você vai cadastrar:</p>
<ul>
<li><b>Completo</b> (16 colunas) — empresas, sócios, participações, saída de
sócio e a distribuição de um ano, tudo de uma vez.</li>
<li><b>Empresas e sócios</b> (11 colunas) — o quadro societário, sem saída nem
distribuição. É o recorte do dia a dia.</li>
<li><b>Só empresas</b> (5 colunas) — uma linha por empresa, sem sócios. Os
sócios entram depois.</li>
</ul>
<p>Importar por um modelo menor <b>não apaga</b> o que ele não tem: mandar a
planilha de "Só empresas" não encerra vínculo nem zera distribuição de quem já
está cadastrado.</p>

<h3>A aba "Exemplo"</h3>
<p>Toda planilha exportada tem uma segunda aba com dados fictícios preenchidos,
mostrando o que costuma gerar dúvida:</p>
<ul>
<li><b>Uma linha por (empresa, sócio).</b> Empresa com três sócios ocupa três
linhas, repetindo os dados da empresa iguais em todas.</li>
<li><b>O mesmo sócio em empresas diferentes</b> é o mesmo cadastro — ele é
reconhecido pelo CPF e não vira sócio duplicado.</li>
<li><b>Sócio pode ser pessoa jurídica</b>: CNPJ no lugar do CPF e tipo
"Jurídica".</li>
</ul>
<p>O exemplo fica numa aba separada de propósito: se estivesse junto dos dados,
quem esquecesse de apagar importaria empresas fictícias para dentro do
sistema.</p>

<h3>Como o sistema reconhece o que já existe</h3>
<p><b>Empresa</b>, na ordem: nº da empresa, depois CNPJ, depois nome exato (e
só se houver uma única empresa com aquele nome). Não achou nenhuma?
<b>A empresa é criada automaticamente.</b></p>
<p><b>Sócio</b>: CPF primeiro; se não achar, nome exato (e só se houver um
único sócio com aquele nome). Não achou? <b>O sócio nunca é criado sozinho</b>
— a linha vai para a tela de revisão, onde você escolhe um sócio existente ou
confirma o cadastro de um novo. É assim de propósito: sócio duplicado espalha
erro para todas as empresas dele.</p>

<h3>Quando a linha se contradiz</h3>
<p>Se o nº da empresa e o CNPJ da mesma linha apontarem para <b>empresas
diferentes</b>, o sistema não escolhe nenhuma: avisa qual é a divergência e
deixa a linha de fora. Isso é quase sempre erro de digitação, e aplicar em cima
de uma das duas lançaria distribuição na empresa errada sem ninguém notar.</p>

<h3>O que a importação nunca faz</h3>
<ul>
<li>Não duplica empresa nem vínculo: se o sócio já tem vínculo ativo com a
empresa, a linha é contada como "já existia" e ignorada.</li>
<li>Não cria sócio sem confirmação.</li>
<li>Não altera período trancado.</li>
</ul>
<p>O nome tem que bater <b>exatamente</b> (só maiúsculas/minúsculas e espaços
das pontas são ignorados). "João" e "Joao" não se encontram — cai na
revisão.</p>
"""

_SOCIOS = """
<h2>Sócios</h2>
<p>O sócio é cadastrado <b>uma vez só</b> e reaproveitado em todas as empresas
de que participa. O painel da direita mostra os vínculos do sócio selecionado.</p>

<h3>Cadastro</h3>
<p>Mesmo formulário de três estados das Empresas: <b>Novo</b> libera os campos
para um cadastro novo; clicar numa linha entra em edição daquele sócio;
<b>Cancelar</b> sai sem gravar. O aviso acima dos campos diz sempre qual é o
caso.</p>
<p><b>Tipo</b> decide a máscara do documento: pessoa física usa CPF, pessoa
jurídica usa CNPJ (holding sócia de outra empresa é comum). O CPF/CNPJ não pode
repetir entre sócios — o sistema recusa e mostra quem já usa aquele
documento.</p>

<h3>Vínculos com empresas</h3>
<p><b>Associar a uma empresa</b> fica solto porque é a única ação que não
precisa de um vínculo selecionado. As outras quatro estão no menu <b>Ações do
vínculo</b>, que só destrava depois de clicar numa linha da tabela. A
diferença entre elas importa:</p>
<ul>
<li><b>Associar a uma empresa</b> — cria o vínculo e abre uma alteração
contratual na empresa.</li>
<li><b>Editar datas</b> — corrige as datas de um vínculo existente.
<b>Não</b> gera alteração contratual: serve para consertar um registro errado,
não para registrar um evento novo.</li>
<li><b>Atualizar cotas</b> — encerra o vínculo atual e abre outro com os novos
valores, preservando o histórico. Gera alteração contratual.</li>
<li><b>Encerrar vínculo</b> — marca a data de saída. O sócio continua no
histórico e nos anos em que participou.</li>
<li><b>Excluir vínculo</b> — apaga o registro de vez. Use <b>só</b> para
corrigir um vínculo cadastrado por engano (empresa errada, sócio errado). Para
registrar uma saída de verdade, use <b>Encerrar vínculo</b>.</li>
</ul>

<h3>Informe de rendimentos</h3>
<p>O botão à direita abre a emissão do comprovante anual do sócio selecionado.
Veja o tópico <i>Informe de rendimentos</i>.</p>
"""

_DISTRIBUICAO = """
<h2>Distribuição anual</h2>
<p>Para uma empresa e um ano, mostra cada sócio que participou naquele ano com
cotas, percentual de capital, valor distribuído, pró-labore, IRRF e empréstimo
recebido da empresa.</p>

<h3>Quem aparece na lista</h3>
<p>Todo sócio que teve vínculo em <b>qualquer momento</b> do ano. Quem entrou
em março ou saiu em agosto aparece igual, destacado por cor (verde entrou,
vermelho saiu), com a situação escrita na última coluna.</p>

<h3>Editar</h3>
<p>O botão <b>Editar</b> libera a edição direto na tabela. Valor distribuído,
pró-labore e IRRF são salvos na hora. Já mexer em <b>% de capital ou cotas</b>
é um evento societário: o sistema pede uma data de vigência e gera uma
alteração contratual. Essa data precisa cair <b>dentro do ano em edição</b>,
senão a mudança só passa a valer depois e a tela daquele ano continua mostrando
o valor antigo — parecendo que não salvou.</p>

<h3>Avisos de inconsistência</h3>
<p>Duas faixas podem aparecer no topo:</p>
<ul>
<li><b>Cotas não conferem</b> — a soma das cotas dos sócios difere do total da
empresa. Normalmente houve aumento de capital sem redistribuir entre os
sócios.</li>
<li><b>Percentuais não somam 100%</b> — o cadastro societário está incompleto
ou desatualizado.</li>
</ul>
<p>São avisos, não travas: o sistema deixa salvar assim mesmo, porque às vezes
a inconsistência é temporária, no meio de uma correção.</p>

<h3>Trancar o período</h3>
<p>Trancar um ano congela <b>tudo</b> daquele ano naquela empresa: distribuição,
pró-labore, IRRF, movimentações, lançamentos trimestrais e qualquer
entrada/saída/mudança de cotas datada dentro dele. Serve para fechar o exercício
depois de conferido. Destrancar é possível a qualquer momento e fica no log.</p>

<h3>Importar planilha</h3>
<p>Importa <b>só os valores</b> — nunca cria empresa nem sócio. A empresa é a
que está selecionada no topo da tela (a planilha nem tem coluna de empresa), e
cada linha é casada com um sócio já cadastrado por CPF, ou por nome exato se o
CPF não bater.</p>
<p>Quando o sócio existe mas <b>não tem vínculo ativo com aquela empresa</b> no
ano, a linha vai para revisão em vez de ser aplicada — é a trava que pega
planilha importada na empresa errada.</p>
<p>O modelo exportado já vem com os sócios da empresa preenchidos: só falta
digitar os valores. A aba <b>Exemplo</b> da planilha mostra o preenchimento com
dados fictícios. Importar substitui os valores dos sócios que estiverem na
planilha; quem não estiver nela não é alterado.</p>

<h3>Movimentações</h3>
<p><b>Gerenciar movimentações</b> registra empréstimos (nos dois sentidos),
adiantamento de lucro e devolução de capital do sócio selecionado. A soma dos
empréstimos <i>da empresa para o sócio</i> alimenta a coluna "Empréstimo (ano)"
e o Quadro 7 do informe de rendimentos.</p>
"""

_TRIMESTRAL = """
<h2>Distribuição trimestral</h2>
<p>Para as empresas que deliberam por trimestre em vez de uma vez no fim do
ano. <b>Empresa que não usa esta tela não muda em nada</b> — continua lançando
só o valor anual.</p>

<h3>Como lançar</h3>
<p>Escolha empresa, ano e trimestre, clique em <b>Lançar trimestre</b>, preencha
valor distribuído, pró-labore e IRRF de cada sócio, e salve.</p>
<p>As setas <b>‹</b> e <b>›</b> ao lado do trimestre andam um período por vez e
atravessam a virada de ano: o anterior ao 1º de 2025 é o 4º de 2024. Elas ficam
travadas durante um lançamento em aberto — trocar de período no meio
descartaria o que foi digitado; salve ou cancele antes.</p>

<h3>O que acontece com a distribuição anual</h3>
<p>A cada lançamento, a distribuição <b>anual</b> daquele sócio passa a ser
a <b>soma dos trimestres já lançados</b>. O anual vai acumulando sozinho, sem
ninguém somar à mão — e o informe de rendimentos, que lê o anual, acompanha.</p>
<p>Na aba anual, a coluna <b>Origem</b> mostra de onde veio cada valor:</p>
<ul>
<li><b>trimestres</b> — o valor é o somatório dos trimestres.</li>
<li><b>editado à mão</b> — alguém digitou outro valor na aba anual. Ele
prevalece <b>até o próximo lançamento trimestral</b>, que volta a escrever a
soma por cima.</li>
<li><b>—</b> — a empresa não usa lançamento trimestral.</li>
</ul>
<p>Basta um dos três valores (distribuído, pró-labore ou IRRF) divergir para a
origem virar "editado à mão".</p>

<h3>Corrigir e apagar</h3>
<p>Corrigir um trimestre <b>recalcula</b> o anual, não soma de novo: mudar o 1º
trimestre de R$ 10.000 para R$ 5.000, com R$ 20.000 no 2º, deixa o anual em
R$ 25.000.</p>
<p><b>Limpar trimestre</b> apaga os lançamentos daquele trimestre e recalcula o
anual com os que sobraram. Apagando o último, o anual daquele sócio zera — o
valor não fica pendurado sem origem.</p>

<h3>Quem aparece</h3>
<p>Só os sócios que estavam na sociedade <b>naquele trimestre</b>. Quem saiu no
1º não aparece no 4º. O acumulado do ano mostrado no rodapé, porém, continua
contando o que essa pessoa recebeu.</p>

<h3>Importar planilha</h3>
<p>Mesma planilha da distribuição anual (CPF, Sócio, Valor Distribuído,
Pró-labore, IRRF): o formato é o mesmo, muda só onde os valores entram.
<b>Exportar modelo</b> traz os sócios do trimestre já preenchidos com o que foi
lançado, o que serve também de conferência.</p>
<p>Os valores entram no <b>trimestre selecionado no topo da tela</b> — a
planilha em si não guarda a que trimestre pertence. Por isso o período e a
empresa aparecem no título da janela ao escolher o arquivo: confira ali antes
de abrir.</p>
<p>Se algum sócio da planilha já tiver valor lançado naquele trimestre, a tela
avisa antes de substituir. Trimestre em branco importa direto.</p>
<p>Importar aqui alimenta a distribuição anual do mesmo jeito que digitar:
o anual passa a mostrar a soma dos trimestres lançados.</p>
"""

_INFORME = """
<h2>Informe de rendimentos</h2>
<p>Emite o <b>Comprovante de Rendimentos Pagos e de Imposto sobre a Renda
Retido na Fonte</b>, no modelo da Instrução Normativa RFB nº 2.060/2021. Abre
pelo botão <b>Informe de rendimentos</b> na aba Sócios, com o sócio
selecionado.</p>

<h3>Um comprovante por empresa</h3>
<p>Cada empresa é uma <b>fonte pagadora</b> distinta e emite o seu próprio
comprovante, com o seu CNPJ. Sócio de três empresas recebe três documentos. A
lista da esquerda traz uma caixa por empresa: marque as que devem sair e clique
em cada uma para conferir os valores dela.</p>

<h3>Ano-calendário e exercício</h3>
<p>Escolha o <b>ano-calendário</b> — o ano em que os rendimentos foram pagos. O
<b>exercício</b> é sempre o ano seguinte: pago em 2025, exercício 2026. O
sistema calcula sozinho.</p>

<h3>O que vem preenchido e o que você digita</h3>
<p>O sistema preenche o que ele já controla:</p>
<ul>
<li><b>Pró-labore</b> → Quadro 3, linha 1</li>
<li><b>IRRF</b> → Quadro 3, linha 5</li>
<li><b>Distribuição de lucros</b> → Quadro 4, linha 5</li>
<li><b>Empréstimo da empresa ao sócio</b> (saldo em 31/12) → Quadro 7</li>
</ul>
<p>O que ele não controla — <b>INSS</b>, 13º, pensão alimentícia, diárias — sai
zerado e precisa ser digitado, conferido contra a folha. Depois de salvo, fica
guardado por sócio, empresa e ano: reemitir no ano seguinte não exige digitar
tudo de novo.</p>
<p><b>Confira sempre antes de emitir.</b> Os valores sugeridos vêm dos
lançamentos do sistema, que podem estar incompletos.</p>

<h3>O saldo de empréstimo</h3>
<p>É a soma dos empréstimos <i>da empresa para o sócio</i> até 31/12 do ano. O
sistema não registra amortização, então <b>é uma sugestão</b> — corrija na tela
se o sócio já pagou parte. Empréstimo no sentido contrário (do sócio para a
empresa) não abate esse saldo: são dívidas em direções opostas, que a
declaração pede em fichas separadas.</p>
<p>Empréstimo não é rendimento: ele sai no Quadro 7, para o sócio lançar na
ficha de <i>Dívidas e Ônus Reais</i>.</p>

<h3>Conferir e emitir</h3>
<p><b>Visualizar</b> mostra o mesmo documento que vai para o PDF — conferir na
tela é conferir o papel. <b>Emitir PDF</b> pede a pasta e grava um arquivo por
empresa marcada, salvando os valores junto.</p>
<p>Reemitir não sobrescreve: o arquivo anterior continua na pasta e o novo sai
com <i>(1)</i> no nome. Assim dá para ver o que já foi entregue ao sócio.</p>

<h3>CPF</h3>
<p>O CPF é validado de verdade (dígito verificador). Se estiver errado, o
sistema avisa no cabeçalho e pergunta antes de emitir — comprovante com CPF
errado impede o sócio de importar os dados na declaração dele, e o erro só
aparece meses depois.</p>
"""

_DASHBOARD = """
<h2>Dashboards</h2>
<p>Duas visões de leitura, sem edição.</p>

<h3>Visão geral</h3>
<p>Panorama de todas as empresas num intervalo de anos: totais distribuídos,
comparativos e a classificação de cada distribuição.</p>

<h3>Análise por empresa</h3>
<p>Uma empresa por vez, com a evolução ao longo dos anos e a situação de cada
sócio.</p>

<h3>Proporcional e desproporcional</h3>
<p>Uma distribuição é <b>proporcional</b> quando o percentual recebido bate com
o percentual de capital do sócio, dentro da <b>tolerância</b> configurada na
tela (em pontos percentuais). Fora disso, é <b>desproporcional</b>.</p>
<p>Desproporcional não é erro — é uma situação que costuma exigir previsão em
contrato e atenção fiscal. O sistema só aponta; a decisão é do escritório.</p>
<p>A tolerância existe porque arredondamento de centavos quase nunca fecha
exatamente no percentual. Aumentá-la demais esconde desproporção real.</p>
"""

_SISTEMA = """
<h2>Usuários, log e backup</h2>

<h3>Usuários</h3>
<p>Cada pessoa usa a sua própria conta, separada do usuário do Windows — a
máquina é compartilhada e o sistema precisa saber quem fez o quê. Só
administradores veem as telas de Usuários e Backup.</p>
<p>Contas <b>nunca são excluídas</b>, só desativadas. Uma conta excluída
deixaria o log de atividades sem dono.</p>
<p>Nesta tela há duas coisas diferentes com nome parecido: <b>Redefinir
senha</b> troca a senha do usuário selecionado na tabela (ação de
administrador, não pede a senha antiga), e <b>Trocar minha senha</b>, no bloco
"Minha conta", troca a sua própria — essa pede a senha atual.</p>
<p>Quem não é administrador não vê esta tela; para essas contas, o atalho
<b>Trocar senha</b> fica no rodapé da barra lateral.</p>

<h3>Log de atividades</h3>
<p>Registra quem fez o quê e quando: cadastros, alterações, exclusões,
trancamento de período, lançamentos e emissão de informe. É onde se responde
"quem mudou esse valor?" — vale consultar antes de refazer um trabalho.</p>

<h3>Backup</h3>
<p>Os dados ficam <b>só nesta máquina</b>, num arquivo local. Não há servidor
nem nuvem: se o computador for perdido ou o disco falhar, o backup é a única
recuperação possível.</p>
<p>Gere um backup <b>com frequência</b> e guarde a cópia <b>fora desta
máquina</b> (pen drive, outro computador, unidade de rede). Backup no mesmo
disco não protege contra falha de disco.</p>
<p>Momentos que pedem backup: antes de importar planilha em massa, antes de
destrancar um período fechado, e no fechamento de cada exercício.</p>
"""

TOPICOS: tuple[Topico, ...] = (
    Topico("inicio", "Começando por aqui", _INICIO),
    Topico("empresas.cadastro", "Empresas · Cadastro", _EMPRESAS),
    Topico("empresas.alteracoes", "Empresas · Alterações contratuais", _ALTERACOES),
    Topico("sistema.importar", "Importação em massa", _IMPORTACAO),
    Topico("socios", "Sócios e vínculos", _SOCIOS),
    Topico("distribuicao", "Distribuição anual", _DISTRIBUICAO),
    Topico("distribuicao.trimestral", "Distribuição trimestral", _TRIMESTRAL),
    Topico("informe", "Informe de rendimentos", _INFORME),
    Topico("dashboard", "Dashboards", _DASHBOARD),
    Topico("sistema", "Usuários, log e backup", _SISTEMA),
)

# Da tela aberta pro tópico que responde a dúvida dela. As chaves são as
# mesmas de MainWindow._paginas; o que não estiver aqui cai no "inicio".
TOPICO_POR_PAGINA = {
    "empresas.cadastro": "empresas.cadastro",
    "empresas.alteracoes": "empresas.alteracoes",
    "socios": "socios",
    "distribuicao": "distribuicao",
    "distribuicao.trimestral": "distribuicao.trimestral",
    "dashboard.geral": "dashboard",
    "dashboard.empresa": "dashboard",
    "sistema.importar": "sistema.importar",
    "sistema.log": "sistema",
    "sistema.usuarios": "sistema",
    "sistema.backup": "sistema",
    "sistema.sobre": "inicio",
}


def topico_da_pagina(chave_pagina: str | None) -> str:
    return TOPICO_POR_PAGINA.get(chave_pagina or "", "inicio")


def buscar_topicos(termo: str) -> list[Topico]:
    """Busca no título e no corpo. Sem índice nem ranking: são dez tópicos,
    e varrer o texto é instantâneo — o que a pessoa precisa é achar a
    palavra, não um resultado ordenado por relevância."""
    termo = termo.strip().lower()
    if not termo:
        return list(TOPICOS)
    return [t for t in TOPICOS if termo in t.titulo.lower() or termo in t.corpo.lower()]


class DialogoManual(QDialog):
    def __init__(self, topico_inicial: str = "inicio", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual do sistema")
        self.setWindowIcon(icone_app())
        self.resize(960, 680)

        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar no manual…")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(self._filtrar)

        self.lista = QListWidget()
        self.lista.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lista.currentRowChanged.connect(self._mostrar)

        painel_esquerdo = QWidget()
        col = QVBoxLayout(painel_esquerdo)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        col.addWidget(self.busca)
        col.addWidget(self.lista, 1)

        self.conteudo = QTextBrowser()
        self.conteudo.setOpenExternalLinks(True)

        divisor = QSplitter(Qt.Horizontal)
        divisor.setChildrenCollapsible(False)
        divisor.addWidget(painel_esquerdo)
        divisor.addWidget(self.conteudo)
        divisor.setStretchFactor(0, 1)
        divisor.setStretchFactor(1, 3)
        divisor.setSizes([260, 700])

        self.vazio = QLabel("Nenhum tópico com esse termo.")
        self.vazio.setProperty("role", "subtitulo")
        self.vazio.hide()

        botoes = QDialogButtonBox(QDialogButtonBox.Close)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(divisor, 1)
        layout.addWidget(self.vazio)
        layout.addWidget(botoes)

        self._visiveis: list[Topico] = []
        self._preencher(list(TOPICOS))
        self.ir_para(topico_inicial)

    def ir_para(self, topico_id: str) -> None:
        for indice, topico in enumerate(self._visiveis):
            if topico.id == topico_id:
                self.lista.setCurrentRow(indice)
                return
        if self._visiveis:
            self.lista.setCurrentRow(0)

    def _preencher(self, topicos: list[Topico]) -> None:
        self._visiveis = topicos
        self.lista.clear()
        for topico in topicos:
            self.lista.addItem(QListWidgetItem(topico.titulo))
        self.vazio.setVisible(not topicos)
        if not topicos:
            self.conteudo.clear()

    def _filtrar(self, termo: str) -> None:
        selecionado = self._visiveis[self.lista.currentRow()].id if self._visiveis and self.lista.currentRow() >= 0 else None
        self._preencher(buscar_topicos(termo))
        if selecionado is not None:
            self.ir_para(selecionado)
        elif self._visiveis:
            self.lista.setCurrentRow(0)

    def _mostrar(self, indice: int) -> None:
        if not (0 <= indice < len(self._visiveis)):
            return
        self.conteudo.setHtml(_estilo() + self._visiveis[indice].corpo)
        self.conteudo.verticalScrollBar().setValue(0)


def _estilo() -> str:
    """O QTextBrowser não aplica o QSS global no HTML que recebe, então o
    estilo vai junto do conteúdo — e é recalculado a cada exibição pra
    acompanhar a troca de tema."""
    return f"""<style>
    body {{ color: {theme.INK()}; font-size: 13px; }}
    h2 {{ font-size: 17px; color: {theme.INK()}; margin-bottom: 2px; }}
    h3 {{ font-size: 14px; color: {theme.BRASS_DARK()}; margin-top: 16px; margin-bottom: 2px; }}
    p, li {{ line-height: 150%; }}
    </style>"""
