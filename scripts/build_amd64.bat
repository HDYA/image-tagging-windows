@echo off
REM ============================================
REM  媒体文件智能分类系统 - Windows AMD64 构建
REM ============================================
REM
REM 前置要求:
REM   1. Python 3.11+ (AMD64)
REM   2. pip install -r requirements.txt
REM   3. pip install nuitka ordered-set zstandard
REM
REM 可选 (人脸模块):
REM   pip install -r requirements-face.txt
REM   pip install onnxruntime-directml
REM

echo [BUILD] 媒体文件智能分类系统 - AMD64
echo.

REM 检查 Python
python --version 2>nul
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请安装 Python 3.11+
    pause
    exit /b 1
)

REM 安装依赖
echo [1/3] 安装依赖...
pip install -r requirements.txt
pip install nuitka ordered-set zstandard

REM 构建 GUI 版本
echo.
echo [2/3] 构建 GUI 版本 (main.exe)...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --windows-console-mode=disable ^
    --enable-plugin=pyside6 ^
    --include-package=core ^
    --include-package=ui ^
    --output-filename=MediaClassifier.exe ^
    --output-dir=dist/amd64 ^
    --windows-icon-from-ico=icon.ico ^
    --company-name="MediaClassifier" ^
    --product-name="媒体文件智能分类系统" ^
    --file-version=1.0.0 ^
    --product-version=1.0.0 ^
    main.py

REM 构建 CLI 版本
echo.
echo [3/3] 构建 CLI 版本 (cli.exe)...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --include-package=core ^
    --output-filename=MediaClassifierCLI.exe ^
    --output-dir=dist/amd64 ^
    main_cli.py

echo.
echo [DONE] 构建完成! 输出目录: dist\amd64\
echo   - MediaClassifier.exe    (GUI)
echo   - MediaClassifierCLI.exe (CLI)
pause
