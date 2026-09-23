; Script do Inno Setup pro instalador do Controle de Distribuição de Lucros.
;
; Pré-requisito: já ter gerado o pacote com
;   python -m PyInstaller --clean controle_lucros.spec
; que produz dist\ControleDeLucros\ e build\versao_installer.iss —
; conforme o README — este script só empacota o que já está em dist\.
;
; Rodar (com o Inno Setup 6 instalado, no Windows):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" controle_lucros.iss
; ou abrir este arquivo direto na IDE do Inno Setup e compilar (Ctrl+F9).
;
; A versão do instalador é lida do .exe já compilado — não há número pra
; manter aqui. Pra subir de versão, mexa em controle_lucros/__init__.py e
; gere o pacote de novo antes de compilar este script.
;
; O instalador some, mas os dados (banco, backups, preferências) ficam em
; %PROGRAMDATA%\ControleDeLucros\ — fora da pasta de instalação — então
; desinstalar o programa NUNCA apaga os dados. Reinstalar/atualizar também
; não mexe neles. Com o banco numa pasta do servidor (perguntado na
; instalação, ver [Code] no fim), fica aqui só a configuração deste PC, e
; desinstalar também não toca no banco do servidor.
;
; %PROGRAMDATA% e não %LOCALAPPDATA%: é o que faz todos os usuários do
; Windows daquele PC trabalharem no MESMO cadastro. Ver [Dirs] no fim deste
; arquivo — é lá que a pasta ganha permissão de escrita pra usuário comum,
; sem a qual só quem criou cada arquivo conseguiria alterá-lo.

#define MyAppName "Controle de Distribuição de Lucros"
#define MyAppPublisher "HenderLab"
#define MyAppURL "https://www.henderlab.com.br/"
#define MyAppExeName "ControleDeLucros.exe"
; SourcePath é a pasta deste .iss (com barra no fim). O FileExists do
; pré-processador resolve caminho relativo pelo diretório de trabalho do
; compilador — que ao compilar pela IDE do Inno não é a pasta do projeto —,
; então sem o SourcePath a checagem abaixo falha mesmo com o pacote pronto.
#define MyAppExePath SourcePath + "dist\ControleDeLucros\ControleDeLucros.exe"

; Sem o pacote pronto não há o que instalar — melhor dizer isso do que falhar
; adiante com uma mensagem sobre arquivo não encontrado.
#if !FileExists(MyAppExePath)
  #error Rode antes: python -m PyInstaller --clean controle_lucros.spec (nao achei dist\ControleDeLucros\ControleDeLucros.exe)
#endif

; MyAppVersion vem daqui, escrito pelo controle_lucros.spec a partir de
; controle_lucros/__init__.py. A versão mora num lugar só: subir de versão é
; mexer naquele arquivo e gerar o pacote de novo, sem risco de o instalador e
; o programa discordarem.
#include SourcePath + "build\versao_installer.iss"

