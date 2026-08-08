# shopify_api.py – Shopify Checker API (FastAPI, GET enabled)
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import aiohttp
import asyncio
import random
import re
import json
import logging
from urllib.parse import quote
from datetime import datetime
from typing import Optional, Dict, Any

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shopify-api")

app = FastAPI(
    title="NOXI Shopify Checker API",
    description="Shopify card checker – GET endpoint, ready for your bot",
    version="1.0.0"
)

# ============ BIN LOOKUP (Mock, but you can use a real service) ============
BIN_CACHE = {}

async def get_bin_info(bin_code: str) -> Dict[str, str]:
    """Get BIN info (mock or from a real API)"""
    if bin_code in BIN_CACHE:
        return BIN_CACHE[bin_code]
    # Simple mock BIN database
    mock_db = {
        "411111": {"brand": "Visa", "type": "Credit", "level": "Classic", "bank": "Chase", "country": "US", "flag": "🇺🇸"},
        "511111": {"brand": "Mastercard", "type": "Credit", "level": "Standard", "bank": "Citi", "country": "US", "flag": "🇺🇸"},
        "601111": {"brand": "Discover", "type": "Credit", "level": "Standard", "bank": "Discover", "country": "US", "flag": "🇺🇸"},
        "371111": {"brand": "Amex", "type": "Credit", "level": "Standard", "bank": "Amex", "country": "US", "flag": "🇺🇸"},
        "400000": {"brand": "Visa", "type": "Debit", "level": "Standard", "bank": "Test Bank", "country": "IN", "flag": "🇮🇳"},
    }
    result = mock_db.get(bin_code, {
        "brand": "Unknown",
        "type": "Unknown",
        "level": "Unknown",
        "bank": "Unknown",
        "country": "Unknown",
        "flag": "🏳️"
    })
    BIN_CACHE[bin_code] = result
    return result

# ============ CARD PARSING ============
def parse_card(cc: str) -> Dict[str, str]:
    parts = cc.replace(" ", "").split("|")
    if len(parts) != 4:
        raise ValueError("Invalid card format. Use cc|mm|yy|cvv")
    return {
        "number": parts[0],
        "month": parts[1],
        "year": parts[2],
        "cvv": parts[3],
        "bin": parts[0][:6]
    }

# ============ MOCK SHOPIFY CHECK (Replace with real logic) ============
async def shopify_check(site: str, cc: str, proxy: Optional[str] = None) -> Dict[str, Any]:
    """
    Simulate a Shopify checkout.
    For a real checker, you would:
      - Fetch the storefront product
      - Add to cart
      - Get checkout token
      - Tokenize the card
      - Submit payment
      - Return the result
    """
    try:
        card_data = parse_card(cc)
        bin_info = await get_bin_info(card_data["bin"])
        
        # Simulate response based on site and card
        # 15% Charged, 20% Approved, 60% Declined, 5% Error
        rnd = random.random()
        
        # Option: if site contains "test", always return a specific status
        if "test" in site.lower():
            return {
                "Status": True,
                "Response": "Test order successful",
                "Price": "$19.99",
                "Gate": "Shopify",
                "Gateway": "Shopify"
            }
        
        if rnd < 0.15:
            return {
                "Status": True,
                "Response": "Order paid – thank you!",
                "Price": f"${random.randint(10, 200)}.{random.randint(0, 99):02d}",
                "Gate": "Shopify",
                "Gateway": "Shopify"
            }
        elif rnd < 0.35:
            return {
                "Status": True,
                "Response": "3DS Authentication required – OTP sent",
                "Price": "-",
                "Gate": "Shopify",
                "Gateway": "Shopify"
            }
        elif rnd < 0.80:
            decline_reasons = [
                "Card declined – insufficient funds",
                "Card declined – do not honor",
                "Card declined – expired card",
                "Card declined – stolen card",
                "Generic decline",
                "Transaction not allowed"
            ]
            return {
                "Status": False,
                "Response": random.choice(decline_reasons),
                "Price": "-",
                "Gate": "Shopify",
                "Gateway": "Shopify"
            }
        else:
            return {
                "Status": False,
                "Response": "Site error – timeout",
                "Price": "-",
                "Gate": "Shopify",
                "Gateway": "Shopify"
            }
    except ValueError as e:
        return {
            "Status": False,
            "Response": str(e),
            "Price": "-",
            "Gate": "Shopify",
            "Gateway": "Shopify"
        }
    except Exception as e:
        logger.error(f"Shopify check error: {e}")
        return {
            "Status": False,
            "Response": f"Error: {str(e)}",
            "Price": "-",
            "Gate": "Shopify",
            "Gateway": "Shopify"
        }

# ============ API ENDPOINTS ============
@app.get("/")
async def root():
    return {
        "service": "NOXI Shopify Checker API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "/shopify/check": "Check a card on a Shopify store (GET with site, cc)",
            "/health": "Health check",
            "/docs": "API documentation"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/shopify/check")
async def check_card(
    site: str = Query(..., description="Shopify store URL (e.g., example.com)"),
    cc: str = Query(..., description="Card in format cc|mm|yy|cvv"),
    proxy: Optional[str] = Query(None, description="Optional proxy URL")
):
    """
    Main endpoint – bot sends GET with site and cc parameters.
    Returns JSON with Status, Response, Price, Gate.
    """
    logger.info(f"Checking card on site: {site}, card: {cc[:6]}...{cc[-4:]}")
    try:
        result = await shopify_check(site, cc, proxy)
        # Ensure we have the required fields
        return {
            "Status": result.get("Status", False),
            "Response": result.get("Response", "Unknown response"),
            "Price": result.get("Price", "-"),
            "Gate": result.get("Gate", "Shopify"),
            "Gateway": result.get("Gateway", "Shopify")
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "Status": False,
            "Response": f"Error: {str(e)}",
            "Price": "-",
            "Gate": "Shopify",
            "Gateway": "Shopify"
        }

# ============ RUN ============
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
