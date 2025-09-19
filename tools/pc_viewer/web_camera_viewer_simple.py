#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ESP32 WiFi摄像头Web显示程序 (简化版)
- 不依赖OpenCV，仅使用Flask和标准库
- 基于Flask的Web服务器，在浏览器中显示摄像头画面
- 从TCP连接接收ESP32发送的JPEG图像数据
- 使用MJPEG流的方式在网页上实时显示

用法示例：
    python web_camera_viewer_simple.py --host 0.0.0.0 --port 8000 --web-port 5000

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
import base64

from flask import Flask, render_template_string, Response

SOI = b"\xff\xd8"  # JPEG Start Of Image
EOI = b"\xff\xd9"  # JPEG End Of Image

# 全局变量用于存储最新的图像帧
frame_queue = Queue(maxsize=10)  # 限制队列大小避免内存溢出

# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>ESP32 WiFi Camera</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: white;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background-color: rgba(255, 255, 255, 0.95);
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
            text-align: center;
            color: #333;
        }
        h1 {
            color: #333;
            margin-bottom: 30px;
            font-size: 2.5em;
            font-weight: 300;
        }
        .camera-container {
            border: 3px solid #ddd;
            border-radius: 15px;
            display: inline-block;
            padding: 15px;
            background: linear-gradient(145deg, #f0f0f0, #ffffff);
            box-shadow: inset 0 2px 5px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        #camera-stream {
            max-width: 100%;
            height: auto;
            border-radius: 10px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }
        .info {
            margin-top: 25px;
            color: #666;
            font-size: 16px;
            line-height: 1.6;
        }
        .status {
            margin: 20px auto;
            padding: 15px 25px;
            border-radius: 25px;
            max-width: 600px;
            font-weight: 500;
            font-size: 16px;
        }
        .status.connected {
            background: linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%);
            color: #155724;
            border: 2px solid #84fab0;
        }
        .status.disconnected {
            background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
            color: #721c24;
            border: 2px solid #fcb69f;
        }
        .controls {
            margin-top: 20px;
        }
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 16px;
            margin: 0 10px;
            transition: all 0.3s ease;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        .tech-info {
            margin-top: 30px;
            padding: 20px;
            background-color: #f8f9fa;
            border-radius: 10px;
            border-left: 4px solid #667eea;
        }
    </style>
    <script>
        let reconnectAttempts = 0;
        let maxReconnectAttempts = 5;
        
        function checkImageStatus() {
            const img = document.getElementById('camera-stream');
            const status = document.getElementById('status');
            
            img.onload = function() {
                status.className = 'status connected';
                status.innerHTML = '🟢 摄像头连接正常 - 正在接收图像流';
                reconnectAttempts = 0;
            };
            
            img.onerror = function() {
                reconnectAttempts++;
                status.className = 'status disconnected';
                if (reconnectAttempts < maxReconnectAttempts) {
                    status.innerHTML = `🔴 摄像头连接断开 - 尝试重连中 (${reconnectAttempts}/${maxReconnectAttempts})`;
                    setTimeout(() => {
                        img.src = img.src.split('?')[0] + '?t=' + new Date().getTime();
                    }, 2000);
                } else {
                    status.innerHTML = '🔴 摄像头连接断开 - 请检查ESP32设备';
                }
            };
        }
        
        function refreshStream() {
            const img = document.getElementById('camera-stream');
            img.src = img.src.split('?')[0] + '?t=' + new Date().getTime();
            reconnectAttempts = 0;
        }
        
        function toggleFullscreen() {
            const img = document.getElementById('camera-stream');
            if (img.requestFullscreen) {
                img.requestFullscreen();
            } else if (img.webkitRequestFullscreen) {
                img.webkitRequestFullscreen();
            } else if (img.msRequestFullscreen) {
                img.msRequestFullscreen();
            }
        }
        
        window.onload = function() {
            checkImageStatus();
            // 定期检查连接状态
            setInterval(checkImageStatus, 10000);
        };
    </script>
