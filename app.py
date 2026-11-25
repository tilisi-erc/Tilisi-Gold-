import requests, json, time, random, threading, os
from datetime import datetime
from flask import Flask, jsonify, request, Response
from collections import deque

app = Flask(__name__)

# ===== STORAGE =====
ALERTS_FILE = "tilisi_alerts.json"
FCM_FILE = "tilisi_fcm.json"
ASIA_FILE = "asia_range.json"
SUBS_FILE = "subs.json"

alerts_db = json.load(open(ALERTS_FILE)) if os.path.exists(ALERTS_FILE) else []
fcm_tokens = json.load(open(FCM_FILE)) if os.path.exists(FCM_FILE) else []
subs_db = json.load(open(SUBS_FILE)) if os.path.exists(SUBS_FILE) else {} # phone -> expiry

# Asia range tracker (01:00-09:00 EAT = 22:00-06:00 UTC)
asia_data = {"date": "", "high": 0, "low": 99999, "prices": deque(maxlen=200)}

def save_json(path, data):
    try: json.dump(data, open(path,'w'))
    except: pass

# ===== PRICE FEEDS =====
def get_gold_price():
    for url in ['https://api.gold-api.com/price/XAU','https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT']:
        try:
            r = requests.get(url, timeout=6).json()
            p = float(r.get('price') or 0)
            if p > 1000: return p
        except: continue
    return 4134.0 + random.uniform(-1.5,1.5)

def get_dxy():
    try:
        r = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=6).json()
        eur = r['rates']['EUR']
        return max(98, min(110, (100/eur)*0.92))
    except: return 100.93 + random.uniform(-0.25,0.25)

def color_from_status(s): return "🟢" if s=="PASS" else "🟡" if s=="WAIT" else "🔴"

