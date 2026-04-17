from __future__ import annotations

import datetime
import math
from typing import Dict, List, Optional
import re

import pandas as pd
from fastapi import HTTPException

from app.ai.loader import get_gam_model, get_goodid_encoder, get_x_columns
from app.ai.utils.naver_searchad_relkeyword import fetch_relkwdstat
from app.ai.utils.naver_shoppinginsite_search import fetch_category_keyword_data

gam = get_gam_model()
X_columns = get_x_columns()
goodid_encoder = get_goodid_encoder()

PRICE_FACTORS = [0.6, 0.8, 1.0, 1.2, 1.4]

PRICE_STEP = 100
SALES_CONVERSION_RATE = 0.5
HIGH_STOCK_MULTIPLIER = 2.0
LOW_STOCK_MULTIPLIER = 1.2
DEFAULT_CATEGORY_CODE = "50000006"

BRAND_PREFIXES = [
    "CJ", "CJ제일제당", "오뚜기", "농심", "삼양", "팔도", "롯데", "코카콜라", "양반"
]

PACK_PATTERNS = [
    r"\b\d+\s*개\b",
    r"\b\d+\s*입\b",
    r"\b\d+\s*박스\b",
    r"\b\d+\s*팩\b",
    r"\b\d+\s*묶음\b",
]

def normalize_search_keyword(product_name: str) -> str:
    if not product_name:
        return ""

    text = product_name.strip()

    # 괄호 제거
    text = re.sub(r"\([^)]*\)", " ", text)

    # 맨 앞 브랜드 제거
    for brand in BRAND_PREFIXES:
        pattern = rf"^\s*{re.escape(brand)}\s+"
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # 포장/수량 표현 제거
    for pattern in PACK_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    # 특수문자 정리
    text = re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", text)

    # 공백 정리
    text = re.sub(r"\s+", " ", text).strip()

    # 단위 제거
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(g|kg|ml|l)\b", " ", text, flags=re.IGNORECASE)

    return text


def get_recent_ratio(keyword: str, category_code: str = DEFAULT_CATEGORY_CODE) -> float:
    """
    최근 4주 클릭수 비율 계산
    """
    search_keyword = normalize_search_keyword(keyword)
    rel_data = fetch_relkwdstat([search_keyword])
    recent_avg = rel_data[0].get("최근4주클릭수평균", 0) if rel_data else 0

    today = pd.Timestamp.today()
    start_date = today - pd.DateOffset(days=30)
    end_date = today

    try:
        search_df = fetch_category_keyword_data(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            category=category_code,
            keyword=search_keyword,
        )
    except Exception as e:
        print(f"⚠️ 검색지표 API 호출 실패: {e}")
        search_df = pd.DataFrame(columns=["날짜", "클릭량"])

    prev_sum = search_df["클릭량"].sum() if not search_df.empty else 0
    total_clicks = recent_avg * 30

    return (total_clicks / prev_sum) if prev_sum > 0 else 0.0


def _encode_good_id(good_id: str) -> int:
    try:
        return int(goodid_encoder.transform([good_id])[0])
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"알 수 없는 good_id 입니다: {good_id}",
        ) from e


def build_test_df(
    price: float,
    good_id: str,
    recent_ratio: float,
    target_date: datetime.date,
) -> pd.DataFrame:
    weekday = target_date.weekday()
    good_id_enc = _encode_good_id(good_id)

    test_data = {
        "discount_price": price,
        "최근4주클릭수_비율": recent_ratio,
        "weekday": weekday,
        "good_id_enc": good_id_enc,
    }

    df = pd.DataFrame([test_data])
    return df.reindex(columns=X_columns, fill_value=0)


def predict_clicks_for_date(
    price: float,
    good_id: str,
    recent_ratio: float,
    target_date: datetime.date,
) -> float:
    test_df = build_test_df(
        price=price,
        good_id=good_id,
        recent_ratio=recent_ratio,
        target_date=target_date,
    )
    pred_clicks = float(gam.predict(test_df)[0])
    return max(pred_clicks, 0.0)


def predict_today_clicks(
    price: float,
    good_id: str,
    recent_ratio: float,
) -> float:
    return predict_clicks_for_date(
        price=price,
        good_id=good_id,
        recent_ratio=recent_ratio,
        target_date=datetime.date.today(),
    )


def predict_today_sales(
    price: float,
    good_id: str,
    recent_ratio: float,
) -> float:
    today_clicks = predict_today_clicks(price, good_id, recent_ratio)
    return today_clicks * SALES_CONVERSION_RATE


