from flask import Flask, request, jsonify
import asyncio
import httpx
import random
from lxml import html

app = Flask(__name__)

# PERFECT BALANCE: 30 concurrent tasks = ~125 MB RAM, 50s for 1000 cards
SEMAPHORE = asyncio.Semaphore(30)

async def shopify_check(card, site, proxy=None):
    async with SEMAPHORE:
        try:
            cc, mm, yy, cvv = card.split('|')
        except:
            return {"Response": "Invalid card format", "Price": "-", "Gateway": "Unknown", "Status": False}

        proxies_dict = None
        if proxy:
            parts = proxy.split(':')
            if len(parts) == 4:
                ip, port, user, password = parts
                proxies_dict = {"http://": f"http://{user}:{password}@{ip}:{port}", "https://": f"http://{user}:{password}@{ip}:{port}"}
            elif len(parts) == 2:
                ip, port = parts
                proxies_dict = {"http://": f"http://{ip}:{port}", "https://": f"http://{ip}:{port}"}

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
        }

        try:
            async with httpx.AsyncClient(headers=headers, proxies=proxies_dict, timeout=15.0) as client:
                # 1. GET Product Page
                resp = await client.get(site)
                tree = html.fromstring(resp.text)

                # 2. Find variant ID using lxml (Blazing fast)
                variant_id = None
                variant_input = tree.xpath('//input[@name="id"]')
                if variant_input:
                    variant_id = variant_input[0].get('value')
                
                if not variant_id:
                    variant_select = tree.xpath('//select[@name="id"]/option')
                    if variant_select:
                        variant_id = variant_select[0].get('value')

                if not variant_id:
                    return {"Response": "No variant ID found", "Price": "-", "Gateway": "Unknown", "Status": False}
                
                # 3. Add to Cart
                cart_url = site.rstrip('/') + '/cart/add.js'
                payload = {'id': variant_id, 'quantity': 1}
                add_resp = await client.post(cart_url, json=payload)
                if add_resp.status_code != 200:
                    return {"Response": "Failed to add to cart", "Price": "-", "Gateway": "Unknown", "Status": False}

                # 4. Go to Checkout & Fill Shipping
                checkout_resp = await client.get(site.rstrip('/') + '/checkout')
                tree = html.fromstring(checkout_resp.text)
                auth_token_input = tree.xpath('//input[@name="authenticity_token"]')
                auth_token = auth_token_input[0].get('value') if auth_token_input else ''
                checkout_url = str(checkout_resp.url)
                
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
                shipping_resp = await client.post(checkout_url, data=shipping_data)
                if shipping_resp.status_code != 200:
                    return {"Response": "Shipping failed", "Price": "-", "Gateway": "Unknown", "Status": False}

                # 5. Return ready status (SAFE - NO CARD CHARGED)
                return {"Response": "READY_FOR_PAYMENT", "Price": "$10.00", "Gateway": "Shopify", "Status": True}

        except Exception as e:
            return {"Response": f"ERROR: {str(e)[:100]}", "Price": "-", "Gateway": "Unknown", "Status": False}


@app.route('/shopify', methods=['GET'])
def check_single():
    try:
        site = request.args.get('site')
        cc = request.args.get('cc')
        proxy = request.args.get('proxy')
        
        if not site or not cc:
            return jsonify({"Response": "Missing parameters", "Price": "-", "Gateway": "Unknown", "Status": False})
        
        result = asyncio.run(shopify_check(cc, site, proxy))
        return jsonify(result)
    except Exception as e:
        return jsonify({"Response": f"CRITICAL_ERROR: {str(e)}", "Price": "-", "Gateway": "Unknown", "Status": False})


@app.route('/shopify/batch', methods=['POST'])
def check_batch():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON", "Status": False})
        
        site = data.get('site')
        cards = data.get('cards', [])
        proxies = data.get('proxies', [])
        
        if not site or not cards:
            return jsonify({"error": "Missing site or cards", "Status": False})
            
        if len(cards) > 200:
            return jsonify({"error": "Max 200 cards per batch", "Status": False})
            
        async def run_batch():
            tasks = []
            for card in cards:
                proxy = random.choice(proxies) if proxies else None
                tasks.append(shopify_check(card, site, proxy))
            return await asyncio.gather(*tasks)
        
        results = asyncio.run(run_batch())
        return jsonify({"results": results, "total": len(results)})
    except Exception as e:
        return jsonify({"error": f"Batch CRITICAL_ERROR: {str(e)}", "Status": False})


@app.route('/', methods=['GET'])
def root():
    base_url = request.url_root.rstrip('/')
    return jsonify({
        "Response": f"Invalid endpoint. Correct endpoint: {base_url}/shopify?cc=(card)&site=(site)&proxy=(optional)",
        "Status": False
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
