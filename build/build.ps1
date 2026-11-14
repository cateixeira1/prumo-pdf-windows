# Prumo PDF - monta o aplicativo e o instalador no Windows.
# Rode pelo arquivo GERAR_INSTALADOR.bat (duplo clique). Precisa de internet só nesta etapa.
#
# O que este script faz:
#   1. instala o "uv" (gerenciador de Python), se ainda não houver;
#   2. cria um ambiente Python 3.12 isolado na pasta .venv (não mexe no resto do PC);
#   3. baixa os modelos de idioma do Tesseract (português, inglês e orientação);
#   4. empacota o aplicativo com o PyInstaller e confere o pacote;
#   5. baixa o instalador oficial do Tesseract (UB Mannheim), confere a soma e põe o motor dentro do aplicativo;
#   6. instala o Inno Setup, se preciso, e gera o instalador final em dist\.

param([switch]$CI)   # -CI: compilação na nuvem (GitHub Actions), sem abrir o Explorador no fim

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # downloads bem mais rápidos no PowerShell 5
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host ""; Write-Host "ERRO: $text" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- 1. uv
Step "Verificando o uv (gerenciador de Python)"
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "Instalando o uv..."
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) { Fail "Não foi possível instalar o uv. Feche esta janela, abra de novo e tente outra vez." }
}
Write-Host (& uv --version)

# ---------------------------------------------------------------- 2. ambiente Python
Step "Preparando o ambiente Python 3.12 (pode levar alguns minutos na primeira vez)"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & uv venv .venv --python 3.12
    if ($LASTEXITCODE -ne 0) { Fail "Falha ao criar o ambiente Python." }
}
# Versões exatas, com a soma SHA-256 de cada arquivo (build\requirements.lock): a montagem de hoje e a de
# amanhã usam as mesmas bibliotecas, e um pacote trocado na origem é recusado.
& uv pip install --python .venv\Scripts\python.exe --require-hashes -r build\requirements.lock
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar as bibliotecas (versão ou soma SHA-256 diferente do esperado)." }
$Py = Join-Path $Root ".venv\Scripts\python.exe"

# ---------------------------------------------------------------- 3. modelos de idioma
Step "Baixando os modelos de idioma do Tesseract"
# Tudo o que vem da internet tem a soma SHA-256 anotada em build\checksums.sha256. Se o arquivo baixado não
# bater com a soma, a montagem para: um arquivo trocado no caminho (ou na origem) não entra no instalador.
$Sums = @{}
Get-Content "build\checksums.sha256" | ForEach-Object {
    if ($_ -match '^([0-9a-fA-F]{64})\s+(\S+)$') { $Sums[$Matches[2]] = $Matches[1].ToLower() }
}
function Test-Sum($path, $key) {
    if (-not $Sums.ContainsKey($key)) { Fail "Falta a soma SHA-256 de $key em build\checksums.sha256." }
    return ((Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLower() -eq $Sums[$key])
}
function Get-Model($repo, $file, $destDir) {
    $dest = Join-Path $destDir $file
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 100000)) { return }
    # Versão fixa (etiqueta 4.1.0), sem reserva no ramo principal, que muda com o tempo.
    $u = "https://github.com/tesseract-ocr/$repo/raw/4.1.0/$file"
    $tmp = "$dest.download"
    try {
        Write-Host "  $repo/$file"
        Invoke-WebRequest -Uri $u -OutFile $tmp -UseBasicParsing
    } catch { Remove-Item $tmp -ErrorAction SilentlyContinue; Fail "Não foi possível baixar $repo/$file." }
    if (-not (Test-Sum $tmp "$repo/$file")) {
        Remove-Item $tmp -Force
        Fail "O arquivo $repo/$file baixado não confere com a soma SHA-256 esperada."
    }
    Move-Item -Force $tmp $dest
}
foreach ($d in @("tessdata", "tessdata_best")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Copy-Item -Recurse -Force "tessdata_common\*" $d
}
# Modelo padrão (tessdata): bom equilíbrio entre precisão e velocidade.
Get-Model "tessdata" "por.traineddata" "tessdata"
Get-Model "tessdata" "eng.traineddata" "tessdata"
Get-Model "tessdata" "osd.traineddata" "tessdata"
# Demais idiomas do OCR (modelo padrão): alemão, chinês simplificado e tradicional (Taiwan), dinamarquês,
# espanhol, finlandês, francês, japonês, norueguês e sueco.
foreach ($l in @("deu", "spa", "fra", "jpn", "chi_sim", "chi_tra", "nor", "swe", "dan", "fin")) {
    Get-Model "tessdata" "$l.traineddata" "tessdata"
}
# Modelo de precisão máxima (tessdata_best): mais lento.
Get-Model "tessdata_best" "por.traineddata" "tessdata_best"
Get-Model "tessdata_best" "eng.traineddata" "tessdata_best"
Copy-Item -Force "tessdata\osd.traineddata" "tessdata_best\osd.traineddata"

