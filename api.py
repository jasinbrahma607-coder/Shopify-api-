import os
import asyncio
import concurrent.futures
import functools
import logging
import time
from typing import Optional, Tuple
from fastapi import FastAPI, Query
from pydantic import BaseModel

# Import the real checkout engine
from checkout_engine import (
    run_checkout_for_card,
    normalize_proxy,
    parse_card_entry,
)

# ==================== CONFIG ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vxo.api")

THREAD_WORKERS = int(os.environ.get("CHECKER_THREADS", "200"))
MAX_RETRIES = int(os.environ.get("CHECKER_RETRIES", "1"))

_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=THREAD_WORKERS,
    thread_name_prefix="chk",
)

app = FastAPI(
    title="ZERO CHECK API",
    description="Real Shopify checkout engine",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

# ==================== MODELS ====================
class CheckRequest(BaseModel):
    card: Optional[str] = None
    shop_url: Optional[str] = None
    proxy: Optional[str] = None
    low: bool = True

# ==================== HELPERS ====================
def _validate_proxy(raw: str) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    try:
        return normalize_proxy(raw)
    except Exception:
        return None

def _validate_card(raw: str) -> Tuple[Optional[str], Optional[str]]:
    if not raw or not raw.strip():
        return None, "Card required"
    try:
        parse_card_entry(raw)
        return raw, None
    except Exception as e:
        return None, str(e)

def _build_response(res, shop_url: str = ""):
    status_name = res.status.name
    return {
        "Response": status_name,
        "CC": res.card or "",
        "Price": res.amount or "0.00",
        "Gate": "Shopify",
        "Charged": "True" if status_name == "CHARGED" else "False",
        "error": str(res.error) if res.error else "",
        "retryable": res.retryable,
        "receipt_url": res.receipt_url or "",
    }

# ==================== ENDPOINTS ====================

@app.get("/health", tags=["meta"])
async def health():
    return {
        "ok": True,
        "threads": THREAD_WORKERS,
        "retries": MAX_RETRIES,
        "status": "running"
    }

@app.get("/check", tags=["check"])
async def check_get(
    card: str = Query(..., description="Card: number|mm|yyyy|cvv"),
    url: str = Query(..., description="Shopify store URL (e.g., https://store.myshopify.com)"),
    proxy: str = Query(..., description="Proxy: http://user:pass@host:port"),
    low: str = Query("true", description="true = prefer products under $5"),
):
    """Check a card via GET query parameters."""
    card_val, err = _validate_card(card)
    if err:
        return {"Response": "ERROR", "CC": card, "Price": "0.00", "Gate": "Shopify", "Charged": "False", "error": err}
    
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    proxy_val = _validate_proxy(proxy)
    if not proxy_val:
        return {"Response": "ERROR", "CC": card, "Price": "0.00", "Gate": "Shopify", "Charged": "False", "error": "Invalid proxy format"}

    low_mode = low.strip().lower() in ("1", "true", "yes")
    
    loop = asyncio.get_event_loop()
    fn = functools.partial(run_checkout_for_card, url, card_val, proxy_val, low_mode)
    res = await loop.run_in_executor(_pool, fn)
    return _build_response(res, url)

@app.post("/check", tags=["check"])
async def check_post(req: CheckRequest):
    """Check a card via POST JSON body."""
    card_val, err = _validate_card(req.card)
    if err:
        return {"Response": "ERROR", "CC": req.card or "", "Price": "0.00", "Gate": "Shopify", "Charged": "False", "error": err}
    
    url = req.shop_url
    if not url:
        return {"Response": "ERROR", "CC": req.card or "", "Price": "0.00", "Gate": "Shopify", "Charged": "False", "error": "shop_url required"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    proxy_val = _validate_proxy(req.proxy)
    if not proxy_val:
        return {"Response": "ERROR", "CC": req.card, "Price": "0.00", "Gate": "Shopify", "Charged": "False", "error": "Invalid proxy format"}

    loop = asyncio.get_event_loop()
    fn = functools.partial(run_checkout_for_card, url, card_val, proxy_val, req.low)
    res = await loop.run_in_executor(_pool, fn)
    return _build_response(res, url)

@app.get("/", tags=["meta"])
async def root():
    return {
        "service": "ZERO CHECK API",
        "version": "2.0.0",
        "endpoints": {
            "health": "/health",
            "check": "/check?card=CARD&url=STORE&proxy=PROXY&low=true",
            "docs": "/docs (disabled)"
        }
    }

# ==================== RUN ====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    logger.info(f"🚀 ZERO CHECK API starting on port {port} (threads={THREAD_WORKERS})")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
