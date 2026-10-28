; Instalador do Prumo PDF (Inno Setup 6.3+ ou 7).
; Gerado pelo build.ps1. Instala o aplicativo e, se ainda não houver, o Tesseract (UB Mannheim).

#define AppName "Prumo PDF"
#define AppVersion "1.7.0"
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
OutputBaseFilename=PrumoPDF_Setup_{#AppVersion}
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
ChangesAssociations=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Instalador do {#AppName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\PrumoPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "redist\tesseract-setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: not TesseractInstalled

[Icons]
; O AppUserModelID é o mesmo que o app declara ao abrir (main.py). Assim o Windows liga a janela
; aberta ao atalho e mostra o logo do Prumo na barra de tarefas (e não um ícone genérico).
Name: "{autoprograms}\Prumo PDF"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; AppUserModelID: "Prumo.PrumoPDF"
Name: "{autodesktop}\Prumo PDF"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; AppUserModelID: "Prumo.PrumoPDF"; Tasks: desktopicon

[Registry]
; "Abrir com > Prumo PDF" nos PDFs (sem tomar o lugar do leitor padrão; isso o usuário escolhe no Windows).
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PrumoPDF.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\PrumoPDF.Document"; ValueType: string; ValueName: ""; ValueData: "Documento PDF (Prumo PDF)"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\PrumoPDF.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\PrumoPDF.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Prumo PDF"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Prumo PDF"; ValueData: "Software\Prumo\PrumoPDF\Capabilities"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Prumo\PrumoPDF\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "Prumo PDF"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Prumo\PrumoPDF\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "PDF e OCR no seu computador"
Root: HKA; Subkey: "Software\Prumo\PrumoPDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "PrumoPDF.Document"
; Botão direito > "Converter em PDF com o Prumo" em fotos, Word, Excel, PowerPoint e texto.
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.heic\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.heic\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.heic\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.heif\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.heif\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.heif\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webp\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webp\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webp\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ods\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odp\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\PrumoConvert"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Converter em PDF com o Prumo"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\PrumoConvert"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\PrumoConvert\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --convert ""%1"""

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
