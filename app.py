import requests, base64, os
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# ====== MPESA SANDBOX CREDENTIALS (Tilisi Gold) ======
CONSUMER_KEY = "tpy9Qnbh85PxX4..."
CONSUMER_SECRET = "zcXI7iFnc0PrV..."
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd..."
SHORTCODE = 174379  # Test - baadaye utaweka Buy Goods Till yako
CALLBACK_URL = "https://yourdomain.com/callback" # Tutaiweka baadaye

def get_access_token():
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    auth = base64.b64encode(f"{CONSUMER_KEY}:{CONSUMER_SECRET}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    res = requests.get(url, headers=headers).json()
    return res['access_token']

@app.route('/stk-push', methods=['POST'])
def stk_push():
    data = request.json
    phone = data.get('phone') # 2547...
    amount = data.get('amount', 1)
    
    token = get_access_token()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{SHORTCODE}{PASSKEY}{timestamp}".encode()).decode()
    
    payload = {
        "BusinessShortCode": SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": "TilisiGold",
        "TransactionDesc": "Gold Signals Subscription"
    }
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processquery"
    res = requests.post(url, json=payload, headers=headers).json()
    return jsonify(res)

if __name__ == "__main__":
    app.run()