[Setup]
; Gerado uma única vez pro app — não muda entre versões, é o que permite ao
; Windows reconhecer que uma nova instalação é uma ATUALIZAÇÃO desta mesma
; ferramenta (e não um programa diferente instalado do lado).
AppId={{B6C0B6E1-3E7B-4B7C-9C1E-6E6C1E7F3A02}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\ControleDeLucros
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=ControleDeLucros_Setup_{#MyAppVersion}
SetupIconFile={#SourcePath}controle_lucros\ui\assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
AppCopyright={#MyAppPublisher}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Instala em Arquivos de Programas, então precisa de elevação — explícito pra
; o pedido de permissão aparecer no começo e não no meio da cópia.
PrivilegesRequired=admin

; O Qt 6 não roda em Windows 10 anterior à versão 1809 (build 17763) — nem
; em nada antes do 10. Barrar aqui dá uma mensagem clara em vez de um "DLL
; load failed while importing QtWidgets" depois de instalado. Só "10.0" não
; basta: deixava instalar num Windows 10 antigo, que falhava assim ao abrir.
MinVersion=10.0.17763

; Atualizar por cima com o programa aberto travaria os arquivos; o Windows é
; avisado pra fechá-lo antes.
CloseApplications=yes
RestartApplications=no

; Propriedades do próprio instalador (aba Detalhes do arquivo).
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Instalador do {#MyAppName}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; GroupDescription: "Atalhos adicionais:"

[Dirs]
; A pasta de dados da máquina, criada já com escrita liberada pra usuário
; comum. Sem "users-modify" o Windows deixa cada um mexer só no que ele
; mesmo criou: o segundo usuário a abrir o programa conseguiria ler o banco
; do primeiro, mas não gravar nele — e o sistema inteiro é gravação.
; O -wal e o -shm que o SQLite cria ao lado do banco entram na mesma regra.
Name: "{commonappdata}\ControleDeLucros"; Permissions: users-modify
Name: "{commonappdata}\ControleDeLucros\data"; Permissions: users-modify
Name: "{commonappdata}\ControleDeLucros\backups"; Permissions: users-modify

[Files]
Source: "{#SourcePath}dist\ControleDeLucros\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; runasoriginaluser: o instalador roda como administrador, e o programa
; aberto assim enxergaria a rede com outra credencial — unidade mapeada (Z:)
; nem existe pro administrador. Abre como quem está usando o PC.
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
// Onde fica o banco de dados. Pergunta só em instalação nova: quem atualiza
// já tem essa resposta (configuracao_local.json) ou um banco local com
// dados, e a pergunta não pode mudar isso por cima.
//
// A resposta vai pro configuracao_local.json, que o programa lê antes de
// abrir o banco (ver db.banco_configurado). Assim o programa já abre no
// banco certo — sem criar um banco local vazio pra depois mover.
//
// Criar ou usar o que já existe não é pergunta separada: o instalador olha
// se a pasta já tem banco e diz o que vai acontecer. Dois bancos na mesma
// pasta não existem, e sobrescrever o do escritório também não.

const
  NOME_DO_BANCO = 'controle_lucros.db';

var
  PaginaOnde: TInputOptionWizardPage;
  PaginaPasta: TInputDirWizardPage;
  PerguntarBanco: Boolean;
  CriarBanco: Boolean;

function PastaDeDados: String;
begin
  Result := ExpandConstant('{commonappdata}\ControleDeLucros\data');
end;

function ArquivoDeConfiguracao: String;
begin
  Result := PastaDeDados + '\configuracao_local.json';
end;

procedure InitializeWizard;
begin
  PerguntarBanco := not FileExists(ArquivoDeConfiguracao)
    and not FileExists(PastaDeDados + '\' + NOME_DO_BANCO);

  PaginaOnde := CreateInputOptionPage(wpSelectTasks,
    'Banco de dados', 'Onde vai ficar o banco de dados do sistema?',
    'Para o escritório inteiro usar o mesmo cadastro, o banco fica numa pasta ' +
    'compartilhada do servidor e todos os computadores apontam para ela.',
    True, False);
  PaginaOnde.Add('Numa pasta compartilhada do servidor (vários computadores)');
  PaginaOnde.Add('Só neste computador');
  PaginaOnde.SelectedValueIndex := 0;

  PaginaPasta := CreateInputDirPage(PaginaOnde.ID,
    'Pasta do banco de dados', 'Em que pasta do servidor fica o banco?',
    'Se outro computador já usa o sistema, escolha a MESMA pasta que ele usa: este ' +
    'computador passa a usar o mesmo banco. Se a pasta ainda não tiver banco, um ' +
    'banco novo é criado nela.' + #13#10#13#10 +
    'Use o caminho de rede, como \\SERVIDOR\ControleDeLucros. Letra de unidade ' +
    'mapeada (Z:) não funciona aqui.',
    False, '');
  PaginaPasta.Add('');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = PaginaOnde.ID) or (PageID = PaginaPasta.ID) then
    Result := not PerguntarBanco;
  if (not Result) and (PageID = PaginaPasta.ID) then
    Result := PaginaOnde.SelectedValueIndex <> 0;
end;

function PastaEscolhida: String;
begin
  Result := RemoveBackslashUnlessRoot(Trim(PaginaPasta.Values[0]));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Banco: String;
begin
  Result := True;
  if CurPageID <> PaginaPasta.ID then
    exit;

  if PastaEscolhida = '' then
  begin
    MsgBox('Escolha a pasta do servidor onde fica o banco.', mbError, MB_OK);
    Result := False;
    exit;
  end;

  // O administrador que instala não enxerga as unidades mapeadas do usuário:
  // Z: cai aqui mesmo existindo — daí a dica do caminho de rede.
  if not DirExists(PastaEscolhida) then
  begin
    MsgBox('Não consegui acessar a pasta:' + #13#10 + PastaEscolhida + #13#10#13#10 +
      'Confira o caminho e se este computador está na rede. Use o caminho de rede ' +
      '(\\SERVIDOR\pasta), não a letra da unidade.', mbError, MB_OK);
    Result := False;
    exit;
  end;

  Banco := AddBackslash(PastaEscolhida) + NOME_DO_BANCO;
  CriarBanco := not FileExists(Banco);
  if CriarBanco then
    Result := MsgBox('Esta pasta ainda não tem banco de dados:' + #13#10 + PastaEscolhida +
      #13#10#13#10 + 'Um banco NOVO vai ser criado nela, vazio, quando o programa abrir.' +
      #13#10#13#10 + 'Se outro computador já usa o sistema, volte e escolha a mesma ' +
      'pasta que ele usa. Criar um banco novo aqui?', mbConfirmation, MB_YESNO) = IDYES
  else
    Result := MsgBox('Encontrei o banco de dados nesta pasta:' + #13#10 + Banco +
      #13#10#13#10 + 'Este computador vai usar esse banco, junto com os outros. Nada ' +
      'nele é apagado ou alterado. Continuar?', mbConfirmation, MB_YESNO) = IDYES;
end;

function ParaJson(Texto: String): String;
var
  Escapado: String;
begin
  Escapado := Texto;
  StringChangeEx(Escapado, '\', '\\', True);
  StringChangeEx(Escapado, '"', '\"', True);
  Result := Escapado;
end;

procedure GravarConfiguracao;
var
  Json: String;
  Linhas: TArrayOfString;
begin
  if PaginaOnde.SelectedValueIndex = 0 then
  begin
    // Instalação silenciosa não passa pelas páginas: sem pasta, o programa
    // pergunta na primeira abertura.
    if PastaEscolhida = '' then
      exit;
    Json := '{"banco": "' + ParaJson(AddBackslash(PastaEscolhida) + NOME_DO_BANCO) + '"';
    if CriarBanco then
      Json := Json + ', "criar_banco": true';
    Json := Json + '}';
  end
  else
    Json := '{"banco": ""}';

  ForceDirectories(PastaDeDados);
  SetArrayLength(Linhas, 1);
  Linhas[0] := Json;
  SaveStringsToUTF8File(ArquivoDeConfiguracao, Linhas, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and PerguntarBanco then
    GravarConfiguracao;
end;
