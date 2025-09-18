#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
TCP 服务器端 Python 显示程序
- 在 PC 上运行，监听指定端口，等待 ESP32 连接
- 从套接字读取连续 JPEG 帧（以 0xFFD8 开始，0xFFD9 结束）
- 使用 OpenCV 实时解码与显示

用法示例（Windows PowerShell）：
    python ./tools/pc_viewer/viewer.py --host 0.0.0.0 --port 8000

按键：
  q  退出
"""
import argparse
import socket
import sys
import time
from typing import Tuple

import cv2
import numpy as np

SOI = b"\xff\xd8"  # JPEG Start Of Image
EOI = b"\xff\xd9"  # JPEG End Of Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ESP32 WiFi Camera PC Viewer (TCP Server)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，需与固件一致，默认 8000")
    parser.add_argument("--window", default="ESP32 Camera", help="显示窗口标题")
    parser.add_argument("--timeout", type=float, default=10.0, help="等待连接超时（秒）")
    return parser.parse_args()


def recv_images(conn: socket.socket, window: str) -> None:
    buf = bytearray()
    last_ts = time.time()
    frames = 0

    conn.settimeout(5.0)
    while True:
        try:
            data = conn.recv(4096)
            if not data:
                print("[INFO] 对端关闭连接")
                break
            buf.extend(data)
        except socket.timeout:
            # 超时不致命，继续等待
            continue
        except ConnectionResetError:
            print("[WARN] 连接被重置")
            break
        except Exception as e:
            print(f"[ERROR] 接收失败: {e}")
            break

        # 丢弃 SOI 之前的冗余
        start = buf.find(SOI)
        if start > 0:
            del buf[:start]
        elif start < 0 and len(buf) > 1024 * 1024:
            # 避免内存无限增长
            buf.clear()
            continue

        # 可能存在多个完整帧，尽量逐个消费
        while True:
            start = buf.find(SOI)
            if start < 0:
                break
            end = buf.find(EOI, start + 2)
            if end < 0:
                break
            end += 2  # 包含 EOI
            frame = bytes(buf[start:end])
            del buf[:end]

            # 解码并显示
            np_frame = np.frombuffer(frame, dtype=np.uint8)
            img = cv2.imdecode(np_frame, cv2.IMREAD_COLOR)
            if img is None:
                # 解码失败，继续
                continue
            cv2.imshow(window, img)
            frames += 1

            # FPS 统计
            now = time.time()
            if now - last_ts >= 1.0:
                fps = frames / (now - last_ts)
                cv2.setWindowTitle(window, f"ESP32 Camera - {fps:.1f} FPS")
                frames = 0
                last_ts = now

            if cv2.waitKey(1) & 0xFF == ord('q'):
                return


def run_server(host: str, port: int, window: str, timeout: float) -> int:
    def _get_default_iface_ip() -> str:
        try:
            tmp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # 不会真正发包，仅用于获知默认路由的本地 IP
            tmp.connect(("8.8.8.8", 80))
            ip = tmp.getsockname()[0]
            tmp.close()
            return ip
        except Exception:
            # 兜底回环地址（仅本机测试用）
            return "127.0.0.1"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except PermissionError as e:
            print(f"[WARN] 绑定 {host}:{port} 失败（权限/安全策略限制）：{e}")
            alt_host = _get_default_iface_ip() if host in ("0.0.0.0", "*") else host
            if alt_host != host:
                try:
                    print(f"[INFO] 尝试使用本机网卡 IP 回退绑定：{alt_host}:{port}")
                    s.bind((alt_host, port))
                    host = alt_host
                except Exception as e2:
                    print("[ERROR] 回退绑定仍失败。建议：\n"
                          "  1) 以管理员方式运行 PowerShell；\n"
                          "  2) 将 --host 指定为你的局域网 IP；\n"
                          "  3) 检查防火墙/杀毒或公司安全策略是否禁止监听端口；\n"
                          "  4) 尝试更换端口（保持与固件一致，默认 8080）。")
                    return 3
            else:
                print("[ERROR] 绑定失败。建议：\n"
                      "  1) 以管理员方式运行 PowerShell；\n"
                      "  2) 将 --host 指定为你的局域网 IP；\n"
                      "  3) 检查防火墙/杀毒或公司安全策略是否禁止监听端口；\n"
                      "  4) 尝试更换端口（保持与固件一致，默认 8080）。")
                return 3
        except OSError as e:
            print(f"[ERROR] 绑定 {host}:{port} 失败：{e}")
            return 3

        s.listen(1)
        s.settimeout(timeout)
        print(f"[INFO] 监听 {host}:{port}，等待 ESP32 连接...")
        try:
            conn, addr = s.accept()
        except socket.timeout:
            print("[ERROR] 等待连接超时，请确认 ESP32 端已将 IP_ADDR 指向本机，并允许出站连接")
            return 2

        print(f"[INFO] 已连接：{addr}")
        with conn:
            try:
                recv_images(conn, window)
            finally:
                cv2.destroyAllWindows()
    return 0


def main() -> int:
    args = parse_args()
    try:
        return run_server(args.host, args.port, args.window, args.timeout)
    except KeyboardInterrupt:
        print("\n[INFO] 已中断")
        return 0


if __name__ == "__main__":
    sys.exit(main())
