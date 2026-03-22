# """
# CardScan - app.py
# =================
# Flask + EasyOCR card scanner.
# Runs over HTTPS so phone browsers allow camera/gallery access.

# SETUP (one time):
#     pip install flask easyocr pillow opencv-python-headless numpy pyopenssl

# RUN:
#     python app.py

# Open the HTTPS URL printed in terminal on your phone browser.
# Accept the "unsafe certificate" warning once — it is safe, it is
# just a local self-signed certificate.
# """

# import os, re, json, uuid, base64, socket
# from io import BytesIO
# from pathlib import Path

# # ── Resolve paths relative to this file ──────────────────────────────
# THIS_FILE    = Path(os.path.abspath(__file__))
# BASE_DIR     = THIS_FILE.parent
# TEMPLATE_DIR = BASE_DIR / "templates"
# STATIC_DIR   = BASE_DIR / "static"
# UPLOAD_DIR   = BASE_DIR / "uploads"
# DATA_FILE    = BASE_DIR / "data" / "cards.json"

# UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

# # ── Startup path check ────────────────────────────────────────────────
# print("\n" + "="*60)
# print("  PATHS CHECK")
# print(f"  app.py     : {THIS_FILE}")
# print(f"  templates/ : {TEMPLATE_DIR}  {'OK' if TEMPLATE_DIR.exists() else 'MISSING!'}")
# print(f"  static/    : {STATIC_DIR}  {'OK' if STATIC_DIR.exists() else 'MISSING!'}")
# print("="*60 + "\n")

# if not TEMPLATE_DIR.exists():
#     raise RuntimeError(
#         f"\n\nERROR: templates/ folder NOT FOUND at:\n   {TEMPLATE_DIR}\n\n"
#         f"Required structure:\n"
#         f"   {BASE_DIR}\\\n"
#         f"   ├── app.py\n"
#         f"   ├── templates\\\n"
#         f"   │   └── index.html\n"
#         f"   └── static\\\n"
#         f"       ├── css\\style.css\n"
#         f"       └── js\\app.js\n"
#     )

# # ── Flask ─────────────────────────────────────────────────────────────
# from flask import Flask, render_template, request, jsonify
# from PIL import Image, ImageEnhance, ImageFilter
# import numpy as np
# import easyocr

# app = Flask(
#     __name__,
#     template_folder=str(TEMPLATE_DIR),
#     static_folder=str(STATIC_DIR),
# )
# app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

# # ── EasyOCR ───────────────────────────────────────────────────────────
# print("Loading EasyOCR... (first run downloads ~100 MB, cached after)")
# reader = easyocr.Reader(["en"], gpu=False, verbose=False)
# print("EasyOCR ready!\n")


# # ═════════════════════════════════════════════════════════════════════
# #  SELF-SIGNED SSL CERTIFICATE (needed for mobile camera/file access)
# # ═════════════════════════════════════════════════════════════════════

# def get_ssl_context():
#     """
#     Create or reuse a self-signed SSL cert so the app runs over HTTPS.
#     Mobile browsers require HTTPS to allow camera and file picker access
#     when connecting from a non-localhost address.
#     """
#     cert_file = BASE_DIR / "cert.pem"
#     key_file  = BASE_DIR / "key.pem"

#     if cert_file.exists() and key_file.exists():
#         print("Using existing SSL certificate.")
#         return (str(cert_file), str(key_file))

#     print("Generating self-signed SSL certificate...")
#     try:
#         from OpenSSL import crypto
#         k = crypto.PKey()
#         k.generate_key(crypto.TYPE_RSA, 2048)
#         cert = crypto.X509()
#         cert.get_subject().C  = "IN"
#         cert.get_subject().ST = "Local"
#         cert.get_subject().L  = "Local"
#         cert.get_subject().O  = "CardScan"
#         cert.get_subject().CN = "localhost"
#         cert.set_serial_number(1000)
#         cert.gmtime_adj_notBefore(0)
#         cert.gmtime_adj_notAfter(365 * 24 * 60 * 60)
#         cert.set_issuer(cert.get_subject())
#         cert.set_pubkey(k)
#         cert.sign(k, "sha256")
#         cert_file.write_bytes(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
#         key_file.write_bytes(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
#         print("SSL certificate created.")
#         return (str(cert_file), str(key_file))
#     except ImportError:
#         print("\nWARNING: pyopenssl not installed. Running on HTTP.")
#         print("Gallery/camera may not work on phone over HTTP.")
#         print("Install with: pip install pyopenssl\n")
#         return None


# # ═════════════════════════════════════════════════════════════════════
# #  IMAGE PRE-PROCESSING
# # ═════════════════════════════════════════════════════════════════════

# def preprocess(pil_img):
#     if pil_img.mode != "RGB":
#         pil_img = pil_img.convert("RGB")
#     # Scale up small images so digits are larger and clearer
#     w, h = pil_img.size
#     if max(w, h) < 1200:
#         s = 1200 / max(w, h)
#         pil_img = pil_img.resize((int(w*s), int(h*s)), Image.LANCZOS)
#     # Contrast boost helps EasyOCR separate digits from background
#     pil_img = ImageEnhance.Contrast(pil_img).enhance(1.8)
#     pil_img = ImageEnhance.Sharpness(pil_img).enhance(2.5)
#     pil_img = pil_img.filter(ImageFilter.SHARPEN)
#     pil_img = pil_img.filter(ImageFilter.SHARPEN)  # double sharpen for text edges
#     return np.array(pil_img)