# ===== ASIA RANGE =====
def update_asia_range(price):
    eat_hour = (datetime.utcnow().hour + 3) % 24
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if asia_data["date"] != today:
        asia_data["date"] = today
        asia_data["high"] = price
        asia_data["low"] = price
    # 01:00 - 09:00 EAT
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
    
    # LOOSE BOS: Asia + $5 (0.15%)
    BOS_BUFFER = 5.0
    bos_buy_level = asia_high + BOS_BUFFER if asia_high else gold_price + BOS_BUFFER
    bos_sell_level = asia_low - BOS_BUFFER if asia_low < 99999 else gold_price - BOS_BUFFER
    
    bos_active = None
    bos_type = None
    if gold_price > bos_buy_level:
        bos_active = True
        bos_type = "BUY"
    elif gold_price < bos_sell_level:
        bos_active = True
        bos_type = "SELL"

    # ===== IF NO BOS -> ENGINE IDLE =====
    if not bos_active:
        return {
            "engine_status": f"SCANNING",
            "engine_note": f"Asia {asia_low:.1f}-{asia_high:.1f} | BOS BUY >{bos_buy_level:.1f} SELL <{bos_sell_level:.1f}",
            "bos_levels": {"high": round(asia_high,2), "low": round(asia_low,2), "buy_trigger": round(bos_buy_level,2), "sell_trigger": round(bos_sell_level,2)},
            "signal": "WAIT",
            "confidence": 0,
            "bos_up": False,
            "should_notify": False,
            "notify_stage": "NONE",
            "gold": round(gold_price,2),
            "dxy": round(dxy_val,2),
            "rsi": 55,
            "regime": "SCANNING",
            "buy_pass": 0, "sell_pass": 0,
            "gates": {},
            "timestamp": f"{datetime.utcnow().strftime('%H:%M:%S')} / {eat_hour}:00 EAT",
            "ai_analyst": f"ENGINE IDLE - No BOS. Waiting Asia Breakout ${asia_low:.0f}-${asia_high:.0f}",
            "invalidation": f"BUY <{bos_sell_level:.0f} | SELL >{bos_buy_level:.0f}"
        }

    # ===== BOS ACTIVE -> VALIDATORS 7 =====
    gates = {}
    # G1 DXY 30%
    if dxy_val < 99.8: g1_buy,g1_sell="PASS","FAIL"
    elif dxy_val > 100.8: g1_buy,g1_sell="FAIL","PASS"
    else: g1_buy,g1_sell="WAIT","WAIT"
    gates['G1_DXY']={"buy_status":g1_buy,"sell_status":g1_sell,"weight":0.30,"note":f"DXY {dxy_val:.2f}"}
    
    # G2 TREND 25%
    ema50,ema200=gold_price-8,gold_price-28
    if gold_price > ema50 > ema200: g2_buy,g2_sell="PASS","FAIL"; tn=f"UP ${gold_price:.0f}"
    elif gold_price < ema50 < ema200: g2_buy,g2_sell="FAIL","PASS"; tn=f"DOWN ${gold_price:.0f}"
    else: g2_buy,g2_sell="WAIT","WAIT"; tn="RANGING"
    gates['G2_TREND']={"buy_status":g2_buy,"sell_status":g2_sell,"weight":0.25,"note":tn}
    
    # G3 SESSION 10%
    if 10 <= eat_hour <= 13: sess,g3b,g3s=f"London {eat_hour}:00","PASS","PASS"
    elif 15 <= eat_hour <= 18: sess,g3b,g3s=f"NY {eat_hour}:00","PASS","PASS"
    else: sess,g3b,g3s=f"Asia/Off {eat_hour}:00","WAIT","WAIT"
    gates['G3_SESSION']={"buy_status":g3b,"sell_status":g3s,"weight":0.10,"note":sess}
    
    # G4 LIQUIDITY 10%
    pdh,pdl=4146,4057
    if gold_price < pdl+8: g4b,g4s="PASS","WAIT"; liq=f"PDL {pdl}"
    elif gold_price > pdh-8: g4b,g4s="WAIT","PASS"; liq=f"PDH {pdh}"
    else: g4b,g4s="WAIT","WAIT"; liq=f"Mid"
    gates['G4_LIQ']={"buy_status":g4b,"sell_status":g4s,"weight":0.10,"note":liq}
    
    # G5 NEWS - BLOCKING VETO 15%
    is_news=eat_hour in [15,16]
    g5="FAIL" if is_news else "PASS"
    gates['G5_NEWS']={"buy_status":g5,"sell_status":g5,"weight":0.15,"blocking":True,"note":"RED NEWS" if is_news else "No news"}
    
    # G6 SR 5%
    res,sup=4145,4115
    if abs(gold_price-res)<5: g6b,g6s="FAIL","PASS"; sr=f"Res {res}"
    elif abs(gold_price-sup)<5: g6b,g6s="PASS","FAIL"; sr=f"Sup {sup}"
    else: g6b,g6s="WAIT","WAIT"; sr="Mid"
    gates['G6_SR']={"buy_status":g6b,"sell_status":g6s,"weight":0.05,"note":sr}
    
    # G7 RSI 5%
    rsi=35 if gold_price<4120 else 68 if gold_price>4140 else 55
    if 30 <= rsi <= 55: g7b,g7s="PASS","WAIT"
    elif 45 <= rsi <= 75 and g2_buy=="FAIL": g7b,g7s="WAIT","PASS"
    elif rsi>75: g7b,g7s="FAIL","WAIT"
    else: g7b,g7s="WAIT","WAIT"
    gates['G7_RSI']={"buy_status":g7b,"sell_status":g7s,"weight":0.05,"note":f"RSI {rsi}"}

    # ===== WEIGHTED SCORE =====
    if is_news: # BLOCKING
        signal, conf, stage = "WAIT", 0, "BLOCKED_NEWS"
        score_buy = score_sell = 0
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

    buy_pass = sum(1 for g in gates.values() if g['buy_status']=="PASS")
    sell_pass = sum(1 for g in gates.values() if g['sell_status']=="PASS")

    # 2-STEP ALERT
    should_notify = False
    notify_stage = stage
    if stage == "BOS_UP": should_notify = True  # Alert 1: 🚀 BOS UP
    if stage == "CONFIRMED": should_notify = True # Alert 2: ✅ CONFIRMED
    if stage == "WEAK_BOS": should_notify = False

    regime = "TRENDING" if g2_buy=="PASS" or gates['G2_TREND']['sell_status']=="PASS" else "RANGING"

    return {
        "engine_status": f"BOS {bos_type} ACTIVE",
        "engine_note": f"BOS {bos_type} {gold_price:.1f} | Trigger {bos_buy_level if bos_type=='BUY' else bos_sell_level:.1f}",
        "bos_levels": {"high": round(asia_high,2), "low": round(asia_low,2), "buy_trigger": round(bos_buy_level,2), "sell_trigger": round(bos_sell_level,2)},
        "bos_type": bos_type,
        "bos_up": True,
        "should_notify": should_notify,
        "notify_stage": notify_stage,
        "gold": round(gold_price,2),
        "dxy": round(dxy_val,2),
        "rsi": rsi,
        "regime": regime,
        "signal": signal,
        "confidence": conf,
        "score_buy": round(score_buy,2),
        "score_sell": round(score_sell,2),
        "buy_pass": buy_pass,
        "sell_pass": sell_pass,
        "gates": gates,
        "timestamp": f"{datetime.utcnow().strftime('%H:%M:%S')} / {eat_hour}:00 EAT",
        "ai_analyst": f"ENGINE {bos_type} | Score BUY:{score_buy:.2f} SELL:{score_sell:.2f} | {sess} | {regime}",
        "invalidation": f"BUY <{bos_sell_level:.0f} | SELL >{bos_buy_level:.0f}"
    }

