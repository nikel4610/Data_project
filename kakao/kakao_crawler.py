import re
import time
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config import (
    SLEEP, MAX_IDLE_ROUNDS, SAFETY_MAX_ROUNDS,
    TEMP_CSV, START_DATE
)


# =====================================
# 드라이버 생성
# =====================================
def create_driver():
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=ko-KR")

    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(2)
    return driver


# =====================================
# 보조 함수
# =====================================
def clean_text(text):
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\t", " ").replace("\r", " ")
    text = text.replace("<br>", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def safe_text(elem):
    try:
        return clean_text(elem.text)
    except Exception:
        return ""


def parse_date(text):
    if not text:
        return ""
    patterns = [
        r"(\d{4}-\d{1,2}-\d{1,2})",
        r"(\d{4}\.\d{1,2}\.\d{1,2})",
        r"(\d{4}/\d{1,2}/\d{1,2})",
        r"(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            d = m.group(1)
            if "년" in d:
                d = d.replace("년", "-").replace("월", "-").replace("일", "")
                d = re.sub(r"\s+", "", d)
            return d.replace(".", "-").replace("/", "-")
    return ""


def check_date_range(date_str):
    if not date_str:
        return "error"
    try:
        from datetime import datetime
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return "valid" if date_obj >= START_DATE else "old"
    except Exception:
        return "error"


def make_review_key(row):
    return (
        row.get("계정 ID", "").strip(),
        row.get("방문 날짜", "").strip(),
        row.get("리뷰 내용", "").strip()
    )


# =====================================
# 식당 이름 수집
# =====================================
def get_place_name(driver):
    for selector in ["h3.tit_place", "h2.tit_place", "h1.tit_place", "[class*='tit_place']"]:
        try:
            name = driver.find_element(By.CSS_SELECTOR, selector).text.strip()
            if name:
                print(f"[INFO] 식당 이름 수집: {name}")
                return name
        except Exception:
            continue
    print("[WARN] 식당 이름을 찾지 못했습니다.")
    return ""


# =====================================
# 리뷰 탭 / 최신순 정렬
# =====================================
def click_review_tab(driver):
    # 카카오맵 실제 구조: <a href="#review" role="tab">후기</a>
    for by, sel in [
        (By.CSS_SELECTOR, "a[href='#review']"),
        (By.XPATH, "//a[@href='#review']"),
        (By.XPATH, "//a[contains(@href,'#review')]"),
    ]:
        try:
            elem = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((by, sel))
            )
            driver.execute_script("arguments[0].click();", elem)
            print("[리뷰 탭] 클릭 성공")
            time.sleep(1.5)
            return True
        except Exception:
            pass
    print("[WARN] 리뷰 탭 클릭 실패")
    return False


def click_load_more_reviews(driver):
    """
    '후기 더보기' 버튼이 있을 때만 클릭.
    버튼이 없으면 조용히 넘어감 (스크롤로 자동 로드되는 경우엔 뜨지 않음).
    """
    for by, sel in [
        (By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[8]/div[3]/a'),  # 실제 XPath
        (By.XPATH, "//a[contains(., '후기 더보기')]"),
        (By.XPATH, "//a[contains(., '리뷰 더보기')]"),
    ]:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((by, sel))
            )
            driver.execute_script("arguments[0].click();", btn)
            print("[후기 더보기] 버튼 클릭 성공")
            time.sleep(1.5)
            return True
        except Exception:
            pass
    return False  # 버튼 없으면 정상 (스크롤 방식)


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


# =====================================
# 리뷰 카드 수집
# =====================================
def get_review_cards(driver):
    # 카카오맵 실제 구조: ul.list_review > li
    try:
        elems = driver.find_elements(By.CSS_SELECTOR, "ul.list_review > li")
        if elems:
            return elems
    except Exception:
        pass
    try:
        return driver.find_elements(By.CSS_SELECTOR, "ul[class*='review'] > li")
    except Exception:
        return []


def scroll_once(driver):
    before = driver.execute_script("return window.scrollY;")
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(SLEEP)
    after = driver.execute_script("return window.scrollY;")
    return before, after


# =====================================
# 카드 파싱
# =====================================
def expand_review_text(card, driver):
    """더보기 버튼 클릭. 카카오맵 실제 구조: <a class='link_review'>...더보기</a>"""
    try:
        btn = card.find_element(By.CSS_SELECTOR, "a.link_review")
        if "더보기" in btn.text:
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.15)
    except Exception:
        pass


def extract_account_id(card):
    # 카카오맵: <span class="name_user"><span class="screen_out">리뷰어 이름, </span>닉네임</span>
    try:
        name_elem = card.find_element(By.CSS_SELECTOR, ".name_user")
        lines = [l.strip() for l in name_elem.text.split("\n") if l.strip()]
        for line in reversed(lines):
            if line and "리뷰어 이름" not in line:
                return line
    except Exception:
        pass
    return ""


def extract_review_text(card):
    # 카카오맵: <p class="desc_review"> 또는 <a class="link_review">
    for selector in ["p.desc_review", "a.link_review"]:
        try:
            elem = card.find_element(By.CSS_SELECTOR, selector)
            t = clean_text(elem.text)
            t = re.sub(r"\s*\.{3}\s*더보기\s*$", "", t).strip()
            if t and len(t) >= 5:
                return t
        except Exception:
            pass
    return ""


def extract_star(card):
    # 카카오맵: <span class="starred_grade">별점\n3.0</span>
    try:
        txt = card.find_element(By.CSS_SELECTOR, ".starred_grade").text
        m = re.search(r"([0-5](?:\.\d+)?)", txt)
        return m.group(1) if m else ""
    except Exception:
        return ""


