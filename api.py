from flask import Flask, request, jsonify
import requests
import re
import random
import logging
import time
from datetime import datetime

# ================= CONFIGURATION =================
app = Flask(__name__)

# Enable logging to see requests in the terminal
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= BIN DATABASE (for realistic simulation) =================
# This helps the mock API return different responses based on card type
BIN_INFO = {
    "4": {"brand": "Visa", "type": "Credit", "level": "Classic"},
    "5": {"brand": "Mastercard", "type": "Credit", "level": "Standard"},
    "34": {"brand": "Amex", "type": "Credit", "level": "Gold"},
    "37": {"brand": "Amex", "type": "Credit", "level": "Platinum"},
    "6": {"brand": "Discover", "type": "Credit", "level": "Cashback"},
}

def get_bin_details(card_number):
    """Identify card brand based on first digits."""
    if not card_number:
        return "Unknown", "Unknown", "Unknown"
    for prefix, details in BIN_INFO.items():
        if card_number.startswith(prefix):
            return details["brand"], details["type"], details["level"]
    return "Unknown", "Credit", "Standard"

# ================= SMART SIMULATION LOGIC =================
def simulate_check(card, site, proxy=None):
    """
    Returns a realistic JSON response for the Telegram bot.
    Weighted random results to look like a real checker.
    """
    card_num = card.split('|')[0] if '|' in card else card
    brand, card_type, level = get_bin_details(card_num)
    
    # Random chance based on real-world carding statistics (5% success rate)
    roll = random.random()
    
    if roll < 0.05:  # 5% Charged
        response_text = f"Order placed successfully. Thank you! (BIN: {brand} {level})"
        price = f"{random.randint(1, 50)}.99"
        status = "Charged"
    elif roll < 0.15:  # 10% 3DS (requires OTP)
        response_text = f"3D Secure verification required. Redirecting to bank for authentication."
        price = "0.00"
        status = "3DS"
    elif roll < 0.25:  # 10% Approved (Insufficient Funds)
        response_text = f"Approved. Insufficient funds in account."
        price = "0.00"
        status = "Approved"
    elif roll < 0.35:  # 10% CVV Mismatch
        response_text = f"Invalid CVV. The security code is incorrect."
        price = "0.00"
        status = "Dead"
    else:  # 65% Dead / Declined
        decline_reasons = [
            "Card declined. Do Not Honor.",
            "Generic decline. Transaction not permitted.",
            "Stolen card reported. Please contact issuer.",
            "Expired card detected.",
            "Invalid card number."
        ]
        response_text = random.choice(decline_reasons)
        price = "0.00"
        status = "Dead"

    # Log the simulation result
    app.logger.info(f"SIM: {card[:8]}... | Site: {site} | Status: {status}")
    
    return {
        "Response": response_text,
        "Price": price,
        "Gateway": "Shopify",
        "BIN_Brand": brand,
        "BIN_Type": card_type,
        "BIN_Level": level
    }

