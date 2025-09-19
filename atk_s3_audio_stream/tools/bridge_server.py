#!/usr/bin/env python3
import asyncio
import websockets
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
import os
import struct

# Ports
HTTP_PORT = int(os.getenv('HTTP_PORT', '9000'))
WS_PORT = int(os.getenv('WS_PORT', '9001'))
TCP_PORT = int(os.getenv('TCP_PORT', '9002'))

PCM_MAGIC = 0x304D4350  # 'PCM0'

# Global state
clients = set()  # websocket clients
board_writer = None  # asyncio StreamWriter to ESP32 board (downlink)

async def ws_handler(websocket):
    global board_writer
    clients.add(websocket)
    try:
        async for message in websocket:
            # Expect binary PCM 24k/16bit mono from browser mic; forward to board
            if isinstance(message, (bytes, bytearray)):
                if board_writer is not None:
                    hdr = struct.pack('<IBH', PCM_MAGIC, 0x02, len(message))
                    try:
                        board_writer.write(hdr)
                        board_writer.write(message)
                        await board_writer.drain()
                    except Exception:
                        pass
    finally:
        clients.discard(websocket)

async def ws_server():
    async with websockets.serve(ws_handler, '0.0.0.0', WS_PORT, max_size=None, ping_interval=None):
        print(f"[WS] WebSocket server on ws://0.0.0.0:{WS_PORT}")
        await asyncio.Future()

async def tcp_board_server():
    async def handle_board(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        global board_writer
        peer = writer.get_extra_info('peername')
        print(f"[TCP] Board connected: {peer}")
        board_writer = writer
        # Robust hello detection (read 8 first for HELLO-UP, else try HELLO-DOWN 10 bytes)
        try:
            hello8 = await reader.readexactly(8)
        except asyncio.IncompleteReadError:
            writer.close()
            await writer.wait_closed()
            return

        try:
            if hello8 == b"HELLO-UP":  # uplink connection (from board mic)
                print("[TCP] Uplink channel")
                while True:
                    hdr = await reader.readexactly(7)  # <IBH
                    magic, ptype, length = struct.unpack('<IBH', hdr)
                    if magic != PCM_MAGIC or ptype != 0x01 or length == 0:
                        print(f"[TCP] Bad header magic={magic:x} type={ptype} len={length}")
                        break
                    payload = await reader.readexactly(length)
                    if clients:
                        await asyncio.gather(*(c.send(payload) for c in list(clients)))
            else:
                extra = await reader.readexactly(2)  # to form 10 bytes
                hello10 = hello8 + extra
                if hello10 == b"HELLO-DOWN":  # downlink connection (to board speaker)
                    print("[TCP] Downlink channel")
                    # keep writer globally to forward WS mic to board
                    board_writer = writer
                    # keep connection open
                    while True:
                        await asyncio.sleep(1)
                else:
                    print(f"[TCP] Unknown hello: {hello8 + extra}")
        except asyncio.IncompleteReadError:
            print("[TCP] Board disconnected")
        except Exception as e:
            print(f"[TCP] Error: {e}")
        finally:
            try:
                await writer.drain()
            except Exception:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            if board_writer is writer:
                board_writer = None

    server = await asyncio.start_server(handle_board, '0.0.0.0', TCP_PORT)
    addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f"[TCP] Board TCP server on {addrs}")
    async with server:
        await server.serve_forever()

class SPAHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Serve files from tools/www
        webroot = os.path.join(os.path.dirname(__file__), 'www')
        if path == '/' or path == '':
            path = '/index.html'
        return os.path.join(webroot, path.lstrip('/'))

def http_thread():
    httpd = HTTPServer(('0.0.0.0', HTTP_PORT), SPAHandler)
    print(f"[HTTP] Serving http://0.0.0.0:{HTTP_PORT}")
    httpd.serve_forever()

async def async_main():
    t = threading.Thread(target=http_thread, daemon=True)
    t.start()
    await asyncio.gather(ws_server(), tcp_board_server())

def main():
    asyncio.run(async_main())

if __name__ == '__main__':
    print("Run: python bridge_server.py ; then open http://localhost:9000")
    print("Ports: HTTP 9000, WS 9001, TCP 9002 (configurable via env)")
    main()
