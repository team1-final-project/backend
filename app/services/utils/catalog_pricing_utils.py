import re


PACK_COUNT_PATTERNS = [
    r"(\d+)\s*개",
    r"(\d+)\s*입",
    r"(\d+)\s*팩",
    r"(\d+)\s*봉",
    r"(\d+)\s*포",
    r"(\d+)\s*캔",
    r"(\d+)\s*병",
]

# 상품 이름 파싱
def parse_pack_count(name: str | None) -> int:
    if not name:
        return 1

    text = re.sub(r"\s+", " ", name).strip()

    for pattern in PACK_COUNT_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = int(match.group(1))
            return value if value > 0 else 1

    return 1

# 파싱한 갯수로 개당 가격 계산
def calculate_unit_sale_price(total_price: int | float | None, pack_count: int) -> int:
    if total_price is None:
        return 0

    total_price = int(total_price)

    if pack_count <= 0:
        return total_price

    return total_price // pack_count