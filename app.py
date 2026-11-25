# TILISI GOLD v10 - COMPLETE AUTH + BILLING + DASHBOARD
import os, base64, requests, sqlite3, secrets, jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.getenv("JWT_SECRET", secrets.token_hex(32))

# ====== CONFIG - FROM .ENV ======
SHORTCODE = int(os.getenv("SHORTCODE", 9153470))
CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET")
PASSKEY = os.getenv("MPESA_PASSKEY")
BASE_URL = "https://api.safaricom.co.ke"
CALLBACK_URL = os.getenv("CALLBACK_URL", "https://tilisigold.co.ke/api/callback")
JWT_EXPIRE_DAYS = 7

# ====== DATABASE ======
def init_db():
    conn = sqlite3.connect('tilisi.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY, phone TEXT UNIQUE, email TEXT UNIQUE, 
                  password TEXT, created_at TEXT, subscription_until TEXT, is_active INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS payments 
                 (id INTEGER PRIMARY KEY, user_id INTEGER, phone TEXT, amount INTEGER, 
                  checkout_id TEXT, mpesa_receipt TEXT, status TEXT, created_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect('tilisi.db')
    conn.row_factory = sqlite3.Row
    return conn

# ====== GOLD ENGINE ======
def analyze_gold(price):
    price = float(price)
    if 3514 <= price <= 3520:
        return {"action": "BUY", "entry": price, "sl": 3505, "tp": [3530, 3540, 3555], "reason": "3514 support held", "confidence": "HIGH"}
    elif 3530 < price < 3555:
        return {"action": "BUY_CONTINUATION", "entry": price, "sl": 3520, "tp": [3555, 3570], "reason": "Breakout 3530", "confidence": "MEDIUM"}
    elif price >= 3555:
        return {"action": "SELL", "entry": price, "sl": 3575, "tp": [3540, 3520], "reason": "Sell zone", "confidence": "MEDIUM"}
    elif price < 3514:
        return {"action": "WAIT_SELL", "entry": price, "sl": 3525, "tp": [3500, 3480], "reason": "Breakdown below 3514", "confidence": "LOW"}
    return {"action": "WAIT", "entry": price, "reason": "No zone", "confidence": "LOW"}

# ====== AUTH HELPERS ======
def create_token(user_id):
    payload = {"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS)}
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm="HS256")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({"error": "Login required"}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            g.user_id = data['user_id']
        except:
            return jsonify({"error": "Invalid token, login again"}), 401
        return f(*args, **kwargs)
    return decorated

def require_subscription(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
        conn.close()
        if not user:
            return jsonify({"error": "User not found"}), 404
        if not user['subscription_until']:
            return jsonify({"error": "No subscription", "need_payment": True}), 402
        until = datetime.fromisoformat(user['subscription_until'])
        if until < datetime.now():
            return jsonify({"error": "Subscription expired", "need_payment": True, "expired_at": user['subscription_until']}), 402
        return f(*args, **kwargs)
    return decorated

# ====== M-PESA ======
def get_access_token():
    url = f"{BASE_URL}/oauth/v1/generate?grant_type=client_credentials"
    b64_auth = base64.b64encode(f"{CONSUMER_KEY}:{CONSUMER_SECRET}".encode()).decode()
    r = requests.get(url, headers={"Authorization": f"Basic {b64_auth}"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

# ====== ROUTES ======

@app.route('/')
def home():
    return jsonify({
        "app": "Tilisi Gold v10",
        "till": SHORTCODE,
        "flow": "1. POST /api/auth/register 2. POST /api/auth/login 3. POST /api/pay 4. GET /api/dashboard",
        "status": "LIVE"
    })

# --- AUTH ---
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    phone = data.get('phone')  # 2547XXXXXXXX
    email = data.get('email')
    password = data.get('password')

    if not phone or not password:
        return jsonify({"error": "phone and password required, phone format 2547XXXXXXXX"}), 400

    conn = get_db()
    try:
        conn.execute("INSERT INTO users (phone, email, password, created_at) VALUES (?,?,?,?)",
                     (phone, email, generate_password_hash(password), datetime.now().isoformat()))
        conn.commit()
        user = conn.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone()
        token = create_token(user['id'])
        return jsonify({"message": "Registered", "token": token, "need_payment": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Phone or email already exists"}), 400
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    phone = data.get('phone')
    password = data.get('password')
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
    conn.close()
    
    if not user or not check_password_hash(user['password'], password):
        return jsonify({"error": "Invalid credentials"}), 401
    
    token = create_token(user['id'])
    is_active = False
    if user['subscription_until']:
        is_active = datetime.fromisoformat(user['subscription_until']) > datetime.now()
    
    return jsonify({
        "token": token,
        "user": {"id": user['id'], "phone": user['phone'], "email": user['email']},
        "subscription_active": is_active,
        "subscription_until": user['subscription_until'],
        "need_payment": not is_active
    })

# --- BILLING ---
@app.route('/api/pay', methods=['POST'])
@require_auth
def stk_push():
    data = request.get_json() or {}
    amount = int(data.get('amount', 500))  # 500 = weekly, 1500 = monthly
    
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
    phone = user['phone']
    
    try:
        token = get_access_token()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{SHORTCODE}{PASSKEY}{timestamp}".encode()).decode()

        payload = {
            "BusinessShortCode": SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerBuyGoodsOnline",
            "Amount": amount,
            "PartyA": phone,
            "PartyB": SHORTCODE,
            "PhoneNumber": phone,
            "CallBackURL": CALLBACK_URL,
            "AccountReference": f"TilisiGold_{g.user_id}",
            "TransactionDesc": f"TilisiGold Sub {amount}"
        }

        url = f"{BASE_URL}/mpesa/stkpush/v1/processquery"
        resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=20).json()
        
        # Save pending payment
        if resp.get('ResponseCode') == '0':
            conn.execute("INSERT INTO payments (user_id, phone, amount, checkout_id, status, created_at) VALUES (?,?,?,?,?,?)",
                         (g.user_id, phone, amount, resp.get('CheckoutRequestID'), 'PENDING', datetime.now().isoformat()))
            conn.commit()
        
        conn.close()
        return jsonify(resp)
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json()
    print(f"[CALLBACK] {data}")
    try:
        stk = data.get('Body', {}).get('stkCallback', {})
        checkout_id = stk.get('CheckoutRequestID')
        result_code = stk.get('ResultCode')
        
        conn = get_db()
        if result_code == 0:
            # Success - Activate subscription
            items = {x['Name']: x.get('Value') for x in stk.get('CallbackMetadata', {}).get('Item', [])}
            receipt = items.get('MpesaReceiptNumber')
            amount = items.get('Amount', 500)
            
            payment = conn.execute("SELECT * FROM payments WHERE checkout_id=?", (checkout_id,)).fetchone()
            if payment:
                # 500=7days, 1500=30days
                days = 30 if int(amount) >= 1500 else 7
                until = datetime.now() + timedelta(days=days)
                
                conn.execute("UPDATE payments SET status=?, mpesa_receipt=? WHERE checkout_id=?", ('COMPLETED', receipt, checkout_id))
                conn.execute("UPDATE users SET subscription_until=?, is_active=1 WHERE id=?", (until.isoformat(), payment['user_id']))
                conn.commit()
                print(f"ACTIVATED user {payment['user_id']} until {until}")
        else:
            conn.execute("UPDATE payments SET status=? WHERE checkout_id=?", ('FAILED', checkout_id))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Callback error: {e}")
    
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

# --- PROTECTED DASHBOARD ---
@app.route('/api/dashboard', methods=['GET'])
@require_auth
@require_subscription
def dashboard():
    price = request.args.get('price', 3518)
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
    conn.close()
    
    return jsonify({
        "user": {"phone": user['phone'], "subscription_until": user['subscription_until']},
        "gold": {
            "price": float(price),
            "dxy": 104.05,
            "signal": analyze_gold(price),
            "zones": {"buy": [3514, 3520], "sell": [3555, 3570], "breakout": 3530}
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/my-subscription', methods=['GET'])
@require_auth
def my_sub():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
    conn.close()
    active = False
    if user['subscription_until']:
        active = datetime.fromisoformat(user['subscription_until']) > datetime.now()
    return jsonify({"active": active, "until": user['subscription_until'], "phone": user['phone']})

if __name__ == '__main__':
    if not all([CONSUMER_KEY, CONSUMER_SECRET, PASSKEY]):
        print("ERROR: .env missing! Fill MPESA_CONSUMER_KEY etc")
    else:
        print(f"Tilisi Gold v10 LIVE - Till {SHORTCODE} - Auth+Billing READY")
    app.run(host='0.0.0.0', port=5000, debug=False)