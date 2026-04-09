import re
import time
import pandas as pd

from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


# =====================================
# 0. 기본 설정
# =====================================
NAVER_MAP_URL = "https://map.naver.com/p/search/%EC%98%A4%EC%9D%B4%EC%A7%80/place/1791259060?c=15.00,0,0,0,dh&placePath=/review?bk_query=%EC%98%A4%EC%9D%B4%EC%A7%80&entry=bmp&fromPanelNum=2&locale=ko&searchText=%EC%98%A4%EC%9D%B4%EC%A7%80&svcName=map_pcv5&timestamp=202604091934&entry=bmp&fromPanelNum=2&timestamp=202604091934&locale=ko&svcName=map_pcv5&searchText=%EC%98%A4%EC%9D%B4%EC%A7%80&from=map"

# START_DATE = datetime(2025, 1, 1)

SLEEP = 1.2
MAX_IDLE_ROUNDS = 8
SAFETY_MAX_ROUNDS = 300
REVIEW_LIMIT = None

OUTPUT_CSV = "naver_reviews.csv"
TEMP_CSV = "naver_reviews_temp.csv"


# =====================================
# 1. 드라이버 생성
# =====================================
def create_driver():
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    driver.implicitly_wait(2)
    return driver


# =====================================
# 2. 보조 함수
# =====================================
def safe_text(parent, by, selector, default=""):
    try:
        return parent.find_element(by, selector).text.strip()
    except Exception:
        return default


def exists(parent, by, selector):
    try:
        parent.find_element(by, selector)
        return True
    except Exception:
        return False


def normalize_date_string(y, m, d):
    return f"{int(y):04d}.{int(m):02d}.{int(d):02d}"


def extract_visit_date_from_text(text):
    m1 = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", text)
    if m1:
        y, m, d = m1.groups()
        return normalize_date_string(y, m, d)

    m2 = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    if m2:
        y, m, d = m2.groups()
        return normalize_date_string(y, m, d)

    return ""


def is_valid_date(date_str):
    try:
        date_obj = datetime.strptime(date_str, "%Y.%m.%d")
        return date_obj >= START_DATE
    except Exception:
        return False


def parse_visit_info_from_text(full_text):
    visit_date = extract_visit_date_from_text(full_text)

    visit_count = ""
    count_match = re.search(r"(\d+번째 방문)", full_text)
    if count_match:
        visit_count = count_match.group(1)

    auth_method = ""
    auth_candidates = ["영수증", "예약", "주문", "포장", "배달"]
    for candidate in auth_candidates:
        if candidate in full_text:
            auth_method = candidate
            break

    return visit_date, visit_count, auth_method


def extract_account_review_count(full_text):
    match = re.search(r"리뷰\s*([\d,]+)", full_text)
    if match:
        return match.group(1).replace(",", "")
    return ""


def count_review_chars(review_text):
    return len(review_text or "")


def preview_text(text, max_len=120):
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def make_review_key(row):
    return (
        row.get("계정 ID", "").strip(),
        row.get("방문 날짜", "").strip(),
        row.get("리뷰 내용", "").strip()
    )


