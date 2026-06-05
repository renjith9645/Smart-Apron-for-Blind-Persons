import requests, time, re, threading, queue, winsound
import cv2, pytesseract, os, uuid
from gtts import gTTS
from playsound import playsound
from datetime import datetime, timedelta
from ultralytics import YOLO

# ================= CONFIG =================
ESP_IP = "192.168.94.94"
GAS_DANGER_LEVEL = 300
READ_INTERVAL = 3
ALERT_REPEAT_TIME = 10

# ================= WAV FILES =================
DANGER_WAV = "gas_danger.wav"
SAFE_WAV   = "gas_safe.wav"

# ================= YOLO =================
yolo = YOLO("yolov8n.pt")

# ================= TESSERACT =================
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# ================= SHARED STATE =================
gas_value = None
btn1_count = None
btn2_count = None
last_btn1 = None
last_btn2 = None

gas_danger = False
last_alert_time = 0

camera_open = False
cam = None
current_frame = None
camera_mode = None   # "OCR" or "YOLO"

audio_queue = queue.Queue()
ocr_queue = queue.Queue()
yolo_queue = queue.Queue()
stop_event = threading.Event()

# ================= SPEAK =================
def speak(text):
    if not text.strip():
        return
    f = f"speech_{uuid.uuid4()}.mp3"
    gTTS(text=text, lang="en").save(f)
    playsound(f)
    os.remove(f)

# ================= GAS AUDIO =================
def audio_worker():
    while not stop_event.is_set():
        try:
            winsound.PlaySound(audio_queue.get(timeout=1), winsound.SND_FILENAME)
        except queue.Empty:
            continue

# ================= OCR (UNCHANGED) =================
def read_text(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    return pytesseract.image_to_string(thresh, config="--psm 6").upper()

def parse_date(date_str):
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(date_str, fmt)
        except:
            pass
    return None

def extract_details(text):
    qty = re.search(r"(NET QTY|NET QUANTITY).*?(\d+\s?(ML|G|KG|L))", text)
    mrp = re.search(r"(MRP|RS\.?)\s*[:\-]?\s*(\d+)", text)
    mfg = re.search(r"(MFG|MFD).*?(\d{2}[/-]\d{2}[/-]\d{4})", text)
    pkd = re.search(r"(PKD|PACKED).*?(\d{2}[/-]\d{2}[/-]\d{4})", text)
    exp = re.search(r"(BEST BEFORE|EXP).*?(\d+\s*DAYS|\d{2}[/-]\d{2}[/-]\d{4})", text)
    return qty, mrp, mfg, pkd, exp

# ================= CAMERA PREVIEW =================
def camera_preview_worker():
    global current_frame
    while not stop_event.is_set():
        if camera_open and cam:
            ret, frame = cam.read()
            if ret:
                current_frame = frame
                cv2.imshow(f"{camera_mode} Camera Preview", frame)
                cv2.waitKey(1)
        else:
            cv2.destroyAllWindows()
            time.sleep(0.1)

# ================= OCR WORKER =================
def ocr_worker():
    while not stop_event.is_set():
        try:
            frame = ocr_queue.get(timeout=1)
            text = read_text(frame)
            print("\nOCR TEXT:\n", text)
            speak(text if text.strip() else "No text detected")
        except queue.Empty:
            continue

# ================= YOLO WORKER =================
def yolo_worker():
    while not stop_event.is_set():
        try:
            frame = yolo_queue.get(timeout=1)
            results = yolo(frame, verbose=False)[0]
            names = set(yolo.names[int(cls)] for cls in results.boxes.cls)
            speak("Detected " + ", ".join(names) if names else "No objects detected")
        except queue.Empty:
            continue

# ================= ESP FETCH =================
def esp_fetch_worker():
    global gas_value, btn1_count, btn2_count
    s = requests.Session()
    while not stop_event.is_set():
        try:
            html = s.get(f"http://{ESP_IP}/", timeout=6).text
            gas = re.search(r"Gas Value.*?<h1>(\d+)</h1>", html, re.S)
            b1  = re.search(r"Button 1 Count.*?<h1>(\d+)</h1>", html, re.S)
            b2  = re.search(r"Button 2 Count.*?<h1>(\d+)</h1>", html, re.S)
            if gas: gas_value = int(gas.group(1))
            if b1: btn1_count = int(b1.group(1))
            if b2: btn2_count = int(b2.group(1))
        except:
            pass
        time.sleep(READ_INTERVAL)

# ================= LOGIC =================
def logic_worker():
    global cam, camera_open, camera_mode
    global last_btn1, last_btn2, gas_danger, last_alert_time

    speak("System ready")

    while not stop_event.is_set():
        now = time.time()

        # ---- GAS ----
        if gas_value is not None:
            if gas_value > GAS_DANGER_LEVEL:
                if not gas_danger or (now - last_alert_time) > ALERT_REPEAT_TIME:
                    audio_queue.put(DANGER_WAV)
                    gas_danger = True
                    last_alert_time = now
            else:
                if gas_danger:
                    audio_queue.put(SAFE_WAV)
                    gas_danger = False

        # ---- BUTTON 1 : OCR ----
        if last_btn1 is not None and btn1_count > last_btn1:
            if btn1_count % 2 == 1:
                cam = cv2.VideoCapture(0)
                camera_open = True
                camera_mode = "OCR"
            else:
                camera_open = False
                cam.release()
                if current_frame is not None:
                    ocr_queue.put(current_frame.copy())
        last_btn1 = btn1_count

        # ---- BUTTON 2 : YOLO ----
        if last_btn2 is not None and btn2_count > last_btn2:
            if btn2_count % 2 == 1:
                cam = cv2.VideoCapture(0)
                camera_open = True
                camera_mode = "YOLO"
            else:
                camera_open = False
                cam.release()
                if current_frame is not None:
                    yolo_queue.put(current_frame.copy())
        last_btn2 = btn2_count

        time.sleep(1)

# ================= MAIN =================
try:
    threading.Thread(target=audio_worker, daemon=True).start()
    threading.Thread(target=camera_preview_worker, daemon=True).start()
    threading.Thread(target=ocr_worker, daemon=True).start()
    threading.Thread(target=yolo_worker, daemon=True).start()
    threading.Thread(target=esp_fetch_worker, daemon=True).start()
    threading.Thread(target=logic_worker, daemon=True).start()

    while True:
        time.sleep(1)

except KeyboardInterrupt:
    stop_event.set()
    cv2.destroyAllWindows()
    print("Stopped cleanly")