# # ═════════════════════════════════════════════════════════════════════
# #  SMART TEXT PARSER
# # ═════════════════════════════════════════════════════════════════════

# def extract_phones(lines, raw):
#     """
#     Multi-strategy phone extraction.
#     Handles Indian (+91), international, and OCR-mangled numbers.
#     Returns list of clean phone strings, most likely first.
#     """
#     found = []

#     # ── Strategy 1: lines that are labelled as phone ──────────────
#     # e.g.  "Tel: 98765 43210"  /  "Mob: +91-9876543210"
#     label_rx = re.compile(
#         r"(?:tel|ph|phone|mob|mobile|cell|contact|call|whatsapp|helpline)"
#         r"[\s:.\-]*([+\d][\d\s\(\)\-\.]{6,20})",
#         re.I,
#     )
#     for line in lines:
#         m = label_rx.search(line)
#         if m:
#             candidate = m.group(1).strip()
#             digits    = re.sub(r"\D", "", candidate)
#             if 7 <= len(digits) <= 15:
#                 found.append(candidate)

#     # ── Strategy 2: lines that are MOSTLY digits (standalone number lines) ──
#     # EasyOCR often isolates a phone number as its own text block
#     for line in lines:
#         # Strip common OCR artefacts around numbers
#         cleaned = re.sub(r"[^\d\s+\-().]+", " ", line).strip()
#         digits  = re.sub(r"\D", "", cleaned)
#         # A line that contains 8-15 digits and little else is a phone number
#         if 8 <= len(digits) <= 15 and len(digits) >= len(line.replace(" ", "")) * 0.55:
#             found.append(line.strip())

#     # ── Strategy 3: broad regex scan on full raw text ─────────────
#     # Covers +91-XXXXX-XXXXX, (022) 12345678, 1800-XXX-XXXX etc.
#     broad_patterns = [
#         # Indian mobile with country code variations
#         r"(?:\+91|0091|91)?[\s\-]?[6-9]\d{9}",
#         # Generic international
#         r"\+?\d{1,3}[\s\-]?\(?\d{2,5}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,5}",
#         # Plain 10-digit run
#         r"\b[6-9]\d{9}\b",
#         # Landline with STD code
#         r"\b0\d{2,5}[\s\-]?\d{6,8}\b",
#     ]
#     for pat in broad_patterns:
#         for m in re.finditer(pat, raw):
#             candidate = m.group().strip()
#             digits    = re.sub(r"\D", "", candidate)
#             if 7 <= len(digits) <= 15:
#                 found.append(candidate)

#     # ── Strategy 4: fix common OCR digit confusions and retry ─────
#     # O→0, I→1, l→1, S→5, B→8, Z→2, G→6
#     ocr_fixed = raw
#     for wrong, right in [("O","0"),("o","0"),("I","1"),("l","1"),
#                           ("S","5"),("B","8"),("Z","2"),("G","6")]:
#         ocr_fixed = ocr_fixed.replace(wrong, right)
#     if ocr_fixed != raw:
#         for m in re.finditer(r"\b[6-9]\d{9}\b", ocr_fixed):
#             candidate = m.group().strip()
#             if re.sub(r"\D","",candidate) not in [re.sub(r"\D","",f) for f in found]:
#                 found.append(candidate)

#     # ── Deduplicate by digit content, keep longest / most formatted ──
#     seen_digits = {}
#     for f in found:
#         d = re.sub(r"\D", "", f)
#         if d not in seen_digits:
#             seen_digits[d] = f
#         else:
#             # Prefer the more formatted version (has dashes/spaces)
#             if len(f) > len(seen_digits[d]):
#                 seen_digits[d] = f

#     # Sort: prefer 10-digit Indian mobiles, then by length
#     results_list = list(seen_digits.values())
#     results_list.sort(key=lambda x: (
#         0 if 10 <= len(re.sub(r"\D","",x)) <= 13 else 1,
#         -len(x)
#     ))
#     return results_list


# def parse_card(results):
#     sorted_r = sorted(results, key=lambda r: (r[0][0][1] + r[0][2][1]) / 2)
#     lines    = [r[1].strip() for r in sorted_r if r[2] > 0.25 and r[1].strip()]
#     raw      = "\n".join(lines)

#     # Phone — use multi-strategy extractor
#     all_phones = extract_phones(lines, raw)
#     phone = all_phones[0] if all_phones else ""
#     # If multiple numbers found, join them (e.g. office + mobile)
#     if len(all_phones) > 1:
#         phone = " / ".join(all_phones[:3])  # max 3 numbers

#     # Email
#     emails  = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", raw)
#     email   = emails[0] if emails else ""

#     # Website
#     webs    = re.findall(r"(?:https?://|www\.)[^\s,;)>\"'\]]+", raw, re.I)
#     website = webs[0].rstrip(".,)") if webs else ""
#     if not website:
#         b = re.search(r"\b([a-zA-Z0-9\-]+\.(?:com|in|co\.in|org|net|io|ai|app|dev|biz))\b", raw, re.I)
#         website = b.group() if b else ""

#     # Social
#     handles  = re.findall(r"@[A-Za-z0-9_.]{2,}", raw)
#     linkedin = re.findall(r"linkedin\.com/in/[A-Za-z0-9_\-]+", raw, re.I)
#     social   = ", ".join(list(dict.fromkeys(handles + linkedin)))