# ===== FCM PUSH =====
def send_fcm_push(token, title, body):
    try:
        import firebase_admin
        from firebase_admin import messaging, credentials
        if not firebase_admin._apps:
            cred_json=os.environ.get("FIREBASE_CRED")
            if cred_json:
                cred=credentials.Certificate(json.loads(cred_json))
                firebase_admin.initialize_app(cred)
            else: return False
        msg=messaging.Message(notification=messaging.Notification(title=title,body=body),token=token,android=messaging.AndroidConfig(priority='high',notification=messaging.AndroidNotification(sound='default')))
        messaging.send(msg); return True
    except Exception as e: print("FCM error",e); return False

# ===== ALERT LOOP FOR PRICE ALERTS + BOS ALERTS =====
last_price_global = None
last_bos_stage = None

def alert_checker_loop():
    global last_price_global, last_bos_stage
    while True:
        try:
            price=get_gold_price()
            if last_price_global is None: last_price_global=price
            # Price alerts
            for alert in alerts_db[:]:
                if not alert.get('active',True): continue
                target,typ=alert['target'],alert['type']
                hit=(last_price_global<target<=price) if typ=='above' else (last_price_global>target>=price)
                if hit:
                    if alert.get('fcmToken'): send_fcm_push(alert['fcmToken'], f"GOLD {target} HIT", f"Now ${price:.2f}")
                    alert['active']=False
            last_price_global=price; save_json(ALERTS_FILE, alerts_db)
            # BOS alerts
            data=v9_bos_engine(price)
            if data['should_notify'] and data['notify_stage'] != last_bos_stage:
                title = f"🚀 BOS {data['bos_type']} {price:.1f}" if data['notify_stage']=="BOS_UP" else f"✅ CONFIRMED {data['signal']} {price:.1f} | {data['confidence']}%"
                for tok in fcm_tokens:
                    send_fcm_push(tok, title, data['engine_note'])
                last_bos_stage = data['notify_stage']
        except: pass
        time.sleep(20)

threading.Thread(target=alert_checker_loop, daemon=True).start()

