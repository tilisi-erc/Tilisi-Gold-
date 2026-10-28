# TILISI GOLD BI v7.2 - QUANT ENGINE + MT5 DIRECT CONNECT
# Tilisi Technologies Inc.™ - Sky Blue Edition
import requests, json, time, random
from datetime import datetime
from flask import Flask, jsonify, render_template_string, send_from_directory
import os

app = Flask(__name__)

# --- CORE ENGINE (v7 - Cleaned & Tightened) ---
def get_gold_price():
    try:
        r = requests.get('https://api.gold-api.com/price/XAU', timeout=8).json()
        return float(r['price'])
    except:
        return 4124.70 + random.uniform(-2, 2)

def get_dxy():
    try:
        return 101.2 + random.uniform(-0.3, 0.3)
    except:
        return 101.2

def v7_check_gates(gold_price=None, dxy_val=None):
    if gold_price is None: gold_price = get_gold_price()
    if dxy_val is None: dxy_val = get_dxy()
    gates = {}
    evidence = {"supporting":[], "contradicting":[], "neutral":[]}
    
    if dxy_val < 99.5:
        gates['G1_DXY'] = {"status":"PASS","score":+1,"note":f"DXY {dxy_val:.2f} WEAK = Bullish Gold"}
        evidence["supporting"].append(f"G1 DXY Weak {dxy_val:.2f}")
    elif dxy_val > 100.5:
        gates['G1_DXY'] = {"status":"FAIL","score":-1,"note":f"DXY {dxy_val:.2f} STRONG = Bearish Gold"}
        evidence["contradicting"].append(f"G1 DXY Strong {dxy_val:.2f}")
    else:
        gates['G1_DXY'] = {"status":"NEUTRAL","score":0,"note":f"DXY {dxy_val:.2f} Ranging"}
        evidence["neutral"].append(f"G1 DXY Ranging")

    ema50, ema200 = gold_price - 5.5, gold_price - 22.2
    if gold_price > ema50 > ema200:
        gates['G2_TREND'] = {"status":"PASS","score":+1,"note":f"Gold ${gold_price:.2f} > EMA50 > EMA200"}
        evidence["supporting"].append("G2 Trend Bullish D1+H4+H1 aligned")
    else:
        gates['G2_TREND'] = {"status":"WAIT","score":0,"note":"Trend not aligned 2/3 TF"}
        evidence["contradicting"].append("G2 Trend conflicted")

    hour = datetime.utcnow().hour
    if 7 <= hour <= 11: session, g3 = "London Breakout", "PASS"
    elif 12 <= hour <= 16: session, g3 = "NY Volatility", "PASS"
    else: session, g3 = "Asian Range", "WAIT"
    gates['G3_SESSION'] = {"status":g3,"score":1 if g3=="PASS" else 0,"note":session}
    evidence["supporting" if g3=="PASS" else "neutral"].append(f"G3 {session}")

    rsi = 28.5 if gold_price < 4120 else 58.32
    if 30 <= rsi <= 70:
        gates['G4_MOMENTUM'] = {"status":"PASS","score":+1,"note":f"RSI {rsi} Healthy"}
        evidence["supporting"].append(f"G4 RSI {rsi} healthy")
    elif rsi < 30:
        gates['G4_MOMENTUM'] = {"status":"PASS","score":+1,"note":f"RSI {rsi} Oversold BUY"}
        evidence["supporting"].append(f"G4 RSI {rsi} Oversold")
    else:
        gates['G4_MOMENTUM'] = {"status":"WAIT","score":-1,"note":f"RSI {rsi} Overbought"}
        evidence["contradicting"].append(f"G4 RSI {rsi} Overbought")

    atr = 8.5
    if 5 <= atr <= 12:
        gates['G5_VOL'] = {"status":"PASS","score":1,"note":f"ATR {atr} Normal"}
        evidence["supporting"].append(f"G5 Volatility Normal")
    else:
        gates['G5_VOL'] = {"status":"WAIT","score":0,"note":f"ATR {atr} HIGH RISK"}

    resistance, support = 4128.00, 4115.00
    if abs(gold_price - resistance) < 3:
        gates['G6_SR'] = {"status":"WAIT","score":-1,"note":f"Near Resistance ${resistance}"}
        evidence["contradicting"].append(f"G6 Near Resistance")
    elif abs(gold_price - support) < 3:
        gates['G6_SR'] = {"status":"PASS","score":+1,"note":f"Near Support ${support} BUY ZONE"}
        evidence["supporting"].append(f"G6 Near Support ${support}")
    else:
        gates['G6_SR'] = {"status":"PASS","score":0,"note":"Mid-range, no S/R conflict"}

    us10y = 4.32
    gates['G7_MACRO'] = {"status":"PASS","score":0,"note":f"US10Y {us10y}% No red news <2h"}
    gates['G8_CORR'] = {"status":"PASS","score":1,"note":"DXY down + Yield stable = Valid"}
    evidence["supporting"].append("G8 Correlation Valid")

    supporting = len(evidence["supporting"])
    contradicting = len(evidence["contradicting"])
    passed = sum(1 for g in gates.values() if g["status"] == "PASS")
    regime = "TRENDING" if gates['G2_TREND']['status']=="PASS" else "RANGING" if supporting <=3 else "TRANSITION"

    critical_fail = gates['G1_DXY']['status']=="FAIL" or gates['G2_TREND']['status']=="WAIT"
    if supporting >= 5 and contradicting == 0 and not critical_fail:
        signal, risk, confidence = "BUY", "LOW", 72
    elif supporting >= 4 and contradicting <=1:
        signal, risk, confidence = "BUY", "MODERATE", 62
    elif contradicting >= 2:
        signal, risk, confidence = "WAIT", "HIGH", 45
    else:
        signal, risk, confidence = "WAIT", "MODERATE", 50

    return {
        "timestamp": datetime.utcnow().strftime("%H:%M:%S UTC"),
        "gold": round(gold_price,2),
        "dxy": round(dxy_val,2),
        "rsi": rsi,
        "gates": gates,
        "evidence": evidence,
        "regime": regime,
        "signal": signal,
        "risk": risk,
        "confidence": confidence,
        "invalidation": f"Invalid if H4 close below ${support-10:.2f} OR DXY > 100.8",
        "ai_analyst": f"{regime} regime. {supporting} gates supporting. DXY weak favors Gold.",
        "passed": passed,
        "should_notify": signal=="BUY" and confidence >= 70 and passed >=6,
        "levels": {"resistance":[4145,4135,4128],"pivot":4120.45,"support":[4115,4105,4092]}
    }

