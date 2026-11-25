# TILISI GOLD v9
import os
import base64
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
CORS(app)

# ====== CONFIG - PRODUCTION ======
SHORTCODE = 9153470
CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET")
PASSKEY = os.getenv("MPESA_PASSKEY")
BASE_URL = "https://api.safaricom.co.ke"
CALLBACK_URL = os.getenv("CALLBACK_URL", "https://tilisigold.co.ke/api/callback")
API_KEY = os.getenv("TILISI_API_KEY", "TilisiGold_Secure_2026")

# ====== AUTH MIDDLEWARE ======
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Safaricom callback haina API key
        if request.path == '/api/callback':
            return f(*args, **kwargs)
        key = request.headers.get('X-API-KEY') or request.args.get('api_key')
        if not key or key != API_KEY:
            return jsonify({"error": "Unauthorized", "message": "Invalid or missing X-API-KEY"}), 401
        return f(*args, **kwargs)
    return decorated

# ====== M-PESA AUTH ======
def get_access_token():
    try:
        url = f"{BASE_URL}/oauth/v1/generate?grant_type=client_credentials"
        auth = f"{CONSUMER_KEY}:{CONSUMER_SECRET}"
        b64_auth = base64.b64encode(auth.encode()).decode()
        headers = {"Authorization": f"Basic {b64_auth}"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.json()["access_token"]
    except Exception as e:
        print(f"Token Error: {e}")
        raise

# ====== GOLD ENGINE ======
GOLD_ZONES = {
    "buy_zone": [3514, 3520],
    "sell_zone": [3555, 3570],
    "breakout": 3530,
}

def analyze_gold(price):
    price = float(price)
    if 3514 <= price <= 3520:
        return {"action": "BUY", "entry": price, "sl": 3505, "tp": [3530, 3540, 3555], "reason": "3514 support held - bounce zone", "confidence": "HIGH"}
    elif price > 3530 and price < 3555:
        return {"action": "BUY_CONTINUATION", "entry": price, "sl": 3520, "tp": [3540, 3555, 3570], "reason": "Breakout 3530 confirmed", "confidence": "MEDIUM"}
    elif price >= 3555:
        return {"action": "SELL", "entry": price, "sl": 3575, "tp": [3540, 3520, 3514], "reason": "Sell pressure zone", "confidence": "MEDIUM"}
    elif price < 3514:
        return {"action": "WAIT_SELL", "entry": price, "sl": 3525, "tp": [3500, 3480], "reason": "Breakdown below 3514", "confidence": "LOW"}
    else:
        return {"action": "WAIT", "entry": price, "reason": "No clear zone", "confidence": "LOW"}

# ====== ROUTES ======
@app.route('/')
def home():
    return jsonify({
        "app": "Tilisi Gold v9",
        "status": "LIVE PRODUCTION",
        "till": SHORTCODE,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/signal', methods=['GET'])
@require_api_key
def gold_signal():
    price = request.args.get('price', 3526.15)
    try:
        signal = analyze_gold(price)
        return jsonify({
            "price": float(price),
            "dxy": 104.05,
            "signal": signal,
            "zones": GOLD_ZONES,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/pay', methods=['POST'])
@require_api_key
def stk_push():
    data = request.get_json() or {}
    phone = data.get('phone')
    amount = data.get('amount', 1)

    if not phone or not phone.startswith('254'):
        return jsonify({"error": "phone must be 2547XXXXXXXX"}), 400

    try:
        token = get_access_token()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{SHORTCODE}{PASSKEY}{timestamp}".encode()).decode()

        payload = {
            "BusinessShortCode": SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerBuyGoodsOnline",
            "Amount": int(amount),
            "PartyA": phone,
            "PartyB": SHORTCODE,
            "PhoneNumber": phone,
            "CallBackURL": CALLBACK_URL,
            "AccountReference": "TilisiGold",
            "TransactionDesc": "Subscription"
        }

        url = f"{BASE_URL}/mpesa/stkpush/v1/processquery"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.post(url, json=payload, headers=headers, timeout=20).json()
        
        print(f"[STK] {phone} - {amount} KES - Response: {resp}")
        return jsonify(resp)

    except Exception as e:
        print(f"[STK ERROR] {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    print(f"[CALLBACK] {data}")
    
    try:
        stk = data.get('Body', {}).get('stkCallback', {})
        result_code = stk.get('ResultCode')
        if result_code == 0:
            # Hapa weka logic ya DB - activate user
            metadata = stk.get('CallbackMetadata', {}).get('Item', [])
            print(f"PAYMENT SUCCESS: {metadata}")
        else:
            print(f"PAYMENT FAILED: {stk.get('ResultDesc')}")
    except Exception as e:
        print(f"Callback parse error: {e}")

    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

@app.route('/api/status', methods=['GET'])
@require_api_key
def status():
    return jsonify({"mpesa": "connected", "shortcode": SHORTCODE, "env": "production"})

if __name__ == '__main__':
    if not all([CONSUMER_KEY, CONSUMER_SECRET, PASSKEY]):
        print("ERROR: Missing .env variables!")
    else:
        print(f"Tilisi Gold v9 LIVE on Till {SHORTCODE}")
    app.run(host='0.0.0.0', port=5000, debug=False)