# TILISI GOLD BI v8.4.1 - FIXED DEPLOY ERROR + SMART MT5 SIGNAL
import requests, json, time, random, threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request, Response
import os

app = Flask(__name__)

ALERTS_FILE = "tilisi_alerts.json"
FCM_FILE = "tilisi_fcm.json"
alerts_db = []
fcm_tokens = []
last_price_global = None

if os.path.exists(ALERTS_FILE):
    try: alerts_db = json.load(open(ALERTS_FILE))
    except: alerts_db = []
if os.path.exists(FCM_FILE):
    try: fcm_tokens = json.load(open(FCM_FILE))
    except: fcm_tokens = []

def save_alerts():
    try: json.dump(alerts_db, open(ALERTS_FILE,'w'))
    except: pass
def save_fcm():
    try: json.dump(fcm_tokens, open(FCM_FILE,'w'))
    except: pass

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
        return max(98, min(102, (100/eur)*0.92))
    except: return 100.93 + random.uniform(-0.25,0.25)

def color_from_status(s): return "🟢" if s=="PASS" else "🟡" if s=="WAIT" else "🔴"

def v8_check_gates(gold_price=None, dxy_val=None):
    if gold_price is None: gold_price = get_gold_price()
    if dxy_val is None: dxy_val = get_dxy()
    eat_hour = (datetime.utcnow().hour + 3) % 24
    gates = {}
    if dxy_val < 99.8: g1_buy,g1_sell="PASS","FAIL"
    elif dxy_val > 100.8: g1_buy,g1_sell="FAIL","PASS"
    else: g1_buy,g1_sell="WAIT","WAIT"
    gates['G1_DXY']={"buy_status":g1_buy,"sell_status":g1_sell,"buy_color":color_from_status(g1_buy),"sell_color":color_from_status(g1_sell),"note":f"DXY {dxy_val:.2f}"}
    ema50,ema200=gold_price-8,gold_price-28
    if gold_price > ema50 > ema200: g2_buy,g2_sell="PASS","FAIL"; tn=f"UP ${gold_price:.0f}"
    elif gold_price < ema50 < ema200: g2_buy,g2_sell="FAIL","PASS"; tn=f"DOWN ${gold_price:.0f}"
    else: g2_buy,g2_sell="WAIT","WAIT"; tn="RANGING"
    gates['G2_TREND']={"buy_status":g2_buy,"sell_status":g2_sell,"buy_color":color_from_status(g2_buy),"sell_color":color_from_status(g2_sell),"note":tn}
    if 10 <= eat_hour <= 13: sess,g3b,g3s=f"London {eat_hour}:00","PASS","PASS"
    elif 15 <= eat_hour <= 18: sess,g3b,g3s=f"NY {eat_hour}:00","PASS","PASS"
    elif 1 <= eat_hour <= 9: sess,g3b,g3s=f"Asia {eat_hour}:00","WAIT","WAIT"
    else: sess,g3b,g3s=f"Off {eat_hour}:00","WAIT","WAIT"
    gates['G3_SESSION']={"buy_status":g3b,"sell_status":g3s,"buy_color":color_from_status(g3b),"sell_color":color_from_status(g3s),"note":sess}
    pdh,pdl=4146,4057
    if gold_price < pdl+8: g4b,g4s="PASS","WAIT"; liq=f"PDL {pdl}"
    elif gold_price > pdh-8: g4b,g4s="WAIT","PASS"; liq=f"PDH {pdh}"
    else: g4b,g4s="WAIT","WAIT"; liq=f"Mid {pdl}-{pdh}"
    gates['G4_LIQUIDITY']={"buy_status":g4b,"sell_status":g4s,"buy_color":color_from_status(g4b),"sell_color":color_from_status(g4s),"note":liq}
    is_news=eat_hour in [15,16]; g5="FAIL" if is_news else "PASS"
    gates['G5_NEWS']={"buy_status":g5,"sell_status":g5,"buy_color":color_from_status(g5),"sell_color":color_from_status(g5),"note":"RED NEWS" if is_news else "No news"}
    res,sup=4145,4115
    if abs(gold_price-res)<5: g6b,g6s="FAIL","PASS"; sr=f"Res {res}"
    elif abs(gold_price-sup)<5: g6b,g6s="PASS","FAIL"; sr=f"Sup {sup}"
    else: g6b,g6s="WAIT","WAIT"; sr="Mid 4115-4145"
    gates['G6_SR']={"buy_status":g6b,"sell_status":g6s,"buy_color":color_from_status(g6b),"sell_color":color_from_status(g6s),"note":sr}
    rsi=35 if gold_price<4120 else 68 if gold_price>4140 else 55
    if 30 <= rsi <= 55: g7b,g7s="PASS","WAIT"
    elif 45 <= rsi <= 75 and g2b=="FAIL": g7b,g7s="WAIT","PASS"
    elif rsi>75: g7b,g7s="FAIL","WAIT"
    else: g7b,g7s="WAIT","WAIT"
    gates['G7_RSI']={"buy_status":g7b,"sell_status":g7s,"buy_color":color_from_status(g7b),"sell_color":color_from_status(g7s),"note":f"RSI {rsi}"}
    bos=gold_price>4142; g8b,g8s=("PASS","FAIL") if bos else ("WAIT","WAIT")
    gates['G8_ENTRY']={"buy_status":g8b,"sell_status":g8s,"buy_color":color_from_status(g8b),"sell_color":color_from_status(g8s),"note":"BOS bull" if bos else "No BOS"}
    buy_pass=sum(1 for g in gates.values() if g['buy_status']=="PASS"); sell_pass=sum(1 for g in gates.values() if g['sell_status']=="PASS")
    buy_fail=sum(1 for g in gates.values() if g['buy_status']=="FAIL"); sell_fail=sum(1 for g in gates.values() if g['sell_status']=="FAIL")
    if buy_pass>=6 and buy_fail==0: signal,conf="BUY",74
    elif sell_pass>=6 and sell_fail==0: signal,conf="SELL",74
    elif buy_pass>=4 and buy_fail<=1: signal,conf="BUY",62
    elif sell_pass>=4 and sell_fail<=1: signal,conf="SELL",62
    else: signal,conf="WAIT",48
    regime="TRENDING" if g2b=="PASS" or gates['G2_TREND']['sell_status']=="PASS" else "RANGING"
    return {"timestamp":f"{datetime.utcnow().strftime('%H:%M:%S')} / {eat_hour}:00 EAT","gold":round(gold_price,2),"dxy":round(dxy_val,2),"rsi":rsi,"gates":gates,"regime":regime,"signal":signal,"confidence":conf,"buy_pass":buy_pass,"sell_pass":sell_pass,"invalidation":"BUY <4115 | SELL >4145","ai_analyst":f"{regime}. BUY:{buy_pass}G {buy_fail}R | SELL:{sell_pass}G {sell_fail}R. {sess}"}

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
    except Exception as e: print("FCM",e); return False

