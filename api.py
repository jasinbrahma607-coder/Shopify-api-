from flask import Flask, request, jsonify
import requests
import json
import logging
import re
from datetime import datetime

# =============== CONFIGURATION ===============
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =============== HELPERS ===============
def extract_cc(text):
    """Extract card number, month, year, CVV from a string like 'card|mm|yy|cvv'"""
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    match = re.search(pattern, text)
    if match:
        card, month, year, cvv = match.groups()
        if len(year) == 2:
            year = '20' + year
        return card, month, year, cvv
    return None, None, None, None

def get_bin_info(card_number):
    """Fetch BIN info from an external API (optional)"""
    try:
        bin_number = card_number[:6]
        response = requests.get(f'https://bins.antipublic.cc/bins/{bin_number}', timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                'brand': data.get('brand', '-'),
                'type': data.get('type', '-'),
                'level': data.get('level', '-'),
                'bank': data.get('bank', '-'),
                'country': data.get('country_name', '-'),
                'flag': data.get('country_flag', '')
            }
    except:
        pass
    return {
        'brand': '-', 'type': '-', 'level': '-',
        'bank': '-', 'country': '-', 'flag': ''
    }

# =============== CORE CHECKOUT LOGIC (YOU NEED TO IMPLEMENT THIS) ===============
def checkout_shopify(site, card, month, year, cvv, proxy=None):
    """
    Perform the actual Shopify checkout.
    
    This is where you need to put your own logic. 
    The function should:
      - Build the checkout payload.
      - Send the request to the Shopify store.
      - Parse the response and return a dict with:
          "Response": the raw response message,
          "Price": the price (float),
          "Gateway": the payment gateway (e.g., "Shopify Payments")
    
    Args:
        site (str): Shopify store URL (e.g., https://example.myshopify.com)
        card (str): Card number
        month (str): Expiry month
        year (str): Expiry year (YYYY)
        cvv (str): CVV
        proxy (str, optional): Proxy in format "ip:port" or "ip:port:user:pass"
    
    Returns:
        dict: {"Response": str, "Price": float, "Gateway": str}
    """
    # ------------------------------------------------------------------
    # TODO: Replace this placeholder with your actual checkout logic.
    # You can copy the implementation from your friend's bot or write your own.
    # ------------------------------------------------------------------
    
    # Example placeholder – always returns a test response
    return {
        "Response": "Checkout logic not implemented – please add your own code.",
        "Price": 0.0,
        "Gateway": "Unknown"
    }

# =============== API ENDPOINT ===============
@app.route('/shopify', methods=['GET'])
def shopify_check():
    """
    Endpoint that your Telegram bot will call.
    Expected query parameters:
      - site: the Shopify store URL
      - cc:   the card in format "card|mm|yy|cvv"
      - proxy: (optional) proxy string
    """
    # 1. Get parameters
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')

    # 2. Validate
    if not site or not cc:
        return jsonify({
            "Response": "Missing site or cc parameters",
            "Price": 0,
            "Gateway": "Unknown"
        }), 400

    # 3. Parse card details
    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({
            "Response": "Invalid card format. Use: card|mm|yy|cvv",
            "Price": 0,
            "Gateway": "Unknown"
        }), 400

    # 4. Normalise site URL
    if not site.startswith('http'):
        site = 'https://' + site

    # 5. Call the checkout function
    try:
        result = checkout_shopify(site, card, month, year, cvv, proxy)
        # Ensure result has all required keys
        if not isinstance(result, dict):
            raise ValueError("checkout_shopify must return a dict")
        result.setdefault('Response', 'Unknown')
        result.setdefault('Price', 0.0)
        result.setdefault('Gateway', 'Unknown')
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Checkout error: {e}")
        return jsonify({
            "Response": f"ERROR: Internal server error – {str(e)}",
            "Price": 0,
            "Gateway": "Unknown"
        }), 500

# =============== HEALTH CHECK (optional) ===============
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

# =============== RUN THE SERVER ===============
if __name__ == '__main__':
    # Railway sets PORT env variable, default to 5000 for local testing
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
