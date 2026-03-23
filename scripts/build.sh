#!/usr/bin/env bash
# ============================================
#  媒体文件智能分类系统 - CI 双架构构建脚本
# ============================================
#
# 用于 GitHub Actions 或本地批量构建
# 根据当前 Python 架构自动检测
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "====================================="
echo " 媒体文件智能分类系统 - 构建"
echo "====================================="

# 检测架构
ARCH=$(python -c "import platform; print(platform.machine())")
echo "Python 架构: $ARCH"

case "$ARCH" in
    AMD64|x86_64)
        ARCH_TAG="amd64"
        ;;
    ARM64|aarch64|AARCH64)
        ARCH_TAG="arm64"
        ;;
    *)
        echo "未知架构: $ARCH, 默认 amd64"
        ARCH_TAG="amd64"
        ;;
esac

echo "构建目标: $ARCH_TAG"
echo ""

# 安装依赖
echo "[1/4] 安装依赖..."
pip install -r requirements.txt
pip install nuitka ordered-set zstandard

# 可选: 人脸模块
if [ "$BUILD_FACE" = "1" ]; then
    echo "  安装人脸模块依赖..."
    pip install -r requirements-face.txt
fi

# 创建输出目录
mkdir -p "dist/$ARCH_TAG"

# 构建 GUI
echo ""
echo "[2/4] 构建 GUI..."
python -m nuitka \
    --standalone \
    --onefile \
    --enable-plugin=pyside6 \
    --include-package=core \
    --include-package=ui \
    --output-filename="MediaClassifier_${ARCH_TAG}" \
    --output-dir="dist/$ARCH_TAG" \
    main.py

# 构建 CLI
echo ""
echo "[3/4] 构建 CLI..."
python -m nuitka \
    --standalone \
    --onefile \
    --include-package=core \
    --output-filename="MediaClassifierCLI_${ARCH_TAG}" \
    --output-dir="dist/$ARCH_TAG" \
    cli.py

# 完成
echo ""
echo "[4/4] 构建完成!"
echo "  输出目录: dist/$ARCH_TAG/"
ls -la "dist/$ARCH_TAG/"