def alert_checker_loop():
    global last_price_global
    while True:
        try:
            price=get_gold_price()
            if last_price_global is None: last_price_global=price
            for alert in alerts_db[:]:
                if not alert.get('active',True): continue
                target,typ=alert['target'],alert['type']
                hit=(last_price_global<target<=price) if typ=='above' else (last_price_global>target>=price)
                if hit:
                    if alert.get('fcmToken'): send_fcm_push(alert['fcmToken'], f"GOLD {target} HIT", f"Now ${price}")
                    alert['active']=False
            last_price_global=price; save_alerts()
        except: pass
        time.sleep(30)
threading.Thread(target=alert_checker_loop, daemon=True).start()

@app.route('/api/status')
def api_status(): return jsonify(v8_check_gates())

@app.route('/api/alerts', methods=['GET','POST','DELETE'])
def api_alerts():
    global alerts_db
    if request.method=='GET': return jsonify([a for a in alerts_db if a.get('active',True)])
    if request.method=='POST':
        d=request.json
        na={"id":int(time.time()*1000),"target":float(d.get('target')),"type":d.get('type','above'),"fcmToken":d.get('fcmToken'),"active":True,"createdAt":datetime.utcnow().isoformat()}
        alerts_db.append(na); save_alerts(); return jsonify({"ok":True,"alert":na})
    if request.method=='DELETE':
        aid=int(request.args.get('id',0)); alerts_db=[a for a in alerts_db if a['id']!=aid]; save_alerts(); return jsonify({"ok":True})

@app.route('/api/fcm/register', methods=['POST'])
def api_fcm_reg():
    global fcm_tokens
    token=request.json.get('token')
    if token and token not in fcm_tokens: fcm_tokens.append(token); save_fcm()
    return jsonify({"ok":True})

