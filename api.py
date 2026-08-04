import os
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/shopify', methods=['GET'])
def shopify():
    # Always return a "Charged" response
    return jsonify({
        "Response": "Order placed successfully",
        "Price": 19.99,
        "Gateway": "Shopify"
    })

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
