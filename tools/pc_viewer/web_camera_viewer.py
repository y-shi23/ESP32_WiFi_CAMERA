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

from flask import Flask, render_template_string, Response, jsonify
import cv2
import numpy as np

SOI = b"\xff\xd8"  # JPEG Start Of Image
EOI = b"\xff\xd9"  # JPEG End Of Image

# 全局变量用于存储最新的图像帧
latest_frame = None
frame_lock = threading.Lock()
frame_queue = Queue(maxsize=10)  # 限制队列大小避免内存溢出

# =============== 人脸检测 / 识别 ===============
face_lock = threading.Lock()
face_db = {}  # face_id -> {id, embedding, first_seen, last_seen, seen_count, thumb_jpeg}
next_face_id = 1
face_enabled = True
face_cascade = None
_face_frame_counter = 0

def _init_face_detector():
    global face_cascade, face_enabled
    try:
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        if face_cascade.empty():
            print('[WARN] 加载Haar人脸分类器失败，将禁用人脸功能')
            face_enabled = False
        else:
            face_enabled = True
            print('[INFO] 人脸检测已启用 (Haar Cascade)')
    except Exception as e:
        print(f'[WARN] 初始化人脸检测失败: {e}')
        face_enabled = False

def _compute_embedding(gray_roi: np.ndarray) -> Optional[np.ndarray]:
    """简单的人脸特征向量：64x64灰度像素直方图均衡后展开并L2归一化。"""
    try:
        face_small = cv2.resize(gray_roi, (64, 64), interpolation=cv2.INTER_AREA)
    except Exception:
        return None
    face_eq = cv2.equalizeHist(face_small)
    vec = face_eq.astype(np.float32).reshape(-1)
    vec -= vec.mean()
    norm = np.linalg.norm(vec) + 1e-6
    vec /= norm
    return vec

def _match_face(embedding: np.ndarray, threshold: float = 0.36) -> Optional[int]:
    """在face_db中查找最相近的人脸，欧氏距离小于阈值则视为同一人。"""
    with face_lock:
        best_id = None
        best_dist = 1e9
        for fid, info in face_db.items():
            emb = info.get('embedding')
            if emb is None or emb.shape != embedding.shape:
                continue
            d = np.linalg.norm(emb - embedding)
            if d < best_dist:
                best_dist = d
                best_id = fid
        if best_dist <= threshold:
            return best_id
        return None

