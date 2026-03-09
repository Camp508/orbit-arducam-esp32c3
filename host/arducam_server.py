#!/usr/bin/env python3
"""
Arducam Mega - Serial capture + local HTTP server
Usage:
    python3 arducam_server.py [--port PORT] [--serial SERIAL_PORT] [--baud BAUD]

Browse to http://localhost:8080 to view the latest image.
POST to http://localhost:8080/capture to trigger a new capture.
"""

import serial
import struct
import time
import threading
import argparse
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO

# Protocol constants
CMD_START      = 0x55
CMD_END        = 0xAA
CMD_TAKE_PIC   = 0x10
RESP_HEAD      = bytes([0xFF, 0xAA, 0x01])
RESP_TAIL      = bytes([0xFF, 0xBB])

# Resolution + format byte for SET_PICTURE_RESOLUTION (cmd 0x01)
# bits[3:0] = resolution, bits[6:4] = format
# 0 = QVGA, format 0 = JPEG -> byte = 0x00
# Use TAKE_PICTURE (0x10) to shoot with current defaults instead.

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

latest_image = None
image_lock   = threading.Lock()


def send_command(ser, cmd, params=None):
    packet = bytes([CMD_START, cmd])
    if params:
        packet += bytes(params)
    packet += bytes([CMD_END])
    ser.write(packet)
    log.debug(f"Sent: {packet.hex()}")


def read_image(ser, timeout=60.0):
    """
    Wait for and read one image response from the ESP32.
    Returns raw JPEG bytes or None on failure.
    """
    deadline = time.time() + timeout
    buf = bytearray()

    # Accumulate until we see the header
    while time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf.extend(chunk)
        idx = buf.find(RESP_HEAD)
        if idx != -1:
            buf = buf[idx:]
            break
    else:
        log.error("Timeout waiting for image header")
        return None

    # Skip header(3) + length(4) + format(1) = 8 bytes
    # Then read until tail 0xFF 0xBB
    log.info("Header found, reading until tail...")
    while time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf.extend(chunk)
        tail_idx = buf.find(RESP_TAIL, 8)
        if tail_idx != -1:
            image_data = bytes(buf[8:tail_idx])
            log.info(f"Image received: {len(image_data)} bytes")
            return image_data

    log.error(f"Timeout waiting for image tail, got {len(buf)} bytes so far")
    return None

def capture(ser):
    """Trigger capture and return JPEG bytes or None."""
    ser.reset_input_buffer()
    # Set 5MP JPEG: (JPG=0x01 << 4) | (WQXGA2=0x0d) = 0x1d
    send_command(ser, 0x01, [0x1d])
    time.sleep(0.5)
    ser.reset_input_buffer()
    send_command(ser, CMD_TAKE_PIC)
    return read_image(ser)


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        log.info(f"HTTP {self.address_string()} {format % args}")

    def do_GET(self):
        if self.path == '/':
            self._serve_page()
        elif self.path.split('?')[0] == '/image.jpg':
            self._serve_image()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/capture':
            self._trigger_capture()
        else:
            self.send_error(404)

    def _serve_page(self):
        html = b"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Arducam Mega</title>
  <style>
    body { background:#111; color:#eee; font-family:sans-serif; text-align:center; padding:2em; }
    img  { max-width:100%; border:2px solid #444; margin-top:1em; }
    button { padding:0.6em 1.4em; font-size:1em; cursor:pointer; margin-top:1em; }
  </style>
</head>
<body>
  <h2>Arducam Mega - Live Capture</h2>
  <br>
  <button onclick="capture()">Capture</button>
  <br>
  <img id="img" src="/image.jpg" alt="No image yet">
  <script>
    function capture() {
      fetch('/capture', {method:'POST'})
        .then(r => r.text())
        .then(() => {
          document.getElementById('img').src = '/image.jpg?t=' + Date.now();
        });
    }
  </script>
</body>
</html>"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(html))
        self.end_headers()
        self.wfile.write(html)

    def _serve_image(self):
        with image_lock:
            data = latest_image
        if data is None:
            self.send_error(503, 'No image captured yet')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def _trigger_capture(self):
        global latest_image
        log.info("Capture triggered via HTTP")
        img = capture(self.server.serial_port)
        if img:
            with image_lock:
                latest_image = img
            log.info(f"Capture OK: {len(img)} bytes")
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            log.error("Capture failed")
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Capture failed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', default='/dev/ttyUSB1')
    parser.add_argument('--baud',   type=int, default=921600)
    parser.add_argument('--port',   type=int, default=8080)
    args = parser.parse_args()

    log.info(f"Opening serial port {args.serial} at {args.baud} baud")
    ser = serial.Serial(args.serial, args.baud, timeout=2)
    time.sleep(2)  # wait for ESP32 to finish booting
    ser.reset_input_buffer()
    log.info("Serial ready")

    server = HTTPServer(('0.0.0.0', args.port), Handler)
    server.serial_port = ser

    log.info(f"HTTP server at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        ser.close()


if __name__ == '__main__':
    main()
