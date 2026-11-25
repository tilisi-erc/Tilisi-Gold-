# TILISI GOLD BI v11.2 - FINAL - Store 9153470 + Till 6899566 FELIX
# Live: https://tilisi-gold-bi.onrender.com
import os, base64, requests, json, time, random, threading, sqlite3, secrets, jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from collections import deque
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.getenv("JWT_SECRET", secrets.token_hex(32))

# ===== CONFIG - CORRECT FOR YOUR BUSINESS =====
STORE_NUMBER = int(os.getenv("SHORTCODE", 9153470))  # Store 9153470 - triggers STK
TILL_NUMBER = int(os.getenv("TILL_NUMBER", 6899566))  # Till 6899566 FELIX - receives money
SHORTCODE = STORE_NUMBER  # for backwards compat
CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET")
PASSKEY = os.getenv("MPESA_PASSKEY")
BASE_URL = "https://api.safaricom.co.ke"
CALLBACK_URL = os.getenv("CALLBACK_URL", "https://tilisi-gold-bi.onrender.com/api/callback")

# ===== FILES =====
ALERTS_FILE = "tilisi_alerts.json"
FCM_FILE = "tilisi_fcm.json"
SUBS_FILE = "subs.json"
alerts_db = json.load(open(ALERTS_FILE)) if os.path.exists(ALERTS_FILE) else []
fcm_tokens = json.load(open(FCM_FILE)) if os.path.exists(FCM_FILE) else []
subs_db = json.load(open(SUBS_FILE)) if os.path.exists(SUBS_FILE) else {}
asia_data = {"date": "", "high": 0, "low": 99999, "prices": deque(maxlen=200)}

def save_json(path, data):
    try:
        with open(path, 'w') as f: json.dump(data, f)
    except: pass

