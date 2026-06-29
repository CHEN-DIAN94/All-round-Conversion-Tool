# 流光一键发布打包脚本
# ============================================================
# 用法：
#   venv\Scripts\python.exe build_release.ps1   # 不对，是 PowerShell
#   powershell -ExecutionPolicy Bypass -File build_release.ps1
#
# 功能：
#   1. PyInstaller 打包 exe
#   2. 生成 ZIP 便携版
#   3. 调用 Inno Setup 生成安装程序（如果已安装）
# ============================================================

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  流光发布打包" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 读取版本号
$constantsContent = Get-Content "constants.py" -Raw
if ($constantsContent -match "VERSION\s*=\s*'([^']+)'") {
    $version = $matches[1]
    Write-Host "[1/5] 版本号: $version" -ForegroundColor Green
} else {
    Write-Host "[ERROR] 无法从 constants.py 读取版本号" -ForegroundColor Red
    exit 1
}

# 步骤 1: 清理旧产物
Write-Host "`n[2/5] 清理旧产物..." -ForegroundColor Yellow
$cleanPaths = @("dist", "build", "Output")
foreach ($p in $cleanPaths) {
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "  已删除 $p"
    }
}

# 步骤 2: PyInstaller 打包
Write-Host "`n[3/5] PyInstaller 打包..." -ForegroundColor Yellow
& "venv\Scripts\python.exe" -m PyInstaller "流光.spec" --noconfirm 2>&1 | Select-Object -Last 5
if (-not (Test-Path "dist\流光.exe")) {
    Write-Host "[ERROR] PyInstaller 打包失败" -ForegroundColor Red
    exit 1
}
$exeSize = [math]::Round((Get-Item "dist\流光.exe").Length / 1MB, 2)
Write-Host "  打包成功: dist\流光.exe ($exeSize MB)" -ForegroundColor Green

# 步骤 3: 创建 ZIP 便携版
Write-Host "`n[4/5] 创建 ZIP 便携版..." -ForegroundColor Yellow
$portableDir = "dist\流光-Portable-v$version"
if (Test-Path $portableDir) { Remove-Item -Recurse -Force $portableDir }
New-Item -ItemType Directory -Path $portableDir -Force | Out-Null
New-Item -ItemType Directory -Path "$portableDir\bin" -Force | Out-Null

Copy-Item "dist\流光.exe" $portableDir
Copy-Item "bin\ffmpeg.exe" "$portableDir\bin\"
Copy-Item "icon.ico" $portableDir -ErrorAction SilentlyContinue

$zipPath = "dist\流光-Portable-v$version.zip"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path "$portableDir\*" -DestinationPath $zipPath -CompressionLevel Optimal
$zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
Write-Host "  便携版 ZIP: $zipPath ($zipSize MB)" -ForegroundColor Green

# 步骤 4: 尝试 Inno Setup 安装程序
Write-Host "`n[5/5] 检查 Inno Setup..." -ForegroundColor Yellow
$isccPaths = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$iscc = $null
foreach ($p in $isccPaths) {
    if (Test-Path $p) { $iscc = $p; break }
}

if ($iscc) {
    Write-Host "  找到 Inno Setup: $iscc"
    & $iscc "流光-installer.iss" 2>&1 | Select-Object -Last 5
    $setupPath = "Output\流光-Setup-v$version.exe"
    if (Test-Path $setupPath) {
        $setupSize = [math]::Round((Get-Item $setupPath).Length / 1MB, 2)
        Write-Host "  安装程序: $setupPath ($setupSize MB)" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] Inno Setup 编译失败，请手动检查" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [SKIP] 未安装 Inno Setup 6，跳过安装程序生成" -ForegroundColor Yellow
    Write-Host "  下载地址: https://jrsoftware.org/isdl.php" -ForegroundColor Cyan
    Write-Host "  安装后运行: ISCC.exe 流光-installer.iss" -ForegroundColor Cyan
}

# 汇总
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  发布打包完成 v$version" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "产物清单:" -ForegroundColor Green
if (Test-Path "dist\流光.exe") {
    Write-Host "  - 主程序: dist\流光.exe"
}
if (Test-Path $zipPath) {
    Write-Host "  - 便携版: $zipPath"
}
if (Test-Path "Output\流光-Setup-v$version.exe") {
    Write-Host "  - 安装版: Output\流光-Setup-v$version.exe"
}