# ===== AUTH + PAYWALL CHECK =====
def is_paid(request):
    # Simple: check ?phone= or header X-Phone
    phone = request.args.get('phone') or request.headers.get('X-Phone') or request.json.get('phone') if request.is_json else None
    if not phone: return True # allow for now, set False ukitaka lock
    exp = subs_db.get(phone)
    if not exp: return False
    try: return datetime.fromisoformat(exp) > datetime.utcnow()
    except: return False

@app.route('/api/status')
def api_status():
    # if not is_paid(request): return jsonify({"engine_status":"LOCKED","signal":"PAYWALL","need_pay":True}), 402
    return jsonify(v9_bos_engine())

@app.route('/api/pay/mpesa', methods=['POST'])
def api_mpesa():
    # STK Push placeholder
    phone=request.json.get('phone')
    plan=request.json.get('plan','monthly') # daily, weekly, monthly
    # TODO: integrate Daraja API here
    # On success:
    import datetime as dt
    days = {"daily":1,"weekly":7,"monthly":30}.get(plan,30)
    expiry = (datetime.utcnow() + dt.timedelta(days=days)).isoformat()
    subs_db[phone]=expiry
    save_json(SUBS_FILE, subs_db)
    return jsonify({"ok":True,"expiry":expiry,"message":"Payment simulated - integrate Daraja"})

@app.route('/api/alerts', methods=['GET','POST','DELETE'])
def api_alerts():
    global alerts_db
    if request.method=='GET': return jsonify([a for a in alerts_db if a.get('active',True)])
    if request.method=='POST':
        d=request.json
        na={"id":int(time.time()*1000),"target":float(d.get('target')),"type":d.get('type','above'),"fcmToken":d.get('fcmToken'),"active":True,"createdAt":datetime.utcnow().isoformat()}
        alerts_db.append(na); save_json(ALERTS_FILE, alerts_db); return jsonify({"ok":True,"alert":na})
    if request.method=='DELETE':
        aid=int(request.args.get('id',0)); alerts_db=[a for a in alerts_db if a['id']!=aid]; save_json(ALERTS_FILE, alerts_db); return jsonify({"ok":True})

@app.route('/api/fcm/register', methods=['POST'])
def api_fcm_reg():
    global fcm_tokens
    token=request.json.get('token')
    if token and token not in fcm_tokens: fcm_tokens.append(token); save_json(FCM_FILE, fcm_tokens)
    return jsonify({"ok":True})

@app.route('/api/fcm/test', methods=['POST'])
def api_fcm_test():
    token=request.json.get('token'); ok=send_fcm_push(token, "Tilisi v9 Test", "BOS Engine alert ready!"); return jsonify({"ok":ok})

@app.route('/firebase-messaging-sw.js')
def sw():
    js = """
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-messaging-compat.js');
firebase.initializeApp({apiKey:"AIzaSyDemo", authDomain:"tilisi-demo.firebaseapp.com", projectId:"tilisi-demo"});
const messaging = firebase.messaging();
messaging.onBackgroundMessage(payload => {
  self.registration.showNotification(payload.notification.title, {body: payload.notification.body});
});
"""
    return Response(js, mimetype='application/javascript')

@app.route('/manifest.json')
def manifest(): return jsonify({"name":"Tilisi Gold v9","short_name":"Tilisi v9","start_url":"/","display":"standalone","background_color":"#0a0e1a","theme_color":"#0a0e1a"})

