# Prumo PDF - monta o aplicativo e o instalador no Windows.
# Rode pelo arquivo GERAR_INSTALADOR.bat (duplo clique). Precisa de internet só nesta etapa.
#
# O que este script faz:
#   1. instala o "uv" (gerenciador de Python), se ainda não houver;
#   2. cria um ambiente Python 3.12 isolado na pasta .venv (não mexe no resto do PC);
#   3. baixa os modelos de idioma do Tesseract (português, inglês e orientação);
#   4. empacota o aplicativo com o PyInstaller e confere o pacote;
#   5. baixa o instalador oficial do Tesseract (UB Mannheim);
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
& uv pip install --python .venv\Scripts\python.exe -r build\requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar as bibliotecas." }
$Py = Join-Path $Root ".venv\Scripts\python.exe"

# ---------------------------------------------------------------- 3. modelos de idioma
Step "Baixando os modelos de idioma do Tesseract"
function Get-Model($repo, $file, $destDir) {
    $dest = Join-Path $destDir $file
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 100000)) { return }
    $urls = @(
        "https://github.com/tesseract-ocr/$repo/raw/4.1.0/$file",
        "https://github.com/tesseract-ocr/$repo/raw/main/$file"
    )
    foreach ($u in $urls) {
        try {
            Write-Host "  $repo/$file"
            Invoke-WebRequest -Uri $u -OutFile $dest -UseBasicParsing
            if ((Get-Item $dest).Length -gt 100000) { return }
        } catch { }
    }
    Fail "Não foi possível baixar $repo/$file."
}
foreach ($d in @("tessdata", "tessdata_best")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Copy-Item -Recurse -Force "tessdata_common\*" $d
}
# Modelo padrão (tessdata): bom equilíbrio entre precisão e velocidade.
Get-Model "tessdata" "por.traineddata" "tessdata"
Get-Model "tessdata" "eng.traineddata" "tessdata"
Get-Model "tessdata" "osd.traineddata" "tessdata"
# Modelo de precisão máxima (tessdata_best): mais lento.
Get-Model "tessdata_best" "por.traineddata" "tessdata_best"
Get-Model "tessdata_best" "eng.traineddata" "tessdata_best"
Copy-Item -Force "tessdata\osd.traineddata" "tessdata_best\osd.traineddata"

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
Step "Baixando o instalador oficial do Tesseract (UB Mannheim)"
New-Item -ItemType Directory -Force -Path "build\redist" | Out-Null
$tessSetup = "build\redist\tesseract-setup.exe"
if (-not (Test-Path $tessSetup)) {
    $headers = @{ "User-Agent" = "PrumoPDF-build" }
    if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/UB-Mannheim/tesseract/releases/latest" -Headers $headers
    $asset = $rel.assets | Where-Object { $_.name -match "w64-setup.*\.exe$" } | Select-Object -First 1
    if (-not $asset) { Fail "Não encontrei o instalador do Tesseract na página de versões da UB Mannheim." }
    Write-Host "  $($asset.name)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tessSetup -UseBasicParsing
}

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
