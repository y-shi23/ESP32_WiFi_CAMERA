/**
 ***************************************************************************************************
 * 实验简介
 * 实验名称：WIFI 网络摄像头实验
 * 实验平台：正点原子 ESP32-S3开发板
 * 实验目的：学习lwIP Socket TCPClient 接口

 ***************************************************************************************************
 * 硬件资源及引脚分配
 * 1 LED
     LED(RED) - IO5
 * 2 正点原子 1.3/2.4 寸SPILCD模块
 * 3 XL9555
 *      INT-->IO0
 *      SDA-->IO41
 *      CLK-->IO42
 * 4 CAMERA
 *      OV_D0-->IO4
 *      OV_D1-->IO5
 *      OV_D2-->IO6
 *      OV_D3-->IO7
 *      OV_D4-->IO15
 *      OV_D5-->IO16
 *      OV_D6-->IO17
 *      OV_D7-->IO18
 *      OV_VSYNC-->IO47
 *      OV_HREF-->IO48
 *      OV_PCLK-->IO45
 *      OV_SCL-->IO38
 *      OV_SDA-->IO39
 *      OV_PWDN-->IO扩展4(OV_PWDN)
 *      OV_RESET-->IO扩展5(OV_RESET)
 * 
 ***************************************************************************************************
 * 实验现象
 * 1 电脑端使用 Python 显示程序接收并显示摄像头画面。
 * 2 LED闪烁，指示程序正在运行。

 ***************************************************************************************************
 * PC 端 Python 显示程序（替代 UartDisplay）
 * 1 位置：tools/pc_viewer/viewer.py
 * 2 依赖：Python 3.8+；pip 安装 opencv-python、numpy（见 requirements.txt）
 * 3 运行（Windows PowerShell）：
 *    pip install -r tools/pc_viewer/requirements.txt
 *    python .\tools\pc_viewer\viewer.py --host 0.0.0.0 --port 8080
 * 4 注意：需将工程中 main/APP/lwip_demo.c 的 IP_ADDR 设置为电脑的局域网 IP（viewer 监听的主机）。
 * 5 运行后，ESP32 连接到 PC，Python 程序将实时显示图像，按 q 退出。

 ***************************************************************************************************
 * 注意事项
 * 无
 
 ***********************************************************************************************************
 * 公司名称：广州市星翼电子科技有限公司（正点原子）
 * 电话号码：020-38271790
 * 传真号码：020-36773971
 * 公司网址：www.alientek.com
 * 购买地址：zhengdianyuanzi.tmall.com
 * 技术论坛：http://www.openedv.com/forum.php
 * 最新资料：www.openedv.com/docs/index.html
 *
 * 在线视频：www.yuanzige.com
 * B 站视频：space.bilibili.com/394620890
 * 公 众 号：mp.weixin.qq.com/s/y--mG3qQT8gop0VRuER9bw
 * 抖    音：douyin.com/user/MS4wLjABAAAAi5E95JUBpqsW5kgMEaagtIITIl15hAJvMO8vQMV1tT6PEsw-V5HbkNLlLMkFf1Bd
 ***********************************************************************************************************
 */