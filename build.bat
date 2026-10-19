@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 安装依赖...
python -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo 开始打包...
python -m PyInstaller --noconfirm --clean --windowed --name "布料出入库" main.py
if errorlevel 1 goto fail

echo.
echo 打包完成。给亲戚用的文件夹在：
echo   dist\布料出入库\
echo 把整个「布料出入库」文件夹拷过去，双击「布料出入库.exe」即可。
echo 数据会保存在同目录下的「库存数据.db」。
pause
exit /b 0

:fail
echo 打包失败，请确认已安装 Python，并已勾选 Add Python to PATH。
pause
exit /b 1