</head>
<body>
    <div class="container">
        <h1>🎥 ESP32 WiFi 摄像头实时显示</h1>
        <div class="camera-container">
            <img id="camera-stream" src="{{ url_for('video_feed') }}" alt="Camera Stream" onclick="toggleFullscreen()">
        </div>
        <div id="status" class="status disconnected">⏳ 等待摄像头连接...</div>
        
        <div class="controls">
            <button class="btn" onclick="refreshStream()">🔄 刷新画面</button>
            <button class="btn" onclick="toggleFullscreen()">🔍 全屏显示</button>
        </div>
        
        <div class="info">
            <p><strong>💡 使用说明：</strong></p>
            <p>• 点击图像可进入全屏模式</p>
            <p>• 如果画面卡顿，点击"刷新画面"按钮</p>
            <p>• 确保ESP32摄像头已连接到同一网络</p>
        </div>
        
        <div class="tech-info">
            <p><strong>📋 技术信息：</strong></p>
            <p>• 服务器地址: {{ server_info.host }}:{{ server_info.tcp_port }}</p>
            <p>• Web端口: {{ server_info.web_port }}</p>
            <p>• 传输协议: TCP + MJPEG Stream</p>
            <p>• 支持的格式: JPEG图像流</p>
        </div>
    </div>
</body>
</html>
'''

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESP32 WiFi Camera Web Viewer (Simple Version)")
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


def create_waiting_image() -> bytes:
    """创建等待连接的占位图像"""
    # 创建一个简单的SVG图像作为占位符
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="320" height="240" xmlns="http://www.w3.org/2000/svg">
    <rect width="320" height="240" fill="#f0f0f0"/>
    <text x="160" y="120" text-anchor="middle" font-family="Arial" font-size="18" fill="#666">
        等待ESP32连接...
    </text>
    <text x="160" y="150" text-anchor="middle" font-family="Arial" font-size="14" fill="#999">
        Waiting for ESP32...
    </text>
</svg>'''
    
    # 由于我们没有图像处理库，返回一个简单的错误信息
    # 实际上，我们在没有帧时会发送最后一帧或者跳过
    return b''


def generate_frames():
    """生成MJPEG流帧"""
    last_frame = None
    
    while True:
        try:
            # 从队列获取最新帧
            frame_data = frame_queue.get(timeout=1.0)
            last_frame = frame_data
            
            # 构造MJPEG边界
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
                   
        except Empty:
            # 队列为空时，如果有最后一帧就重复发送，否则发送空响应
            if last_frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + last_frame + b'\r\n')
            else:
                # 发送一个最小的JPEG头，避免浏览器报错
                time.sleep(0.1)
                continue


# 创建Flask应用
app = Flask(__name__)

# 全局服务器信息
server_info = {
    'host': '0.0.0.0',
    'tcp_port': 8000,
    'web_port': 5000
}

@app.route('/')
def index():
    """主页"""
    return render_template_string(HTML_TEMPLATE, server_info=server_info)

@app.route('/video_feed')
def video_feed():
    """视频流端点"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/status')
def status():
    """状态检查端点"""
    queue_size = frame_queue.qsize()
    return {
        'queue_size': queue_size,
        'status': 'connected' if queue_size > 0 else 'waiting',
        'server_info': server_info
    }

def main() -> int:
    args = parse_args()
    
    # 更新全局服务器信息
    server_info.update({
        'host': args.host,
        'tcp_port': args.port,
        'web_port': args.web_port
    })
    
    print("ESP32 WiFi摄像头Web显示程序 (简化版)")
    print("=" * 55)
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
    print(f"\n🌐 请在浏览器中访问:")
    print(f"  本机访问: http://localhost:{args.web_port}")
    print(f"  局域网访问: http://{local_ip}:{args.web_port}")
    print(f"\n📡 等待ESP32连接到 {args.host}:{args.port}...")
    print("💻 按 Ctrl+C 退出程序")
    print("\n" + "=" * 55)
    
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