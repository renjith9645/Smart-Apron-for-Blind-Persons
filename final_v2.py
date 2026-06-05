import requests, time, re, threading, queue, winsound
import cv2, pytesseract, os, uuid
from gtts import gTTS
from playsound import playsound
from datetime import datetime, timedelta
from ultralytics import YOLO

# ================= CONFIG =================
ESP_IP = "10.185.241.20"
GAS_DANGER_LEVEL = 300
READ_INTERVAL = 3
ALERT_REPEAT_TIME = 10

DANGER_WAV = "gas_danger.wav"
SAFE_WAV   = "gas_safe.wav"

# ================= YOLO =================
yolo = YOLO("yolov8n.pt")

# ================= CART CLASSES =================
FRUIT_CLASSES = {
    "apple", "banana", "orange", "mango",
    "pineapple", "grape", "watermelon"
}

KITCHEN_CLASSES = {
    "bottle", "cup", "fork", "knife", "spoon",
    "bowl", "plate", "wine glass",
    "microwave", "oven", "toaster",
    "sink", "refrigerator"
}

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

current_frame = None
frame_lock = threading.Lock()

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

# ================= AUDIO =================
def audio_worker():
    while not stop_event.is_set():
        try:
            winsound.PlaySound(
                audio_queue.get(timeout=1),
                winsound.SND_FILENAME
            )
        except queue.Empty:
            pass

# =================================================
# ================= OCR FUNCTIONS (UNCHANGED) =====
# =================================================
def read_text(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11, 2
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

# ================= OCR THREAD =================
def ocr_worker():
    while not stop_event.is_set():
        try:
            frame = ocr_queue.get(timeout=1)
            text = read_text(frame)
            print("\nOCR TEXT:\n", text)

            qty, mrp, mfg, pkd, exp = extract_details(text)
            today = datetime.now()

            base_date = None
            base_label = ""

            if mfg:
                base_date = parse_date(mfg.group(2))
                base_label = "Manufacturing date"
            elif pkd:
                base_date = parse_date(pkd.group(2))
                base_label = "Packed date"

            if not base_date or not exp:
                speak("Date information not complete")
                continue

            if qty:
                speak(f"Net quantity is {qty.group(2)}")

            if mrp:
                speak(f"Maximum retail price is {mrp.group(2)} rupees")

            speak(f"{base_label} is {base_date.strftime('%d %B %Y')}")

            if "DAYS" in exp.group(2):
                days = int(re.search(r"\d+", exp.group(2)).group())
                expiry_date = base_date + timedelta(days=days)
            else:
                expiry_date = parse_date(exp.group(2))

            remaining_days = (expiry_date - today).days

            if remaining_days > 0:
                speak(f"This product is safe to use for {remaining_days} more days")
            else:
                speak("Warning. This product is expired. Do not use")

        except queue.Empty:
            pass

# ================= YOLO THREAD (FRUITS + KITCHEN) =================
def yolo_worker():
    while not stop_event.is_set():
        try:
            frame = yolo_queue.get(timeout=1)
            results = yolo(frame, verbose=False)[0]

            item_count = {}

            for cls in results.boxes.cls:
                name = yolo.names[int(cls)]
                if name in FRUIT_CLASSES or name in KITCHEN_CLASSES:
                    item_count[name] = item_count.get(name, 0) + 1

            if not item_count:
                speak("Empty cart")
            else:
                summary = []
                for item, count in item_count.items():
                    if count == 1:
                        summary.append(f"1 {item}")
                    else:
                        summary.append(f"{count} {item}s")
                speak(", ".join(summary))

        except queue.Empty:
            pass

# ================= CAMERA (ALWAYS ON) =================
def camera_worker():
    global current_frame
    cam = cv2.VideoCapture(0)

    if not cam.isOpened():
        print("❌ Camera not opened")
        stop_event.set()
        return

    while not stop_event.is_set():
        ret, frame = cam.read()
        if ret:
            with frame_lock:
                current_frame = frame.copy()

            cv2.imshow("Live Camera", frame)
            cv2.waitKey(1)

    cam.release()
    cv2.destroyAllWindows()

# ================= ESP FETCH =================
def esp_fetch_worker():
    global gas_value, btn1_count, btn2_count
    s = requests.Session()

    while not stop_event.is_set():
        try:
            html = s.get(f"http://{ESP_IP}/", timeout=5).text

            gas = re.search(r"Gas Value.*?<h1>(\d+)</h1>", html, re.S)
            b1  = re.search(r"Button 1 Count.*?<h1>(\d+)</h1>", html, re.S)
            b2  = re.search(r"Button 2 Count.*?<h1>(\d+)</h1>", html, re.S)

            if gas: gas_value = int(gas.group(1))
            if b1: btn1_count = int(b1.group(1))
            if b2: btn2_count = int(b2.group(1))

        except:
            pass

        time.sleep(READ_INTERVAL)

# ================= MAIN LOGIC =================
def logic_worker():
    global last_btn1, last_btn2
    global gas_danger, last_alert_time

    speak("System ready")

    while not stop_event.is_set():
        now = time.time()

        # ---- GAS ALERT ----
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
            with frame_lock:
                if current_frame is not None:
                    ocr_queue.put(current_frame.copy())
        last_btn1 = btn1_count

        # ---- BUTTON 2 : YOLO ----
        if last_btn2 is not None and btn2_count > last_btn2:
            with frame_lock:
                if current_frame is not None:
                    yolo_queue.put(current_frame.copy())
        last_btn2 = btn2_count

        time.sleep(0.3)

# ================= START =================
try:
    threading.Thread(target=audio_worker, daemon=True).start()
    threading.Thread(target=camera_worker, daemon=True).start()
    threading.Thread(target=ocr_worker, daemon=True).start()
    threading.Thread(target=yolo_worker, daemon=True).start()
    threading.Thread(target=esp_fetch_worker, daemon=True).start()
    threading.Thread(target=logic_worker, daemon=True).start()

    while True:
        time.sleep(1)

except KeyboardInterrupt:
    stop_event.set()
    print("Stopped cleanly")