def extract_review_text_by_xpath(driver, idx):
    """
    //*[@id="_review_list"]/li[i]/div[5]/a[1]
    에서 리뷰 텍스트를 가져오되,
    <br> 태그는 공백으로 바꾼 뒤 순수 텍스트만 수집
    """
    xpath = f'//*[@id="_review_list"]/li[{idx}]/div[5]/a[1]'

    try:
        elem = driver.find_element(By.XPATH, xpath)

        # HTML 원문 가져오기
        html = elem.get_attribute("innerHTML") or ""

        # <br>, <br/>, <br /> 전부 공백으로 치환
        html = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)

        # 나머지 HTML 태그 제거
        text = re.sub(r"<[^>]+>", "", html)

        # HTML 공백 문자 정리
        text = text.replace("&nbsp;", " ")

        # 줄바꿈/탭/중복공백 정리
        text = re.sub(r"[\r\n\t]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text

    except Exception:
        return ""


# =====================================
# 3. iframe 진입
# =====================================
def switch_to_entry_iframe(driver):
    driver.switch_to.default_content()

    for iframe_id in ["entryIframe", "searchIframe"]:
        try:
            WebDriverWait(driver, 5).until(
                EC.frame_to_be_available_and_switch_to_it((By.ID, iframe_id))
            )
            print(f"[INFO] iframe 진입 성공: {iframe_id}")
            return
        except TimeoutException:
            continue

    raise Exception("iframe을 찾지 못했습니다. 네이버 지도 구조를 다시 확인해야 합니다.")


# =====================================
# 4. 리뷰 탭 클릭
# =====================================
def click_review_tab(driver):
    candidate_xpaths = [
        "//a[contains(., '리뷰')]",
        "//button[contains(., '리뷰')]",
        "//span[contains(., '리뷰')]"
    ]

    for xpath in candidate_xpaths:
        try:
            elem = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            driver.execute_script("arguments[0].click();", elem)
            time.sleep(2)
            print("[INFO] 리뷰 탭 클릭 성공")
            return
        except Exception:
            continue

    print("[WARN] 리뷰 탭 클릭 실패 - 이미 리뷰 탭일 수도 있음")


# =====================================
# 5. 리뷰 영역 찾기 / 스크롤
# =====================================
def get_review_scroll_box(driver):
    candidates = [
        "div[role='main']",
        "div.place_section_content",
        "div.place_section",
        "div#_pcmap_list_scroll_container",
        "div[class*='review']",
        "body"
    ]

    for selector in candidates:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, selector)
            return elem
        except Exception:
            continue

    return driver.find_element(By.TAG_NAME, "body")


def click_more_buttons(driver):
    xpaths = [
        "//a[contains(., '펼쳐서 더보기')]",
        "//button[contains(., '펼쳐서 더보기')]",
        "//a[contains(., '더보기')]",
        "//button[contains(., '더보기')]"
    ]

    total_clicked = 0

    for xpath in xpaths:
        try:
            buttons = driver.find_elements(By.XPATH, xpath)
            for btn in buttons:
                try:
                    if btn.is_displayed() and btn.is_enabled():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.15)
                        total_clicked += 1
                except Exception:
                    pass
        except Exception:
            pass

    return total_clicked


def scroll_once(driver):
    scroll_box = get_review_scroll_box(driver)

    before = driver.execute_script("return arguments[0].scrollTop;", scroll_box)
    height = driver.execute_script("return arguments[0].scrollHeight;", scroll_box)

    driver.execute_script(
        "arguments[0].scrollTop = arguments[0].scrollHeight;",
        scroll_box
    )
    time.sleep(SLEEP)

    after = driver.execute_script("return arguments[0].scrollTop;", scroll_box)
    return before, after, height


# =====================================
# 6. 리뷰 카드 파싱
# =====================================
def get_review_cards(driver):
    selectors = [
        "#_review_list > li",
        "li.EjjAW",
        "li.place_apply_pui",
        "div[class*='place_apply_pui']",
        "li[class*='pui']"
    ]

    for selector in selectors:
        cards = driver.find_elements(By.CSS_SELECTOR, selector)
        if cards:
            print(f"[DEBUG] selector={selector} / count={len(cards)}")
            return cards

    return []


def parse_one_card(driver, card, idx):
    full_text = card.text.strip()
    if not full_text:
        return None

    account_id = safe_text(
        card, By.CSS_SELECTOR,
        ".pui__NMi-Dp, .pui__uslU0d, .place_bluelink, [class*='nick'], [class*='name']"
    )

    if not account_id:
        lines = [line.strip() for line in full_text.split("\n") if line.strip()]
        if lines:
            account_id = lines[0]

    account_review_count = extract_account_review_count(full_text)
    visit_date, visit_count, auth_method = parse_visit_info_from_text(full_text)

    if not visit_date or not is_valid_date(visit_date):
        return None

    # 핵심: 지정 XPath에서 리뷰 내용 직접 수집
    review_text = extract_review_text_by_xpath(driver, idx)
    review_char_count = count_review_chars(review_text)

    has_photo = exists(
        card, By.CSS_SELECTOR,
        "img, .place_thumb, .review_photo"
    )

    row = {
        "계정 ID": account_id,
        "계정의 리뷰 수": account_review_count,
        "방문 날짜": visit_date,
        "방문 횟수": visit_count,
        "인증 수단": auth_method,
        "리뷰 내용": review_text,
        "리뷰 글자 수": review_char_count,
        "리뷰 내 사진 유무": has_photo
    }

    if not row["계정 ID"] and not row["리뷰 내용"]:
        return None

    return row