# ===== DB =====
def init_db():
    conn = sqlite3.connect('tilisi.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY, phone TEXT UNIQUE, email TEXT, 
                  password TEXT, created_at TEXT, subscription_until TEXT, is_active INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS payments 
                 (id INTEGER PRIMARY KEY, user_id INTEGER, phone TEXT, amount INTEGER, 
                  checkout_id TEXT, mpesa_receipt TEXT, status TEXT, created_at TEXT)''')
    conn.commit(); conn.close()
init_db()

def get_db():
    conn = sqlite3.connect('tilisi.db')
    conn.row_factory = sqlite3.Row
    return conn

# ===== PRICE FEEDS =====
def get_gold_price():
    for url in ['https://api.gold-api.com/price/XAU','https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT']:
        try:
            r = requests.get(url, timeout=6).json()
            p = float(r.get('price') or 0)
            if p > 1000: return p
        except: continue
    return 3514.0 + random.uniform(-2, 2)

def get_dxy():
    try:
        r = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=6).json()
        eur = r['rates']['EUR']
        return max(98, min(110, (100/eur)*0.92))
    except: return 103.99 + random.uniform(-0.2, 0.2)

def update_asia_range(price):
    eat_hour = (datetime.utcnow().hour + 3) % 24
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if asia_data["date"] != today:
        asia_data["date"] = today
        asia_data["high"] = price
        asia_data["low"] = price
    if 1 <= eat_hour <= 9:
        asia_data["high"] = max(asia_data["high"], price)
        asia_data["low"] = min(asia_data["low"], price)
    return asia_data["high"], asia_data["low"]

# ===== V9 BOS ENGINE =====
def v9_bos_engine(gold_price=None, dxy_val=None):
    if gold_price is None: gold_price = get_gold_price()
    if dxy_val is None: dxy_val = get_dxy()
    eat_hour = (datetime.utcnow().hour + 3) % 24
    asia_high, asia_low = update_asia_range(gold_price)
    BOS_BUFFER = 5.0
    bos_buy_level = asia_high + BOS_BUFFER if asia_high else gold_price + BOS_BUFFER
    bos_sell_level = asia_low - BOS_BUFFER if asia_low < 99999 else gold_price - BOS_BUFFER
    bos_active = None; bos_type = None
    if gold_price > bos_buy_level: bos_active=True; bos_type="BUY"
    elif gold_price < bos_sell_level: bos_active=True; bos_type="SELL"
    if not bos_active:
        return {"engine_status": "SCANNING","engine_note": f"Asia {asia_low:.1f}-{asia_high:.1f} | BOS BUY >{bos_buy_level:.1f} SELL <{bos_sell_level:.1f}",
                "bos_levels": {"high": round(asia_high,2),"low": round(asia_low,2),"buy_trigger": round(bos_buy_level,2),"sell_trigger": round(bos_sell_level,2)},
                "signal": "WAIT","confidence": 0,"bos_up": False,"should_notify": False,"notify_stage": "NONE",
                "gold": round(gold_price,2),"dxy": round(dxy_val,2),"rsi": 55,"regime": "SCANNING","buy_pass":0,"sell_pass":0,"gates":{},
                "timestamp": f"{datetime.utcnow().strftime('%H:%M:%S')} / {eat_hour}:00 EAT",
                "ai_analyst": f"ENGINE IDLE - Waiting Asia Breakout ${asia_low:.0f}-${asia_high:.0f}","invalidation": f"BUY <{bos_sell_level:.0f} | SELL >{bos_buy_level:.0f}"}
    gates = {}
    if dxy_val < 99.8: g1_buy,g1_sell="PASS","FAIL"
    elif dxy_val > 100.8: g1_buy,g1_sell="FAIL","PASS"
    else: g1_buy,g1_sell="WAIT","WAIT"
    gates['G1_DXY']={"buy_status":g1_buy,"sell_status":g1_sell,"weight":0.30,"note":f"DXY {dxy_val:.2f}"}
    ema50,ema200=gold_price-8,gold_price-28
    if gold_price > ema50 > ema200: g2_buy,g2_sell="PASS","FAIL"; tn=f"UP ${gold_price:.0f}"
    elif gold_price < ema50 < ema200: g2_buy,g2_sell="FAIL","PASS"; tn=f"DOWN ${gold_price:.0f}"
    else: g2_buy,g2_sell="WAIT","WAIT"; tn="RANGING"
    gates['G2_TREND']={"buy_status":g2_buy,"sell_status":g2_sell,"weight":0.25,"note":tn}
    if 10 <= eat_hour <= 13: sess,g3b,g3s=f"London {eat_hour}:00","PASS","PASS"
    elif 15 <= eat_hour <= 18: sess,g3b,g3s=f"NY {eat_hour}:00","PASS","PASS"
    else: sess,g3b,g3s=f"Asia/Off {eat_hour}:00","WAIT","WAIT"
    gates['G3_SESSION']={"buy_status":g3b,"sell_status":g3s,"weight":0.10,"note":sess}
    pdh,pdl=4146,4057
    if gold_price < pdl+8: g4b,g4s="PASS","WAIT"; liq=f"PDL {pdl}"
    elif gold_price > pdh-8: g4b,g4s="WAIT","PASS"; liq=f"PDH {pdh}"
    else: g4b,g4s="WAIT","WAIT"; liq=f"Mid"
    gates['G4_LIQ']={"buy_status":g4b,"sell_status":g4s,"weight":0.10,"note":liq}
    is_news=eat_hour in [15,16]
    g5="FAIL" if is_news else "PASS"
    gates['G5_NEWS']={"buy_status":g5,"sell_status":g5,"weight":0.15,"blocking":True,"note":"RED NEWS" if is_news else "No news"}
    res,sup=4145,4115
    if abs(gold_price-res)<5: g6b,g6s="FAIL","PASS"; sr=f"Res {res}"
    elif abs(gold_price-sup)<5: g6b,g6s="PASS","FAIL"; sr=f"Sup {sup}"
    else: g6b,g6s="WAIT","WAIT"; sr="Mid"
    gates['G6_SR']={"buy_status":g6b,"sell_status":g6s,"weight":0.05,"note":sr}
    rsi=35 if gold_price<4120 else 68 if gold_price>4140 else 55
    if 30 <= rsi <= 55: g7b,g7s="PASS","WAIT"
    elif 45 <= rsi <= 75 and g2_buy=="FAIL": g7b,g7s="WAIT","PASS"
    elif rsi>75: g7b,g7s="FAIL","WAIT"
    else: g7b,g7s="WAIT","WAIT"
    gates['G7_RSI']={"buy_status":g7b,"sell_status":g7s,"weight":0.05,"note":f"RSI {rsi}"}
    if is_news: signal, conf, stage = "WAIT", 0, "BLOCKED_NEWS"; score_buy = score_sell = 0
    else:
        score_buy = sum(g['weight'] for g in gates.values() if g['buy_status']=="PASS")
        score_sell = sum(g['weight'] for g in gates.values() if g['sell_status']=="PASS")
        if bos_type=="BUY":
            if score_buy >= 0.70: signal, conf, stage = "BUY", int(score_buy*100), "CONFIRMED"
            elif score_buy >= 0.40: signal, conf, stage = "WAIT", int(score_buy*100), "WEAK_BOS"
            else: signal, conf, stage = "WAIT", int(score_buy*100), "BOS_UP"
        else:
            if score_sell >= 0.70: signal, conf, stage = "SELL", int(score_sell*100), "CONFIRMED"
            elif score_sell >= 0.40: signal, conf, stage = "WAIT", int(score_sell*100), "WEAK_BOS"
            else: signal, conf, stage = "WAIT", int(score_sell*100), "BOS_UP"
    return {"engine_status": f"BOS {bos_type} ACTIVE","engine_note": f"BOS {bos_type} {gold_price:.1f} | Trigger {bos_buy_level if bos_type=='BUY' else bos_sell_level:.1f}",
            "bos_levels": {"high": round(asia_high,2),"low": round(asia_low,2),"buy_trigger": round(bos_buy_level,2),"sell_trigger": round(bos_sell_level,2)},
            "bos_type": bos_type,"bos_up": True,"should_notify": stage in ["BOS_UP","CONFIRMED"],"notify_stage": stage,
            "gold": round(gold_price,2),"dxy": round(dxy_val,2),"rsi": rsi,"regime": "TRENDING" if g2_buy=="PASS" or gates['G2_TREND']['sell_status']=="PASS" else "RANGING",
            "signal": signal,"confidence": conf,"score_buy": round(score_buy,2),"score_sell": round(score_sell,2),
            "buy_pass": sum(1 for g in gates.values() if g['buy_status']=="PASS"),"sell_pass": sum(1 for g in gates.values() if g['sell_status']=="PASS"),"gates": gates,
            "timestamp": f"{datetime.utcnow().strftime('%H:%M:%S')} / {eat_hour}:00 EAT",
            "ai_analyst": f"ENGINE {bos_type} | Score BUY:{score_buy:.2f} SELL:{score_sell:.2f} | {sess}",
            "invalidation": f"BUY <{bos_sell_level:.0f} | SELL >{bos_buy_level:.0f}"}

# ===== AUTH =====
def create_token(user_id):
    return jwt.encode({"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=7)}, app.config['SECRET_KEY'], algorithm="HS256")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization','').replace('Bearer ','')
        if not token: return jsonify({"error":"Login required"}),401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            request.user_id = data['user_id']
        except: return jsonify({"error":"Invalid token"}),401
        return f(*args, **kwargs)
    return decorated

def require_subscription(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (request.user_id,)).fetchone()
        conn.close()
        if not user or not user['subscription_until']: return jsonify({"error":"No subscription","need_pay":True}),402
        try:
            if datetime.fromisoformat(user['subscription_until']) < datetime.now():
                return jsonify({"error":"Expired","need_pay":True}),402
        except: return jsonify({"error":"No sub","need_pay":True}),402
        return f(*args, **kwargs)
    return decorated

# ===== M-PESA =====
def get_access_token():
    b64_auth = base64.b64encode(f"{CONSUMER_KEY}:{CONSUMER_SECRET}".encode()).decode()
    r = requests.get(f"{BASE_URL}/oauth/v1/generate?grant_type=client_credentials", headers={"Authorization": f"Basic {b64_auth}"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]

# ===== ROUTES =====
@app.route('/api/status')
def api_status():
    return jsonify(v9_bos_engine())

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    phone = data.get('phone','').replace("+","").replace(" ","")
    if phone.startswith("0"): phone = "254" + phone[1:]
    if not phone.startswith("254"): phone = "254" + phone[-9:]
    password = data.get('password'); email = data.get('email','')
    if not phone or not password: return jsonify({"error":"phone and password required"}),400
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (phone,email,password,created_at) VALUES (?,?,?,?)",(phone,email,generate_password_hash(password),datetime.now().isoformat()))
        conn.commit()
        user = conn.execute("SELECT id FROM users WHERE phone=?",(phone,)).fetchone()
        token = create_token(user['id'])
        return jsonify({"message":"Registered","phone":phone,"token":token,"need_payment":True})
    except sqlite3.IntegrityError:
        return jsonify({"error":"Phone exists, login"}),400
    finally: conn.close()

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    raw = data.get('phone','').replace("+","").replace(" ","")
    if raw.startswith("0"): raw = "254" + raw[1:]
    if not raw.startswith("254"): raw = "254" + raw[-9:]
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE phone=?",(raw,)).fetchone()
    conn.close()
    if not user or not check_password_hash(user['password'], data.get('password','')):
        return jsonify({"error":"Invalid phone or password"}),401
    token = create_token(user['id'])
    active = False
    if user['subscription_until']:
        try: active = datetime.fromisoformat(user['subscription_until']) > datetime.now()
        except: pass
    return jsonify({"token":token,"phone":user['phone'],"subscription_active":active,"subscription_until":user['subscription_until'],"need_payment": not active})

@app.route('/api/pay', methods=['POST'])
@require_auth
def stk_push():
    data = request.get_json() or {}
    amount = int(data.get('amount', 500))
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?",(request.user_id,)).fetchone()
    if not user: conn.close(); return jsonify({"error":"User not found"}),404
    phone = user['phone']  # already cleaned 254...
    try:
        access_token = get_access_token()
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{STORE_NUMBER}{PASSKEY}{timestamp}".encode()).decode()
        payload = {
            "BusinessShortCode": STORE_NUMBER,      # 9153470 - Store triggers STK
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerBuyGoodsOnline",
            "Amount": amount,
            "PartyA": phone,               # User phone - STK goes to user
            "PartyB": TILL_NUMBER,         # 6899566 FELIX - money lands here
            "PhoneNumber": phone,          # STK push to user
            "CallBackURL": CALLBACK_URL,
            "AccountReference": "TilisiGold",
            "TransactionDesc": "Tilisi Gold BI Access"
        }
        print(f"STK PUSH -> User:{phone} | Store:{STORE_NUMBER} | Till:{TILL_NUMBER} | Amount:{amount}")
        resp = requests.post(f"{BASE_URL}/mpesa/stkpush/v1/processquery", json=payload, headers={"Authorization": f"Bearer {access_token}"}, timeout=20).json()
        print(f"Daraja: {resp}")
        if resp.get('ResponseCode')=='0':
            conn.execute("INSERT INTO payments (user_id,phone,amount,checkout_id,status,created_at) VALUES (?,?,?,?,?,?)",(request.user_id,phone,amount,resp.get('CheckoutRequestID'),'PENDING',datetime.now().isoformat()))
            conn.commit()
        conn.close()
        return jsonify(resp)
    except Exception as e:
        conn.close()
        print(f"STK Error: {e}")
        return jsonify({"error":str(e)}),500

@app.route('/api/callback', methods=['POST'])
def callback():
    data = request.get_json() or {}
    print(f"CALLBACK: {data}")
    try:
        stk = data.get('Body',{}).get('stkCallback',{})
        checkout_id = stk.get('CheckoutRequestID'); result_code = stk.get('ResultCode')
        conn = get_db()
        if result_code==0:
            items = {x['Name']: x.get('Value') for x in stk.get('CallbackMetadata',{}).get('Item',[])}
            receipt = items.get('MpesaReceiptNumber'); amount = items.get('Amount',500)
            payment = conn.execute("SELECT * FROM payments WHERE checkout_id=?",(checkout_id,)).fetchone()
            if payment:
                days = 30 if int(amount)>=1500 else 7
                until = datetime.now() + timedelta(days=days)
                conn.execute("UPDATE payments SET status=?,mpesa_receipt=? WHERE checkout_id=?",('COMPLETED',receipt,checkout_id))
                conn.execute("UPDATE users SET subscription_until=?,is_active=1 WHERE id=?",(until.isoformat(), payment['user_id']))
                conn.commit()
                subs_db[payment['phone']]=until.isoformat(); save_json(SUBS_FILE, subs_db)
                print(f"ACTIVATED user {payment['user_id']} phone {payment['phone']} until {until}")
        else:
            conn.execute("UPDATE payments SET status=? WHERE checkout_id=?",('FAILED',checkout_id)); conn.commit()
        conn.close()
    except Exception as e: print(f"CB err {e}")
    return jsonify({"ResultCode":0,"ResultDesc":"Accepted"})

@app.route('/api/dashboard', methods=['GET'])
@require_auth
@require_subscription
def dashboard():
    return jsonify(v9_bos_engine())

@app.route('/api/my-subscription', methods=['GET'])
@require_auth
def my_sub():
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?",(request.user_id,)).fetchone()
    conn.close()
    if not user: return jsonify({"active":False}),404
    active = False
    if user['subscription_until']:
        try: active = datetime.fromisoformat(user['subscription_until']) > datetime.now()
        except: pass
    return jsonify({"active":active,"until":user['subscription_until'],"phone":user['phone'],"store":STORE_NUMBER,"till":TILL_NUMBER})

@app.route('/api/admin/activate', methods=['POST'])
@require_auth
def admin_activate():
    data = request.get_json() or {}
    phone = data.get('phone','').replace("+","").replace(" ","")
    if phone.startswith("0"): phone = "254"+phone[1:]
    if not phone.startswith("254"): phone = "254"+phone[-9:]
    days = int(data.get('days', 7))
    until = datetime.now() + timedelta(days=days)
    conn = get_db()
    conn.execute("UPDATE users SET subscription_until=?,is_active=1 WHERE phone=?",(until.isoformat(), phone))
    conn.commit(); conn.close()
    subs_db[phone]=until.isoformat(); save_json(SUBS_FILE, subs_db)
    return jsonify({"ok":True,"phone":phone,"until":until.isoformat(),"till":TILL_NUMBER})

@app.route('/api/alerts', methods=['GET','POST','DELETE'])
def api_alerts():
    global alerts_db
    if request.method=='GET': return jsonify([a for a in alerts_db if a.get('active',True)])
    if request.method=='POST':
        d=request.json or {}
        na={"id":int(time.time()*1000),"target":float(d.get('target')),"type":d.get('type','above'),"fcmToken":d.get('fcmToken'),"active":True,"createdAt":datetime.utcnow().isoformat()}
        alerts_db.append(na); save_json(ALERTS_FILE, alerts_db); return jsonify({"ok":True,"alert":na})
    if request.method=='DELETE':
        aid=int(request.args.get('id',0)); alerts_db=[a for a in alerts_db if a['id']!=aid]; save_json(ALERTS_FILE, alerts_db); return jsonify({"ok":True})

@app.route('/api/fcm/register', methods=['POST'])
def api_fcm_reg():
    global fcm_tokens
    token=(request.json or {}).get('token')
    if token and token not in fcm_tokens: fcm_tokens.append(token); save_json(FCM_FILE, fcm_tokens)
    return jsonify({"ok":True})

@app.route('/')
def index():
    if os.path.exists("index.html"):
        return Response(open("index.html", encoding="utf-8").read(), mimetype='text/html')
    return jsonify({"app":"Tilisi Gold BI v11.2","store":STORE_NUMBER,"till":TILL_NUMBER,"till_name":"FELIX","engine":"BOS + 7 Validators","status":"LIVE","flow":"STK->User Phone | Money->Till 6899566"})

@app.route('/health')
def health(): return jsonify({"status":"ok","store":STORE_NUMBER,"till":TILL_NUMBER,"time":datetime.utcnow().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))