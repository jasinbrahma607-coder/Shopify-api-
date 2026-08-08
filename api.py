# api.py – Shopify Checker API (GET enabled)
from fastapi import FastAPI, Query
import random
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shopify-api")

app = FastAPI(title="NOXI Shopify Checker API", version="1.0.0")

# ============ BIN LOOKUP (Mock) ============
BIN_CACHE = {}

async def get_bin_info(bin_code: str) -> Dict[str, str]:
    if bin_code in BIN_CACHE:
        return BIN_CACHE[bin_code]
    mock_db = {
        "411111": {"brand": "Visa", "type": "Credit", "level": "Classic", "bank": "Chase", "country": "US", "flag": "🇺🇸"},
        "511111": {"brand": "Mastercard", "type": "Credit", "level": "Standard", "bank": "Citi", "country": "US", "flag": "🇺🇸"},
        "601111": {"brand": "Discover", "type": "Credit", "level": "Standard", "bank": "Discover", "country": "US", "flag": "🇺🇸"},
        "371111": {"brand": "Amex", "type": "Credit", "level": "Standard", "bank": "Amex", "country": "US", "flag": "🇺🇸"},
        "400000": {"brand": "Visa", "type": "Debit", "level": "Standard", "bank": "Test Bank", "country": "IN", "flag": "🇮🇳"},
    }
    result = mock_db.get(bin_code, {"brand": "Unknown", "type": "Unknown", "level": "Unknown", "bank": "Unknown", "country": "Unknown", "flag": "🏳️"})
    BIN_CACHE[bin_code] = result
    return result

def parse_card(cc: str) -> Dict[str, str]:
    parts = cc.replace(" ", "").split("|")
    if len(parts) != 4:
        raise ValueError("Invalid card format. Use cc|mm|yy|cvv")
    return {"number": parts[0], "month": parts[1], "year": parts[2], "cvv": parts[3], "bin": parts[0][:6]}

async def shopify_check(site: str, cc: str, proxy: Optional[str] = None) -> Dict[str, Any]:
    try:
        card_data = parse_card(cc)
        bin_info = await get_bin_info(card_data["bin"])
        rnd = random.random()
        if "test" in site.lower():
            return {"Status": True, "Response": "Test order successful", "Price": "$19.99", "Gate": "Shopify"}
        if rnd < 0.15:
            return {"Status": True, "Response": "Order paid – thank you!", "Price": f"${random.randint(10, 200)}.{random.randint(0, 99):02d}", "Gate": "Shopify"}
        elif rnd < 0.35:
            return {"Status": True, "Response": "3DS Authentication required – OTP sent", "Price": "-", "Gate": "Shopify"}
        elif rnd < 0.80:
            decline = ["Card declined – insufficient funds", "Card declined – do not honor", "Card declined – expired card", "Generic decline"]
            return {"Status": False, "Response": random.choice(decline), "Price": "-", "Gate": "Shopify"}
        else:
            return {"Status": False, "Response": "Site error – timeout", "Price": "-", "Gate": "Shopify"}
    except ValueError as e:
        return {"Status": False, "Response": str(e), "Price": "-", "Gate": "Shopify"}
    except Exception as e:
        return {"Status": False, "Response": f"Error: {str(e)}", "Price": "-", "Gate": "Shopify"}

@app.get("/")
async def root():
    return {"service": "NOXI Shopify Checker API", "version": "1.0.0", "status": "running"}

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/shopify/check")
async def check_card(site: str = Query(...), cc: str = Query(...), proxy: Optional[str] = Query(None)):
    logger.info(f"Checking card on site: {site}")
    try:
        result = await shopify_check(site, cc, proxy)
        return {"Status": result.get("Status"), "Response": result.get("Response"), "Price": result.get("Price"), "Gate": result.get("Gate")}
    except Exception as e:
        return {"Status": False, "Response": f"Error: {str(e)}", "Price": "-", "Gate": "Shopify"}
