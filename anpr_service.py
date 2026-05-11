"""
ANPR WebSocket Server
=====================
Camera se number plate detect karta hai aur port 3003 pe broadcast karta hai.

Install:
    pip install websockets opencv-python easyocr numpy

Run:
    python anpr_service.py
    python anpr_service.py --camera 0          # USB cam index
    python anpr_service.py --camera rtsp://... # IP cam
    python anpr_service.py --port 3003
"""

import asyncio
import json
import re
import time
import argparse
import logging
from datetime import datetime, timezone

import cv2
import numpy as np
import easyocr
import websockets
from websockets.server import serve

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("anpr")

# ── Config ────────────────────────────────────────────────────────────────────
CAMERA_SOURCE  = 0          # 0 = default USB cam, or rtsp://... for IP cam
WS_PORT        = 3003
CAMERA_ID      = "cam_01"
SCAN_INTERVAL  = 0.5        # seconds between scans (don't hammer CPU)
COOLDOWN       = 4.0        # ignore same plate again for N seconds
MIN_CONFIDENCE = 0.50       # discard detections below this

# Pakistan plate pattern examples: ABC-1234, LHR-123, 4567
# Adjust regex for your country's format
PLATE_PATTERN = re.compile(r'^[A-Z]{2,4}[-\s]?\d{2,4}$', re.IGNORECASE)

# ── Shared state ──────────────────────────────────────────────────────────────
connected_clients: set = set()
last_seen: dict = {}          # plate → epoch timestamp (cooldown tracking)

# ── EasyOCR reader (loads once) ───────────────────────────────────────────────
log.info("Loading EasyOCR model — please wait...")
reader = easyocr.Reader(['en'], gpu=False)   # set gpu=True if CUDA available
log.info("EasyOCR ready.")


# ── Image preprocessing ───────────────────────────────────────────────────────

def preprocess(frame: np.ndarray) -> np.ndarray:
    """
    Grayscale + CLAHE contrast boost + adaptive threshold.
    Better OCR accuracy on low-light / blurry plates.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


def find_plate_region(frame: np.ndarray) -> list[tuple]:
    """
    Optional: try to isolate plate-like rectangular regions
    so EasyOCR doesn't have to read the whole frame.
    Returns list of (x, y, w, h) ROIs. Falls back to full frame.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 200)
    contours, _ = cv2.findContours(edged, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    rois = []
    h_frame, w_frame = frame.shape[:2]

    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:20]:
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = w / float(h) if h else 0
        # Plates are roughly 2:1 to 5:1 aspect ratio, not tiny
        if 2.0 <= aspect <= 6.0 and w > 60 and h > 15:
            # Add small padding
            pad = 5
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w_frame, x + w + pad)
            y2 = min(h_frame, y + h + pad)
            rois.append((x1, y1, x2 - x1, y2 - y1))

    return rois or [(0, 0, w_frame, h_frame)]   # full frame fallback


# ── OCR + plate validation ────────────────────────────────────────────────────

def clean_plate(text: str) -> str:
    """Strip noise, uppercase, normalize separators."""
    cleaned = re.sub(r'[^A-Za-z0-9\-]', '', text).upper()
    # Insert dash if format is LETTERS+DIGITS with no separator
    cleaned = re.sub(r'^([A-Z]{2,4})(\d{2,4})$', r'\1-\2', cleaned)
    return cleaned


def is_valid_plate(text: str) -> bool:
    return bool(PLATE_PATTERN.match(text))


def scan_frame(frame: np.ndarray) -> list[dict]:
    """Run OCR on frame, return list of valid plate detections."""
    processed = preprocess(frame)
    rois = find_plate_region(processed)

    detections = []
    seen_in_frame: set = set()

    for (x, y, w, h) in rois:
        roi = processed[y:y+h, x:x+w]
        results = reader.readtext(roi, detail=1, paragraph=False)

        for (bbox_pts, text, conf) in results:
            plate = clean_plate(text)
            if not plate or conf < MIN_CONFIDENCE:
                continue
            if not is_valid_plate(plate):
                continue
            if plate in seen_in_frame:
                continue
            seen_in_frame.add(plate)

            # Convert bbox relative to ROI → full frame coords
            pts = np.array(bbox_pts, dtype=int)
            bx, by, bw, bh = cv2.boundingRect(pts)
            detections.append({
                "plateNumber": plate,
                "confidence": round(conf, 3),
                "bbox": {"x": x + bx, "y": y + by, "w": bw, "h": bh},
            })

    return detections


# ── Cooldown check ────────────────────────────────────────────────────────────

def should_broadcast(plate: str) -> bool:
    now = time.monotonic()
    last = last_seen.get(plate, 0)
    if now - last >= COOLDOWN:
        last_seen[plate] = now
        return True
    return False


# ── WebSocket helpers ─────────────────────────────────────────────────────────

def build_message(plate: str, conf: float, bbox: dict) -> str:
    """
    Build the JSON message plate-receiver.js expects:
    {
      type: 'plateNumber',
      data: {
        plateNumber: 'LHR-1234',
        confidence: 0.94,
        timestamp: '2025-05-08T14:32:01.123Z',
        camera_id: 'cam_01',
        bbox: { x, y, w, h }
      }
    }
    """
    return json.dumps({
        "type": "plateNumber",
        "data": {
            "plateNumber": plate,
            "confidence": conf,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "camera_id": CAMERA_ID,
            "bbox": bbox,
        }
    })


async def broadcast(message: str):
    """Send to all currently connected clients."""
    if not connected_clients:
        return
    dead = set()
    for ws in connected_clients:
        try:
            await ws.send(message)
        except websockets.ConnectionClosed:
            dead.add(ws)
    connected_clients.difference_update(dead)


async def ws_handler(websocket):
    """Called for each new client connection."""
    client = websocket.remote_address
    connected_clients.add(websocket)
    log.info("Client connected: %s  (total: %d)", client, len(connected_clients))
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)
        log.info("Client disconnected: %s  (total: %d)", client, len(connected_clients))


# ── Camera loop ───────────────────────────────────────────────────────────────

async def camera_loop():
    log.info("Opening camera: %s", CAMERA_SOURCE)
    cap = cv2.VideoCapture(CAMERA_SOURCE)

    if not cap.isOpened():
        log.error("Cannot open camera '%s'. Check --camera argument.", CAMERA_SOURCE)
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    log.info("Camera opened. Starting scan loop...")

    loop = asyncio.get_event_loop()

    while True:
        ret, frame = cap.read()
        if not ret:
            log.warning("Frame read failed — retrying in 1s")
            await asyncio.sleep(1)
            continue

        # Run blocking OCR in thread pool so event loop stays responsive
        detections = await loop.run_in_executor(None, scan_frame, frame)

        for det in detections:
            plate = det["plateNumber"]
            if should_broadcast(plate):
                msg = build_message(plate, det["confidence"], det["bbox"])
                log.info("PLATE: %s  conf=%.2f  clients=%d",
                         plate, det["confidence"], len(connected_clients))
                await broadcast(msg)

        await asyncio.sleep(SCAN_INTERVAL)

    cap.release()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    log.info("WebSocket server starting on ws://0.0.0.0:%d", WS_PORT)
    async with serve(ws_handler, "0.0.0.0", WS_PORT):
        log.info("Ready — waiting for clients on port %d", WS_PORT)
        await camera_loop()   # runs forever


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ANPR WebSocket Server")
    parser.add_argument("--camera", default=0,
                        help="Camera index (0) or RTSP URL")
    parser.add_argument("--port", type=int, default=3003)
    parser.add_argument("--camera-id", default="cam_01")
    parser.add_argument("--cooldown", type=float, default=4.0,
                        help="Seconds to suppress duplicate plate detection")
    parser.add_argument("--confidence", type=float, default=0.50,
                        help="Minimum OCR confidence (0.0–1.0)")
    args = parser.parse_args()

    # Apply CLI args to globals
    CAMERA_SOURCE  = int(args.camera) if str(args.camera).isdigit() else args.camera
    WS_PORT        = args.port
    CAMERA_ID      = args.camera_id
    COOLDOWN       = args.cooldown
    MIN_CONFIDENCE = args.confidence

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped.")