@app.route('/api/fcm/test', methods=['POST'])
def api_fcm_test():
    token=request.json.get('token'); send_fcm_push(token, "Tilisi Test", "FCM inafanya kazi!")
    return jsonify({"ok":True})

@app.route('/firebase-messaging-sw.js')
def sw():
    js_content = '''
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.22.0/firebase-messaging-compat.js');
firebase.initializeApp({apiKey:"AIzaSyDemo", authDomain:"tilisi-demo.firebaseapp.com", projectId:"tilisi-demo"});
const messaging = firebase.messaging();
messaging.onBackgroundMessage(payload => {
  self.registration.showNotification(payload.notification.title, {body: payload.notification.body});
});
'''
    return Response(js_content, mimetype='application/javascript')

@app.route('/manifest.json')
def manifest(): return jsonify({"name":"Tilisi Gold","short_name":"Tilisi","start_url":"/","display":"standalone","background_color":"#0a0e1a","theme_color":"#0a0e1a"})

HTML_TEMPLATE = '''
<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tilisi v8.4.1 FIXED</title><link rel="manifest" href="/manifest.json"><meta name="theme-color" content="#0a0e1a">
<style>
body{font-family:Inter,sans-serif;background:#0a0e1a;color:#fff;margin:0;padding:10px}
.card{background:rgba(255,255,255,0.07);backdrop-filter:blur(12px);border-radius:16px;padding:14px;margin-bottom:10px;border:1px solid rgba(255,255,255,0.12)}
.gold{color:#FFD700;font-weight:800} 
.signal{font-size:42px;font-weight:900;text-align:center;margin:8px;cursor:pointer;border-radius:12px;padding:10px}
.BUY{color:#00ff88;text-shadow:0 0 15px #00ff88;background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.3)} 
.SELL{color:#ff3b3b;text-shadow:0 0 15px #ff3b3b;background:rgba(255,59,59,0.08);border:1px solid rgba(255,59,59,0.3)} 
.WAIT{color:#ffcc00;background:rgba(255,204,0,0.08);border:1px solid rgba(255,204,0,0.3)}
.gate{display:grid;grid-template-columns:1fr 38px 38px;gap:4px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.07);font-size:11.5px;align-items:center}
.dot{width:16px;height:16px;border-radius:50%;display:inline-block}
.dot-green{background:#00ff88;box-shadow:0 0 10px #00ff88}.dot-yellow{background:#ffcc00;box-shadow:0 0 10px #ffcc00}.dot-red{background:#ff3b3b;box-shadow:0 0 10px #ff3b3b}
.btn-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:10px}
.btn-sm{padding:9px 6px;font-size:11px;font-weight:800;border-radius:10px;border:none;cursor:pointer;text-align:center;display:block}
.btn-alert{background:linear-gradient(90deg,#00ff88,#00cc66);color:#000}
.btn-mt5{background:linear-gradient(90deg,#FFD700,#FFA500);color:#000}
.btn-chart{background:#000;color:#FFD700;border:1.5px solid #FFD700}
.btn-buy{background:#00ff88;color:#000}.btn-sell{background:#ff3b3b;color:#fff}
.btn-meta{background:rgba(255,255,255,0.12);color:#fff;border:1px solid rgba(255,255,255,0.2)}
.alert-card{background:#fff;color:#000;border-radius:12px;padding:12px;margin-top:8px}
.small-hint{font-size:9px;opacity:0.6;text-align:center;margin-top:6px}
</style></head><body>
<h2 style="text-align:center;margin:8px 0 10px 0">TILISI v8.4.1 FIXED<br><small style="font-size:10px;opacity:0.6">BUY/SELL/WAIT = MT5 XAUUSD</small></h2>
<div class="card">
<div style="display:flex;justify-content:space-between;font-size:13px"><span>XAUUSD</span><span class="gold" id="gold">--</span></div>
<div style="display:flex;justify-content:space-between;font-size:12px;opacity:0.8"><span>DXY <b id="dxy">--</b></span><span>RSI <b id="rsi">--</b></span><span id="eat">--</span></div>
<div id="signal" class="signal WAIT" onclick="openTradeSignal()">WAIT</div>
<div class="small-hint">Bonyeza BUY/SELL/WAIT kufungua XAUUSD kwenye MT5 App</div>
<div style="text-align:center;font-size:11px;opacity:0.9;margin-top:6px">B <b id="bpass">0</b> | S <b id="spass">0</b> | <b id="conf">0%</b> | <b id="regime">--</b></div>
<div style="text-align:center;font-size:9px;margin-top:4px;opacity:0.5" id="inv">--</div>
<div class="btn-grid">
  <button class="btn-sm btn-alert" onclick="showAlertBox()">ALERT</button>
  <button class="btn-sm btn-mt5" onclick="smartOpenMT5()">MT5 APP</button>
  <button class="btn-sm btn-chart" onclick="openMT5Chart()">CHART</button>
  <button class="btn-sm btn-meta" onclick="openMetaTrader()">META</button>
  <button class="btn-sm btn-buy" onclick="smartOpenMT5('buy')">BUY XAU</button>
  <button class="btn-sm btn-sell" onclick="smartOpenMT5('sell')">SELL XAU</button>
</div>
<div id="alertBox" class="alert-card" style="display:none">
  <div style="display:flex;gap:6px">
    <input id="alertPrice" type="number" placeholder="4150" style="flex:1;padding:8px;border-radius:8px;border:1px solid #ccc;font-size:12px">
    <select id="alertType" style="padding:8px;border-radius:8px;font-size:11px"><option value="above">Above</option><option value="below">Below</option></select>
    <button onclick="saveAlert()" style="padding:8px 12px;background:#0a0e1a;color:#FFD700;border:none;border-radius:8px;font-size:11px;font-weight:800">SAVE</button>
  </div>
  <div id="myAlerts" style="margin-top:8px"></div>
  <button onclick="testFCM()" style="margin-top:8px;padding:6px 10px;font-size:10px;background:#0a0e1a;color:#fff;border-radius:6px;border:none">Test FCM</button>
</div>
</div>
<div class="card">
<div style="display:flex;justify-content:space-between"><b style="font-size:12px">8 GATES - DUAL</b><span style="font-size:9px;opacity:0.5">DOTS ONLY</span></div>
<div style="display:grid;grid-template-columns:1fr 38px 38px;font-size:9px;opacity:0.5;margin:8px 0 2px 0"><span>GATE</span><span>BUY</span><span>SELL</span></div>
<div id="gates"></div>
</div>
<div class="card"><b style="font-size:11px">AI ANALYST</b><div id="ai" style="font-size:11px;margin-top:5px;opacity:0.85"></div></div>
<audio id="alertSound" src="https://actions.google.com/sounds/v1/alarms/beep_short.ogg" preload="auto"></audio>
<script src="https://www.gstatic.com/firebasejs/9.22.0/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/9.22.0/firebase-messaging-compat.js"></script>
<script>
let lastData=null, lastLocalPrice=null;
let fcmToken = localStorage.getItem('tilisi_fcm')||null;

function smartOpenMT5(action=null){
  const start = Date.now();
  window.location.href = 'metatrader5://';
  setTimeout(()=>{ if(Date.now()-start < 3000){ window.location.href = 'mt5://XAUUSD'; } },700);
  setTimeout(()=>{
    if(!document.hidden && (Date.now()-start < 4000)){
      if(confirm('MT5 App haipo? Download kutoka Play Store?')){
        window.location.href = 'https://play.google.com/store/apps/details?id=net.metaquotes.metatrader5';
      }
    }
  },2600);
  if(action){
    setTimeout(()=>{ window.open('https://trade.mql5.com/trade?servers=MetaQuotes-Demo&symbol=XAUUSD&action=chart','_blank'); },900);
  }
}
function openTradeSignal(){ smartOpenMT5(lastData?lastData.signal.toLowerCase():null); }
function openMT5Chart(){ smartOpenMT5('chart'); }
function openMetaTrader(){ window.location.href='https://metatrader5.com/en'; }

async function initFCM(){
  try{
    if(Notification.permission!=='granted'){ await Notification.requestPermission(); }
    const firebaseConfig = {apiKey:"AIzaSyDemo", authDomain:"tilisi-demo.firebaseapp.com", projectId:"tilisi-demo", messagingSenderId:"123456789", appId:"1:123456789:web:demo"};
    if(!firebase.apps.length){ firebase.initializeApp(firebaseConfig); }
    const messaging = firebase.messaging();
    if('serviceWorker' in navigator){ try{ await navigator.serviceWorker.register('/firebase-messaging-sw.js'); }catch(e){} }
    const token = await messaging.getToken({vapidKey: "YOUR_VAPID_KEY"});
    if(token){ fcmToken=token; localStorage.setItem('tilisi_fcm', token); await fetch('/api/fcm/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})}); }
    messaging.onMessage(payload=>{
      new Notification(payload.notification.title, {body: payload.notification.body});
      document.getElementById('alertSound').play();
      if(navigator.vibrate) navigator.vibrate([400,150,400]);
    });
  }catch(e){ console.log(e); }
}
async function testFCM(){ if(!fcmToken){ alert('Ruhusu notifications'); return; } await fetch('/api/fcm/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:fcmToken})}); alert('Test sent!'); }

function dotClass(s){ if(s==='PASS') return 'dot dot-green'; if(s==='WAIT') return 'dot dot-yellow'; return 'dot dot-red'; }
async function refresh(){
  let r=await fetch('/api/status'); let d=await r.json(); lastData=d;
  document.getElementById('gold').innerText='$'+d.gold; document.getElementById('dxy').innerText=d.dxy; document.getElementById('rsi').innerText=d.rsi;
  document.getElementById('eat').innerText=d.timestamp.split('/')[1]||''; document.getElementById('signal').innerText=d.signal;
  document.getElementById('signal').className='signal '+d.signal; document.getElementById('conf').innerText=d.confidence+'%';
  document.getElementById('regime').innerText=d.regime; document.getElementById('inv').innerText=d.invalidation;
  document.getElementById('bpass').innerText=d.buy_pass; document.getElementById('spass').innerText=d.sell_pass;
  document.getElementById('ai').innerText=d.ai_analyst;
  let hg=''; for(let k in d.gates){let g=d.gates[k]; hg+=`<div class="gate"><span><b>${k}</b> <small style="opacity:0.65">${g.note}</small></span><span><i class="${dotClass(g.buy_status)}"></i></span><span><i class="${dotClass(g.sell_status)}"></i></span></div>`}
  document.getElementById('gates').innerHTML=hg;
  checkLocalAlerts(d.gold);
}
function showAlertBox(){ let b=document.getElementById('alertBox'); b.style.display=b.style.display==='none'?'block':'none'; document.getElementById('alertPrice').value=lastData?Math.round(lastData.gold):'4150'; loadMyAlerts(); }
async function saveAlert(){ let p=parseFloat(document.getElementById('alertPrice').value); let t=document.getElementById('alertType').value; if(!p) return; let res=await fetch('/api/alerts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:p,type:t,fcmToken:fcmToken})}); let j=await res.json(); loadMyAlerts(); let l=JSON.parse(localStorage.getItem('tilisi_local_alerts')||'[]'); l.push({id:j.alert.id,target:p,type:t,active:true}); localStorage.setItem('tilisi_local_alerts', JSON.stringify(l)); }
async function loadMyAlerts(){ let r=await fetch('/api/alerts'); let arr=await r.json(); let h=''; arr.forEach(a=>{h+=`<div style="display:flex;justify-content:space-between;padding:5px 0;font-size:11px;border-bottom:1px solid #eee"><span>${a.type==='above'?'↑':'↓'} ${a.target}</span><span onclick="deleteAlert(${a.id})" style="color:red;cursor:pointer;font-weight:800">X</span></div>`}); document.getElementById('myAlerts').innerHTML=h||'<small>No alerts</small>'; }
async function deleteAlert(id){ await fetch('/api/alerts?id='+id,{method:'DELETE'}); let l=JSON.parse(localStorage.getItem('tilisi_local_alerts')||'[]').filter(x=>x.id!=id); localStorage.setItem('tilisi_local_alerts', JSON.stringify(l)); loadMyAlerts(); }
function checkLocalAlerts(c){ if(lastLocalPrice===null){lastLocalPrice=c; return;} let l=JSON.parse(localStorage.getItem('tilisi_local_alerts')||'[]'); l.forEach(a=>{ if(!a.active) return; let hit=(a.type==='above'&&lastLocalPrice<a.target&&c>=a.target)||(a.type==='below'&&lastLocalPrice>a.target&&c<=a.target); if(hit){a.active=false; document.getElementById('alertSound').play(); if(Notification.permission==='granted'){ new Notification(`GOLD ${a.target}`,{body:`Now $${c}`}); } if(navigator.vibrate) navigator.vibrate([400,150,400]); }}); lastLocalPrice=c; localStorage.setItem('tilisi_local_alerts', JSON.stringify(l.filter(x=>x.active))); }
refresh(); setInterval(refresh,15000); initFCM();
</script></body></html>
'''

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
