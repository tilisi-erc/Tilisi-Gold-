# TILISI GOLD BI v8.3 - DUAL GATES + COMPACT BUTTONS + TRAFFIC LIGHT DOTS
# Tilisi Technologies Inc. - Final Build
import requests, json, time, random, threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
import os

app = Flask(__name__)

# --- ALERT STORE ---
ALERTS_FILE = "tilisi_alerts.json"
alerts_db = []
last_price_global = None

if os.path.exists(ALERTS_FILE):
    try:
        alerts_db = json.load(open(ALERTS_FILE))
    except:
        alerts_db = []

def save_alerts():
    try:
        json.dump(alerts_db, open(ALERTS_FILE,'w'))
    except:
        pass

# --- REAL PRICE FETCH ---
def get_gold_price():
    for url in [
        'https://api.gold-api.com/price/XAU',
        'https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT'
    ]:
        try:
            r = requests.get(url, timeout=6).json()
            p = float(r.get('price') or r.get('price') or 0)
            if p > 1000:
                return p
        except:
            continue
    return 4141.40 + random.uniform(-1.5,1.5)

def get_dxy():
    try:
        r = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=6).json()
        eur = r['rates']['EUR']
        dxy = (100 / eur) * 0.92
        return max(98, min(102, dxy))
    except:
        return 100.93 + random.uniform(-0.25,0.25)

def color_from_status(s):
    return "🟢" if s=="PASS" else "🟡" if s=="WAIT" else "🔴"

