# ATK-DNESP32S3 Two-way Audio Stream (Standalone ESP-IDF Project)

This is a self-contained ESP-IDF project that reuses the ES8388 audio codec wrapper from the main repo to stream audio between the ATK-DNESP32S3 board and a web page via a Python bridge.

- Uplink: Board microphone -> Python server -> Web page playback
- Downlink: Web page microphone -> Python server -> Board speaker

## Layout
- `components/audio/` — Minimal copy of `audio_codec` and `es8388_audio_codec` used in this repo
- `main/` — Wi‑Fi, TCP client, and audio stream tasks
- `tools/bridge_server.py` — Python async server (HTTP + WebSocket + TCP bridge)
- `tools/www/index.html` — Web UI

## Prerequisites
- ESP-IDF 5.4+
- Python 3.8+
- `pip install websockets`

## Configure and Build
```
cd atk_s3_audio_stream
idf.py set-target esp32s3
idf.py menuconfig   # Set WiFi SSID/PASSWORD and PC server host/port
idf.py build flash monitor
```

Menuconfig entries:
- `atk_s3_audio_stream -> WiFi SSID`
- `atk_s3_audio_stream -> WiFi Password`
- `atk_s3_audio_stream -> Stream server host (PC IP)` (default 192.168.1.2)
- `atk_s3_audio_stream -> Stream server TCP port` (default 9002)

## Run the Python Bridge
In a terminal on your PC:
```
cd atk_s3_audio_stream/tools
python bridge_server.py
# HTTP: 9000, WS: 9001, TCP: 9002
```
Open http://localhost:9000 in a browser.

- Click “Connect WS” to connect the web UI to the Python server.
- Click “Start Mic” to stream your browser mic to the board speaker.
- You should hear the board mic audio in the web page.

## Notes
- The board streams raw PCM 16-bit mono at 24000 Hz. The web page performs simple 2:1 up/down sampling.
- If you need better quality, replace the naive resampling with an AudioWorklet resampler or add server-side resampling.
- Pins and sample rates are set for ATK-DNESP32S3 (MCLK=GPIO3, BCLK=46, WS=9, DOUT=10, DIN=14; I2C SDA=41, SCL=42).

## Troubleshooting
- If you don’t hear anything:
  - Ensure board and PC are on the same network; set correct `Stream server host`.
  - Check Python output for board connection on TCP 9002.
  - Make sure the browser granted mic permissions.

