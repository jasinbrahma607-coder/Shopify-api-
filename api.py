import os, aiohttp, asyncio
from flask import Flask, request, jsonify

app = Flask(__name__)
BARRYX_API = "https://api.barryxapi.xyz/shopify_graphql"
API_KEY    = "BRY-KESNP-TUPWH-JFOT9"

async def call_barryx(site, card, proxy):
    payload = {
        "key": API_KEY,
        "card": card,
        "product_url": site,
        "proxy": proxy or ""
    }
    async with aiohttp.ClientSession() as sess:
        async with sess.post(BARRYX_API, json=payload) as resp:
            return await resp.json()

@app.route("/check", methods=["GET"])
def check():
    cc = request.args.get("cc")          # bot sends cc
    proxy = request.args.get("proxy")    # bot sends proxy
    # Use a default product URL – you can change this
    site = "https://shop.wedsociety.com/products/2026-wed-society®-indianapolis-book-of-weddings-digital-issue"
    result = asyncio.run(call_barryx(site, cc, proxy))
    # Map BarryX response to bot's expected format
    return jsonify({
        "Response": result.get("message", "Unknown"),
        "Price": result.get("price", "-"),
        "Gate": result.get("gateway", "Shopify")
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
