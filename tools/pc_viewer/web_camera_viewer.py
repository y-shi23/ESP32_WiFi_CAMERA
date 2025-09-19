#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ESP32 WiFi摄像头Web显示程序
- 基于Flask的Web服务器，在浏览器中显示摄像头画面
- 从TCP连接接收ESP32发送的JPEG图像数据
- 使用MJPEG流的方式在网页上实时显示

用法示例：
    python web_camera_viewer.py --host 0.0.0.0 --port 8000 --web-port 5000

访问方式：
    在浏览器中打开 http://localhost:5000 或 http://your-ip:5000
"""

import argparse
import socket
import sys
import time
import threading
from typing import Optional
from queue import Queue, Empty
import io

from flask import Flask, render_template_string, Response
import cv2
import numpy as np

SOI = b"\xff\xd8"  # JPEG Start Of Image
EOI = b"\xff\xd9"  # JPEG End Of Image

# 全局变量用于存储最新的图像帧
latest_frame = None
frame_lock = threading.Lock()
frame_queue = Queue(maxsize=10)  # 限制队列大小避免内存溢出

# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>ESP32 WiFi Camera</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f0f0f0;
            text-align: center;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            margin-bottom: 30px;
        }
        .camera-container {
            border: 3px solid #ddd;
            border-radius: 10px;
            display: inline-block;
            padding: 10px;
            background-color: #f9f9f9;
        }
        #camera-stream {
            max-width: 100%;
            height: auto;
            border-radius: 5px;
        }
        .info {
            margin-top: 20px;
            color: #666;
            font-size: 14px;
        }
        .status {
            margin-top: 10px;
            padding: 10px;
            border-radius: 5px;
        }
        .status.connected {
            background-color: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .status.disconnected {
            background-color: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
    </style>
    <script>
        // 检查图像加载状态
        function checkImageStatus() {
            const img = document.getElementById('camera-stream');
            const status = document.getElementById('status');
            
            img.onload = function() {
                status.className = 'status connected';
                status.textContent = '摄像头连接正常 - 正在接收图像流';
            };
            
            img.onerror = function() {
                status.className = 'status disconnected';
                status.textContent = '摄像头连接断开 - 等待重新连接...';
            };
        }
        
        // 页面加载后开始检查
        window.onload = function() {
            checkImageStatus();
            // 定期刷新页面状态
            setInterval(checkImageStatus, 5000);
        };
    </script>
</head>
<body>
    <div class="container">
        <h1>ESP32 WiFi 摄像头实时显示</h1>
        <div class="camera-container">
            <img id="camera-stream" src="{{ url_for('video_feed') }}" alt="Camera Stream">
        </div>
        <div id="status" class="status disconnected">等待摄像头连接...</div>
        <div class="info">
            <p><strong>说明：</strong></p>
            <p>• 确保ESP32摄像头已连接到同一网络</p>
            <p>• ESP32需要配置正确的服务器IP和端口</p>
            <p>• 如果画面卡顿，请检查网络连接</p>
        </div>
    </div>
</body>
</html>
'''

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESP32 WiFi Camera Web Viewer")
    parser.add_argument("--host", default="0.0.0.0", help="TCP监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000, help="TCP监听端口，需与ESP32固件一致，默认 8000")
    parser.add_argument("--web-port", type=int, default=5000, help="Web服务端口，默认 5000")
    parser.add_argument("--timeout", type=float, default=10.0, help="等待连接超时（秒）")
    return parser.parse_args()


def get_default_ip() -> str:
    """获取本机默认网卡IP地址"""
    try:
        tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tmp.connect(("8.8.8.8", 80))
        ip = tmp.getsockname()[0]
        tmp.close()
        return ip
    except Exception:
        return "127.0.0.1"


def recv_images_thread(host: str, port: int, timeout: float) -> None:
    """TCP图像接收线程"""
    global latest_frame
    
    while True:
        print(f"[INFO] 尝试在 {host}:{port} 监听TCP连接...")
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                
                try:
                    s.bind((host, port))
                except PermissionError as e:
                    print(f"[WARN] 绑定失败，尝试使用本机IP...")
                    alt_host = get_default_ip() if host == "0.0.0.0" else host
                    s.bind((alt_host, port))
                    host = alt_host
                
                s.listen(1)
                s.settimeout(timeout)
                print(f"[INFO] TCP服务器监听 {host}:{port}，等待ESP32连接...")
                
                try:
                    conn, addr = s.accept()
                    print(f"[INFO] ESP32已连接：{addr}")
                    
                    with conn:
                        recv_images_from_connection(conn)
                        
                except socket.timeout:
                    print("[WARN] 等待连接超时，继续监听...")
                    continue
                    
        except Exception as e:
            print(f"[ERROR] TCP服务器错误: {e}")
            time.sleep(2)
            continue


def recv_images_from_connection(conn: socket.socket) -> None:
    """从TCP连接接收图像数据"""
    global latest_frame
    
    buf = bytearray()
    conn.settimeout(5.0)
    
    while True:
        try:
            data = conn.recv(4096)
            if not data:
                print("[INFO] ESP32断开连接")
                break
            buf.extend(data)
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[ERROR] 接收数据失败: {e}")
            break

        # 查找JPEG帧边界
        start = buf.find(SOI)
        if start > 0:
            del buf[:start]
        elif start < 0 and len(buf) > 1024 * 1024:
            buf.clear()
            continue

        # 提取完整的JPEG帧
        while True:
            start = buf.find(SOI)
            if start < 0:
                break
            end = buf.find(EOI, start + 2)
            if end < 0:
                break
            end += 2
            
            frame_data = bytes(buf[start:end])
            del buf[:end]
            
            # 将帧数据放入队列
            try:
                frame_queue.put_nowait(frame_data)
            except:
                # 队列满时丢弃旧帧
                try:
                    frame_queue.get_nowait()
                    frame_queue.put_nowait(frame_data)
                except Empty:
                    pass


def generate_frames():
    """生成MJPEG流帧"""
    while True:
        try:
            # 从队列获取最新帧
            frame_data = frame_queue.get(timeout=1.0)
            
            # 构造MJPEG边界
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
                   
        except Empty:
            # 队列为空时发送空白帧
            # 创建一个简单的"等待连接"图像
            img = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.putText(img, "Waiting for ESP32...", (50, 120), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            _, buffer = cv2.imencode('.jpg', img)
            frame_data = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')


# 创建Flask应用
app = Flask(__name__)

@app.route('/')
def index():
    """主页"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/video_feed')
def video_feed():
    """视频流端点"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

def main() -> int:
    args = parse_args()
    
    print("ESP32 WiFi摄像头Web显示程序")
    print("=" * 50)
    print(f"TCP监听地址: {args.host}:{args.port}")
    print(f"Web服务端口: {args.web_port}")
    
    # 启动TCP图像接收线程
    tcp_thread = threading.Thread(
        target=recv_images_thread, 
        args=(args.host, args.port, args.timeout),
        daemon=True
    )
    tcp_thread.start()
    
    # 获取本机IP用于显示访问地址
    local_ip = get_default_ip()
    print(f"\n请在浏览器中访问:")
    print(f"  本机访问: http://localhost:{args.web_port}")
    print(f"  局域网访问: http://{local_ip}:{args.web_port}")
    print(f"\n等待ESP32连接到 {args.host}:{args.port}...")
    print("按 Ctrl+C 退出程序")
    
    try:
        # 启动Flask Web服务器
        app.run(host='0.0.0.0', port=args.web_port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n[INFO] 程序已退出")
        return 0
    except Exception as e:
        print(f"[ERROR] Web服务器启动失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())