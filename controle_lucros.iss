; Script do Inno Setup pro instalador do Controle de Distribuição de Lucros.
;
; Pré-requisito: já ter gerado o pacote com o PyInstaller (dist\ControleDeLucros\),
; conforme o README — este script só empacota o que já está em dist\.
;
; Rodar (com o Inno Setup instalado, no Windows):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" controle_lucros.iss
; ou abrir este arquivo direto na IDE do Inno Setup e compilar (Ctrl+F9).
;
; O instalador some, mas os dados do usuário (banco, backups, preferências)
; ficam em %LOCALAPPDATA%\ControleDeLucros\ — fora da pasta de instalação —
; então desinstalar o programa NUNCA apaga os dados. Reinstalar/atualizar
; também não mexe neles.

#define MyAppName "Controle de Distribuição de Lucros"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "HenderLab"
#define MyAppURL "https://www.henderlab.com.br/"
#define MyAppExeName "ControleDeLucros.exe"

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
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

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
