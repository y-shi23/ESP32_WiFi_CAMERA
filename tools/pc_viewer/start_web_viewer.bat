@echo off
echo ESP32 WiFi摄像头Web显示程序启动器
echo =====================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: 未找到Python，请先安装Python 3.7或更高版本
    pause
    exit /b 1
)

REM 检查Flask是否安装
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo 检测到Flask未安装，正在安装依赖...
    pip install flask
    if %errorlevel% neq 0 (
        echo 错误: 安装Flask失败，请手动运行 "pip install flask"
        pause
        exit /b 1
    )
)

echo 启动Web摄像头显示程序...
echo.
echo 程序启动后，请在浏览器中打开显示的网址
echo 按 Ctrl+C 可以退出程序
echo.

REM 启动程序，使用默认参数
python web_camera_viewer_simple.py

pause