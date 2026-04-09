import re
import time
from dataclasses import dataclass
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


URL = "https://place.map.kakao.com/1567468475"
TARGET_COUNT = 10
OUTPUT_CSV = f"reviews_{int(time.time())}.csv"

DEFAULT_WAIT_SECONDS = 5
PAGE_LOAD_SLEEP = 3.0
CLICK_SLEEP = 1.0


@dataclass
class ReviewRow:
    account_id: str = ""
    user_level: str = ""
    visit_date: str = ""
    review_text: str = ""


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
    return bool(text) and (bool(parse_date(text)))


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


def debug_card(cards: List[WebElement]) -> None:
    if not cards:
        print("[DEBUG] 카드 없음")
        return

    for i, card in enumerate(cards[:5], start=1):
        text = get_text(card)
        print(f"\n[DEBUG CARD {i}]")
        print(text[:500])


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


def crawl_reviews() -> pd.DataFrame:
    driver = create_driver()

    try:
        print("[STEP] open site")
        driver.get(URL)
        time.sleep(PAGE_LOAD_SLEEP)

        review_tab_ok = click_review_tab(driver)
        latest_sort_ok = click_latest_sort(driver)
        print(f"[INFO] review_tab_ok={review_tab_ok}, latest_sort_ok={latest_sort_ok}")

        cards = []
        for _ in range(20):
            new_cards = get_review_cards(driver)

            print(f"[INFO] 현재 카드 수: {len(new_cards)}")

            if len(new_cards) > len(cards):
                cards = new_cards
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        print(f"[INFO] 카드 수: {len(cards)}")
        debug_card(cards)

        rows = []
        for idx, card in enumerate(cards[:TARGET_COUNT], start=1):
            full_text = get_text(card)
            candidates = extract_review_candidates(card)

            print(f"\n[DEBUG REVIEW {idx}]")
            print("FULL:", full_text[:300])
            print("CANDIDATES:", candidates[:10])

            rows.append(
                {
                    "index": idx,
                    "full_text": full_text,
                    "candidate_count": len(candidates),
                    "first_candidate": candidates[0] if candidates else "",
                }
            )

        df = pd.DataFrame(rows)
        df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"[DONE] 저장 완료: {OUTPUT_CSV}")
        return df

    finally:
        driver.quit()


if __name__ == "__main__":
    crawl_reviews()