def predict_week(
    keyword: str,
    price: float,
    good_id: str,
    category_code: str = DEFAULT_CATEGORY_CODE,
    price_factors: Optional[List[float]] = None,
) -> Dict:
    if price <= 0:
        raise HTTPException(status_code=400, detail="가격은 0보다 커야 합니다.")

    factors = price_factors or PRICE_FACTORS
    recent_ratio = get_recent_ratio(keyword, category_code=category_code)

    results = []

    for offset in range(7):
        target_date = datetime.date.today() + datetime.timedelta(days=offset)
        day_result = {
            "예측일": str(target_date),
            "예측요일": target_date.strftime("%A"),
            "배율별예측": {},
        }

        for factor in factors:
            target_price = price * factor
            pred_clicks = predict_clicks_for_date(
                price=target_price,
                good_id=good_id,
                recent_ratio=recent_ratio,
                target_date=target_date,
            )
            day_result["배율별예측"][f"{int(factor * 100)}%"] = pred_clicks

        results.append(day_result)

    return {
        "keyword": keyword,
        "good_id": good_id,
        "results": results,
    }


def floor_to_step(value: float, step: int = PRICE_STEP) -> float:
    return float(math.floor(value / step) * step)


def ceil_to_step(value: float, step: int = PRICE_STEP) -> float:
    return float(math.ceil(value / step) * step)


def round_change_rate(old_price: float, new_price: float) -> float:
    if old_price <= 0:
        return 0.0
    return round(((new_price - old_price) / old_price) * 100, 1)


def validate_price_inputs(
    current_price: float,
    min_price_limit: float,
    max_price_limit: float,
    current_stock: float,
    safety_stock: float,
) -> None:
    if current_price <= 0:
        raise HTTPException(status_code=400, detail="현재 가격은 0보다 커야 합니다.")

    if min_price_limit <= 0:
        raise HTTPException(status_code=400, detail="최저가 제한은 0보다 커야 합니다.")

    if max_price_limit <= 0:
        raise HTTPException(status_code=400, detail="최고가 제한은 0보다 커야 합니다.")

    if min_price_limit > max_price_limit:
        raise HTTPException(
            status_code=400,
            detail="최저가 제한은 최고가 제한보다 클 수 없습니다.",
        )

    if current_stock < 0:
        raise HTTPException(status_code=400, detail="현재 재고는 0 이상이어야 합니다.")

    if safety_stock <= 0:
        raise HTTPException(status_code=400, detail="안전 재고는 0보다 커야 합니다.")

    if current_price < min_price_limit or current_price > max_price_limit:
        raise HTTPException(
            status_code=400,
            detail="현재 가격은 최저가 제한과 최고가 제한 사이여야 합니다.",
        )

    min_step_price = ceil_to_step(min_price_limit)
    max_step_price = floor_to_step(max_price_limit)

    if min_step_price > max_step_price:
        raise HTTPException(
            status_code=400,
            detail="최저가 제한과 최고가 제한 사이에 100원 단위 가격 후보가 없습니다.",
        )


def generate_price_candidates(
    current_price: float,
    min_price_limit: float,
    max_price_limit: float,
    max_change: float,
    mode: str,
) -> List[float]:
    raw_low = max(min_price_limit, current_price - max_change)
    raw_high = min(max_price_limit, current_price + max_change)

    if mode == "up":
        start = ceil_to_step(max(current_price, min_price_limit))
        end = floor_to_step(raw_high)
    elif mode == "down":
        start = ceil_to_step(raw_low)
        end = floor_to_step(min(current_price, max_price_limit))
    elif mode == "both":
        start = ceil_to_step(raw_low)
        end = floor_to_step(raw_high)
    else:
        raise ValueError(f"지원하지 않는 mode 입니다: {mode}")

    candidates: List[float] = []

    if start <= end:
        candidates.extend(
            float(p) for p in range(int(start), int(end) + PRICE_STEP, PRICE_STEP)
        )

    if raw_low <= current_price <= raw_high and min_price_limit <= current_price <= max_price_limit:
        candidates.append(float(current_price))

    return sorted(set(candidates))


def get_inventory_state(current_stock: float, safety_stock: float) -> str:
    if current_stock >= safety_stock * HIGH_STOCK_MULTIPLIER:
        return "high"
    if current_stock <= safety_stock * LOW_STOCK_MULTIPLIER:
        return "low"
    return "normal"


