import time
import hmac
import hashlib
import base64
import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
CUSTOMER_ID = os.getenv("CUSTOMER_ID")
BASE_URL = "https://api.naver.com"

def generate_signature(method, uri, timestamp):
    msg = f"{timestamp}.{method}.{uri}"
    signature = hmac.new(API_SECRET.encode('utf-8'),
                         msg.encode('utf-8'),
                         hashlib.sha256).digest()
    return base64.b64encode(signature).decode('utf-8')

def fetch_relkwdstat(hint_keywords):
    uri = "/keywordstool"
    method = "GET"
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(method, uri, timestamp)

    headers = {
        "X-Timestamp": timestamp,
        "X-API-KEY": API_KEY,
        "X-Customer": CUSTOMER_ID,
        "X-Signature": signature
    }

    # ✅ 공백 제거 정제
    cleaned_keywords = [str(kw).replace(" ", "").strip() for kw in hint_keywords if kw]

    params = {
        "hintKeywords": ",".join(cleaned_keywords),
        "showDetail": 1
    }

    response = requests.get(BASE_URL + uri, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        results = []
        for item in data.get("keywordList", []):
            # ✅ 월평균 PC/모바일 클릭수를 합산 → 최근4주클릭수평균
            pc_click_avg = float(item.get("monthlyAvePcClkCnt", 0))
            mobile_click_avg = float(item.get("monthlyAveMobileClkCnt", 0))
            recent_4weeks_click_avg = pc_click_avg + mobile_click_avg

            results.append({
                "relKeyword": item.get("relKeyword"),
                "최근4주클릭수평균": recent_4weeks_click_avg
            })
        return results
    else:
        print("API 호출 실패:", response.status_code, response.text)
        return []