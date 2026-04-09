import re
import time
from typing import List, Optional, Sequence, Tuple

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


URL = "https://place.map.kakao.com/1567468475#comment"
TARGET_COUNT = 10
OUTPUT_CSV = f"reviews_{int(time.time())}.csv"

DEFAULT_WAIT_SECONDS = 5
PAGE_LOAD_SLEEP = 3.0
CLICK_SLEEP = 1.0


def create_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--lang=ko-KR")
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(2)
    return driver


def normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("\n", " ").replace("\t", " ").replace("\r", " ")).strip()


def preview_text(text: str, limit: int = 120) -> str:
    text = normalize_whitespace(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def get_text(element: WebElement) -> str:
    try:
        return normalize_whitespace(element.text)
    except (StaleElementReferenceException, WebDriverException):
        return ""


def find_first_clickable(
    driver: webdriver.Chrome,
    xpaths: Sequence[str],
    timeout: int = DEFAULT_WAIT_SECONDS,
) -> Optional[WebElement]:
    wait = WebDriverWait(driver, timeout)
    for xpath in xpaths:
        try:
            return wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        except TimeoutException:
            continue
    return None


def click_first_matching(
    driver: webdriver.Chrome,
    xpaths: Sequence[str],
    success_message: str,
    fail_message: str,
) -> bool:
    element = find_first_clickable(driver, xpaths)
    if element is None:
        print(fail_message)
        return False

    try:
        driver.execute_script("arguments[0].click();", element)
        print(success_message)
        time.sleep(CLICK_SLEEP)
        return True
    except WebDriverException as exc:
        print(f"{fail_message} ({exc})")
        return False


def parse_date(text: str) -> str:
    patterns = [
        r"(\d{4}-\d{1,2}-\d{1,2})",
        r"(\d{4}\.\d{1,2}\.\d{1,2})",
        r"(\d{4}/\d{1,2}/\d{1,2})",
        r"(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            value = match.group(1)
            if "년" in value:
                value = value.replace("년", "-").replace("월", "-").replace("일", "")
                value = re.sub(r"\s+", "", value)
            return value.replace(".", "-").replace("/", "-")
    return ""


def click_review_tab(driver: webdriver.Chrome) -> bool:
    return click_first_matching(
        driver,
        [
            "//a[contains(@href, '#comment')]",
            "//a[contains(@href, '#review')]",
            "//a[contains(., '리뷰')]",
            "//button[contains(., '리뷰')]",
        ],
        "[OK] 리뷰 탭 클릭 성공",
        "[WARN] 리뷰 탭 클릭 실패",
    )


def click_latest_sort(driver: webdriver.Chrome) -> bool:
    return click_first_matching(
        driver,
        [
            "//*[self::a or self::button][contains(., '최신순')]",
            "//*[contains(., '최신순')]",
        ],
        "[OK] 최신순 클릭 성공",
        "[WARN] 최신순 클릭 실패",
    )


def is_valid_review_card(card: WebElement) -> bool:
    text = get_text(card)
    return bool(text) and bool(parse_date(text))


def get_review_cards(driver: webdriver.Chrome) -> List[WebElement]:
    selectors: Sequence[Tuple[str, str]] = [
        (By.CSS_SELECTOR, "[data-review-item]"),
        (By.CSS_SELECTOR, "li"),
        (By.CSS_SELECTOR, "article"),
    ]

    best_cards: List[WebElement] = []

    for by, selector in selectors:
        try:
            elements = driver.find_elements(by, selector)
            filtered = [element for element in elements if is_valid_review_card(element)]
            print(f"[DEBUG] selector={selector}, raw={len(elements)}, valid={len(filtered)}")

            if len(filtered) > len(best_cards):
                best_cards = filtered
        except WebDriverException as exc:
            print(f"[WARN] selector 실패: {selector} ({exc})")

    return best_cards


def extract_review_candidates(card: WebElement) -> List[str]:
    candidates: List[str] = []
    selectors: Sequence[Tuple[str, str]] = [
        (By.CSS_SELECTOR, "p"),
        (By.CSS_SELECTOR, "span"),
        (By.CSS_SELECTOR, "div"),
    ]

    for by, selector in selectors:
        try:
            elements = card.find_elements(by, selector)
        except WebDriverException:
            continue

        for element in elements:
            text = get_text(element)
            if not text:
                continue
            candidates.append(text)

    seen = set()
    unique_candidates = []
    for text in candidates:
        if text not in seen:
            seen.add(text)
            unique_candidates.append(text)

    return unique_candidates


def make_review_key(row: dict) -> tuple:
    return (
        row.get("계정 ID", ""),
        row.get("방문 날짜", ""),
        row.get("리뷰 내용", ""),
    )


def parse_one_card(driver: webdriver.Chrome, card: WebElement, idx: int) -> Optional[dict]:
    full_text = get_text(card)
    if not full_text:
        return None

    candidates = extract_review_candidates(card)

    account_id = ""
    account_review_count = ""
    user_level = ""
    visit_date = parse_date(full_text)
    visit_count = ""
    auth_method = ""
    review_text = ""
    has_photo = False

    # 짧은 텍스트 위주로 닉네임 / 레벨 추정
    short_candidates = [c for c in candidates if c and len(c) <= 30]

    level_keywords = ["레벨", "Lv", "LV", "블루", "브론즈", "실버", "골드", "플래티넘"]
    for text in short_candidates:
        if any(k in text for k in level_keywords):
            user_level = text
            break

    for text in short_candidates:
        if text == user_level:
            continue
        if parse_date(text):
            continue
        if "방문" in text or "인증" in text or "후기" in text or "리뷰" in text or "팔로워" in text:
            continue
        if len(text) >= 2:
            account_id = text
            break

    # 계정의 리뷰 수 추정
    review_count_patterns = [
        r"후기\s*(\d+)",
        r"리뷰\s*(\d+)",
        r"(\d+)\s*개의?\s*리뷰",
        r"리뷰\s*수\s*(\d+)",
    ]
    for text in candidates:
        for pattern in review_count_patterns:
            m = re.search(pattern, text)
            if m:
                account_review_count = m.group(1)
                break
        if account_review_count:
            break

    # 방문 횟수 추정
    visit_count_match = re.search(r"(\d+번째\s*방문)", full_text)
    if visit_count_match:
        visit_count = normalize_whitespace(visit_count_match.group(1))

    # 인증 수단 추정
    auth_keywords = ["예약", "주문", "결제", "영수증", "방문", "포장", "배달"]
    for text in candidates:
        if "인증" in text:
            cleaned = text.replace("인증 수단", "").replace("인증", "").strip(" :")
            if cleaned:
                auth_method = cleaned
                break

    if not auth_method:
        for text in candidates:
            if text in auth_keywords:
                auth_method = text
                break

    # 사진 유무 추정
    try:
        imgs = card.find_elements(By.TAG_NAME, "img")
        has_photo = len(imgs) > 0
    except WebDriverException:
        has_photo = False

    # 리뷰 본문 추정
    meta_keywords = ["레벨", "방문", "인증", "후기", "리뷰", "팔로워"]
    review_candidates = []

    for text in candidates:
        if not text:
            continue
        if parse_date(text):
            continue
        if text == account_id or text == user_level or text == auth_method or text == visit_count:
            continue
        if any(k in text for k in meta_keywords) and len(text) < 25:
            continue
        if len(text) >= 5:
            review_candidates.append(text)

    if review_candidates:
        review_text = max(review_candidates, key=len)
    else:
        review_text = full_text

    review_text = normalize_whitespace(review_text)
    review_char_count = len(review_text)

    row = {
        "계정 ID": account_id,
        "계정의 리뷰 수": account_review_count,
        "방문 날짜": visit_date,
        "방문 횟수": visit_count,
        "인증 수단": auth_method,
        "리뷰 내 사진 유무": has_photo,
        "리뷰 글자 수": review_char_count,
        "리뷰 내용": review_text,
        "카카오맵 리뷰다는 사람 레벨": user_level,
    }

    return row


def collect_visible_reviews(driver, collected_dict, limit=TARGET_COUNT):
    cards = get_review_cards(driver)
    new_count = 0
    parsed_count = 0

    for idx, card in enumerate(cards, start=1):
        if limit is not None and len(collected_dict) >= limit:
            break

        try:
            row = parse_one_card(driver, card, idx)
            if not row:
                continue

            parsed_count += 1
            key = make_review_key(row)

            if key not in collected_dict:
                collected_dict[key] = row
                new_count += 1

                print("\n" + "=" * 70)
                print(f"[PREVIEW] 수집 #{len(collected_dict)}")
                print(f"계정 ID       : {row['계정 ID']}")
                print(f"계정의 리뷰 수 : {row['계정의 리뷰 수']}")
                print(f"방문 날짜      : {row['방문 날짜']}")
                print(f"방문 횟수      : {row['방문 횟수']}")
                print(f"인증 수단      : {row['인증 수단']}")
                print(f"사진 유무      : {row['리뷰 내 사진 유무']}")
                print(f"글자 수        : {row['리뷰 글자 수']}")
                print(f"리뷰 내용      : {preview_text(row['리뷰 내용'], 120)}")
                print("=" * 70)

                if limit is not None and len(collected_dict) >= limit:
                    print(f"[INFO] 목표 수집 개수 {limit}개 도달")
                    break

        except Exception as e:
            print(f"[WARN] 카드 파싱 실패: {e}")

    print(
        f"[INFO] 현재 화면 파싱 성공: {parsed_count}개 / "
        f"신규 누적: {new_count}개 / 총 누적: {len(collected_dict)}개"
    )
    return new_count


def try_click_more_button(driver: webdriver.Chrome) -> bool:
    xpaths = [
        "//*[self::a or self::button][contains(., '더보기')]",
        "//*[self::a or self::button][contains(., '후기 더보기')]",
        "//*[self::a or self::button][contains(., '리뷰 더보기')]",
    ]

    for xpath in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed() and el.is_enabled():
                    driver.execute_script("arguments[0].click();", el)
                    print("[OK] 더보기 클릭")
                    time.sleep(1.5)
                    return True
        except WebDriverException:
            continue

    print("[WARN] 더보기 버튼 못 찾음")
    return False


def crawl_reviews() -> pd.DataFrame:
    driver = create_driver()

    try:
        print("[STEP] open site")
        driver.get(URL)
        time.sleep(PAGE_LOAD_SLEEP)

        review_tab_ok = click_review_tab(driver)
        latest_sort_ok = click_latest_sort(driver)
        print(f"[INFO] review_tab_ok={review_tab_ok}, latest_sort_ok={latest_sort_ok}")

        collected_dict = {}
        no_new_rounds = 0
        max_rounds = 30

        for round_idx in range(1, max_rounds + 1):
            print(f"\n[STEP] load round {round_idx}/{max_rounds}")

            new_count = collect_visible_reviews(driver, collected_dict, limit=TARGET_COUNT)

            if TARGET_COUNT is not None and len(collected_dict) >= TARGET_COUNT:
                print(f"[INFO] 목표 수집 개수 {TARGET_COUNT}개 도달로 종료")
                break

            clicked = try_click_more_button(driver)

            if not clicked:
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    print("[INFO] 페이지 하단으로 스크롤")
                except WebDriverException:
                    pass
                time.sleep(2)

            if new_count == 0:
                no_new_rounds += 1
            else:
                no_new_rounds = 0

            if no_new_rounds >= 3:
                print("[INFO] 더 이상 신규 리뷰가 없어 종료")
                break

        rows = list(collected_dict.values())
        df = pd.DataFrame(rows)
        df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

        print(f"[INFO] 총 수집된 리뷰 수: {len(df)}")
        print(f"[DONE] 저장 완료: {OUTPUT_CSV}")
        print(df.head(10))

        return df

    finally:
        driver.quit()


if __name__ == "__main__":
    crawl_reviews()