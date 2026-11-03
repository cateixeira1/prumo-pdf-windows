# Empacota o Prumo PDF (pasta dist\PrumoPDF, do PyInstaller) em MSIX.
#
#   .\build\msix.ps1                       pacote de TESTE: identidade provisória, assinado com certificado
#                                          autoassinado (instala só em computador que confie no .cer gerado)
#   .\build\msix.ps1 -IdentityName "..." -Publisher "CN=..." -PublisherDisplayName "..." -Store
#                                          pacote para a Microsoft Store, com os valores do Partner Center,
#                                          SEM assinatura (a Microsoft assina ao aceitar o envio)
param(
    [string]$IdentityName = "PrumoPDF.Teste",
    [string]$Publisher = "CN=Prumo PDF Teste",
    [string]$PublisherDisplayName = "Prumo PDF (teste)",
    [string]$DisplayName = "Prumo PDF",
    [switch]$Store,
    [string]$OutDir = "dist\msix"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Fail($m) { Write-Host "ERRO: $m" -ForegroundColor Red; exit 1 }

if (-not (Test-Path "dist\PrumoPDF\PrumoPDF.exe")) { Fail "Rode antes o build\build.ps1 (falta dist\PrumoPDF)." }

# versão: 1.12.0 (do instalador) -> 1.12.0.0 (MSIX exige quatro partes)
$iss = Get-Content "build\PrumoPDF.iss" -Raw
if ($iss -notmatch '#define AppVersion "(\d+)\.(\d+)\.(\d+)"') { Fail "Não achei a versão em build\PrumoPDF.iss." }
$Version = "$($Matches[1]).$($Matches[2]).$($Matches[3]).0"

# ferramentas do Windows SDK
$kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
$bin = Get-ChildItem $kits -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^10\.' } |
    Sort-Object { [version]$_.Name } -Descending | Where-Object { Test-Path "$($_.FullName)\x64\makeappx.exe" } | Select-Object -First 1
if (-not $bin) { Fail "makeappx.exe não encontrado (instale o Windows SDK)." }
$makeappx = "$($bin.FullName)\x64\makeappx.exe"
$signtool = "$($bin.FullName)\x64\signtool.exe"
Write-Host "Windows SDK: $($bin.Name)"

# pasta do pacote: o app + manifesto + logos
$stage = Join-Path $Root "build\work\msix_stage"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item -Recurse -Force "dist\PrumoPDF\*" $stage
New-Item -ItemType Directory -Force -Path "$stage\Assets" | Out-Null

# Tesseract dentro do pacote: o MSIX não pode rodar o instalador dele, então o instalador oficial (UB Mannheim)
# é aberto aqui, numa pasta temporária, e só o motor (exe + DLLs) vai para o pacote. Os modelos de idioma
# já estão em _internal\tessdata.
$tessSetup = "build\redist\tesseract-setup.exe"
if (-not (Test-Path $tessSetup)) { Fail "Falta $tessSetup (o build.ps1 baixa)." }
$tessTmp = Join-Path $Root "build\work\tesseract_bundle"
function Find-Tess {
    $e = Get-ChildItem $tessTmp -Recurse -Filter tesseract.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($e) { return $e }
    foreach ($d in @("$env:ProgramFiles\Tesseract-OCR", "${env:ProgramFiles(x86)}\Tesseract-OCR")) {
        if (Test-Path "$d\tesseract.exe") { return (Get-Item "$d\tesseract.exe") }
    }
    return $null
}
# O instalador só pode rodar uma vez por computador (na segunda ele fica esperando resposta), então só roda
# se o tesseract.exe ainda não estiver em lugar nenhum. Ele pode ignorar /D, por isso Find-Tess olha os dois lugares.
$tessExe = Find-Tess
if (-not $tessExe) {
    $p = Start-Process -FilePath $tessSetup -ArgumentList "/S", "/D=$tessTmp" -PassThru
    if (-not $p.WaitForExit(300000)) { $p.Kill(); Fail "O instalador do Tesseract não terminou em 5 minutos." }
    $tessExe = Find-Tess
}
if (-not $tessExe) { Fail "Não consegui extrair o Tesseract." }
$tessSrc = $tessExe.DirectoryName
Write-Host "Tesseract em: $tessSrc"
$tessDest = Join-Path $stage "tesseract"
New-Item -ItemType Directory -Force -Path $tessDest | Out-Null
Get-ChildItem $tessSrc -Force | Where-Object { $_.Name -notin @("tessdata", "doc", "unins000.exe", "unins000.dat") -and $_.Name -notlike "unins*" } |
    ForEach-Object { Copy-Item $_.FullName $tessDest -Recurse -Force }
# O Prumo só chama o tesseract.exe. As ferramentas de treinamento do instalador (lstmtraining, text2image etc.)
# não são usadas e pesam bastante: ficam de fora. As bibliotecas (.dll) permanecem todas, para não arriscar.
Get-ChildItem $tessDest -Filter *.exe | Where-Object { $_.Name -ne "tesseract.exe" } | ForEach-Object {
    Write-Host ("  fora do pacote: {0} ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
    Remove-Item $_.FullName -Force
}
# a biblioteca de execução do Visual C++, caso o computador não tenha
foreach ($dll in @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")) {
    $src = Join-Path $stage "_internal\$dll"
    if ((Test-Path $src) -and -not (Test-Path "$tessDest\$dll")) { Copy-Item $src $tessDest }
}
Write-Host ("Tesseract no pacote: {0:N0} MB" -f ((Get-ChildItem $tessDest -Recurse | Measure-Object Length -Sum).Sum / 1MB))

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py "build\msix_assets.py" "assets\icon_256.png" "$stage\Assets"
if ($LASTEXITCODE -ne 0) { Fail "Falha ao gerar os logos." }

function Esc($s) { [System.Security.SecurityElement]::Escape($s) }
$xml = Get-Content "build\msix\AppxManifest.template.xml" -Raw -Encoding UTF8
$xml = $xml.Replace("@IDENTITY_NAME@", (Esc $IdentityName)).Replace("@PUBLISHER@", (Esc $Publisher)).
    Replace("@VERSION@", $Version).Replace("@DISPLAY_NAME@", (Esc $DisplayName)).
    Replace("@PUBLISHER_DISPLAY_NAME@", (Esc $PublisherDisplayName))
[System.IO.File]::WriteAllText("$stage\AppxManifest.xml", $xml, (New-Object System.Text.UTF8Encoding($false)))

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$name = if ($Store) { "PrumoPDF_$Version`_Store_sem_assinatura.msix" } else { "PrumoPDF_$Version`_teste.msix" }
$msix = Join-Path $OutDir $name
Remove-Item $msix -ErrorAction SilentlyContinue
& $makeappx pack /d $stage /p $msix /o
if ($LASTEXITCODE -ne 0) { Fail "makeappx falhou." }

if (-not $Store) {
    $cert = New-SelfSignedCertificate -Type Custom -Subject $Publisher -KeyUsage DigitalSignature `
        -FriendlyName "Prumo PDF (teste)" -CertStoreLocation "Cert:\CurrentUser\My" `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
    $pwd = ConvertTo-SecureString -String ([guid]::NewGuid().ToString()) -Force -AsPlainText
    $pfx = Join-Path $OutDir "teste.pfx"
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $pwd | Out-Null
    Export-Certificate -Cert $cert -FilePath (Join-Path $OutDir "PrumoPDF_teste.cer") | Out-Null
    $plain = [System.Net.NetworkCredential]::new("", $pwd).Password
    & $signtool sign /fd SHA256 /f $pfx /p $plain $msix
    if ($LASTEXITCODE -ne 0) { Fail "signtool falhou." }
    Remove-Item $pfx -Force
    Remove-Item "Cert:\CurrentUser\My\$($cert.Thumbprint)" -Force
}

Write-Host ""
Write-Host "PRONTO: $msix" -ForegroundColor Green
Write-Host ("Tamanho: {0:N0} MB" -f ((Get-Item $msix).Length / 1MB))
