; Instalador do Prumo PDF (Inno Setup 6.3+ ou 7).
; Gerado pelo build.ps1. Instala o aplicativo e, se ainda não houver, o Tesseract (UB Mannheim).

#define AppName "Prumo PDF"
#define AppVersion "1.2.0"
#define AppExe "PrumoPDF.exe"

[Setup]
AppId={{6F1B2C4E-8D3A-4F5B-9C7E-2A1D0E3F4B5C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Prumo PDF
DefaultDirName={autopf}\Prumo PDF
DefaultGroupName=Prumo PDF
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Instalador_PrumoPDF_{#AppVersion}
SetupIconFile=..\assets\PrumoPDF.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\PrumoPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "redist\tesseract-setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not TesseractInstalled

[Icons]
Name: "{autoprograms}\Prumo PDF"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\Prumo PDF"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\tesseract-setup.exe"; Parameters: "/S"; \
    StatusMsg: "Instalando o motor de OCR (Tesseract)... isso pode levar um minuto."; \
    Check: not TesseractInstalled; Flags: waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "Abrir o Prumo PDF"; Flags: nowait postinstall skipifsilent

[Code]
function TesseractInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf64}\Tesseract-OCR\tesseract.exe'))
         or RegKeyExists(HKLM64, 'SOFTWARE\Tesseract-OCR');
end;
