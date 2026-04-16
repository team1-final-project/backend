import requests
import json
import pandas as pd
from dotenv import load_dotenv
import os

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
URL = "https://openapi.naver.com/v1/datalab/shopping/category/keywords"

def fetch_category_keyword_data(start_date, end_date, category, keyword):
    payload = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "date",  # day, week, month 가능
        "category": category,  # 예: "50000006" (식품)
        "keyword": [
            {"name": keyword, "param": [keyword]}
        ]
    }

    headers = {
        "X-Naver-Client-Id": CLIENT_ID,
        "X-Naver-Client-Secret": CLIENT_SECRET,
        "Content-Type": "application/json"
    }

    response = requests.post(URL, headers=headers, data=json.dumps(payload))
    if response.status_code == 200:
        result = response.json()
        df = pd.DataFrame(result["results"][0]["data"])
        if df.empty:
            print(f"⚠️ 카테고리 {category}, 키워드 '{keyword}' 기간 {start_date}~{end_date} 데이터 없음")
            return pd.DataFrame(columns=["날짜", "클릭량"])   # ✅ 클릭량으로 반환
        df["날짜"] = pd.to_datetime(df["period"])
        df.rename(columns={"ratio": "클릭량"}, inplace=True)   # ✅ 클릭량으로 변경
        return df[["날짜", "클릭량"]]
    else:
        print(f"❌ API 요청 실패: {response.status_code}, {response.text}")
        return pd.DataFrame(columns=["날짜", "클릭량"])   # ✅ 실패 시에도 클릭량 컬럼