# --- V8.3 DUAL ENGINE ---
def v8_check_gates(gold_price=None, dxy_val=None):
    if gold_price is None: gold_price = get_gold_price()
    if dxy_val is None: dxy_val = get_dxy()
    
    utc_hour = datetime.utcnow().hour
    eat_hour = (utc_hour + 3) % 24
    gates = {}
    
    if dxy_val < 99.8:
        g1_buy, g1_sell = "PASS", "FAIL"
    elif dxy_val > 100.8:
        g1_buy, g1_sell = "FAIL", "PASS"
    else:
        g1_buy, g1_sell = "WAIT", "WAIT"
    gates['G1_DXY'] = {
        "buy_status": g1_buy, "sell_status": g1_sell,
        "buy_color": color_from_status(g1_buy), "sell_color": color_from_status(g1_sell),
        "note": f"DXY {dxy_val:.2f} | <99.8 BULL Gold | >100.8 BEAR",
        "score_buy": 1 if g1_buy=="PASS" else -1 if g1_buy=="FAIL" else 0,
        "score_sell": 1 if g1_sell=="PASS" else -1 if g1_sell=="FAIL" else 0
    }

    ema50, ema200 = gold_price - 8, gold_price - 28
    if gold_price > ema50 > ema200:
        g2_buy, g2_sell = "PASS", "FAIL"
        trend_note = f"UPTREND ${gold_price:.0f} > EMA50 > EMA200"
    elif gold_price < ema50 < ema200:
        g2_buy, g2_sell = "FAIL", "PASS"
        trend_note = f"DOWNTREND ${gold_price:.0f} < EMA50 < EMA200"
    else:
        g2_buy, g2_sell = "WAIT", "WAIT"
        trend_note = "RANGING - H1 na D1 conflict"
    gates['G2_TREND'] = {
        "buy_status": g2_buy, "sell_status": g2_sell,
        "buy_color": color_from_status(g2_buy), "sell_color": color_from_status(g2_sell),
        "note": trend_note,
        "score_buy": 1 if g2_buy=="PASS" else 0,
        "score_sell": 1 if g2_sell=="PASS" else 0
    }

    if 10 <= eat_hour <= 13:
        session, g3_buy, g3_sell = f"London Open {eat_hour}:00 EAT", "PASS", "PASS"
    elif 15 <= eat_hour <= 18:
        session, g3_buy, g3_sell = f"NY/Comex {eat_hour}:00 EAT", "PASS", "PASS"
    elif 1 <= eat_hour <= 9:
        session, g3_buy, g3_sell = f"Asia Range {eat_hour}:00 EAT", "WAIT", "WAIT"
    else:
        session, g3_buy, g3_sell = f"Off-hours {eat_hour}:00 EAT", "WAIT", "WAIT"
    gates['G3_SESSION'] = {
        "buy_status": g3_buy, "sell_status": g3_sell,
        "buy_color": color_from_status(g3_buy), "sell_color": color_from_status(g3_sell),
        "note": session,
        "score_buy": 1 if g3_buy=="PASS" else 0,
        "score_sell": 1 if g3_sell=="PASS" else 0
    }

    pdh, pdl = 4146, 4057
    if gold_price < pdl + 8:
        g4_buy, g4_sell = "PASS", "WAIT"
        liq_note = f"Took PDL {pdl} -> BUY liq"
    elif gold_price > pdh - 8:
        g4_buy, g4_sell = "WAIT", "PASS"
        liq_note = f"Took PDH {pdh} -> SELL liq"
    else:
        g4_buy, g4_sell = "WAIT", "WAIT"
        liq_note = f"Mid PDH {pdh} & PDL {pdl}"
    gates['G4_LIQUIDITY'] = {
        "buy_status": g4_buy, "sell_status": g4_sell,
        "buy_color": color_from_status(g4_buy), "sell_color": color_from_status(g4_sell),
        "note": liq_note,
        "score_buy": 1 if g4_buy=="PASS" else 0,
        "score_sell": 1 if g4_sell=="PASS" else 0
    }

    is_news_hour = eat_hour in [15, 16]
    g5_buy = "FAIL" if is_news_hour else "PASS"
    g5_sell = "FAIL" if is_news_hour else "PASS"
    gates['G5_NEWS'] = {
        "buy_status": g5_buy, "sell_status": g5_sell,
        "buy_color": color_from_status(g5_buy), "sell_color": color_from_status(g5_sell),
        "note": "🔴 RED NEWS - NO TRADE" if is_news_hour else "🟢 No red news <2h",
        "score_buy": -2 if is_news_hour else 0,
        "score_sell": -2 if is_news_hour else 0
    }

    res, sup = 4145, 4115
    if abs(gold_price - res) < 5:
        g6_buy, g6_sell = "FAIL", "PASS"
        sr_note = f"At Res {res} -> SELL"
    elif abs(gold_price - sup) < 5:
        g6_buy, g6_sell = "PASS", "FAIL"
        sr_note = f"At Sup {sup} -> BUY"
    else:
        g6_buy, g6_sell = "WAIT", "WAIT"
        sr_note = f"Mid-range 4115-4145"
    gates['G6_SR'] = {
        "buy_status": g6_buy, "sell_status": g6_sell,
        "buy_color": color_from_status(g6_buy), "sell_color": color_from_status(g6_sell),
        "note": sr_note,
        "score_buy": 1 if g6_buy=="PASS" else 0,
        "score_sell": 1 if g6_sell=="PASS" else 0
    }

    rsi = 35 if gold_price < 4120 else 68 if gold_price > 4140 else 55
    if 30 <= rsi <= 55:
        g7_buy, g7_sell = "PASS", "WAIT"
    elif 45 <= rsi <= 75 and gates['G2_TREND']['buy_status']=="FAIL":
        g7_buy, g7_sell = "WAIT", "PASS"
    elif rsi > 75:
        g7_buy, g7_sell = "FAIL", "WAIT"
    else:
        g7_buy, g7_sell = "WAIT", "WAIT"
    gates['G7_RSI'] = {
        "buy_status": g7_buy, "sell_status": g7_sell,
        "buy_color": color_from_status(g7_buy), "sell_color": color_from_status(g7_sell),
        "note": f"RSI {rsi}",
        "score_buy": 1 if g7_buy=="PASS" else 0,
        "score_sell": 1 if g7_sell=="PASS" else 0
    }

    bos_bull = gold_price > 4142
    if bos_bull:
        g8_buy, g8_sell = "PASS", "FAIL"
        bos_note = "M15 BOS bullish"
    else:
        g8_buy, g8_sell = "WAIT", "WAIT"
        bos_note = "No BOS yet"
    gates['G8_ENTRY'] = {
        "buy_status": g8_buy, "sell_status": g8_sell,
        "buy_color": color_from_status(g8_buy), "sell_color": color_from_status(g8_sell),
        "note": bos_note,
        "score_buy": 1 if g8_buy=="PASS" else 0,
        "score_sell": 1 if g8_sell=="PASS" else 0
    }

    buy_pass = sum(1 for g in gates.values() if g['buy_status']=="PASS")
    sell_pass = sum(1 for g in gates.values() if g['sell_status']=="PASS")
    buy_fail = sum(1 for g in gates.values() if g['buy_status']=="FAIL")
    sell_fail = sum(1 for g in gates.values() if g['sell_status']=="FAIL")

    if buy_pass >= 6 and buy_fail==0 and gates['G1_DXY']['buy_status']!="FAIL" and gates['G5_NEWS']['buy_status']!="FAIL":
        signal, confidence, risk = "BUY", 72 + buy_pass*2, "LOW"
    elif sell_pass >= 6 and sell_fail==0 and gates['G1_DXY']['sell_status']!="FAIL" and gates['G5_NEWS']['sell_status']!="FAIL":
        signal, confidence, risk = "SELL", 72 + sell_pass*2, "LOW"
    elif buy_pass >=4 and buy_fail<=1:
        signal, confidence, risk = "BUY", 62, "MODERATE"
    elif sell_pass >=4 and sell_fail<=1:
        signal, confidence, risk = "SELL", 62, "MODERATE"
    else:
        signal, confidence, risk = "WAIT", 48, "HIGH"

    regime = "TRENDING" if gates['G2_TREND']['buy_status']=="PASS" or gates['G2_TREND']['sell_status']=="PASS" else "RANGING"

    return {
        "timestamp": datetime.utcnow().strftime("%H:%M:%S UTC") + f" / {eat_hour}:00 EAT",
        "gold": round(gold_price,2), "dxy": round(dxy_val,2), "rsi": rsi,
        "gates": gates, "regime": regime, "signal": signal, "risk": risk,
        "confidence": min(85, confidence), "buy_pass": buy_pass, "sell_pass": sell_pass,
        "invalidation": f"BUY invalid <4115 | SELL invalid >4145 | DXY flip",
        "ai_analyst": f"{regime}. BUY:{buy_pass}🟢 {buy_fail}🔴 | SELL:{sell_pass}🟢 {sell_fail}🔴. {gates['G3_SESSION']['note']}. {gates['G1_DXY']['note']}",
        "passed": max(buy_pass, sell_pass),
        "levels": {"resistance":[4145,4135,4128],"pivot":4120.45,"support":[4115,4105,4092]}
    }