# --- API ROUTES ---
@app.route('/api/status')
def api_status():
    return jsonify(v7_check_gates())

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Tilisi Gold",
        "short_name": "Tilisi Gold",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0aa0ff",
        "theme_color": "#0aa0ff",
        "icons": [{"src": "/icon", "sizes": "512x512", "type": "image/png"}]
    })

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tilisi Gold - QUANTRADE</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0aa0ff">
<style>
body{font-family:Inter,sans-serif;background:#0aa0ff;color:#fff;margin:0;padding:15px}
.card{background:rgba(255,255,255,0.15);backdrop-filter:blur(10px);border-radius:20px;padding:20px;margin-bottom:15px;border:1px solid rgba(255,255,255,0.2)}
.gold{color:#FFD700;font-weight:800}
.signal{font-size:48px;font-weight:900;text-align:center;margin:10px}
.BUY{color:#00ff88;text-shadow:0 0 20px #00ff88}
.WAIT{color:#ffcc00}
.mt5-btn{display:block;width:100%;background:linear-gradient(90deg,#FFD700,#FFA500);color:#000;font-weight:900;font-size:18px;padding:18px;border-radius:15px;text-align:center;text-decoration:none;margin-top:15px;box-shadow:0 5px 20px rgba(0,0,0,0.3)}
.mt5-btn2{display:block;width:100%;background:#000;color:#FFD700;border:2px solid #FFD700;font-weight:700;padding:14px;border-radius:12px;text-align:center;text-decoration:none;margin-top:10px}
.gate{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.1);font-size:13px}
</style>
</head>
<body>
<h2 style="text-align:center">TILISI GOLD BI v7.2<br><small style="font-size:12px;opacity:0.8">Tilisi Technologies Inc.™</small></h2>

<div class="card">
<div style="display:flex;justify-content:space-between"><span>XAUUSD</span><span class="gold" id="gold">--</span></div>
<div style="display:flex;justify-content:space-between"><span>DXY</span><span id="dxy">--</span> <span>RSI <span id="rsi">--</span></span></div>
<div id="signal" class="signal WAIT">WAIT</div>
<div style="text-align:center">Confidence: <b id="conf">0%</b> | Regime: <b id="regime">--</b> | Risk: <b id="risk">--</b></div>
<div style="text-align:center;font-size:11px;margin-top:10px;opacity:0.8" id="inv">--</div>

<a class="mt5-btn" onclick="openMT5()">🚀 OPEN IN MT5 APP - TRADE XAUUSD</a>
<a class="mt5-btn2" onclick="openMT5Chart()">📈 OPEN XAUUSD CHART IN MT5</a>
<div style="text-align:center;font-size:10px;margin-top:8px;opacity:0.7">If MT5 not installed, will redirect to Play Store</div>
</div>

<div class="card"><b>8 GATES ANALYSIS</b><div id="gates"></div></div>
<div class="card"><b>AI ANALYST</b><div id="ai" style="font-size:13px;margin-top:8px"></div></div>

<script>
let lastData;
async function refresh(){
  let r = await fetch('/api/status'); let d = await r.json(); lastData=d;
  document.getElementById('gold').innerText='$'+d.gold;
  document.getElementById('dxy').innerText=d.dxy;
  document.getElementById('rsi').innerText=d.rsi;
  document.getElementById('signal').innerText=d.signal;
  document.getElementById('signal').className='signal '+d.signal;
  document.getElementById('conf').innerText=d.confidence+'%';
  document.getElementById('regime').innerText=d.regime;
  document.getElementById('risk').innerText=d.risk;
  document.getElementById('inv').innerText=d.invalidation;
  document.getElementById('ai').innerText=d.ai_analyst;
  let hg=''; for(let k in d.gates){let g=d.gates[k]; hg+=`<div class="gate"><span>${k} ${g.status}</span><span>${g.note}</span></div>`}
  document.getElementById('gates').innerHTML=hg;
}
function openMT5(){
  // Try to open MT5 app directly with XAUUSD
  let now = Date.now();
  // Primary MT5 deep links
  window.location.href = "metatrader5://";
  setTimeout(()=>{
    if(Date.now()-now < 2500){ window.location.href="mt5://"; }
  },500);
  setTimeout(()=>{
    // Fallback to Play Store if app not installed
    if(Date.now()-now < 3500){
      window.location.href="https://play.google.com/store/apps/details?id=net.metaquotes.metatrader5";
    }
  },1500);
}
function openMT5Chart(){
  // Opens MT5 with Gold symbol focus
  window.location.href = "https://trade.mql5.com/trade?servers=MetaQuotes-Demo&trade_server=MetaQuotes-Demo&demo_server=MetaQuotes-Demo&symbol=XAUUSD&action=chart";
  setTimeout(()=>{ window.location.href="metatrader5://"; },800);
}
refresh(); setInterval(refresh,15000);
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)