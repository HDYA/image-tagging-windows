@echo off
REM ============================================
REM  媒体文件智能分类系统 - Windows ARM64 构建
REM ============================================
REM
REM 前置要求:
REM   1. Python 3.11+ (ARM64 版本)
REM      下载: https://www.python.org/downloads/
REM      确认: python -c "import platform; print(platform.machine())"
REM      应输出: ARM64
REM
REM   2. pip install -r requirements.txt
REM   3. pip install nuitka ordered-set zstandard
REM
REM 注意: ARM64 上部分包可能需要从源码编译
REM   - PySide6 >= 6.6.0 已提供 ARM64 wheel
REM   - onnxruntime 的 ARM64 支持请使用 onnxruntime >= 1.17
REM

echo [BUILD] 媒体文件智能分类系统 - ARM64
echo.

REM 检查架构
python -c "import platform; m=platform.machine(); print(f'架构: {m}'); exit(0 if 'ARM' in m.upper() or 'AARCH' in m.upper() else 1)"
if errorlevel 1 (
    echo [WARN] 当前 Python 不是 ARM64 版本!
    echo        请安装 ARM64 版 Python 或使用交叉编译。
    echo        继续构建可能生成 AMD64 二进制...
    echo.
    choice /C YN /M "是否继续?"
    if errorlevel 2 exit /b 1
)

REM 安装依赖
echo [1/3] 安装依赖...
pip install -r requirements.txt
pip install nuitka ordered-set zstandard

REM 构建 GUI
echo.
echo [2/3] 构建 GUI 版本 (ARM64)...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --windows-console-mode=disable ^
    --enable-plugin=pyside6 ^
    --include-package=core ^
    --include-package=ui ^
    --output-filename=MediaClassifier_ARM64.exe ^
    --output-dir=dist/arm64 ^
    --windows-icon-from-ico=icon.ico ^
    --company-name="MediaClassifier" ^
    --product-name="媒体文件智能分类系统" ^
    --file-version=1.0.0 ^
    --product-version=1.0.0 ^
    main.py

REM 构建 CLI
echo.
echo [3/3] 构建 CLI 版本 (ARM64)...
python -m nuitka ^
    --standalone ^
    --onefile ^
    --include-package=core ^
    --output-filename=MediaClassifierCLI_ARM64.exe ^
    --output-dir=dist/arm64 ^
    cli.py

echo.
echo [DONE] 构建完成! 输出目录: dist\arm64\
echo   - MediaClassifier_ARM64.exe    (GUI)
echo   - MediaClassifierCLI_ARM64.exe (CLI)
pause
