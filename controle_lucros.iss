; Script do Inno Setup pro instalador do Controle de Distribuição de Lucros.
;
; Pré-requisito: já ter gerado o pacote com o PyInstaller (dist\ControleDeLucros\),
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
; O instalador some, mas os dados do usuário (banco, backups, preferências)
; ficam em %LOCALAPPDATA%\ControleDeLucros\ — fora da pasta de instalação —
; então desinstalar o programa NUNCA apaga os dados. Reinstalar/atualizar
; também não mexe neles.

#define MyAppName "Controle de Distribuição de Lucros"
#define MyAppPublisher "HenderLab"
#define MyAppURL "https://www.henderlab.com.br/"
#define MyAppExeName "ControleDeLucros.exe"
#define MyAppExePath "dist\ControleDeLucros\ControleDeLucros.exe"

; Sem o pacote pronto não há o que instalar — melhor dizer isso do que falhar
; adiante com uma mensagem sobre arquivo não encontrado.
#if !FileExists(MyAppExePath)
  #error Gere o pacote antes: pyinstaller controle_lucros.spec
#endif

; MyAppVersion vem daqui, escrito pelo controle_lucros.spec a partir de
; controle_lucros/__init__.py. A versão mora num lugar só: subir de versão é
; mexer naquele arquivo e gerar o pacote de novo, sem risco de o instalador e
; o programa discordarem.
#include "build\versao_installer.iss"

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
SetupIconFile=controle_lucros\ui\assets\logo.ico
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

; O Qt 6 desta versão não roda em Windows anterior ao 10; barrar aqui dá uma
; mensagem clara em vez de um erro de DLL depois de instalado.
MinVersion=10.0

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

[Files]
Source: "dist\ControleDeLucros\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent
