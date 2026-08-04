import os
import re
import asyncio
import traceback
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright, TimeoutError

app = Flask(__name__)

def extract_cc(text):
    m = re.search(r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})', text)
    if m:
        card, month, year, cvv = m.groups()
        if len(year) == 2:
            year = '20' + year
        return card, month, year, cvv
    return None, None, None, None

async def perform_checkout(site, card, month, year, cvv):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            page = await browser.new_page()
            try:
                await page.goto(site, timeout=15000, wait_until='domcontentloaded')
                await page.goto(f"{site}/checkout", timeout=30000, wait_until='networkidle')
                await page.fill('input[name="checkout[credit_card][number]"]', card)
                await page.fill('input[name="checkout[credit_card][month]"]', month)
                await page.fill('input[name="checkout[credit_card][year]"]', year)
                await page.fill('input[name="checkout[credit_card][verification_value]"]', cvv)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(8000)
                url = page.url
                content = await page.content()
                if 'thank_you' in url.lower() or 'order' in url.lower():
                    price_match = re.search(r'<span[^>]*data-total-price[^>]*>([\d.]+)</span>', content)
                    price = float(price_match.group(1)) if price_match else 0.0
                    return {"Response": "Order placed", "Price": price, "Gateway": "Shopify"}
                elif any(x in content.lower() for x in ['3d', 'authenticate', 'verification required']):
                    return {"Response": "3DS_REQUIRED", "Price": 0, "Gateway": "Shopify"}
                else:
                    error_match = re.search(r'<p[^>]*class="error"[^>]*>(.*?)</p>', content, re.DOTALL)
                    msg = error_match.group(1).strip() if error_match else "Declined"
                    return {"Response": msg, "Price": 0, "Gateway": "Shopify"}
            except Exception as e:
                return {"Response": f"Checkout error: {str(e)[:100]}", "Price": 0, "Gateway": "Shopify"}
            finally:
                await browser.close()
    except Exception as e:
        return {"Response": f"Playwright launch error: {str(e)[:100]}", "Price": 0, "Gateway": "Shopify"}

@app.route('/shopify', methods=['GET'])
def shopify():
    try:
        site = request.args.get('site')
        cc = request.args.get('cc')
        if not site or not cc:
            return jsonify({"Response": "Missing site/cc", "Price": 0, "Gateway": "Shopify"}), 200
        card, month, year, cvv = extract_cc(cc)
        if not card:
            return jsonify({"Response": "Invalid card format", "Price": 0, "Gateway": "Shopify"}), 200
        if not site.startswith('http'):
            site = 'https://' + site
        result = asyncio.run(perform_checkout(site, card, month, year, cvv))
        return jsonify(result)
    except Exception as e:
        # Return the error as JSON instead of 500
        error_msg = str(e)
        return jsonify({"Response": f"Server error: {error_msg[:100]}", "Price": 0, "Gateway": "Shopify"})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