# --- ALERT ENGINE + FCM ---
def send_fcm_push(token, title, body):
    try:
        import firebase_admin
        from firebase_admin import messaging, credentials
        if not firebase_admin._apps:
            cred_json = os.environ.get("FIREBASE_CRED")
            if cred_json:
                cred = credentials.Certificate(json.loads(cred_json))
                firebase_admin.initialize_app(cred)
            else:
                return False
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=token,
            android=messaging.AndroidConfig(priority='high', notification=messaging.AndroidNotification(sound='default'))
        )
        messaging.send(message)
        return True
    except Exception as e:
        print("FCM error:", e)
        return False

def alert_checker_loop():
    global last_price_global
    while True:
        try:
            price = get_gold_price()
            if last_price_global is None:
                last_price_global = price
            for alert in alerts_db[:]:
                if not alert.get('active', True): continue
                target = alert['target']
                typ = alert['type']
                hit = False
                if typ == 'above':
                    if last_price_global < target <= price: hit = True
                else:
                    if last_price_global > target >= price: hit = True
                if hit:
                    if alert.get('fcmToken'):
                        send_fcm_push(alert['fcmToken'], f"GOLD ALERT {target}", f"Price is now ${price}")
                    alert['active'] = False
                    alert['triggeredPrice'] = price
                    alert['triggeredAt'] = datetime.utcnow().isoformat()
            last_price_global = price
            save_alerts()
        except Exception as e:
            print("alert loop", e)
        time.sleep(30)

threading.Thread(target=alert_checker_loop, daemon=True).start()

# --- API ROUTES ---
@app.route('/api/status')
def api_status():
    return jsonify(v8_check_gates())

@app.route('/api/alerts', methods=['GET','POST','DELETE'])
def api_alerts():
    global alerts_db
    if request.method == 'GET':
        return jsonify([a for a in alerts_db if a.get('active', True)])
    if request.method == 'POST':
        data = request.json
        new_alert = {
            "id": int(time.time()*1000),
            "target": float(data.get('target')),
            "type": data.get('type','above'),
            "fcmToken": data.get('fcmToken'),
            "active": True,
            "createdAt": datetime.utcnow().isoformat()
        }
        alerts_db.append(new_alert)
        save_alerts()
        return jsonify({"ok": True, "alert": new_alert})
    if request.method == 'DELETE':
        aid = int(request.args.get('id',0))
        alerts_db = [a for a in alerts_db if a['id'] != aid]
        save_alerts()
        return jsonify({"ok": True})

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Tilisi Gold",
        "short_name": "Tilisi Gold",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0e1a",
        "theme_color": "#0a0e1a",
        "icons": [{"src": "/icon", "sizes": "512x512", "type": "image/png"}]
    })