def _make_thumbnail(bgr: np.ndarray, size: int = 112) -> Optional[bytes]:
    try:
        h, w = bgr.shape[:2]
        side = min(h, w)
        y0 = (h - side) // 2
        x0 = (w - side) // 2
        crop = bgr[y0:y0+side, x0:x0+side]
        thumb = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode('.jpg', thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if ok else None
    except Exception:
        return None

def _update_face_db(face_img_bgr: np.ndarray, gray_roi: np.ndarray, embedding: np.ndarray) -> int:
    """匹配或新增人脸，返回face_id。"""
    global next_face_id
    fid = _match_face(embedding)
    now = time.time()
    thumb = _make_thumbnail(face_img_bgr)
    with face_lock:
        if fid is None:
            fid = next_face_id
            next_face_id += 1
            face_db[fid] = {
                'id': fid,
                'embedding': embedding.copy(),
                'first_seen': now,
                'last_seen': now,
                'seen_count': 1,
                'thumb_jpeg': thumb,
            }
        else:
            info = face_db.get(fid)
            if info is not None:
                info['embedding'] = 0.8 * info['embedding'] + 0.2 * embedding
                info['last_seen'] = now
                info['seen_count'] += 1
                if info['seen_count'] % 20 == 0 and thumb is not None:
                    info['thumb_jpeg'] = thumb
    return fid

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
        /* 全屏样式 */
        .fullscreen-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-color: black;
            z-index: 9999;
            display: none;
            justify-content: center;
            align-items: center;
        }
        .fullscreen-container.show {
            display: flex;
        }
        .fullscreen-container img {
            width: 100vw;
            height: 100vh;
            object-fit: cover; /* 填满屏幕，可能会裁剪 */
        }
        .fullscreen-container img.contain {
            width: auto;
            height: auto;
            max-width: 100vw;
            max-height: 100vh;
            object-fit: contain; /* 保持比例，完整显示 */
        }
        .fullscreen-container img.fill {
            width: 100vw;
            height: 100vh;
            object-fit: fill; /* 拉伸填满，可能变形 */
        }
        .fullscreen-controls {
            position: absolute;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .fullscreen-exit-btn {
            background-color: rgba(255, 255, 255, 0.8);
            border: none;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            font-size: 20px;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        .fullscreen-exit-btn:hover {
            background-color: rgba(255, 255, 255, 1);
        }
        .fullscreen-mode-btn {
            background-color: rgba(0, 123, 255, 0.8);
            color: white;
            border: none;
            border-radius: 20px;
            padding: 8px 12px;
            font-size: 12px;
            cursor: pointer;
            transition: background-color 0.3s;
            white-space: nowrap;
        }
        .fullscreen-mode-btn:hover {
            background-color: rgba(0, 123, 255, 1);
        }
        .fullscreen-mode-btn.active {
            background-color: rgba(40, 167, 69, 0.8);
        }
        /* 控制按钮 */
        .controls {
            margin-top: 20px;
        }
        .control-btn {
            background-color: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            margin: 0 5px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            transition: background-color 0.3s;
        }
        .control-btn:hover {
            background-color: #0056b3;
        }
        .control-btn.fullscreen {
            background-color: #28a745;
        }
        .control-btn.fullscreen:hover {
            background-color: #1e7e34;
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
        
        // 全屏模式状态
        let currentFullscreenMode = 'cover'; // 默认为填满模式
        
        // 全屏功能
        function toggleFullscreen() {
            const fullscreenContainer = document.getElementById('fullscreen-container');
            const fullscreenImg = document.getElementById('fullscreen-stream');
            const originalImg = document.getElementById('camera-stream');
            
            if (fullscreenContainer.classList.contains('show')) {
                // 退出全屏
                exitFullscreen();
            } else {
                // 进入全屏
                enterFullscreen();
            }
        }
        
        function enterFullscreen() {
            const fullscreenContainer = document.getElementById('fullscreen-container');
            const fullscreenImg = document.getElementById('fullscreen-stream');
            const originalImg = document.getElementById('camera-stream');
            
            // 复制视频流到全屏容器
            fullscreenImg.src = originalImg.src;
            fullscreenContainer.classList.add('show');
            
            // 设置初始显示模式
            setFullscreenMode(currentFullscreenMode);
            
            // 隐藏页面滚动条
            document.body.style.overflow = 'hidden';
            
            // 监听ESC键退出全屏
            document.addEventListener('keydown', handleEscapeKey);
        }
        
        function setFullscreenMode(mode) {
            const fullscreenImg = document.getElementById('fullscreen-stream');
            const buttons = document.querySelectorAll('.fullscreen-mode-btn');
            
            // 清除所有模式类
            fullscreenImg.className = '';
            buttons.forEach(btn => btn.classList.remove('active'));
            
            // 设置新模式
            currentFullscreenMode = mode;
            if (mode === 'contain') {
                fullscreenImg.classList.add('contain');
            } else if (mode === 'fill') {
                fullscreenImg.classList.add('fill');
            }
            // cover模式是默认的，不需要额外类
            
            // 高亮当前模式按钮
            const activeButton = document.querySelector(`[onclick="setFullscreenMode('${mode}')"]`);
            if (activeButton) {
                activeButton.classList.add('active');
            }
        }
            fullscreenContainer.classList.add('show');
            
            // 隐藏页面滚动条
            document.body.style.overflow = 'hidden';
            
            // 监听ESC键退出全屏
            document.addEventListener('keydown', handleEscapeKey);
        }
        
        function exitFullscreen() {
            const fullscreenContainer = document.getElementById('fullscreen-container');
            
            fullscreenContainer.classList.remove('show');
            document.body.style.overflow = 'auto';
            
            // 移除ESC键监听
            document.removeEventListener('keydown', handleEscapeKey);
        }
        
        function handleEscapeKey(event) {
            if (event.key === 'Escape') {
                exitFullscreen();
            }
        }
        
        // 刷新视频流
        function refreshStream() {
            const img = document.getElementById('camera-stream');
            const fullscreenImg = document.getElementById('fullscreen-stream');
            const timestamp = new Date().getTime();
            
            // 刷新主图像
            img.src = img.src.split('?')[0] + '?t=' + timestamp;
            
            // 如果在全屏模式，也刷新全屏图像
            if (document.getElementById('fullscreen-container').classList.contains('show')) {
                fullscreenImg.src = fullscreenImg.src.split('?')[0] + '?t=' + timestamp;
            }
        }
        
        // 页面加载后开始检查
        window.onload = function() {
            checkImageStatus();
            // 定期刷新页面状态
            setInterval(checkImageStatus, 5000);
            
            // 为图像添加双击全屏事件
            const img = document.getElementById('camera-stream');
            img.addEventListener('dblclick', toggleFullscreen);
        };
        // 人脸列表刷新函数
        async function refreshFaces() {
            try {
                const res = await fetch('/faces?t=' + Date.now());
                if (!res.ok) return;
                const data = await res.json();
                const list = document.getElementById('faces-grid');
                const totalEl = document.getElementById('face-total');
                if (!list) return;
                list.innerHTML = '';
                if (totalEl) totalEl.textContent = data.faces.length;
                for (const f of data.faces) {
                    const item = document.createElement('div');
                    item.className = 'face-item';
                    const img = document.createElement('img');
                    img.className = 'face-thumb';
                    img.alt = 'face ' + f.id;
                    img.src = `/face_thumbnail/${f.id}.jpg?ts=${Math.floor(f.last_seen*1000)}`;
                    const meta = document.createElement('div');
                    meta.className = 'face-meta';
                    const idSpan = document.createElement('span');
                    idSpan.className = 'face-id';
                    idSpan.textContent = `#${f.id}`;
                    const statSpan = document.createElement('span');
                    statSpan.className = 'face-stat';
                    statSpan.title = `首次: ${new Date(f.first_seen*1000).toLocaleString()}\n最近: ${new Date(f.last_seen*1000).toLocaleString()}`;
                    statSpan.textContent = `出现 ${f.seen_count}`;
                    meta.appendChild(idSpan);
                    meta.appendChild(statSpan);
                    item.appendChild(img);
                    item.appendChild(meta);
                    list.appendChild(item);
                }
            } catch (e) {
                // 忽略错误
            }
        }
        // 页面加载后启动定时刷新
        window.addEventListener('load', () => { try { refreshFaces(); } catch(e){} setInterval(refreshFaces, 2000); });
    </script>
</head>
<body>
    <div class="container">
        <h1>ESP32 WiFi 摄像头实时显示</h1>
        <div class="camera-container">
            <img id="camera-stream" src="{{ url_for('video_feed') }}" alt="Camera Stream" title="双击进入全屏">
        </div>
        <div id="status" class="status disconnected">等待摄像头连接...</div>
        
        <!-- 控制按钮 -->
        <div class="controls">
            <button class="control-btn fullscreen" onclick="toggleFullscreen()">🔍 全屏显示</button>
            <button class="control-btn" onclick="refreshStream()">🔄 刷新画面</button>
        </div>
        
        <div class="info">
            <p><strong>说明：</strong></p>
            <p>• 双击图像或点击"全屏显示"按钮进入全屏模式</p>
            <p>• 在全屏模式下可以切换不同的显示模式：</p>
            <p>&nbsp;&nbsp;- 填满屏幕：图像填满整个屏幕（可能裁剪）</p>
            <p>&nbsp;&nbsp;- 完整显示：保持比例完整显示（可能有黑边）</p>
            <p>&nbsp;&nbsp;- 拉伸填满：强制填满屏幕（可能变形）</p>
            <p>• 按ESC键或点击×按钮退出全屏</p>
            <p>• 确保ESP32摄像头已连接到同一网络</p>
            <p>• ESP32需要配置正确的服务器IP和端口</p>
            <p>• 如果画面卡顿，请点击"刷新画面"按钮</p>
        </div>

        <!-- 人脸列表卡片 -->
        <div class="card faces-card">
            <header>
                <div style="font-weight:600">已识别人脸</div>
                <div class="hint">共 <span id="face-total">0</span> 个</div>
            </header>
            <div id="faces-grid" class="faces-grid"></div>
            <div class="hint" style="margin-top:8px">识别采用轻量特征，正面、充足光照效果更佳</div>
        </div>

    </div>

    <!-- 全屏容器 -->
    <div id="fullscreen-container" class="fullscreen-container">
        <div class="fullscreen-controls">
            <button class="fullscreen-exit-btn" onclick="exitFullscreen()" title="退出全屏">×</button>
            <button class="fullscreen-mode-btn active" onclick="setFullscreenMode('cover')" title="填满屏幕">🖼️ 填满</button>
            <button class="fullscreen-mode-btn" onclick="setFullscreenMode('contain')" title="完整显示">📐 完整</button>
            <button class="fullscreen-mode-btn" onclick="setFullscreenMode('fill')" title="拉伸填满">📏 拉伸</button>
        </div>
        <img id="fullscreen-stream" src="" alt="Fullscreen Camera Stream">
    </div>
</body>
</html>
'''

# 新版极简美观前端模板
HTML_TEMPLATE_NEW = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ESP32 WiFi Camera</title>
    <style>
        :root {
            --bg: #f7f8fb;
            --card: #ffffff;
            --text: #0f172a;
            --muted: #64748b;
            --border: #e5e7eb;
            --accent: #2563eb; /* Google/Apple-like blue */
            --pill-bg: #eef2ff;
            --success: #10b981;
            --danger: #ef4444;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg: #0b0f1a;
                --card: #0f172a;
                --text: #e5e7eb;
                --muted: #94a3b8;
                --border: #1f2937;
                --pill-bg: #1e293b;
            }
        }

        * { box-sizing: border-box; }
        html, body { height: 100%; }
        body {
            margin: 0;
            font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji", sans-serif;
            background: var(--bg);
            color: var(--text);
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        .shell { max-width: 1080px; margin: 0 auto; padding: 24px; }

        /* 顶部栏 */
        .topbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
        .brand { font-size: 18px; font-weight: 600; letter-spacing: .2px; }
        .status-pill {
            display: inline-flex; align-items: center; gap: 8px;
            padding: 6px 10px; border-radius: 999px; background: var(--pill-bg);
            color: var(--muted); border: 1px solid var(--border); font-size: 13px;
        }
        .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
        .status-pill.connected { color: #065f46; }
        .status-pill.connected .dot { background: var(--success); }
        .status-pill.disconnected { color: #7f1d1d; }
        .status-pill.disconnected .dot { background: var(--danger); }

        /* 卡片 */
        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 1px 2px rgba(0,0,0,.06);
        }

        .video-wrap { position: relative; background: #0b0b0c; border-radius: 10px; overflow: hidden; }
        .video-wrap::after { content: ""; display: block; padding-top: 56.25%; }
        #camera-stream { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; background: #000; }
        #camera-stream[data-fit="contain"] { object-fit: contain; }
        #camera-stream[data-fit="fill"] { object-fit: fill; }

        /* 全屏时拉伸到视口 */
        #camera-stream:fullscreen { width: 100vw; height: 100vh; object-fit: cover; background: #000; }
        #camera-stream[data-fit="contain"]:fullscreen { object-fit: contain; }
        #camera-stream[data-fit="fill"]:fullscreen { object-fit: fill; }

        /* 控件 */
        .controls { display: flex; align-items: center; gap: 10px; justify-content: space-between; margin-top: 12px; flex-wrap: wrap; }
        .left-controls, .right-controls { display: flex; align-items: center; gap: 8px; }

        .btn {
            appearance: none; border: 1px solid var(--border);
            background: #fff; color: var(--text); font-size: 14px;
            padding: 8px 12px; border-radius: 8px; cursor: pointer;
            transition: background .15s ease, border-color .15s ease, transform .06s ease;
        }
        .btn:hover { background: #f8fafc; }
        .btn:active { transform: translateY(1px); }
        .btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
        .btn.ghost { background: transparent; }

        /* 分段控件（Fit 模式） */
        .segmented {
            display: inline-flex; background: var(--pill-bg);
            border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
        }
        .segmented .seg-btn {
            background: transparent; border: 0; color: var(--muted);
            padding: 8px 10px; cursor: pointer; font-size: 13px;
        }
        .segmented .seg-btn.active { color: var(--text); background: #fff; }
        .hint { color: var(--muted); font-size: 12px; }

        /* 人脸列表 */
        .faces-card header { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
        .faces-grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
        @media (min-width: 1200px) { .faces-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
        .face-item { border:1px solid var(--border); border-radius:10px; overflow:hidden; background:#fff; }
        .face-thumb { width:100%; aspect-ratio:1 / 1; object-fit:cover; display:block; background:#111; }
        .face-meta { padding:8px; display:flex; align-items:center; justify-content:space-between; font-size:12px; color:var(--muted);} 
        .face-id { font-weight:600; color:var(--text); font-size:12px; }
        .face-stat { font-variant-numeric: tabular-nums; }
    </style>
    <script>
        // 连接状态与尝试重连
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 5;

        function updateStatus(connected) {
            const pill = document.getElementById('status-pill');
            pill.classList.remove('connected', 'disconnected');
            pill.classList.add(connected ? 'connected' : 'disconnected');
            pill.querySelector('.label').textContent = connected ? '已连接' : '未连接';
        }

        function attachImageHandlers() {
            const img = document.getElementById('camera-stream');
            img.onload = function () {
                reconnectAttempts = 0;
                updateStatus(true);
            };
            img.onerror = function () {
                updateStatus(false);
                if (reconnectAttempts < maxReconnectAttempts) {
                    reconnectAttempts++;
                    setTimeout(() => {
                        img.src = img.src.split('?')[0] + '?t=' + Date.now();
                    }, 1500);
                }
            };
        }

        function refreshStream() {
            const img = document.getElementById('camera-stream');
            img.src = img.src.split('?')[0] + '?t=' + Date.now();
            reconnectAttempts = 0;
        }

        // Fit 模式（cover/contain/fill）
        function setFit(mode) {
            const img = document.getElementById('camera-stream');
            img.dataset.fit = mode;
            document.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
            const active = document.querySelector(`[data-fit-btn="${mode}"]`);
            if (active) active.classList.add('active');
        }

        // 全屏：使用原生 Fullscreen API（更简洁）
        function toggleFullscreen() {
            const img = document.getElementById('camera-stream');
            if (!document.fullscreenElement) {
                if (img.requestFullscreen) img.requestFullscreen();
            } else {
                document.exitFullscreen && document.exitFullscreen();
            }
        }

        window.addEventListener('DOMContentLoaded', () => {
            attachImageHandlers();
            setFit('cover');
            // 双击进入/退出全屏
            document.getElementById('camera-stream').addEventListener('dblclick', toggleFullscreen);
            // 键盘 F 切换全屏
            document.addEventListener('keydown', (e) => { if (e.key.toLowerCase() === 'f') toggleFullscreen(); });
        });
    </script>
</head>
<body>
    <div class="shell">
        <div class="topbar">
            <div class="brand">ESP32 WiFi Camera</div>
            <div id="status-pill" class="status-pill disconnected">
                <span class="dot"></span>
                <span class="label">未连接</span>
            </div>
        </div>

        <div class="card">
            <div class="video-wrap" aria-label="Camera">
                <img id="camera-stream" src="{{ url_for('video_feed') }}" alt="Camera Stream" title="双击切换全屏 (F)" />
            </div>

            <div class="controls">
                <div class="left-controls">
                    <div class="segmented" role="tablist" aria-label="Fit Mode">
                        <button class="seg-btn active" data-fit-btn="cover" onclick="setFit('cover')" aria-selected="true">填满</button>
                        <button class="seg-btn" data-fit-btn="contain" onclick="setFit('contain')">完整</button>
                        <button class="seg-btn" data-fit-btn="fill" onclick="setFit('fill')">拉伸</button>
                    </div>
                    <span class="hint">双击画面或按 F 进入全屏</span>
                </div>
                <div class="right-controls">
                    <button class="btn" onclick="refreshStream()">刷新</button>
                    <button class="btn primary" onclick="toggleFullscreen()">全屏</button>
                </div>
            </div>
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


def _annotate_and_track(frame_bgr: np.ndarray) -> np.ndarray:
    """对图像做人脸检测、识别与标注，返回标注后的BGR图。"""
    global _face_frame_counter
    h, w = frame_bgr.shape[:2]

    if not face_enabled or face_cascade is None:
        return frame_bgr

    # 降频检测以降低CPU占用
    _face_frame_counter = (_face_frame_counter + 1) % 3
    do_detect = (_face_frame_counter == 0)

    try:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    except Exception:
        return frame_bgr

    faces_rects = []
    if do_detect:
        try:
            scale = 0.6
            small = cv2.resize(gray, (max(1, int(w*scale)), max(1, int(h*scale))), interpolation=cv2.INTER_AREA)
            rects = face_cascade.detectMultiScale(small, scaleFactor=1.15, minNeighbors=5, minSize=(50, 50))
            for (x, y, ww, hh) in rects:
                X = int(x/scale); Y = int(y/scale); W = int(ww/scale); H = int(hh/scale)
                pad = int(0.1 * max(W, H))
                X0 = max(0, X - pad); Y0 = max(0, Y - pad)
                X1 = min(w, X + W + pad); Y1 = min(h, Y + H + pad)
                faces_rects.append((X0, Y0, X1 - X0, Y1 - Y0))
        except Exception:
            faces_rects = []

    for (x, y, ww, hh) in faces_rects:
        try:
            roi_gray = gray[y:y+hh, x:x+ww]
            roi_bgr = frame_bgr[y:y+hh, x:x+ww]
            emb = _compute_embedding(roi_gray)
            if emb is None:
                continue
            fid = _update_face_db(roi_bgr, roi_gray, emb)
            cv2.rectangle(frame_bgr, (x, y), (x+ww, y+hh), (0, 200, 255), 2)
            cv2.putText(frame_bgr, f"ID {fid}", (x, max(0, y-8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)
        except Exception:
            continue

    return frame_bgr

def generate_frames():
    """生成MJPEG流帧"""
    # 初始化人脸检测器
    if face_enabled and (face_cascade is None):
        _init_face_detector()
    while True:
        try:
            # 从队列获取最新帧
            frame_data = frame_queue.get(timeout=1.0)
            # 解码、标注后再编码
            npbuf = np.frombuffer(frame_data, dtype=np.uint8)
            frame = cv2.imdecode(npbuf, cv2.IMREAD_COLOR)
            if frame is None:
                out_bytes = frame_data
            else:
                # 人脸检测与标注
                try:
                    out_img = _annotate_and_track(frame)
                except NameError:
                    # 尚未定义标注函数（安全兜底）
                    out_img = frame
                ok, enc = cv2.imencode('.jpg', out_img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                out_bytes = enc.tobytes() if ok else frame_data
            # 构造MJPEG边界
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + out_bytes + b'\r\n')
                   
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
    # 使用新版更简洁的前端模板
    return render_template_string(HTML_TEMPLATE_NEW)

@app.route('/video_feed')
def video_feed():
    """视频流端点"""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/faces')
def faces():
    """返回已识别人脸列表。"""
    with face_lock:
        faces_list = [
            {
                'id': info['id'],
                'first_seen': info['first_seen'],
                'last_seen': info['last_seen'],
                'seen_count': info['seen_count'],
            }
            for info in face_db.values()
        ]
    faces_list.sort(key=lambda x: x['last_seen'], reverse=True)
    return jsonify({'faces': faces_list})

@app.route('/face_thumbnail/<int:face_id>.jpg')
def face_thumbnail(face_id: int):
    with face_lock:
        info = face_db.get(face_id)
        data = info.get('thumb_jpeg') if info else None
    if not data:
        # 返回简单占位图
        img = np.zeros((112, 112, 3), dtype=np.uint8)
        cv2.putText(img, 'N/A', (28, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode('.jpg', img)
        data = buf.tobytes() if ok else b''
    resp = Response(data, mimetype='image/jpeg')
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    return resp

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
        _init_face_detector()
        app.run(host='0.0.0.0', port=args.web_port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n[INFO] 程序已退出")
        return 0
    except Exception as e:
        print(f"[ERROR] Web服务器启动失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