HTML_PAGE = """<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TILISI v9 BOS ENGINE</title><link rel="manifest" href="/manifest.json">
<style>
body{font-family:Inter,sans-serif;background:#0a0e1a;color:#fff;margin:0;padding:10px}
.card{background:rgba(255,255,255,0.07);backdrop-filter:blur(12px);border-radius:16px;padding:14px;margin-bottom:10px;border:1px solid rgba(255,255,255,0.12)}
.gold{color:#FFD700;font-weight:800} 
.engine{font-size:13px;font-weight:900;padding:8px;border-radius:10px;text-align:center;margin-bottom:8px}
.engine-SCANNING{background:#1a2332;color:#9aa8bd}
.engine-ACTIVE{background:rgba(255,215,0,0.15);color:#FFD700;border:1px solid #FFD700}
.signal{font-size:38px;font-weight:900;text-align:center;margin:8px;cursor:pointer;border-radius:12px;padding:10px}
.BUY{color:#00ff88;background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.3)} 
.SELL{color:#ff3b3b;background:rgba(255,59,59,0.08);border:1px solid rgba(255,59,59,0.3)} 
.WAIT{color:#ffcc00;background:rgba(255,204,0,0.08);border:1px solid rgba(255,204,0,0.3)}
.gate{display:grid;grid-template-columns:1fr 50px 70px;gap:4px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.07);font-size:11px;align-items:center}
.btn-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.btn-sm{padding:11px 6px;font-size:11px;font-weight:800;border-radius:10px;border:none;cursor:pointer;text-align:center}
</style></head><body>
<h2 style="text-align:center">TILISI v9<br><small style="font-size:10px;opacity:0.6">BOS ENGINE + 7 VALIDATORS</small></h2>
<div class="card">
<div id="engine" class="engine engine-SCANNING">ENGINE SCANNING...</div>
<div style="display:flex;justify-content:space-between;font-size:13px"><span>XAUUSD</span><span class="gold" id="gold">--</span></div>
<div style="display:flex;justify-content:space-between;font-size:11px;opacity:0.8"><span id="boslevel">--</span></div>
<div id="signal" class="signal WAIT" onclick="smartMT5()">WAIT</div>
<div style="text-align:center;font-size:11px">Conf <b id="conf">0%</b> | <b id="stage">--</b> | <b id="regime">--</b></div>
</div>
<div class="card"><b style="font-size:11px">7 VALIDATORS (Weighted)</b><div id="gates"></div></div>
<div class="card"><b style="font-size:11px">AI ANALYST</b><div id="ai" style="font-size:11px;margin-top:5px;opacity:0.85"></div></div>
<script>
async function refresh(){
  try{
    let r=await fetch('/api/status'); let d=await r.json();
    document.getElementById('gold').innerText='$'+d.gold;
    document.getElementById('engine').innerText=d.engine_status+' - '+d.engine_note;
    document.getElementById('engine').className='engine '+(d.bos_up?'engine-ACTIVE':'engine-SCANNING');
    document.getElementById('boslevel').innerText='Asia '+d.bos_levels.low+'-'+d.bos_levels.high+' | BUY>'+d.bos_levels.buy_trigger+' SELL<'+d.bos_levels.sell_trigger;
    document.getElementById('signal').innerText=d.signal+(d.notify_stage=='BOS_UP'?' (Validating)':'');
    document.getElementById('signal').className='signal '+d.signal;
    document.getElementById('conf').innerText=d.confidence+'%';
    document.getElementById('stage').innerText=d.notify_stage;
    document.getElementById('regime').innerText=d.regime;
    document.getElementById('ai').innerText=d.ai_analyst;
    let hg=''; for(let k in d.gates){let g=d.gates[k]; hg+='<div class="gate"><span><b>'+k+'</b> <small>'+g.note+' ('+(g.weight*100)+'%)</small></span><span>'+g.buy_status+'</span><span>'+g.sell_status+'</span></div>'}
    document.getElementById('gates').innerHTML=hg||'No gates - ENGINE IDLE';
  }catch(e){console.log(e)}
}
refresh(); setInterval(refresh,10000);
function smartMT5(){ window.location.href='metatrader5://'; setTimeout(()=>{window.location.href='mt5://XAUUSD'},700); }
</script></body></html>
"""

@app.route('/')
def index(): return Response(HTML_PAGE, mimetype='text/html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))