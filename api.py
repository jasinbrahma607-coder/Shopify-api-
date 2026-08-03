from flask import Flask, request, jsonify
import os
import logging
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ---------- HEALTH CHECK ----------
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})

# ---------- MAIN SHOPIFY ENDPOINT ----------
@app.route('/shopify', methods=['GET'])
def shopify_check():
    # Get parameters
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')  # optional

    # Validate inputs
    if not site or not cc:
        app.logger.warning("Missing site or cc parameters")
        return jsonify({
            "Response": "Missing site or cc parameters",
            "Price": 0,
            "Gateway": "Shopify Payments"
        }), 400

    # Log incoming request (for debugging)
    app.logger.info(f"Received request: site={site}, cc={cc[:10]}...")

    # Always return a test response that the bot will accept
    # This will be treated as "Approved" because the Response contains "approved"
    return jsonify({
        "Response": "approved - test response from API",
        "Price": 10.0,
        "Gateway": "Shopify Payments"
    })

# ---------- ERROR HANDLER ----------
@app.errorhandler(500)
def internal_error(e):
    return jsonify({
        "Response": "Internal server error",
        "Price": 0,
        "Gateway": "Shopify Payments"
    }), 500

# ---------- RUN ----------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