def extract_level(card):
    # 카카오맵: <span class="ico_badge ico_badge_blue">블루 레벨</span>
    try:
        txt = card.find_element(By.CSS_SELECTOR, "[class*='ico_badge']").text.strip()
        return txt if txt else ""
    except Exception:
        return ""


def extract_detail_info(card):
    """계정의 후기수, 별점평균. 카카오맵: <ul class="list_detail"><li>후기 N</li><li>별점평균 X.X</li>"""
    review_count, avg_star = "", ""
    try:
        items = card.find_elements(By.CSS_SELECTOR, ".list_detail li")
        for item in items:
            t = item.text.strip()
            if "후기" in t:
                m = re.search(r"후기\s*(\d+)", t)
                if m:
                    review_count = m.group(1)
            elif "별점평균" in t:
                m = re.search(r"별점평균\s*([0-5](?:\.\d+)?)", t)
                if m:
                    avg_star = m.group(1)
    except Exception:
        pass
    return review_count, avg_star


def parse_one_card(card, driver, place_name=""):
    """
    카카오 리뷰 카드 1개를 파싱합니다.
    반환값:
        dict   - 정상 파싱된 리뷰 데이터
        "stop" - START_DATE 이전 리뷰 (수집 중단 신호)
        None   - 스킵
    """
    # 날짜 먼저 확인 (빠른 early exit) - safe_text(card) 전체 파싱 불필요
    try:
        date_text = card.find_element(By.CSS_SELECTOR, ".txt_date").text.strip()
    except Exception:
        date_text = ""

    visit_date = parse_date(date_text)
    date_status = check_date_range(visit_date)

    if date_status == "old":
        return "stop"
    if date_status == "error":
        return None

    # 더보기 펼치기
    expand_review_text(card, driver)

    # 리뷰 텍스트
    review_text = extract_review_text(card)
    if not review_text:
        return None

    # 사진 유무 (프로필 이미지 제외)
    has_photo = 1 if card.find_elements(By.CSS_SELECTOR, ".list_photo img, .area_photo img") else 0

    review_count, avg_star = extract_detail_info(card)

    row = {
        "식당 이름":            place_name,
        "계정 ID":             extract_account_id(card),
        "리뷰 다는 사람 레벨":   extract_level(card),
        "방문 날짜":            visit_date,
        "리뷰 내용":            review_text,
        "리뷰 글자 수":         len(review_text),
        "리뷰 내 사진 유무":     has_photo,
        "별점":                extract_star(card),
        "계정의 별점 평균":      avg_star,
        "계정의 리뷰 수":       review_count,
    }
    return row


# =====================================
# 전체 수집 루프
# =====================================
def check_and_click_load_more(driver):
    """
    '후기 더보기' 버튼이 화면에 있으면 클릭하고 True 반환.
    버튼 클릭 후 페이지가 초기화되므로 수집 루프를 리셋해야 함.
    """
    for by, sel in [
        (By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[8]/div[3]/a'),
        (By.XPATH, "//a[contains(., '후기 더보기')]"),
        (By.XPATH, "//a[contains(., '리뷰 더보기')]"),
    ]:
        try:
            btn = driver.find_element(by, sel)
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                print("[후기 더보기] 버튼 클릭 → 페이지 재로드 대기")
                time.sleep(2.5)  # 페이지 재로드 대기
                return True
        except Exception:
            pass
    return False


def collect_all_reviews(driver, place_name=""):
    collected = {}
    idle_rounds = 0
    more_clicked = False  # 후기 더보기 버튼 클릭 여부

    for round_idx in range(1, SAFETY_MAX_ROUNDS + 1):
        print(f"\n[===== 라운드 {round_idx} =====]")

        # 후기 더보기 버튼 감지: 클릭하면 페이지 초기화되므로 idle 리셋 후 재시작
        if not more_clicked:
            if check_and_click_load_more(driver):
                more_clicked = True
                idle_rounds = 0
                print("[INFO] 후기 더보기 클릭 완료 → 스크롤부터 재시작")
                before, after = scroll_once(driver)
                print(f"[INFO] 재시작 스크롤: {before} → {after}")
                continue  # 카드 수집은 다음 라운드부터

        cards = get_review_cards(driver)
        new_count = 0
        should_stop = False

        for card in cards:
            try:
                result = parse_one_card(card, driver, place_name)

                if result == "stop":
                    print("[INFO] START_DATE 이전 리뷰 발견 → 수집 중단")
                    should_stop = True
                    break

                if result is None:
                    continue

                key = make_review_key(result)
                if key not in collected:
                    collected[key] = result
                    new_count += 1
                    print(
                        f"[수집 #{len(collected)}] {result['계정 ID']} | "
                        f"{result['방문 날짜']} | 별점:{result['별점']} | "
                        f"{result['리뷰 내용'][:60]}"
                    )

            except Exception as e:
                print(f"[WARN] 카드 파싱 실패: {e}")

        print(f"[INFO] 신규 {new_count}개 / 누적 {len(collected)}개")

        if should_stop:
            break

        if collected:
            pd.DataFrame(list(collected.values())).to_csv(
                TEMP_CSV, index=False, encoding="utf-8-sig"
            )

        idle_rounds = 0 if new_count > 0 else idle_rounds + 1

        if idle_rounds >= MAX_IDLE_ROUNDS:
            print("[INFO] 신규 리뷰 없음 → 수집 종료")
            break

        before, after = scroll_once(driver)
        print(f"[INFO] scrollY: {before} → {after}")

        if before == after:
            idle_rounds += 1

    return list(collected.values())