def evaluate_price(
    price: float,
    current_stock: float,
    safety_stock: float,
    good_id: str,
    recent_ratio: float,
    cache: Dict[float, Dict[str, float]],
) -> Dict[str, float]:
    if price in cache:
        return cache[price]

    predicted_sales = predict_today_sales(price, good_id, recent_ratio)
    remaining_stock = current_stock - predicted_sales
    expected_revenue = price * predicted_sales

    result = {
        "price": float(price),
        "predicted_sales": float(predicted_sales),
        "remaining_stock": float(remaining_stock),
        "expected_revenue": float(expected_revenue),
        "is_safe": remaining_stock >= safety_stock,
    }
    cache[price] = result
    return result


def pick_closest_candidate(
    candidates: List[float],
    target_price: float,
    prefer: str = "lower",
) -> float:
    if not candidates:
        raise ValueError("후보 가격이 없습니다.")

    if prefer == "higher":
        return min(candidates, key=lambda p: (abs(p - target_price), -p))

    return min(candidates, key=lambda p: (abs(p - target_price), p))


def select_best_revenue_candidate(
    candidates: List[float],
    current_stock: float,
    safety_stock: float,
    good_id: str,
    recent_ratio: float,
    cache: Dict[float, Dict[str, float]],
) -> Dict[str, float]:
    if not candidates:
        raise ValueError("후보 가격이 없습니다.")

    evaluated = [
        evaluate_price(
            price=p,
            current_stock=current_stock,
            safety_stock=safety_stock,
            good_id=good_id,
            recent_ratio=recent_ratio,
            cache=cache,
        )
        for p in candidates
    ]

    safe_candidates = [x for x in evaluated if x["is_safe"]]

    if safe_candidates:
        return max(
            safe_candidates,
            key=lambda x: (
                x["expected_revenue"],
                x["remaining_stock"],
                -abs(x["price"]),
            ),
        )

    return max(
        evaluated,
        key=lambda x: (
            x["remaining_stock"],
            x["expected_revenue"],
            x["price"],
        ),
    )


def select_best_sales_candidate(
    candidates: List[float],
    current_stock: float,
    safety_stock: float,
    good_id: str,
    recent_ratio: float,
    cache: Dict[float, Dict[str, float]],
) -> Dict[str, float]:
    if not candidates:
        raise ValueError("후보 가격이 없습니다.")

    evaluated = [
        evaluate_price(
            price=p,
            current_stock=current_stock,
            safety_stock=safety_stock,
            good_id=good_id,
            recent_ratio=recent_ratio,
            cache=cache,
        )
        for p in candidates
    ]

    return max(
        evaluated,
        key=lambda x: (
            x["predicted_sales"],
            -x["price"],
        ),
    )


