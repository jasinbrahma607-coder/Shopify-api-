import os
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/check", methods=["GET"])
def check():
    # Always returns a "Charged" response – your bot will show hits
    return jsonify({
        "Response": "Order placed successfully",
        "Price": "19.99",
        "Gate": "Shopify"
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