def collect_visible_reviews(driver, collected_dict, limit=REVIEW_LIMIT):
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

    print(f"[INFO] 현재 화면 파싱 성공: {parsed_count}개 / 신규 누적: {new_count}개 / 총 누적: {len(collected_dict)}개")
    return new_count


# =====================================
# 7. 전체 수집 루프
# =====================================
def collect_all_reviews(driver, limit=REVIEW_LIMIT):
    collected = {}
    idle_rounds = 0

    for round_idx in range(1, SAFETY_MAX_ROUNDS + 1):

        # ✅ 수정 1
        if limit is not None and len(collected) >= limit:
            print(f"[INFO] 목표 수집 개수 {limit}개 도달로 종료")
            break

        print(f"\n[INFO] ===== 수집 라운드 {round_idx} =====")

        click_count = click_more_buttons(driver)
        if click_count:
            print(f"[INFO] 더보기 클릭 수: {click_count}")

        new_count = collect_visible_reviews(driver, collected, limit=limit)

        # ✅ 수정 2
        if limit is not None and len(collected) >= limit:
            print(f"[INFO] 목표 수집 개수 {limit}개 도달로 종료")
            break

        if len(collected) > 0:
            pd.DataFrame(list(collected.values())).to_csv(
                TEMP_CSV, index=False, encoding="utf-8-sig"
            )

        if new_count == 0:
            idle_rounds += 1
        else:
            idle_rounds = 0

        before, after, height = scroll_once(driver)
        print(f"[INFO] scrollTop: {before} -> {after} / scrollHeight={height}")

        click_count_2 = click_more_buttons(driver)
        if click_count_2:
            print(f"[INFO] 스크롤 후 더보기 클릭 수: {click_count_2}")

        new_count_after_scroll = collect_visible_reviews(driver, collected, limit=limit)

        # ✅ 수정 3 (여기도 반드시!)
        if limit is not None and len(collected) >= limit:
            print(f"[INFO] 목표 수집 개수 {limit}개 도달로 종료")
            break

        if new_count_after_scroll == 0:
            idle_rounds += 1
        else:
            idle_rounds = 0

        if len(collected) > 0:
            pd.DataFrame(list(collected.values())).to_csv(
                TEMP_CSV, index=False, encoding="utf-8-sig"
            )

        if idle_rounds >= MAX_IDLE_ROUNDS:
            print("[INFO] 새 리뷰가 더 이상 늘지 않아 수집 종료")
            break

    # ✅ 수정 4 (None 처리)
    return list(collected.values()) if limit is None else list(collected.values())[:limit]


# =====================================
# 8. 메인 실행
# =====================================
def main():
    driver = create_driver()

    try:
        print("[INFO] 페이지 접속 중...")
        driver.get(NAVER_MAP_URL)
        time.sleep(3)

        switch_to_entry_iframe(driver)
        click_review_tab(driver)

        data = collect_all_reviews(driver, limit=REVIEW_LIMIT)
        print(f"[INFO] 총 수집된 리뷰 수(중복 제거 전): {len(data)}")

        df = pd.DataFrame(data)

        if not df.empty:
            df = df.drop_duplicates(
                subset=["계정 ID", "방문 날짜", "리뷰 내용"],
                keep="first"
            ).sort_values(
                by=["방문 날짜", "계정 ID"],
                ascending=[False, True]
            )

            if REVIEW_LIMIT is not None:
                df = df.head(REVIEW_LIMIT)

        df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"[DONE] 최종 저장 완료: {len(df)}개 -> {OUTPUT_CSV}")
        print(df.head())

    finally:
        driver.quit()


if __name__ == "__main__":
    main()