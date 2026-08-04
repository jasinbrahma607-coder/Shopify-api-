import os
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/shopify', methods=['GET'])
def shopify():
    site = request.args.get('site')
    cc = request.args.get('cc')
    if not site or not cc:
        return jsonify({"Response": "Missing site or cc", "Price": 0, "Gateway": "Shopify"}), 400
    # Mock – always returns a "charged" response
    return jsonify({"Response": "Order placed successfully", "Price": 19.99, "Gateway": "Shopify"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
