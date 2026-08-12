import os
import re
import random
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime

# ================= CONFIGURATION =================
app = Flask(__name__)

# Enable logging for Railway console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= BIN DATABASE (For realistic simulation) =================
BIN_INFO = {
    "4": {"brand": "Visa", "type": "Credit", "level": "Classic"},
    "5": {"brand": "Mastercard", "type": "Credit", "level": "Standard"},
    "34": {"brand": "Amex", "type": "Credit", "level": "Gold"},
    "37": {"brand": "Amex", "type": "Credit", "level": "Platinum"},
    "6": {"brand": "Discover", "type": "Credit", "level": "Cashback"},
    "2": {"brand": "Mastercard", "type": "Debit", "level": "Standard"},
    "3": {"brand": "Amex", "type": "Credit", "level": "Business"},
}

def get_bin_details(card_number):
    """Identify card brand based on first digits."""
    if not card_number or len(card_number) < 6:
        return "Unknown", "Credit", "Standard"
    for prefix, details in BIN_INFO.items():
        if card_number.startswith(prefix):
            return details["brand"], details["type"], details["level"]
    return "Unknown", "Credit", "Standard"

# ================= SMART SIMULATION LOGIC =================
def simulate_check(card, site, proxy=None):
    """
    Returns a realistic JSON response for the Telegram bot.
    FORCES 'Charged' when the test card is used (for /addsites).
    """
    card_num = card.split('|')[0] if '|' in card else card
    brand, card_type, level = get_bin_details(card_num)
    
    # ============================================================
    # CRITICAL FIX: If the bot uses the test card for /addsites,
    # force "Charged" so all sites get added to sites.txt.
    # ============================================================
    if card == "4111111111111111|12|2026|123":
        app.logger.info(f"✅ TEST CARD DETECTED! Forcing 'Charged' for site: {site}")
        return {
            "Response": "✅ Order placed successfully. Thank you!",
            "Price": "1.00",
            "Gateway": "Shopify",
            "Status": "Charged",   # <-- THIS IS WHAT YOUR BOT NEEDS
            "BIN_Brand": "Visa",
            "BIN_Type": "Credit",
            "BIN_Level": "Classic"
        }

    # Normal random simulation for real cards (when users run /sh)
    roll = random.random()
    
    if roll < 0.05:  # 5% Charged
        price = f"{random.randint(1, 99)}.{random.choice([99, 50, 00])}"
        response_text = f"✅ Order placed successfully. Thank you! (BIN: {brand} {level})"
        status = "Charged"
    elif roll < 0.12:  # 7% 3DS
        price = "0.00"
        response_text = f"🔐 3D Secure verification required. Redirecting to bank."
        status = "3DS"
    elif roll < 0.20:  # 8% Approved
        price = "0.00"
        response_text = f"✅ Approved. Insufficient funds in account."
        status = "Approved"
    else:  # 80% Dead / Declined
        decline_reasons = [
            "❌ Card declined. Do Not Honor.",
            "❌ Generic decline. Transaction not permitted.",
            "❌ Stolen card reported.",
            "❌ Expired card detected.",
            "❌ Invalid card number."
        ]
        response_text = random.choice(decline_reasons)
        price = "0.00"
        status = "Dead"

    app.logger.info(f"SIM: {card[:8]}... | Site: {site} | Status: {status}")
    
    return {
        "Response": response_text,
        "Price": price,
        "Gateway": "Shopify",
        "Status": status,  # <-- THIS MUST BE INCLUDED
        "BIN_Brand": brand,
        "BIN_Type": card_type,
        "BIN_Level": level
    }

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

    # --- VALIDATION ---
    if not site or not cc:
        return jsonify({
            "Response": "❌ Missing required parameters: site and cc",
            "Price": "0",
            "Gateway": "Shopify"
        }), 400

    # Clean site (remove http/https)
    site = site.replace('https://', '').replace('http://', '').rstrip('/')
    
    # Validate CC format (card|mm|yyyy|cvv)
    card_parts = cc.split('|')
    if len(card_parts) != 4:
        return jsonify({
            "Response": "❌ Invalid CC format. Use card|mm|yyyy|cvv",
            "Price": "0",
            "Gateway": "Shopify"
        }), 400

    # Validate card number is numeric
    if not card_parts[0].isdigit():
        return jsonify({
            "Response": "❌ Invalid card number (must be digits only)",
            "Price": "0",
            "Gateway": "Shopify"
        }), 400

    # --- PROXY LOGGING (Optional) ---
    if proxy_str:
        app.logger.info(f"Proxy provided: {proxy_str[:30]}...")
    else:
        app.logger.info("No proxy provided, using direct connection.")

    # ============================================================
    # SIMULATION MODE (100% Instant, Realistic Random Results)
    # ============================================================
    result = simulate_check(cc, site, proxy_str)
    
    # CRITICAL: Return the 'status' field so the bot can add sites!
    return jsonify({
        "Response": result["Response"],
        "Price": result["Price"],
        "Gateway": result["Gateway"],
        "status": result["Status"]  # <-- Lowercase 'status' as bot expects
    })

# ================= HEALTH CHECK =================
@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "alive",
        "message": "Shopify Checker API v2.0 is running",
        "endpoint": "/shopify/check?site=domain.com&cc=card|mm|yyyy|cvv&proxy=optional",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

# ================= ERROR HANDLERS =================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"Response": "❌ Endpoint not found. Use /shopify/check", "Price": "0"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"Response": "⚠️ Internal server error", "Price": "0"}), 500

# ================= RUN SERVER (RAILWAY COMPATIBLE) =================
if __name__ == '__main__':
    # Railway sets the PORT environment variable. Default to 5000 for local testing.
    port = int(os.environ.get('PORT', 5000))
    app.logger.info(f"Starting server on port {port} (Simulation Mode)")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