#     # Address
#     addr_kw = re.compile(
#         r"\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|drive|dr\.?|"
#         r"boulevard|blvd|nagar|colony|sector|phase|plot|flat|floor|building|"
#         r"tower|near|opp\.?|dist\.?|pin|zip|state|city|village|town|"
#         r"mumbai|delhi|bangalore|bengaluru|chennai|hyderabad|pune|kolkata|"
#         r"gujarat|maharashtra|karnataka|rajasthan|tamil|pradesh)\b", re.I)
#     pin_rx     = re.compile(r"\b\d{6}\b")
#     addr_lines = [l for l in lines if addr_kw.search(l) or pin_rx.search(l)]
#     address    = ", ".join(addr_lines)

#     # Clean lines
#     used = {v.strip() for v in [phone, email, website] + handles + linkedin + addr_lines if v}
#     clean = [
#         l for l in lines
#         if not any(u in l for u in used if len(u) > 3)
#         and not re.match(r"^(tel|ph|phone|mob|fax|email|www|http)[\s:\-]", l, re.I)
#         and len(l) > 1
#     ]

#     # Card type
#     ct = "Business Card"
#     if re.search(r"happy birthday|congratulations|best wishes|with love|dear\s|warm wishes|greetings from", raw, re.I):
#         ct = "Greeting Card"
#     elif re.search(r"\binvitation\b|you are invited|rsvp|cordially|wedding|reception", raw, re.I):
#         ct = "Invitation"
#     elif re.search(r"\bid card\b|\bidentity card\b|\bemployee id\b|\bstudent id\b", raw, re.I):
#         ct = "ID Card"
#     elif not phone and not email and len(clean) < 4:
#         ct = "Personal Card"

#     comp_kw  = re.compile(r"\b(pvt|ltd|llc|inc|corp|co\.|company|technologies|tech|solutions|services|industries|enterprises|group|associates|consultancy|studio|agency|hospital|school|college|university|institute|labs|systems|ventures|global|international|india)\b", re.I)
#     title_kw = re.compile(r"\b(manager|director|ceo|cto|cfo|coo|vp|vice president|founder|co-founder|engineer|developer|designer|consultant|executive|officer|president|head|lead|architect|analyst|associate|specialist|coordinator|advisor|professor|proprietor|partner|principal|owner|dr\.|md|phd|intern|trainee|senior|junior)\b", re.I)

#     name = ""
#     for l in clean:
#         wds = l.split()
#         if (2 <= len(wds) <= 5 and not re.search(r"\d", l)
#                 and not comp_kw.search(l) and not title_kw.search(l)
#                 and sum(1 for w in wds if w[0].isupper()) >= max(1, len(wds)-1)):
#             name = l; break
#     if not name and clean:
#         name = clean[0]

#     title   = next((l for l in clean if title_kw.search(l) and l != name), "")
#     company = next((l for l in clean if comp_kw.search(l) and l not in {name, title}), "")
#     notes   = ""
#     if ct in ("Greeting Card", "Invitation"):
#         notes = " ".join(l for l in clean if l not in {name, title, company})

#     return {
#         "cardType":    ct,
#         "name":        name.strip(),
#         "title":       title.strip(),
#         "company":     company.strip(),
#         "phone":       phone.strip(),
#         "email":       email.strip(),
#         "website":     website.strip(),
#         "address":     address.strip(),
#         "socialMedia": social.strip(),
#         "notes":       notes.strip(),
#         "rawText":     raw.strip(),
#     }


# # ═════════════════════════════════════════════════════════════════════
# #  CARD STORAGE
# # ═════════════════════════════════════════════════════════════════════

# def load_cards():
#     if DATA_FILE.exists():
#         try:
#             return json.loads(DATA_FILE.read_text(encoding="utf-8"))
#         except Exception:
#             return []
#     return []

# def save_cards(cards):
#     DATA_FILE.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")


# # ═════════════════════════════════════════════════════════════════════
# #  ROUTES
# # ═════════════════════════════════════════════════════════════════════

# @app.route("/")
# def index():
#     return render_template("index.html")


# @app.route("/scan", methods=["POST"])
# def scan():
#     pil_img = None
#     if "image" in request.files:
#         pil_img = Image.open(request.files["image"].stream)
#     elif request.is_json and "imageData" in request.json:
#         data = request.json["imageData"]
#         if "," in data:
#             data = data.split(",", 1)[1]
#         pil_img = Image.open(BytesIO(base64.b64decode(data)))
#     else:
#         return jsonify({"error": "No image provided"}), 400
#     try:
#         arr = preprocess(pil_img)
#         # Run OCR twice: once normal, once with digit-friendly settings
#         results1 = reader.readtext(arr, detail=1, paragraph=False)
#         results2 = reader.readtext(
#             arr, detail=1, paragraph=False,
#             allowlist="0123456789+()-. ",  # digit-focused pass
#             low_text=0.3,
#         )
#         # Merge: keep all results, parser will deduplicate
#         results = results1 + [r for r in results2 if r[2] > 0.4]
#         data    = parse_card(results)
#         return jsonify({"success": True, "data": data})
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500


# @app.route("/cards", methods=["GET"])
# def get_cards():
#     return jsonify(load_cards())


