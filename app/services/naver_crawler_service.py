import re
import subprocess
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


_DEBUG_PORT = 9222
_USER_DATA_DIR = r"C:\chrometemp"
_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

_chrome_process = None
_shared_driver = None


# 카탈로그 최저가 찾아서 반환
def _parse_lowest_price_from_text(text: str) -> float | None:
    if not text:
        return None

    normalized = re.sub(r"\s+", " ", text)

    patterns = [
        r"최저\s*([\d,]+)\s*원",
        r"최저가\s*([\d,]+)\s*원",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return float(match.group(1).replace(",", ""))

    return None


# 카탈로그 이름 찾아서 반환
def _parse_catalog_name_from_text(text: str) -> str | None:
    if not text:
        return None

    stop_words = [
        "카탈로그",
        "평점", "최저", "최저가", "배송비포함", "배송", "무료",
        "리뷰", "찜", "수량", "공식인증", "구매가기", "kcal", "로딩 중"
    ]

    leading_noise_words = [
        "장바구니", "마이쇼핑", "카테고리",
        "검색영역", "검색레이어", "검색",
        "가격비교", "네이버페이", "네이버", "NAVER",
        "로그인", "서비스", "더보기", "사용자", "링크"
    ]

    normalized = re.sub(r"\s+", " ", text).strip()

    match = re.search(r"브랜드\s*카탈로그\s*(.+)", normalized)
    if match:
        candidate = match.group(1).strip()
    else:
        candidate = normalized

    cut_positions = [candidate.find(word) for word in stop_words if word in candidate]
    if cut_positions:
        candidate = candidate[:min(cut_positions)].strip()

    last_noise_end = -1
    for word in leading_noise_words:
        idx = candidate.rfind(word)
        if idx != -1:
            last_noise_end = max(last_noise_end, idx + len(word))

    if last_noise_end != -1:
        candidate = candidate[last_noise_end:].strip()

    candidate = re.sub(r"\s*\d+건.*$", "", candidate).strip()

    if re.fullmatch(r"[\d.]+", candidate):
        return None

    if not re.search(r"[A-Za-z가-힣]", candidate):
        return None

    return candidate or None


def _launch_debug_chrome_once() -> None:
    global _chrome_process

    if _chrome_process is not None and _chrome_process.poll() is None:
        return

    cmd = [
        _CHROME_PATH,
        f"--remote-debugging-port={_DEBUG_PORT}",
        f"--user-data-dir={_USER_DATA_DIR}",
    ]
    _chrome_process = subprocess.Popen(cmd)
    time.sleep(1.5)


def _create_or_get_driver() -> webdriver.Chrome:
    global _shared_driver

    if _shared_driver is not None:
        try:
            _ = _shared_driver.current_url
            return _shared_driver
        except Exception:
            _shared_driver = None

    _launch_debug_chrome_once()

    option = webdriver.ChromeOptions()
    option.add_argument("--window-size=1920,1080")
    option.add_argument("--start-maximized")
    option.add_experimental_option("debuggerAddress", f"127.0.0.1:{_DEBUG_PORT}")

    _shared_driver = webdriver.Chrome(options=option)
    _shared_driver.set_window_size(1920, 1080)
    return _shared_driver


def _keep_only_one_window(driver: webdriver.Chrome) -> None:
    handles = driver.window_handles
    if not handles:
        return

    main_handle = handles[0]
    driver.switch_to.window(main_handle)

    for handle in handles[1:]:
        try:
            driver.switch_to.window(handle)
            driver.close()
        except Exception:
            pass

    driver.switch_to.window(main_handle)


def _cleanup_after_crawl(driver: webdriver.Chrome, keep_current_page: bool = False) -> None:
    try:
        _keep_only_one_window(driver)
        driver.switch_to.window(driver.window_handles[0])

        if not keep_current_page:
            driver.get("about:blank")
    except Exception:
        pass


# 크롤링 (카테고리명, 최저가)
def fetch_catalog_info_by_catalog(catalog_code: str) -> dict:
    url = f"https://search.shopping.naver.com/catalog/{catalog_code}"
    driver = _create_or_get_driver()
    is_blocked = False

    try:
        _keep_only_one_window(driver)
        driver.switch_to.window(driver.window_handles[0])
        driver.get(url)

        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        body_text = driver.find_element(By.TAG_NAME, "body").text
        page_source = driver.page_source

        blocked_keywords = [
            "보안 확인을 완료해 주세요",
            "captcha",
            "스팸을 방지",
            "실제 사용자임을 확인",
        ]
        joined_text = f"{driver.title}\n{body_text}\n{page_source[:2000]}".lower()

        if any(keyword.lower() in joined_text for keyword in blocked_keywords):
            is_blocked = True
            print(f"⚠️ 네이버 보안 페이지 감지(catalog_code={catalog_code}) - 창을 유지합니다.")
            return {
                "catalog_code": catalog_code,
                "catalog_name": None,
                "lowest_price": None,
            }

        lowest_price = _parse_lowest_price_from_text(body_text)
        if lowest_price is None:
            lowest_price = _parse_lowest_price_from_text(page_source)

        catalog_name = _parse_catalog_name_from_text(body_text)
        if catalog_name is None:
            catalog_name = _parse_catalog_name_from_text(page_source)

        if lowest_price is None:
            xpath_candidates = [
                "//*[contains(text(), '최저')]/following::*[contains(text(), '원')][1]",
                "//*[contains(text(), '최저가')]/following::*[contains(text(), '원')][1]",
            ]

            for xpath in xpath_candidates:
                elements = driver.find_elements(By.XPATH, xpath)
                for el in elements:
                    text = el.text.strip()
                    match = re.search(r"([\d,]+)\s*원", text)
                    if match:
                        lowest_price = float(match.group(1).replace(",", ""))
                        break
                if lowest_price is not None:
                    break

        return {
            "catalog_code": catalog_code,
            "catalog_name": catalog_name,
            "lowest_price": lowest_price,
        }

    except Exception as e:
        print(f"⚠️ 카탈로그 정보 조회 실패(catalog_code={catalog_code}): {e}")
        return {
            "catalog_code": catalog_code,
            "catalog_name": None,
            "lowest_price": None,
        }

    finally:
        _cleanup_after_crawl(driver, keep_current_page=is_blocked)

# 크롤링 (최저가)
def fetch_lowest_price_by_catalog(catalog_code: str) -> float | None:
    return fetch_catalog_info_by_catalog(catalog_code)["lowest_price"]


# 크롤링 (카테고리명)
def fetch_catalog_name_by_catalog(catalog_code: str) -> str | None:
    return fetch_catalog_info_by_catalog(catalog_code)["catalog_name"]