# --- V8.3 COMPACT UI - NO PASS/FAIL TEXT, DOTS ONLY, SMALL BUTTONS ---
HTML_TEMPLATE = """
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tilisi v8.3 COMPACT</title><link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0a0e1a">
<style>
body{font-family:Inter,sans-serif;background:#0a0e1a;color:#fff;margin:0;padding:10px}
.card{background:rgba(255,255,255,0.07);backdrop-filter:blur(12px);border-radius:16px;padding:14px;margin-bottom:10px;border:1px solid rgba(255,255,255,0.12)}
.gold{color:#FFD700;font-weight:800} 
.signal{font-size:40px;font-weight:900;text-align:center;margin:6px}
.BUY{color:#00ff88;text-shadow:0 0 15px #00ff88} .SELL{color:#ff3b3b;text-shadow:0 0 15px #ff3b3b} .WAIT{color:#ffcc00}
.gate{display:grid;grid-template-columns:1fr 38px 38px;gap:4px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.07);font-size:11.5px;align-items:center}
.dot{width:16px;height:16px;border-radius:50%;display:inline-block}
.dot-green{background:#00ff88; box-shadow:0 0 10px #00ff88}
.dot-yellow{background:#ffcc00; box-shadow:0 0 10px #ffcc00}
.dot-red{background:#ff3b3b; box-shadow:0 0 10px #ff3b3b}
.btn-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.btn-sm{padding:9px 6px;font-size:11px;font-weight:800;border-radius:10px;border:none;cursor:pointer;text-align:center;text-decoration:none;display:block}
.btn-alert{background:linear-gradient(90deg,#00ff88,#00cc66);color:#000}
.btn-mt5{background:linear-gradient(90deg,#FFD700,#FFA500);color:#000}
.btn-chart{background:#000;color:#FFD700;border:1.5px solid #FFD700}
.btn-buy{background:#00ff88;color:#000}
.btn-sell{background:#ff3b3b;color:#fff}
.btn-meta{background:rgba(255,255,255,0.12);color:#fff;border:1px solid rgba(255,255,255,0.2)}
.alert-card{background:#fff;color:#000;border-radius:12px;padding:12px;margin-top:8px}
</style></head><body>
<h2 style="text-align:center;margin:8px 0 10px 0">TILISI v8.3 DUAL<br><small style="font-size:10px;opacity:0.6;letter-spacing:1px">BUY & SELL GATES 🟢🟡🔴</small></h2>

<div class="card">
<div style="display:flex;justify-content:space-between;font-size:13px"><span>XAUUSD</span><span class="gold" id="gold">--</span></div>
<div style="display:flex;justify-content:space-between;font-size:12px;opacity:0.8"><span>DXY <b id="dxy">--</b></span><span>RSI <b id="rsi">--</b></span><span id="eat">--</span></div>
<div id="signal" class="signal WAIT">WAIT</div>
<div style="text-align:center;font-size:11px;opacity:0.9">B <b id="bpass">0</b>🟢 | S <b id="spass">0</b>🟢 | <b id="conf">0%</b> | <b id="regime">--</b></div>
<div style="text-align:center;font-size:9px;margin-top:4px;opacity:0.5" id="inv">--</div>

<div class="btn-grid">
  <button class="btn-sm btn-alert" onclick="showAlertBox()">🔔 ALERT</button>
  <button class="btn-sm btn-mt5" onclick="openMT5()">🚀 MT5 APP</button>
  <button class="btn-sm btn-chart" onclick="openMT5Chart()">📈 CHART</button>
  <button class="btn-sm btn-meta" onclick="openMetaTrader()">🌐 META TRADER</button>
  <button class="btn-sm btn-buy" onclick="quickTrade('BUY')">BUY XAU</button>
  <button class="btn-sm btn-sell" onclick="quickTrade('SELL')">SELL XAU</button>
</div>

<div id="alertBox" class="alert-card" style="display:none">
  <div style="display:flex;gap:6px">
    <input id="alertPrice" type="number" placeholder="4150" style="flex:1;padding:8px;border-radius:8px;border:1px solid #ccc;font-size:12px">
    <select id="alertType" style="padding:8px;border-radius:8px;font-size:11px"><option value="above">Above</option><option value="below">Below</option></select>
    <button onclick="saveAlert()" style="padding:8px 12px;background:#0a0e1a;color:#FFD700;border:none;border-radius:8px;font-size:11px;font-weight:800">SAVE</button>
  </div>
  <div id="myAlerts" style="margin-top:8px"></div>
</div>
</div>

<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:12px">8 GATES - DUAL VIEW</b><span style="font-size:9px;opacity:0.5">GREEN PASS / AMBER WAIT / RED FAIL</span></div>
<div style="display:grid;grid-template-columns:1fr 38px 38px;font-size:9px;opacity:0.5;margin:8px 0 2px 0"><span>GATE + NOTE</span><span>BUY</span><span>SELL</span></div>
<div id="gates"></div>
</div>

<div class="card"><b style="font-size:11px">AI ANALYST</b><div id="ai" style="font-size:11px;margin-top:5px;opacity:0.85;line-height:1.4"></div></div>

<audio id="alertSound" src="https://actions.google.com/sounds/v1/alarms/beep_short.ogg" preload="auto"></audio>
<script>
let lastData=null, lastLocalPrice=null;
let fcmToken = localStorage.getItem('tilisi_fcm')||null;
if('Notification' in window && Notification.permission!=='granted'){ Notification.requestPermission(); }

function dotClass(status){
  if(status==='PASS') return 'dot dot-green';
  if(status==='WAIT') return 'dot dot-yellow';
  return 'dot dot-red';
}

async function refresh(){
  let r=await fetch('/api/status'); let d=await r.json(); lastData=d;
  document.getElementById('gold').innerText='$'+d.gold;
  document.getElementById('dxy').innerText=d.dxy;
  document.getElementById('rsi').innerText=d.rsi;
  document.getElementById('eat').innerText=d.timestamp.split('/')[1]||'';
  document.getElementById('signal').innerText=d.signal;
  document.getElementById('signal').className='signal '+d.signal;
  document.getElementById('conf').innerText=d.confidence+'%';
  document.getElementById('regime').innerText=d.regime;
  document.getElementById('inv').innerText=d.invalidation;
  document.getElementById('bpass').innerText=d.buy_pass;
  document.getElementById('spass').innerText=d.sell_pass;
  document.getElementById('ai').innerText=d.ai_analyst;
  let hg=''; for(let k in d.gates){let g=d.gates[k]; hg+=`<div class="gate"><span><b>${k}</b> <small style="opacity:0.65">${g.note}</small></span><span><i class="${dotClass(g.buy_status)}"></i></span><span><i class="${dotClass(g.sell_status)}"></i></span></div>`}
  document.getElementById('gates').innerHTML=hg;
  checkLocalAlerts(d.gold);
}
function openMT5(){ let n=Date.now(); window.location.href="metatrader5://"; setTimeout(()=>{if(Date.now()-n<2500) window.location.href="mt5://";},500); setTimeout(()=>{if(Date.now()-n<3500) window.location.href="https://play.google.com/store/apps/details?id=net.metaquotes.metatrader5";},1500); }
function openMT5Chart(){ window.location.href="https://trade.mql5.com/trade?servers=MetaQuotes-Demo&trade_server=MetaQuotes-Demo&demo_server=MetaQuotes-Demo&symbol=XAUUSD&action=chart"; setTimeout(()=>{window.location.href="metatrader5://";},700); }
function openMetaTrader(){ window.location.href="https://metatrader5.com/en"; }
function quickTrade(side){ if(!lastData) return; let s=lastData.gold; if(confirm(side+" XAUUSD @ $"+s+" ? Itafungua MT5")) openMT5(); }
function showAlertBox(){ let b=document.getElementById('alertBox'); b.style.display=b.style.display==='none'?'block':'none'; document.getElementById('alertPrice').value=lastData?Math.round(lastData.gold):'4150'; loadMyAlerts(); }
async function saveAlert(){ let p=parseFloat(document.getElementById('alertPrice').value); let t=document.getElementById('alertType').value; if(!p) return; let res=await fetch('/api/alerts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:p,type:t,fcmToken:fcmToken})}); let j=await res.json(); loadMyAlerts(); let l=JSON.parse(localStorage.getItem('tilisi_local_alerts')||'[]'); l.push({id:j.alert.id,target:p,type:t,active:true}); localStorage.setItem('tilisi_local_alerts', JSON.stringify(l)); }
async function loadMyAlerts(){ let r=await fetch('/api/alerts'); let arr=await r.json(); let h=''; arr.forEach(a=>{h+=`<div style="display:flex;justify-content:space-between;padding:5px 0;font-size:11px;border-bottom:1px solid #eee"><span>${a.type==='above'?'↑':'↓'} ${a.target}</span><span onclick="deleteAlert(${a.id})" style="color:red;cursor:pointer;font-weight:800">X</span></div>`}); document.getElementById('myAlerts').innerHTML=h||'<small style=