# @app.route("/cards", methods=["POST"])
# def add_card():
#     card = request.json
#     if not card:
#         return jsonify({"error": "No data"}), 400
#     card["id"] = str(uuid.uuid4())
#     cards = load_cards()
#     cards.insert(0, card)
#     save_cards(cards)
#     return jsonify({"success": True, "card": card})


# @app.route("/cards/<card_id>", methods=["DELETE"])
# def delete_card(card_id):
#     cards = [c for c in load_cards() if c.get("id") != card_id]
#     save_cards(cards)
#     return jsonify({"success": True})


# # ═════════════════════════════════════════════════════════════════════
# #  START
# # ═════════════════════════════════════════════════════════════════════

# if __name__ == "__main__":
#     try:
#         local_ip = socket.gethostbyname(socket.gethostname())
#     except Exception:
#         local_ip = "127.0.0.1"

#     ssl_ctx = get_ssl_context()
#     scheme  = "https" if ssl_ctx else "http"

#     print("\n" + "="*60)
#     print("  CardScan is running!")
#     print(f"  PC    : {scheme}://127.0.0.1:5000")
#     print(f"  PHONE : {scheme}://{local_ip}:5000  <- open this on phone")
#     print()
#     if ssl_ctx:
#         print("  NOTE: Your phone browser will show a security warning.")
#         print("  Tap 'Advanced' -> 'Proceed' (or 'Accept Risk') once.")
#         print("  This is safe — it is just a local self-signed certificate.")
#     else:
#         print("  Running HTTP — install pyopenssl for HTTPS (better mobile support):")
#         print("  pip install pyopenssl")
#     print("  Phone and PC must be on the SAME WiFi network.")
#     print("="*60 + "\n")

#     app.run(
#         host="0.0.0.0",
#         port=5000,
#         debug=False,
#         ssl_context=ssl_ctx if ssl_ctx else None,
#     ) 


# main1
"""
CardScan - app.py
=================
Flask + EasyOCR card scanner with OpenCV preprocessing.

SETUP:
    pip install flask easyocr pillow opencv-python numpy pyopenssl

RUN:
    python app.py

Open the HTTPS URL on your phone (same WiFi).
Accept the one-time "unsafe certificate" warning — it is a local
self-signed cert and completely safe.
"""

import os, re, json, uuid, base64, socket
from io import BytesIO
from pathlib import Path
from copy import deepcopy

# ── Resolve paths ─────────────────────────────────────────────────────
THIS_FILE    = Path(os.path.abspath(__file__))
BASE_DIR     = THIS_FILE.parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR   = BASE_DIR / "static"
UPLOAD_DIR   = BASE_DIR / "uploads"
DATA_FILE    = BASE_DIR / "data" / "cards.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

# ── Startup check ─────────────────────────────────────────────────────
print("\n" + "="*60)
print(f"  app.py     : {THIS_FILE}")
print(f"  templates/ : {'OK' if TEMPLATE_DIR.exists() else 'MISSING!'}")
print(f"  static/    : {'OK' if STATIC_DIR.exists() else 'MISSING!'}")
print("="*60 + "\n")

if not TEMPLATE_DIR.exists():
    raise RuntimeError(
        f"templates/ folder missing at {TEMPLATE_DIR}\n"
        "Put index.html inside a 'templates' folder next to app.py"
    )

# ── Imports ───────────────────────────────────────────────────────────
from flask import Flask, render_template, request, jsonify
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import numpy as np
import cv2
import easyocr

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

print("Loading EasyOCR... (first run ~100 MB download, cached after)")
reader = easyocr.Reader(["en"], gpu=False, verbose=False)
print("EasyOCR ready!\n")


# ═════════════════════════════════════════════════════════════════════
#  SSL  (HTTPS is required for camera/file access on mobile)
# ═════════════════════════════════════════════════════════════════════

def get_ssl_context():
    cert_f = BASE_DIR / "cert.pem"
    key_f  = BASE_DIR / "key.pem"
    if cert_f.exists() and key_f.exists():
        return (str(cert_f), str(key_f))
    try:
        from OpenSSL import crypto
        k = crypto.PKey()
        k.generate_key(crypto.TYPE_RSA, 2048)
        c = crypto.X509()
        c.get_subject().CN = "cardscan.local"
        c.set_serial_number(1001)
        c.gmtime_adj_notBefore(0)
        c.gmtime_adj_notAfter(730 * 86400)
        c.set_issuer(c.get_subject())
        c.set_pubkey(k)
        c.sign(k, "sha256")
        cert_f.write_bytes(crypto.dump_certificate(crypto.FILETYPE_PEM, c))
        key_f.write_bytes(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
        print("SSL certificate generated.")
        return (str(cert_f), str(key_f))
    except ImportError:
        print("WARNING: pyopenssl missing — running HTTP (install: pip install pyopenssl)")
        return None


# ═════════════════════════════════════════════════════════════════════
#  IMAGE PRE-PROCESSING
#
#  Goal: give EasyOCR the clearest possible image.
#  Pipeline:
#    1. Upscale  — ensure long edge >= 1800px for camera shots
#    2. Denoise  — remove camera noise (NL Means)
#    3. Deskew   — straighten slightly tilted cards
#    4. Adaptive threshold — convert to clean black/white
#    5. Morphology — thicken thin strokes (helps thin fonts)
#
#  We return BOTH the enhanced colour image AND the B&W version and
#  run OCR on both, then merge results.
# ═════════════════════════════════════════════════════════════════════

def pil_to_cv(pil_img):
    return cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)

