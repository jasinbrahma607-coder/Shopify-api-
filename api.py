from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route('/shopify')
def shopify():
    return jsonify({
        "Response": "Order placed successfully",
        "Price": "19.99",
        "Gateway": "Shopify"
    })

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    import os
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
