import os
import re
import json
import asyncio
import logging
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import stealth_async  # optional: hides automation

# ===== CONFIGURATION =====
PORT = int(os.environ.get('PORT', 5000))
HEADLESS = os.environ.get('HEADLESS', 'true').lower() == 'true'
TIMEOUT = int(os.environ.get('TIMEOUT', 30000))  # milliseconds per action
USER_AGENT = os.environ.get('USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# ===== APP SETUP =====
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ===== HELPERS =====
def extract_cc(text: str):
    """Extract card, month, year, cvv from 'card|mm|yy|cvv'."""
    pattern = r'(\d{15,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})'
    match = re.search(pattern, text)
    if match:
        card, month, year, cvv = match.groups()
        if len(year) == 2:
            year = '20' + year
        return card, month, year, cvv
    return None, None, None, None

def build_proxy_config(proxy_string: str):
    """Convert proxy string to Playwright proxy dict."""
    if not proxy_string:
        return None
    parts = proxy_string.split(':')
    if len(parts) == 2:  # ip:port
        return {"server": f"http://{proxy_string}"}
    elif len(parts) == 4:  # ip:port:user:pass
        ip, port, user, password = parts
        return {
            "server": f"http://{ip}:{port}",
            "username": user,
            "password": password
        }
    return None

def is_cloudflare_page(content: str, url: str) -> bool:
    """Check if page is behind Cloudflare challenge."""
    lower = content.lower()
    return any(x in lower for x in ['cf-browser-verification', 'cf-challenge', 'cloudflare']) or '/cdn-cgi/' in url

def is_3ds_page(content: str) -> bool:
    """Check if page indicates 3DS/challenge."""
    lower = content.lower()
    return any(x in lower for x in ['3d secure', '3ds', 'authenticate', 'verification required', 'challenge required'])

def parse_shopify_error(content: str) -> str:
    """Extract error message from Shopify checkout page."""
    # Common Shopify error containers
    patterns = [
        r'<p[^>]*class="error"[^>]*>(.*?)</p>',
        r'<div[^>]*class="field__message--error"[^>]*>(.*?)</div>',
        r'<li[^>]*class="error"[^>]*>(.*?)</li>',
        r'<span[^>]*class="error"[^>]*>(.*?)</span>'
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            error_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            if error_text:
                return error_text
    return None

# ===== CORE CHECKOUT LOGIC (ASYNCIO) =====
async def perform_checkout(site_url: str, card: str, month: str, year: str, cvv: str, proxy_string: str = None):
    """
    Perform Shopify checkout using Playwright.
    Returns a dict with 'Response', 'Price', 'Gateway'.
    """
    proxy_config = build_proxy_config(proxy_string)
    async with async_playwright() as p:
        # Launch browser with anti-detection arguments
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-gpu'
            ]
        )
        # Create context with proxy and user agent
        context = await browser.new_context(
            proxy=proxy_config,
            user_agent=USER_AGENT,
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()

        # Apply stealth (optional)
        try:
            await stealth_async(page)
        except ImportError:
            pass  # stealth not installed, skip

        # Step 1: Go to the store homepage to set cookies & session
        try:
            await page.goto(site_url, timeout=TIMEOUT, wait_until='domcontentloaded')
        except Exception as e:
            await browser.close()
            return {"Response": f"Failed to reach store: {str(e)[:80]}", "Price": 0, "Gateway": "Shopify Payments"}

        # Step 2: Go to /checkout
        try:
            await page.goto(f"{site_url}/checkout", timeout=TIMEOUT, wait_until='networkidle')
        except Exception as e:
            await browser.close()
            return {"Response": f"Failed to reach checkout: {str(e)[:80]}", "Price": 0, "Gateway": "Shopify Payments"}

        # Check for Cloudflare after navigation
        content = await page.content()
        if is_cloudflare_page(content, page.url):
            await browser.close()
            return {"Response": "Cloudflare challenge detected", "Price": 0, "Gateway": "Shopify Payments"}

        # Step 3: Fill card details and submit
        try:
            # Wait for card number field – use common selectors
            card_selector = 'input[name="checkout[credit_card][number]"], input#credit_card_number, input[data-credit-card-field="number"]'
            await page.wait_for_selector(card_selector, timeout=TIMEOUT)
            
            # Fill card number
            await page.fill(card_selector, card)
            
            # Fill cardholder name (if present)
            name_selector = 'input[name="checkout[credit_card][name]"], input#credit_card_name'
            if await page.locator(name_selector).count() > 0:
                await page.fill(name_selector, "John Doe")

            # Fill expiry month/year
            month_selector = 'input[name="checkout[credit_card][month]"], input#credit_card_month'
            year_selector = 'input[name="checkout[credit_card][year]"], input#credit_card_year'
            await page.fill(month_selector, month)
            await page.fill(year_selector, year)

            # Fill CVV
            cvv_selector = 'input[name="checkout[credit_card][verification_value]"], input#credit_card_verification_value'
            await page.fill(cvv_selector, cvv)

            # Click the "Pay now" or "Complete order" button
            pay_button = 'button[type="submit"][name="button"], button:has-text("Pay"), button:has-text("Complete order"), button[data-testid="checkout-pay"]'
            await page.click(pay_button, timeout=5000)

            # Wait for the result (either success page or error)
            # We'll wait up to 10 seconds for navigation or error
            await page.wait_for_timeout(8000)

        except PlaywrightTimeout as e:
            await browser.close()
            return {"Response": f"Timeout during payment form: {str(e)[:50]}", "Price": 0, "Gateway": "Shopify Payments"}
        except Exception as e:
            await browser.close()
            return {"Response": f"Payment form error: {str(e)[:80]}", "Price": 0, "Gateway": "Shopify Payments"}

        # Step 4: Analyze the final page
        final_url = page.url
        content = await page.content()
        lower_content = content.lower()
        await browser.close()

        # Check for success (thank you / order placed)
        if any(x in final_url.lower() for x in ['thank_you', 'order/']):
            # Try to extract price from the page
            price_match = re.search(r'<span[^>]*data-total-price[^>]*>([\d.]+)</span>', content)
            price = float(price_match.group(1)) if price_match else 0.0
            return {"Response": "Order placed successfully", "Price": price, "Gateway": "Shopify Payments"}

        # Check for 3DS/challenge
        if is_3ds_page(content):
            return {"Response": "3DS_REQUIRED", "Price": 0, "Gateway": "Shopify Payments"}

        # Check for Shopify error messages
        error_msg = parse_shopify_error(content)
        if error_msg:
            # Normalize some common errors for better classification
            lower_err = error_msg.lower()
            if 'cvv' in lower_err:
                return {"Response": "Invalid CVV", "Price": 0, "Gateway": "Shopify Payments"}
            if 'insufficient' in lower_err:
                return {"Response": "Insufficient funds", "Price": 0, "Gateway": "Shopify Payments"}
            if 'declined' in lower_err:
                return {"Response": "Card declined", "Price": 0, "Gateway": "Shopify Payments"}
            return {"Response": error_msg[:100], "Price": 0, "Gateway": "Shopify Payments"}

        # Fallback: look for generic decline indicators
        decline_keywords = ['declined', 'error', 'invalid', 'incorrect', 'not supported', 'expired']
        if any(k in lower_content for k in decline_keywords):
            return {"Response": "Card declined", "Price": 0, "Gateway": "Shopify Payments"}

        # Unknown outcome – treat as dead
        return {"Response": "Could not determine payment status", "Price": 0, "Gateway": "Shopify Payments"}

# ===== FLASK ENDPOINTS =====
@app.route('/shopify', methods=['GET'])
def shopify_check():
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')

    if not site or not cc:
        return jsonify({"Response": "Missing site or cc", "Price": 0, "Gateway": "Shopify Payments"}), 400

    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({"Response": "Invalid card format", "Price": 0, "Gateway": "Shopify Payments"}), 400

    if not site.startswith('http'):
        site = 'https://' + site

    # Run async function inside Flask
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(perform_checkout(site, card, month, year, cvv, proxy))
    except Exception as e:
        app.logger.error(f"Unhandled exception: {e}")
        result = {"Response": f"ERROR: {str(e)[:80]}", "Price": 0, "Gateway": "Shopify Payments"}
    finally:
        loop.close()

    return jsonify(result)

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive"})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

# ===== RUN =====
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