# Os modelos "tessdata" trazem, além do motor LSTM (o único que o Prumo usa), o motor antigo (legacy), que
# só ocupa espaço. Tiramos o legacy e guardamos os originais em tessdata_full (fora do pacote), para o teste
# conferir que o texto reconhecido é idêntico.
Step "Enxugando os modelos de idioma (tira só o motor antigo, sem mexer no LSTM)"
& $Py build\slim_tessdata.py tessdata tessdata_full
if ($LASTEXITCODE -ne 0) { Fail "Falha ao enxugar os modelos de idioma." }

# ---------------------------------------------------------------- 4. PyInstaller
Step "Empacotando o aplicativo"
& $Py -m PyInstaller build\PrumoPDF.spec --noconfirm --clean --distpath dist --workpath build\work
if ($LASTEXITCODE -ne 0) { Fail "Falha no PyInstaller." }

Step "Conferindo o pacote"
$report = Join-Path $env:TEMP "prumo_selftest.json"
Remove-Item $report -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "dist\PrumoPDF\PrumoPDF.exe" -ArgumentList "--self-test", "`"$report`"" -Wait -PassThru
if (Test-Path $report) { Get-Content $report | Write-Host }
if ($p.ExitCode -ne 0) { Fail "O pacote não passou na conferência (veja acima)." }

# ---------------------------------------------------------------- 5. Tesseract
Step "Baixando o instalador oficial do Tesseract (UB Mannheim), versão fixa e conferida"
New-Item -ItemType Directory -Force -Path "build\redist" | Out-Null
$tessName = "tesseract-ocr-w64-setup-5.4.0.20240606.exe"
$tessUrl = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/$tessName"
$tessSetup = "build\redist\tesseract-setup.exe"
if ((Test-Path $tessSetup) -and -not (Test-Sum $tessSetup $tessName)) { Remove-Item $tessSetup -Force }
if (-not (Test-Path $tessSetup)) {
    Write-Host "  $tessName"
    Invoke-WebRequest -Uri $tessUrl -OutFile $tessSetup -UseBasicParsing
    if (-not (Test-Sum $tessSetup $tessName)) {
        Remove-Item $tessSetup -Force
        Fail "O instalador do Tesseract baixado não confere com a soma SHA-256 esperada."
    }
}

# O motor de OCR vai dentro da pasta do Prumo (dist\PrumoPDF\tesseract), como já era no pacote da Microsoft
# Store: o instalador do Prumo não roda mais o instalador do Tesseract no computador de quem instala, e ficam
# de fora as ferramentas de treinamento e os modelos de idioma do Tesseract, que o Prumo não usa (os modelos
# do Prumo estão em _internal\tessdata).
Step "Colocando o motor de OCR dentro do aplicativo"
$tessTmp = Join-Path $Root "build\work\tesseract_bundle"
function Find-Tess {
    $e = Get-ChildItem $tessTmp -Recurse -Filter tesseract.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($e) { return $e }
    foreach ($d in @("$env:ProgramFiles\Tesseract-OCR", "${env:ProgramFiles(x86)}\Tesseract-OCR")) {
        if (Test-Path "$d\tesseract.exe") { return (Get-Item "$d\tesseract.exe") }
    }
    return $null
}
# O instalador do Tesseract só pode rodar uma vez por computador (na segunda ele fica esperando resposta), então
# só roda se o tesseract.exe ainda não estiver em lugar nenhum. Ele pode ignorar /D: Find-Tess olha os dois lugares.
$tessExe = Find-Tess
if (-not $tessExe) {
    $p = Start-Process -FilePath $tessSetup -ArgumentList "/S", "/D=$tessTmp" -PassThru
    if (-not $p.WaitForExit(300000)) { $p.Kill(); Fail "O instalador do Tesseract não terminou em 5 minutos." }
    $tessExe = Find-Tess
}
if (-not $tessExe) { Fail "Não consegui extrair o Tesseract." }
$tessSrc = $tessExe.DirectoryName
Write-Host "Tesseract em: $tessSrc"
$tessDest = Join-Path $Root "dist\PrumoPDF\tesseract"
Remove-Item $tessDest -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $tessDest | Out-Null
Get-ChildItem $tessSrc -Force | Where-Object { $_.Name -notin @("tessdata", "doc") -and $_.Name -notlike "unins*" } |
    ForEach-Object { Copy-Item $_.FullName $tessDest -Recurse -Force }
# O Prumo só chama o tesseract.exe. As bibliotecas (.dll) permanecem todas, para não arriscar.
Get-ChildItem $tessDest -Filter *.exe | Where-Object { $_.Name -ne "tesseract.exe" } | ForEach-Object {
    Write-Host ("  fora do pacote: {0} ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB))
    Remove-Item $_.FullName -Force
}
# a biblioteca de execução do Visual C++, caso o computador não tenha
foreach ($dll in @("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")) {
    $src = Join-Path $Root "dist\PrumoPDF\_internal\$dll"
    if ((Test-Path $src) -and -not (Test-Path "$tessDest\$dll")) { Copy-Item $src $tessDest }
}
Write-Host ("Tesseract no aplicativo: {0:N0} MB" -f ((Get-ChildItem $tessDest -Recurse | Measure-Object Length -Sum).Sum / 1MB))

# Conferência: o aplicativo empacotado precisa achar e rodar o motor que vai dentro dele.
$report2 = Join-Path $env:TEMP "prumo_selftest_tess.json"
Remove-Item $report2 -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "dist\PrumoPDF\PrumoPDF.exe" -ArgumentList "--self-test", "`"$report2`"" -Wait -PassThru
if ($p.ExitCode -ne 0) { Fail "O pacote não passou na conferência depois de incluir o Tesseract." }
if ((Get-Content $report2 -Raw) -notmatch "PrumoPDF[^`"]*tesseract[^`"]*tesseract\.exe") {
    Get-Content $report2 | Write-Host
    Fail "O aplicativo não está usando o Tesseract que vai dentro dele."
}
& "$tessDest\tesseract.exe" --version | Select-Object -First 1 | Write-Host
if ($LASTEXITCODE -ne 0) { Fail "O tesseract.exe incluído não rodou." }

# ---------------------------------------------------------------- 6. Inno Setup
Step "Gerando o instalador"
function Find-ISCC {
    $cands = @(
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    return $null
}
$iscc = Find-ISCC
if (-not $iscc) {
    Write-Host "Instalando o Inno Setup 7 pelo winget..."
    if ($CI) { choco install innosetup -y --no-progress | Out-Null; $iscc = Find-ISCC }
    if (-not $iscc) { winget install --id JRSoftware.InnoSetup.7 -e -s winget --silent --accept-package-agreements --accept-source-agreements
    $iscc = Find-ISCC }
    if (-not $iscc) { Fail "Instale o Inno Setup (jrsoftware.org/isdl.php) e rode este script de novo." }
}
& $iscc "build\PrumoPDF.iss"
if ($LASTEXITCODE -ne 0) { Fail "Falha ao gerar o instalador." }

$out = Get-ChildItem "dist\PrumoPDF_Setup_*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host ""
Write-Host "PRONTO! Instalador gerado:" -ForegroundColor Green
Write-Host "  $($out.FullName)" -ForegroundColor Green
Write-Host "Dê dois cliques nele para instalar o Prumo PDF."
if (-not $CI) { explorer.exe "/select,`"$($out.FullName)`"" }
