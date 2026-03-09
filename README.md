# Arducam Mega 5MP w/ ESP32C3

ESP32-C3 + Arducam Mega 5MP camera integration using Arduino and Python. This code is used to test the capture mode of the camera to be deployed inside the CubeSat. Captured images are served via a local HTTP server and viewable in any browser on the same network.

---

## Hardware

- **MCU:** ESP32-C3
- **Camera:** Arducam Mega 5MP (SPI)

### Wiring

| Arducam Mega | ESP32-C3 |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SCK | GPIO 4 |
| MISO | GPIO 5 |
| MOSI | GPIO 6 |
| CS | GPIO 1 |

---

## Repository Structure

```
orbit-arducam-esp32c3/
├── arduino_sketch/         # Arduino sketch for the ESP32-C3
│   ├── full_featured.ino   # Main sketch
│   ├── ArducamLink.cpp     # Serial protocol implementation (modified)
│   ├── ArducamLink.h       # Serial protocol header
│   └── ArducamUart.h       # UART macro definitions
├── arducam_library/        # Full Arducam Mega library (MIT license)
│   ├── src/
│   │   ├── Arducam_Mega.cpp
│   │   ├── Arducam_Mega.h
│   │   └── Arducam/
│   │       ├── ArducamCamera.c
│   │       ├── ArducamCamera.h
│   │       ├── ArducamSpi.cpp  ← patched (see below)
│   │       ├── ArducamSpi.h
│   │       └── ...
│   ├── keywords.txt
│   ├── library.properties
│   └── LICENSE
└── host/
    └── arducam_server.py   # Python HTTP server for triggering captures
```

---

## Setup

### 1. Install Arduino IDE

Download and install [Arduino IDE 2.x](https://www.arduino.cc/en/software) for your platform (version used: 2.3.6).

### 2. Install ESP32 Board Support

1. Open Arduino IDE
2. Go to **File → Preferences**
3. Add the following URL to "Additional boards manager URLs":
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
4. Go to **Tools → Board → Boards Manager**
5. Search `esp32` and install **esp32 by Espressif Systems** (version 3.x or later)
6. Go to **Tools → Board → ESP32 Arduino** and select **ESP32C3 Dev Module**

### 3. Install the Arducam Library

Copy the `arducam_library/` folder from this repository into your Arduino libraries directory:

- **Linux:** `~/Arduino/libraries/Arducam_Mega/`

This should replace any previously installed version of the Arducam Mega library. The library included here contains the patches described below.

### 4. Upload the Sketch

1. Copy the contents of `arduino_sketch/` into a folder named `full_featured`
2. Open `full_featured.ino` in Arduino IDE
3. Connect the ESP32-C3 via USB
4. Select the correct port under **Tools → Port**
5. Click **Upload**

On Linux, if the port is not detected, check:
```bash
ls /dev/ttyUSB*
```
The ESP32-C3 typically appears as `/dev/ttyUSB0` or `/dev/ttyUSB1`. If the port is busy:
```bash
fuser -k /dev/ttyUSB1
```

### 5. Install Python Dependency

`pyserial` is required. On most Linux systems it is already present. If not:
```bash
pip install pyserial
```

---

## Running the HTTP Server

```bash
python3 host/arducam_server.py --serial /dev/ttyUSB1 --baud 921600
```

Open a browser and go to:
```
http://localhost:8080
```

Click **Capture** to trigger an image capture. The image will appear in the browser. Any device on the same local network can also access it at:
```
http://<your-machine-ip>:8080
```

### Options

| Argument | Default | Description |
|---|---|---|
| `--serial` | `/dev/ttyUSB0` | Serial port the ESP32-C3 is connected to |
| `--baud` | `921600` | Baud rate (must match the sketch) |
| `--port` | `8080` | HTTP server port |

---

## Code Changes

### `arducam_library/src/Arducam/ArducamSpi.cpp`

The original library had two `void` functions incorrectly using `return` with a value, which caused a compilation error under the ESP32 toolchain (gcc with `-fpermissive` as error):

```cpp
// Original - causes compilation error
void arducamSpiBegin(void) {
    return SPI.begin();
}

void arducamSpiTransferBlock(uint8_t *buff, uint16_t len) {
    return SPI.transfer(buff, len);
}
```

Fixed by removing the `return` statement:

```cpp
// Fixed
void arducamSpiBegin(void) {
    SPI.begin();
}

void arducamSpiTransferBlock(uint8_t *buff, uint16_t len) {
    SPI.transfer(buff, len);
}
```

### `arduino_sketch/full_featured.ino`

Two changes from the original example:

1. `myUart.println()` does not exist in `ArducamLink`. Changed to `myUart.printf()`:
   ```cpp
   // Original - causes compilation error
   myUart.println("Hello esp32-c3!");

   // Fixed
   myUart.printf("Hello esp32-c3!");
   ```

2. `myCAM.captureThread()` was removed from `loop()`. In the original example this causes the camera to stream data continuously, which interferes with the command/response protocol used by the Python host script:
   ```cpp
   // Commented
   // myCAM.captureThread();
   ```

### `arduino_sketch/full_featured.ino` - Baud Rate

The baud rate was increased from `115200` to `921600` to reduce image transfer time. The Arducam library introduces a 12µs delay per byte in `ArducamLink::arducamUartWrite()`, which limits throughput regardless of baud rate. At the default rate, transferring a 5MP JPEG takes several minutes. At 921600 this is reduced to roughly 30 seconds.

### `host/arducam_server.py`

This file is new and not part of the original Arducam repository. It implements:

- A serial communication layer that sends commands to the ESP32-C3 using the Arducam binary protocol (`0x55 [cmd] [params] 0xAA`)
- Image response parsing: waits for the `0xFF 0xAA 0x01` header, reads until the `0xFF 0xBB` tail
- A resolution/format command sent before each capture: 5MP JPEG (`SET_PICTURE_RESOLUTION`, byte `0x1d`)
- A local HTTP server exposing:
  - `GET /` - browser UI with a Capture button
  - `GET /image.jpg` - latest captured image
  - `POST /capture` - triggers a new capture

---

## Notes

- The camera has a fixed-focus lens. It is optimized for distances beyond approximately 30-50cm. Images captured at very short distances will appear blurry.
- Transfer time per capture is approximately 30 seconds at 921600 baud due to the per-byte delay in the library.
- Only one process can hold the serial port at a time. If the server fails to open the port, check for other processes using it with `fuser /dev/ttyUSB1`.

---

## License

The Arducam Mega library is licensed under the MIT License. See `arducam_library/LICENSE` for details.

The Arduino sketch (`arduino_sketch/`) is derived from the Arducam Mega examples and is also MIT licensed.

`host/arducam_server.py` is original work released under the MIT License.