def cv_to_pil(cv_img):
    return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))


def upscale(img_bgr, min_long_edge=1800):
    h, w = img_bgr.shape[:2]
    long_edge = max(h, w)
    if long_edge < min_long_edge:
        scale = min_long_edge / long_edge
        img_bgr = cv2.resize(
            img_bgr,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_CUBIC,
        )
    return img_bgr


def denoise(img_bgr):
    """Fast NL-Means denoising — removes camera grain without blurring text."""
    return cv2.fastNlMeansDenoisingColored(img_bgr, None, 6, 6, 7, 21)


def deskew(img_bgr):
    """Detect and correct slight rotation using Hough line transform."""
    gray  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 200)
    if lines is None:
        return img_bgr
    angles = []
    for line in lines[:20]:
        rho, theta = line[0]
        angle = (theta - np.pi / 2) * 180 / np.pi
        if abs(angle) < 15:           # only small corrections
            angles.append(angle)
    if not angles:
        return img_bgr
    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.5:       # not worth rotating
        return img_bgr
    h, w = img_bgr.shape[:2]
    M   = cv2.getRotationMatrix2D((w / 2, h / 2), median_angle, 1.0)
    return cv2.warpAffine(img_bgr, M, (w, h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def enhance_colour(img_bgr):
    """Boost contrast and sharpness on the colour image."""
    pil = cv_to_pil(img_bgr)
    pil = ImageEnhance.Contrast(pil).enhance(1.7)
    pil = ImageEnhance.Sharpness(pil).enhance(2.5)
    pil = pil.filter(ImageFilter.SHARPEN)
    return pil_to_cv(pil)


def make_bw(img_bgr):
    """
    Convert to a clean black-on-white binary image.
    Adaptive threshold handles uneven lighting (common in camera shots).
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # CLAHE improves contrast before thresholding
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray  = clahe.apply(gray)
    bw    = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        21, 10,
    )
    # Thicken thin strokes so OCR reads them better
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    bw     = cv2.dilate(bw, kernel, iterations=1)
    # Convert B&W back to 3-channel so EasyOCR is happy
    return cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)


def preprocess_all(pil_img):
    """
    Returns a list of numpy arrays to run OCR on.
    Multiple versions improve recall — one may capture what another misses.
    """
    img  = pil_to_cv(pil_img)
    img  = upscale(img)
    img  = denoise(img)
    img  = deskew(img)

    colour = enhance_colour(img)
    bw     = make_bw(colour)

    return [colour, bw]   # [colour array, B&W array]


# ═════════════════════════════════════════════════════════════════════
#  OCR  — run EasyOCR on multiple image versions and merge
# ═════════════════════════════════════════════════════════════════════

def run_ocr(pil_img):
    """
    Run OCR on colour + B&W versions, plus a digit-only pass.
    Merge all results, deduplicate by position proximity.
    Returns sorted list of (bbox, text, conf).
    """
    images = preprocess_all(pil_img)
    all_results = []

    for img_arr in images:
        # Full text pass
        r = reader.readtext(img_arr, detail=1, paragraph=False,
                            min_size=10, text_threshold=0.5,
                            low_text=0.3, link_threshold=0.4)
        all_results.extend(r)
        # Digit-focused pass (helps with phone numbers on camera shots)
        r2 = reader.readtext(img_arr, detail=1, paragraph=False,
                             allowlist="0123456789+()-. /",
                             min_size=10, text_threshold=0.4,
                             low_text=0.25)
        all_results.extend([x for x in r2 if x[2] > 0.35])

    # Deduplicate: keep highest-confidence result for each spatial cluster
    return dedupe_ocr(all_results)


def bbox_center(bbox):
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return (sum(xs)/4, sum(ys)/4)


def dedupe_ocr(results, dist_thresh=30):
    """Remove near-duplicate OCR results (same position, different passes)."""
    kept = []
    for r in sorted(results, key=lambda x: -x[2]):   # highest conf first
        cx, cy = bbox_center(r[0])
        duplicate = False
        for k in kept:
            kx, ky = bbox_center(k[0])
            if abs(cx - kx) < dist_thresh and abs(cy - ky) < dist_thresh:
                duplicate = True
                break
        if not duplicate:
            kept.append(r)
    return kept


# ═════════════════════════════════════════════════════════════════════
#  PHONE EXTRACTION  — the most important and hardest field
# ═════════════════════════════════════════════════════════════════════

# Common OCR confusion map: letter → likely digit
OCR_FIX = str.maketrans("OoIlSBZGqD", "0011582260")


def fix_ocr_digits(s):
    """Apply OCR confusion corrections ONLY inside digit-heavy tokens."""
    tokens  = s.split()
    fixed   = []
    for tok in tokens:
        digit_count = sum(c.isdigit() for c in tok)
        total       = len(tok)
        # If >40% of characters are already digits, fix confusions
        if total > 0 and digit_count / total > 0.4:
            tok = tok.translate(OCR_FIX)
        fixed.append(tok)
    return " ".join(fixed)


def clean_phone(raw_num):
    """Normalise a phone string: remove junk, keep digits + + - ( ) space."""
    s = re.sub(r"[^\d+\-() ]", "", raw_num).strip()
    # Collapse multiple spaces
    s = re.sub(r"\s{2,}", " ", s)
    return s


def is_valid_phone(s):
    digits = re.sub(r"\D", "", s)
    return 7 <= len(digits) <= 15


def extract_phones(lines, raw):
    """
    5-strategy phone extraction.
    Priority order: labelled > digit-dominant line > Indian pattern > generic > OCR-fixed.
    Returns deduplicated list, best match first.
    """
    candidates = []   # list of (phone_string, priority)

    # ── S1: Labelled line  "Tel: 98765 43210" ─────────────────────
    label_rx = re.compile(
        r"(?:tel(?:ephone)?|ph(?:one)?|mob(?:ile)?|cell|contact|call"
        r"|whatsapp|helpline|hotline|fax|direct|off(?:ice)?|res(?:idence)?)"
        r"[\s:.\-\#]*"
        r"([+()0-9][\d\s()\-+.]{5,24})",
        re.I,
    )
    for line in lines:
        fixed = fix_ocr_digits(line)
        m = label_rx.search(fixed)
        if m:
            p = clean_phone(m.group(1))
            if is_valid_phone(p):
                candidates.append((p, 0))          # highest priority

    # ── S2: Line is mostly digits ──────────────────────────────────
    for line in lines:
        fixed  = fix_ocr_digits(line)
        digits = re.sub(r"\D", "", fixed)
        non_sp = fixed.replace(" ", "")
        if len(non_sp) > 0 and len(digits) / len(non_sp) >= 0.60 and 7 <= len(digits) <= 15:
            p = clean_phone(fixed)
            if is_valid_phone(p):
                candidates.append((p, 1))

    # ── S3: Indian mobile patterns ─────────────────────────────────
    fixed_raw = fix_ocr_digits(raw)
    indian_patterns = [
        r"(?:\+91|0091|91)[\s\-]?[6-9]\d{9}",   # +91 9xxxxxxxxx
        r"\b[6-9]\d{4}[\s\-]?\d{5}\b",            # 98765 43210
        r"\b[6-9]\d{9}\b",                         # 9876543210
        r"\b0[1-9]\d[\s\-]?\d{7,8}\b",             # 011 12345678 landline
        r"\b1800[\s\-]?\d{3}[\s\-]?\d{4}\b",       # toll-free 1800
    ]
    for pat in indian_patterns:
        for m in re.finditer(pat, fixed_raw):
            p = clean_phone(m.group())
            if is_valid_phone(p):
                candidates.append((p, 2))

    # ── S4: Generic international ──────────────────────────────────
    intl_rx = re.compile(
        r"\+?\d{1,3}[\s\-]?\(?\d{2,5}\)?[\s\-]\d{3,5}[\s\-]\d{3,5}"
    )
    for m in intl_rx.finditer(fixed_raw):
        p = clean_phone(m.group())
        if is_valid_phone(p):
            candidates.append((p, 3))

    # ── S5: Fallback — any 10-digit run after OCR fix ─────────────
    for m in re.finditer(r"\b\d{10}\b", fixed_raw):
        p = m.group()
        if is_valid_phone(p):
            candidates.append((p, 4))

    # ── Deduplicate by digit content ──────────────────────────────
    seen   = {}   # digit_key → (phone_str, priority)
    for phone_str, pri in candidates:
        key = re.sub(r"\D", "", phone_str)
        # Remove leading 91 country code for dedup key
        if key.startswith("91") and len(key) == 12:
            key = key[2:]
        if key not in seen or pri < seen[key][1]:
            seen[key] = (phone_str, pri)

    # Sort by priority then by digit length (longer = more complete)
    results = sorted(seen.values(), key=lambda x: (x[1], -len(re.sub(r"\D","",x[0]))))
    return [r[0] for r in results]


# ═════════════════════════════════════════════════════════════════════
#  FULL CARD PARSER
# ═════════════════════════════════════════════════════════════════════

def parse_card(ocr_results):
    # Sort top-to-bottom (reading order)
    sorted_r = sorted(ocr_results,
                      key=lambda r: (r[0][0][1] + r[0][2][1]) / 2)
    # Only keep results with confidence ≥ 0.25
    lines = [r[1].strip() for r in sorted_r if r[2] >= 0.25 and r[1].strip()]
    raw   = "\n".join(lines)

    # ── Phone ─────────────────────────────────────────────────────
    all_phones = extract_phones(lines, raw)
    if len(all_phones) == 0:
        phone = ""
    elif len(all_phones) == 1:
        phone = all_phones[0]
    else:
        phone = " / ".join(all_phones[:3])   # up to 3 numbers

    # ── Email ─────────────────────────────────────────────────────
    # Also try OCR-fixing common confusions in email (0/O, 1/l etc.)
    email_candidates = re.findall(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", raw
    )
    # Try on OCR-fixed version too
    fixed_raw = fix_ocr_digits(raw)
    email_candidates += re.findall(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", fixed_raw
    )
    email = email_candidates[0] if email_candidates else ""

    # ── Website ───────────────────────────────────────────────────
    webs = re.findall(r"(?:https?://|www\.)[^\s,;)>\"'\]]+", raw, re.I)
    website = webs[0].rstrip(".,)") if webs else ""
    if not website:
        m = re.search(
            r"\b([a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?"
            r"\.(?:com|in|co\.in|org|net|io|ai|app|dev|biz|info|edu|gov))\b",
            raw, re.I
        )
        website = m.group() if m else ""

    # ── Social media ──────────────────────────────────────────────
    handles  = re.findall(r"@[A-Za-z0-9_.]{2,30}", raw)
    linkedin = re.findall(r"linkedin\.com/(?:in|company)/[A-Za-z0-9_\-]+", raw, re.I)
    twitter  = re.findall(r"twitter\.com/[A-Za-z0-9_]+", raw, re.I)
    insta    = re.findall(r"instagram\.com/[A-Za-z0-9_.]+", raw, re.I)
    social   = ", ".join(list(dict.fromkeys(handles + linkedin + twitter + insta)))

    # ── Address ───────────────────────────────────────────────────
    addr_kw = re.compile(
        r"\b(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|drive|dr\.?"
        r"|boulevard|blvd|nagar|colony|sector|phase|plot|flat|floor|building"
        r"|tower|near|opp\.?|dist\.?|pin|zip|state|city|village|town|taluka"
        r"|tehsil|district|block|ward|area|locality|society|complex|park|marg"
        r"|chowk|bazaar|market|crossing|junction|highway|nh\s*\d+"
        r"|mumbai|delhi|bangalore|bengaluru|chennai|hyderabad|pune|kolkata"
        r"|ahmedabad|surat|jaipur|lucknow|nagpur|indore|thane|bhopal|patna"
        r"|vadodara|ludhiana|agra|nashik|faridabad|meerut|rajkot|varanasi"
        r"|gujarat|maharashtra|karnataka|rajasthan|tamilnadu|tamil\s*nadu"
        r"|andhra|telangana|kerala|punjab|haryana|uttarakhand|himachal"
        r"|bihar|jharkhand|odisha|assam|westbengal|west\s*bengal|up|mp)\b",
        re.I,
    )
    pin_rx     = re.compile(r"\b[1-9]\d{5}\b")   # Indian PIN code
    addr_lines = [l for l in lines if addr_kw.search(l) or pin_rx.search(l)]
    address    = ", ".join(dict.fromkeys(addr_lines))  # dedup while preserving order

    # ── Build "clean" lines (remove lines we already identified) ──
    identified = set()
    for v in [email, website] + handles + linkedin + twitter + insta + addr_lines:
        if v: identified.add(v.strip())
    # Also exclude lines that are purely phone numbers
    for ph in all_phones:
        identified.add(ph.strip())

    clean = []
    for l in lines:
        if any(ident in l for ident in identified if len(ident) > 3):
            continue
        if re.match(
            r"^(tel|ph|phone|mob|mobile|fax|email|www|http|@)[\s:.\-]",
            l, re.I
        ):
            continue
        if re.sub(r"\D", "", l) and len(re.sub(r"\D","",l)) / max(len(l),1) > 0.6:
            continue   # skip digit-heavy lines (already captured as phone)
        if len(l) > 1:
            clean.append(l)

    # ── Card type ─────────────────────────────────────────────────
    ct = "Business Card"
    if re.search(
        r"happy\s*birthday|congratulations|best\s*wishes|with\s*love"
        r"|dear\s|warm\s*wishes|greetings|many\s*happy\s*returns|regards",
        raw, re.I
    ):
        ct = "Greeting Card"
    elif re.search(
        r"\binvitation\b|you\s*are\s*invited|rsvp|cordially|wedding"
        r"|reception|engagement|anniversary\s*celebration",
        raw, re.I
    ):
        ct = "Invitation"
    elif re.search(
        r"\bid\s*card\b|\bidentity\b|\bemployee\s*id\b|\bstudent\s*id\b"
        r"|\badmission\b|\benrollment\b",
        raw, re.I
    ):
        ct = "ID Card"
    elif not phone and not email and len(clean) < 4:
        ct = "Personal Card"

    # ── Keywords for Name / Title / Company detection ─────────────
    comp_kw = re.compile(
        r"\b(pvt\.?\s*ltd|pvt|ltd|llp|llc|inc\.?|corp\.?|co\.|company"
        r"|technologies|tech|solutions|services|industries|enterprises"
        r"|group|associates|consultancy|consultants|studio|agency|bureau"
        r"|hospital|clinic|pharmacy|school|college|university|institute"
        r"|academy|foundation|trust|ngo|society|labs?|systems|ventures"
        r"|global|international|worldwide|india|bharat|exports|imports"
        r"|traders|manufacturer|supplier|distributor|dealer|retailer"
        r"|constructions?|developers?|builders?|realty|realtors?|properties"
        r"|infrastr?ucture|infra|engineering|automation|electronics"
        r"|software|hardware|digital|media|publications?|printing"
        r"|logistics|transport|travels?|aviation|shipping)\b",
        re.I,
    )

    title_kw = re.compile(
        r"\b(managing\s*director|general\s*manager|vice\s*president"
        r"|chief\s*(?:executive|technology|financial|operating|marketing|"
        r"information|product|human|sales)\s*officer"
        r"|manager|director|ceo|cto|cfo|coo|cmo|cpo|chro|cso"
        r"|vp|svp|avp|president|founder|co-founder|co\s*founder"
        r"|engineer|developer|designer|architect|analyst|consultant"
        r"|executive|officer|head|lead|team\s*lead|tech\s*lead"
        r"|specialist|coordinator|advisor|counsellor|counselor"
        r"|professor|lecturer|teacher|principal|dean|rector"
        r"|proprietor|partner|principal|owner|chairman|chairperson"
        r"|secretary|treasurer|trustee|director|trustee"
        r"|dr\.|prof\.|advocate|adv\.|ca\s|cs\s|cpa\s"
        r"|intern|trainee|apprentice|associate|assistant|deputy"
        r"|senior|junior|sr\.|jr\.|sr\s|jr\s"
        r"|representative|agent|broker|relationship\s*manager)\b",
        re.I,
    )

    # ── Name (most prominent non-metadata line) ───────────────────
    name = ""
    name_scores = []
    for idx, l in enumerate(clean):
        wds = l.split()
        score = 0
        # More weight to shorter lines near top (names are usually first)
        if 2 <= len(wds) <= 5:           score += 3
        if not re.search(r"\d", l):      score += 2
        if not comp_kw.search(l):        score += 2
        if not title_kw.search(l):       score += 2
        capitalized = sum(1 for w in wds if w and w[0].isupper())
        score += min(capitalized, 3)
        # Penalize lines that look like addresses or labels
        if re.search(r"[,@#/\\]", l):    score -= 2
        if len(l) > 50:                  score -= 3
        # Favour lines appearing in the top half
        if idx < len(clean) * 0.4:       score += 2
        name_scores.append((l, score))

    if name_scores:
        name_scores.sort(key=lambda x: -x[1])
        if name_scores[0][1] >= 5:
            name = name_scores[0][0]
    if not name and clean:
        name = clean[0]

    # ── Title ─────────────────────────────────────────────────────
    title = ""
    for l in clean:
        if l == name:
            continue
        if title_kw.search(l):
            # Prefer shorter, cleaner title lines
            title = l
            break

    # ── Company ───────────────────────────────────────────────────
    company = ""
    for l in clean:
        if l in {name, title}:
            continue
        if comp_kw.search(l):
            company = l
            break
    # If no keyword match, try lines in ALL CAPS (common for company names)
    if not company:
        for l in clean:
            if l in {name, title}:
                continue
            words = l.split()
            if (len(words) >= 2
                    and all(w.isupper() or not w.isalpha() for w in words)
                    and not re.search(r"\d", l)):
                company = l
                break

    # ── Notes ─────────────────────────────────────────────────────
    notes = ""
    if ct in ("Greeting Card", "Invitation"):
        leftover = [l for l in clean if l not in {name, title, company}]
        notes = " ".join(leftover)
    else:
        # For business cards, capture taglines / slogans
        tagline_candidates = [
            l for l in clean
            if l not in {name, title, company}
            and 3 <= len(l.split()) <= 12
            and not re.search(r"\d", l)
        ]
        if tagline_candidates:
            notes = tagline_candidates[0]

    return {
        "cardType":    ct,
        "name":        name.strip(),
        "title":       title.strip(),
        "company":     company.strip(),
        "phone":       phone.strip(),
        "email":       email.strip(),
        "website":     website.strip(),
        "address":     address.strip(),
        "socialMedia": social.strip(),
        "notes":       notes.strip(),
        "rawText":     raw.strip(),
    }


# ═════════════════════════════════════════════════════════════════════
#  CARD STORAGE
# ═════════════════════════════════════════════════════════════════════

def load_cards():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_cards(cards):
    DATA_FILE.write_text(
        json.dumps(cards, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ═════════════════════════════════════════════════════════════════════
#  ROUTES
# ═════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/scan", methods=["POST"])
def scan():
    pil_img = None
    try:
        if "image" in request.files:
            pil_img = Image.open(request.files["image"].stream)
        elif request.is_json and "imageData" in request.json:
            b64 = request.json["imageData"]
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            pil_img = Image.open(BytesIO(base64.b64decode(b64)))
        else:
            return jsonify({"error": "No image provided"}), 400

        ocr_results = run_ocr(pil_img)
        card_data   = parse_card(ocr_results)
        return jsonify({"success": True, "data": card_data})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/cards", methods=["GET"])
def get_cards():
    return jsonify(load_cards())


@app.route("/cards", methods=["POST"])
def add_card():
    card = request.json
    if not card:
        return jsonify({"error": "No data"}), 400
    card["id"] = str(uuid.uuid4())
    cards = load_cards()
    cards.insert(0, card)
    save_cards(cards)
    return jsonify({"success": True, "card": card})


@app.route("/cards/<card_id>", methods=["DELETE"])
def delete_card(card_id):
    save_cards([c for c in load_cards() if c.get("id") != card_id])
    return jsonify({"success": True})


# ═════════════════════════════════════════════════════════════════════
#  START
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "127.0.0.1"

    ssl_ctx = get_ssl_context()
    scheme  = "https" if ssl_ctx else "http"

    print("\n" + "="*60)
    print("  CardScan is running!")
    print(f"  PC    : {scheme}://127.0.0.1:5000")
    print(f"  PHONE : {scheme}://{local_ip}:5000  <- open this on phone")
    if ssl_ctx:
        print()
        print("  PHONE BROWSER WARNING:")
        print("  Tap 'Advanced' then 'Proceed to site' (or 'Accept risk').")
        print("  Safe — it is only a local self-signed certificate.")
    else:
        print()
        print("  TIP: install pyopenssl for HTTPS (better on mobile):")
        print("  pip install pyopenssl")
    print("  Phone and PC must be on the SAME WiFi.")
    print("="*60 + "\n")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        ssl_context=ssl_ctx if ssl_ctx else None,
    )
