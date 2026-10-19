#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "安装依赖..."
python3 -m pip install -r requirements.txt

echo "开始打包..."
python3 -m PyInstaller --noconfirm --clean --windowed --name "布料出入库" main.py

echo ""
echo "打包完成。给亲戚用的程序在："
echo "  dist/布料出入库.app"
echo ""
echo "用法：把「布料出入库.app」拷到 Mac 上，双击打开即可。"
echo "数据会保存在 .app 同级目录下的「库存数据.db」。"
echo ""
echo "若双击提示无法打开：右键 → 打开 → 仍要打开"
echo "（因为没有做苹果开发者签名）"