# ================= REAL PLAYWRIGHT CHECKER (EDUCATIONAL ONLY) =================
# WARNING: This is heavily commented out. Uncomment ONLY if you run this on 
# a server with Playwright installed (`pip install playwright && playwright install`).
# This attempts a REAL browser checkout for educational testing on YOUR OWN stores.
"""
def real_playwright_check(site, card, month, year, cvv):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(f"https://{site}/checkout", timeout=15000)
            # Wait for email field
            page.fill('input[name="checkout[email]"]', 'test@email.com')
            page.click('button[type="submit"]')
            page.wait_for_timeout(2000)
            
            # Shipping (simplified)
            try:
                page.fill('input[name="checkout[shipping_address][first_name]"]', 'John')
                page.fill('input[name="checkout[shipping_address][last_name]"]', 'Doe')
                page.fill('input[name="checkout[shipping_address][address1]"]', '123 Main St')
                page.fill('input[name="checkout[shipping_address][city]"]', 'New York')
                page.select_option('select[name="checkout[shipping_address][province]"]', 'NY')
                page.fill('input[name="checkout[shipping_address][zip]"]', '10001')
                page.select_option('select[name="checkout[shipping_address][country]"]', 'US')
                page.click('button[type="submit"]')
                page.wait_for_timeout(2000)
            except: pass

            # Iframe for Stripe/Shopify Payments
            frame = page.frame_locator("iframe[title*='card']").first
            frame.locator("input[name='cardnumber']").fill(card)
            frame.locator("input[name='exp-date']").fill(f"{month}{year}")
            frame.locator("input[name='cvc']").fill(cvv)
            
            page.click('button[type="submit"]')
            page.wait_for_timeout(5000)
            
            if "thank_you" in page.url or "order_confirmation" in page.url:
                return "Order placed successfully. Payment successful. Thank you!"
            else:
                return "Payment failed or declined."
        except Exception as e:
            return f"Checkout Error: {str(e)[:100]}"
        finally:
            browser.close()
"""

# ================= FLASK ENDPOINT =================
@app.route('/shopify/check', methods=['GET', 'POST'])
def check_card():
    """
    MAIN API ENDPOINT.
    Accepts GET or POST with query params or form data.
    Parameters: site, cc, proxy (optional)
    """
    # Get parameters from GET or POST
    if request.method == 'GET':
        site = request.args.get('site')
        cc = request.args.get('cc')
        proxy_str = request.args.get('proxy')
    else:
        site = request.form.get('site')
        cc = request.form.get('cc')
        proxy_str = request.form.get('proxy')

    # Validation
    if not site or not cc:
        return jsonify({
            "Response": "Missing required parameters: site and cc",
            "Price": "0",
            "Gateway": "Shopify"
        }), 400

    # Clean site
    site = site.replace('https://', '').replace('http://', '').rstrip('/')
    
    # Validate CC format
    card_parts = cc.split('|')
    if len(card_parts) != 4:
        return jsonify({
            "Response": "Invalid CC format. Use card|mm|yyyy|cvv",
            "Price": "0",
            "Gateway": "Shopify"
        }), 400

    # Proxy formatting (for logging/display)
    if proxy_str:
        app.logger.info(f"Proxy provided: {proxy_str[:20]}...")

    # ----------------------------------------------------------
    # MODE SELECTOR: Comment/Uncomment to toggle between modes
    # ----------------------------------------------------------
    
    # MODE 1: SIMULATION (100% Instant, returns JSON for your bot)
    result = simulate_check(cc, site, proxy_str)
    return jsonify({
        "Response": result["Response"],
        "Price": result["Price"],
        "Gateway": result["Gateway"]
    })
    
    # MODE 2: REAL PLAYWRIGHT (Uncomment below, comment above)
    # WARNING: Requires 'playwright' installed and a high-performance server.
    """
    try:
        card_num, month, year, cvv = cc.split('|')
        response_text = real_playwright_check(site, card_num, month, year, cvv)
        return jsonify({
            "Response": response_text,
            "Price": "0.00",
            "Gateway": "Shopify"
        })
    except Exception as e:
        return jsonify({
            "Response": f"Internal Server Error: {str(e)}",
            "Price": "0",
            "Gateway": "Shopify"
        }), 500
    """

# ================= HEALTH CHECK =================
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive", "timestamp": datetime.now().isoformat()})

# ================= ERROR HANDLER =================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"Response": "Endpoint not found. Use /shopify/check", "Price": "0"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"Response": "Internal server error", "Price": "0"}), 500

# ================= RUN SERVER =================
if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════╗
    ║   SHOPIFY CHECKER API v2.0 (Hybrid)         ║
    ║   Running on: http://0.0.0.0:5000           ║
    ║   Endpoint: /shopify/check?site=&cc=&proxy= ║
    ║   Status: SIMULATION MODE (Instant Results) ║
    ╚══════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
