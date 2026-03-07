#!/bin/bash
# iflow-bot 打包脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
DIST_DIR="$PROJECT_ROOT/dist"

echo "========================================="
echo "  iflow-bot 打包脚本"
echo "========================================="
echo ""

# 清理旧的构建文件
echo "清理旧的构建文件..."
rm -rf "$PROJECT_ROOT/build"
rm -rf "$DIST_DIR"
rm -rf "$PROJECT_ROOT/*.egg-info"
echo "✓ 清理完成"
echo ""

# 构建源码包和 wheel
echo "开始构建..."
cd "$PROJECT_ROOT"
python3 -m build --wheel --sdist
echo "✓ 构建完成"
echo ""

# 显示生成的文件
echo "生成的文件:"
ls -lh "$DIST_DIR"
echo ""

# 计算文件校验和
echo "计算校验和..."
cd "$DIST_DIR"
sha256sum *.tar.gz *.whl > SHA256SUMS
echo "✓ 校验和已生成"
echo ""

echo "========================================="
echo "  打包完成！"
echo "========================================="
echo ""
echo "文件位置: $DIST_DIR"
echo ""
echo "安装方法:"
echo "  pip install dist/iflow_bot-*.tar.gz"
echo "  或"
echo "  pip install dist/iflow_bot-*.whl"
echo ""