def decide_price(
    current_price: float,
    price_change_limit: float,
    min_price_limit: float,
    max_price_limit: float,
    current_stock: float,
    safety_stock: float,
    market_lowest_price: Optional[float],
    good_id: str,
    recent_ratio: float,
) -> Dict[str, float]:
    max_change = price_change_limit
    inventory_state = get_inventory_state(current_stock, safety_stock)
    cache: Dict[float, Dict[str, float]] = {}

    if inventory_state == "high":
        if market_lowest_price is not None:
            market_lowest_price = float(market_lowest_price)

            if current_price <= market_lowest_price:
                candidates = generate_price_candidates(
                    current_price=current_price,
                    min_price_limit=min_price_limit,
                    max_price_limit=max_price_limit,
                    max_change=max_change,
                    mode="up",
                )

                target_price = min(
                    current_price + max_change,
                    market_lowest_price,
                    max_price_limit,
                )

                if not candidates:
                    final_price = floor_to_step(
                        min(max(current_price, min_price_limit), max_price_limit)
                    )
                else:
                    final_price = pick_closest_candidate(
                        candidates,
                        target_price,
                        prefer="higher",
                    )

            elif current_price - max_change <= market_lowest_price:
                candidates = generate_price_candidates(
                    current_price=current_price,
                    min_price_limit=min_price_limit,
                    max_price_limit=max_price_limit,
                    max_change=max_change,
                    mode="down",
                )

                target_price = floor_to_step(market_lowest_price - 1)
                target_price = max(target_price, min_price_limit)

                if not candidates:
                    final_price = floor_to_step(
                        min(max(current_price, min_price_limit), max_price_limit)
                    )
                else:
                    final_price = pick_closest_candidate(
                        candidates,
                        target_price,
                        prefer="lower",
                    )

            else:
                candidates = generate_price_candidates(
                    current_price=current_price,
                    min_price_limit=min_price_limit,
                    max_price_limit=max_price_limit,
                    max_change=max_change,
                    mode="down",
                )

                target_price = max(current_price - max_change, min_price_limit)

                if not candidates:
                    final_price = floor_to_step(
                        min(max(current_price, min_price_limit), max_price_limit)
                    )
                else:
                    final_price = pick_closest_candidate(
                        candidates,
                        target_price,
                        prefer="lower",
                    )

            chosen = evaluate_price(
                price=final_price,
                current_stock=current_stock,
                safety_stock=safety_stock,
                good_id=good_id,
                recent_ratio=recent_ratio,
                cache=cache,
            )
            return chosen

        candidates = generate_price_candidates(
            current_price=current_price,
            min_price_limit=min_price_limit,
            max_price_limit=max_price_limit,
            max_change=max_change,
            mode="both",
        )

        if not candidates:
            raise HTTPException(
                status_code=400,
                detail="재고 많음 상태에서 생성 가능한 가격 후보가 없습니다.",
            )

        return select_best_sales_candidate(
            candidates=candidates,
            current_stock=current_stock,
            safety_stock=safety_stock,
            good_id=good_id,
            recent_ratio=recent_ratio,
            cache=cache,
        )

    if inventory_state == "normal":
        candidates = generate_price_candidates(
            current_price=current_price,
            min_price_limit=min_price_limit,
            max_price_limit=max_price_limit,
            max_change=max_change,
            mode="both",
        )

        if not candidates:
            raise HTTPException(
                status_code=400,
                detail="재고 보통 상태에서 생성 가능한 가격 후보가 없습니다.",
            )

        return select_best_revenue_candidate(
            candidates=candidates,
            current_stock=current_stock,
            safety_stock=safety_stock,
            good_id=good_id,
            recent_ratio=recent_ratio,
            cache=cache,
        )

    candidates = generate_price_candidates(
        current_price=current_price,
        min_price_limit=min_price_limit,
        max_price_limit=max_price_limit,
        max_change=max_change,
        mode="up",
    )

    if not candidates:
        raise HTTPException(
            status_code=400,
            detail="재고 부족 상태에서 생성 가능한 가격 후보가 없습니다.",
        )

    return select_best_revenue_candidate(
        candidates=candidates,
        current_stock=current_stock,
        safety_stock=safety_stock,
        good_id=good_id,
        recent_ratio=recent_ratio,
        cache=cache,
    )


def predict_optimal_price(
    keyword: str,
    current_price: float,
    price_change_limit: float,
    min_price_limit: float,
    max_price_limit: float,
    current_stock: float,
    safety_stock: float,
    good_id: str,
    market_lowest_price: Optional[float] = None,
    catalog_code: Optional[str] = None,
    catalog_name: Optional[str] = None,
    category_code: str = DEFAULT_CATEGORY_CODE,
) -> Dict:
    """
    가격 결정 메인 함수
    외부 최저가는 서비스/엔드포인트에서 먼저 가져와서 넣어주면 된다.
    """
    validate_price_inputs(
        current_price=current_price,
        min_price_limit=min_price_limit,
        max_price_limit=max_price_limit,
        current_stock=current_stock,
        safety_stock=safety_stock,
    )

    recent_ratio = get_recent_ratio(keyword, category_code=category_code)

    chosen = decide_price(
        current_price=current_price,
        price_change_limit=price_change_limit,
        min_price_limit=min_price_limit,
        max_price_limit=max_price_limit,
        current_stock=current_stock,
        safety_stock=safety_stock,
        market_lowest_price=market_lowest_price,
        good_id=good_id,
        recent_ratio=recent_ratio,
    )

    changed_price = float(chosen["price"])
    expected_sales = round(float(chosen["predicted_sales"]), 2)
    change_rate = round_change_rate(current_price, changed_price)

    return {
        "keyword": keyword,
        "catalog_code": catalog_code,
        "catalog_name": catalog_name,
        "expect_sale_amount": expected_sales,
        "market_lowest_price": market_lowest_price,
        "change_price": changed_price,
        "change_rate": change_rate,
        "remaining_stock": round(float(chosen["remaining_stock"]), 2),
        "expected_revenue": round(float(chosen["expected_revenue"]), 2),
    }