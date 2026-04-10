import re
import time
from typing import List, Optional, Sequence

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


URL = "https://place.map.kakao.com/27306859#review" # 나중에 가게 ID를 변수로 바꿔서 여러 가게 크롤링할 수 있게 개선 가능
TARGET_COUNT = 50 # 수집할 리뷰 개수 (None이면 가능한 최대한 많이 수집) -> 년도를 기준으로 수집하도록 수정해야 함
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


def click_latest_sort(driver):
    """
    카카오맵 정렬 구조:
      .btn_sort 클릭 → .layer_sort 드롭다운 열림 (display:none → block)
      → .link_sort 중 '최신 순' 클릭
    """
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn_sort"))
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(0.5)

        links = driver.find_elements(By.CSS_SELECTOR, ".link_sort")
        for link in links:
            if "최신" in link.text:
                driver.execute_script("arguments[0].click();", link)
                print("[최신순] 정렬 클릭 성공")
                time.sleep(1.0)
                return True

    except Exception as e:
        print(f"[DEBUG] click_latest_sort 예외: {e}")

    print("[WARN] 최신순 정렬 클릭 실패 - 기본 정렬로 진행")
    return False


def is_valid_review_card(card: WebElement) -> bool:
    text = get_text(card)
    return bool(text) and bool(parse_date(text))


def get_review_cards(driver: webdriver.Chrome) -> List[WebElement]:
    selectors: Sequence[tuple] = [
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


def make_review_key(row: dict) -> tuple:
    return (
        row.get("계정 ID", ""),
        row.get("방문 날짜", ""),
        row.get("리뷰 내용", ""),
    )


def expand_more_in_card(driver: webdriver.Chrome, card: WebElement) -> None:
    """
    카드 내 .btn_more span을 execute_script .click()으로 클릭해 리뷰 전문을 펼친다.
    - .btn_more.click() → 텍스트 펼쳐짐, URL 변경 없음 (정상)
    - .link_review 클릭 → URL이 #review → # 으로 이동해버림 (사용 금지)
    - dispatchEvent(click) → 동작 안 함 (사용 금지)
    """
    try:
        btn_more = card.find_element(By.CSS_SELECTOR, ".btn_more")
        driver.execute_script("arguments[0].click();", btn_more)
        time.sleep(0.3)
    except (WebDriverException, Exception):
        pass  # btn_more 없으면 이미 전문 상태 — 그냥 통과


def get_css_text(card: WebElement, selector: str) -> str:
    """card 내에서 CSS selector로 첫 번째 요소의 텍스트를 반환"""
    try:
        return normalize_whitespace(card.find_element(By.CSS_SELECTOR, selector).text)
    except (WebDriverException, Exception):
        return ""


def parse_one_card(driver: webdriver.Chrome, card: WebElement, idx: int) -> Optional[dict]:
    # ── 0. 더보기 펼치기 (.link_review 클릭) ────────────────────────────
    expand_more_in_card(driver, card)

    # ── 1. CSS 클래스로 각 필드 직접 추출 ───────────────────────────────

    # 닉네임: .name_user 내 .screen_out("리뷰어 이름," 텍스트) 제거 후 추출
    account_id = ""
    try:
        name_el = card.find_element(By.CSS_SELECTOR, ".name_user")
        account_id = driver.execute_script(
            """
            const el = arguments[0].cloneNode(true);
            el.querySelectorAll('.screen_out').forEach(s => s.remove());
            return el.innerText.trim();
            """,
            name_el,
        )
    except (WebDriverException, Exception):
        pass

    # 레벨: .ico_badge
    user_level = get_css_text(card, ".ico_badge")

    # 리뷰 수: 후기 li (list_detail 첫 번째 li)
    account_review_count = ""
    raw_review_count = get_css_text(card, ".list_detail li:first-child")
    if raw_review_count:
        m = re.search(r"(\d+)", raw_review_count)
        if m:
            account_review_count = m.group(1)

    # 날짜: .txt_date
    visit_date = ""
    raw_date = get_css_text(card, ".txt_date")
    if raw_date:
        visit_date = parse_date(raw_date)

    # 별점: .starred_grade 내 두 번째 .screen_out (CSS hidden이라 JS로 추출)
    rating = ""
    try:
        sg_el = card.find_element(By.CSS_SELECTOR, ".starred_grade")
        rating = driver.execute_script(
            """
            const spans = arguments[0].querySelectorAll('.screen_out');
            return spans.length >= 2 ? spans[1].innerText.trim() : '';
            """,
            sg_el,
        )
    except (WebDriverException, Exception):
        pass

    # 리뷰 본문: .desc_review (더보기 펼친 후의 전문)
    review_text = ""
    try:
        desc_el = card.find_element(By.CSS_SELECTOR, ".desc_review")
        # .btn_more("더보기"), .btn_fold("접기") span 텍스트 제거 후 추출
        review_text = driver.execute_script(
            """
            const el = arguments[0].cloneNode(true);
            el.querySelectorAll('.btn_more, .btn_fold').forEach(s => s.remove());
            return el.innerText.trim();
            """,
            desc_el,
        )
        review_text = normalize_whitespace(review_text)
    except (WebDriverException, Exception):
        pass

    # ── 2. 텍스트 리뷰 없는 카드 제외 (별점만 남긴 유저) ────────────────
    if not review_text:
        return None

    # ── 3. 사진 유무: .review_thumb 또는 .list_photo 존재 여부 ───────────
    has_photo = False
    try:
        card.find_element(By.CSS_SELECTOR, ".review_thumb")
        has_photo = True
    except (WebDriverException, Exception):
        has_photo = False

    review_char_count = len(review_text)

    row = {
        "계정 ID": account_id,
        "계정의 리뷰 수": account_review_count,
        "방문 날짜": visit_date,
        "별점": rating,
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
                print(f"별점           : {row['별점']}")
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


def scroll_down(driver: webdriver.Chrome) -> None:
    """단계적으로 스크롤을 내려 무한스크롤 트리거"""
    try:
        current_height = driver.execute_script("return document.body.scrollHeight")
        step = current_height // 4
        for i in range(1, 5):
            driver.execute_script(f"window.scrollTo(0, {step * i});")
            time.sleep(0.4)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        print("[INFO] 단계적 스크롤 완료")
        time.sleep(3.0)
    except WebDriverException as e:
        print(f"[WARN] 스크롤 실패: {e}")


def crawl_reviews() -> pd.DataFrame:
    driver = create_driver()

    try:
        print("[STEP] open site")
        driver.get(URL)
        time.sleep(PAGE_LOAD_SLEEP)

        latest_sort_ok = click_latest_sort(driver)
        print(f"latest_sort_ok={latest_sort_ok}")

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
            scroll_down(driver)  # 더보기 클릭 성공 여부와 무관하게 항상 스크롤

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