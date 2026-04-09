from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from datetime import datetime
import time
import csv
import re

URL = "https://place.map.kakao.com/27306859#review"
SAVE_CSV = "kakao_reviews_from_2024.csv"
START_DATE = datetime(2024, 1, 1)

# -----------------------------
# 브라우저 설정
# -----------------------------
options = Options()
# options.add_argument("--headless=new")  # 필요하면 주석 해제
options.add_argument("--start-maximized")
options.add_argument("--disable-blink-features=AutomationControlled")

driver = webdriver.Chrome(options=options)
wait = WebDriverWait(driver, 15)


# -----------------------------
# 유틸 함수
# -----------------------------
def safe_text(el):
    if el:
        return el.get_text(" ", strip=True)
    return ""


def parse_date(date_text):
    """
    날짜 문자열을 datetime으로 변환
    예:
    2026.03.03
    2026-03-03
    2026/03/03
    2026. 3. 3.
    """
    if not date_text:
        return None

    text = date_text.strip()

    # 숫자 패턴만 추출
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", text)
    if not m:
        return None

    y, mth, d = map(int, m.groups())
    try:
        return datetime(y, mth, d)
    except:
        return None


def clean_review_text(text):
    if not text:
        return ""
    # <br> 등으로 줄바꿈된 텍스트를 공백으로 정리
    text = re.sub(r"\s+", " ", text).strip()
    return text


def try_click_review_tab():
    xpaths = [
        "//a[contains(@href, '#review')]",
        "//a[contains(., '후기')]",
        "//a[contains(., '리뷰')]",
    ]
    for xp in xpaths:
        try:
            el = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
            driver.execute_script("arguments[0].click();", el)
            print(f"[OK] 리뷰탭 click: {xp}")
            time.sleep(1.5)
            return True
        except:
            continue
    print("[WARN] 리뷰탭 클릭 실패")
    return False


def click_more_button():
    """
    리뷰 더보기 버튼이 있으면 클릭
    """
    candidates = [
        (By.XPATH, "//*[self::a or self::button][contains(., '더보기')]"),
        (By.XPATH, "//*[contains(@class, 'more') and (self::a or self::button)]"),
        (By.CSS_SELECTOR, "a.more"),
        (By.CSS_SELECTOR, "button.more"),
    ]

    for by, sel in candidates:
        try:
            btns = driver.find_elements(by, sel)
            for btn in btns:
                if btn.is_displayed() and btn.is_enabled():
                    driver.execute_script("arguments[0].click();", btn)
                    print("[OK] 더보기 클릭")
                    time.sleep(1.2)
                    return True
        except:
            continue
    return False


def scroll_down():
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(1)


def get_review_li_elements():
    """
    현재 페이지에서 리뷰 카드(li) 후보들을 최대한 넓게 수집
    """
    selectors = [
        "ul.list_review > li",
        "ul[class*='review'] > li",
        "div.review_list > ul > li",
        "div.cont_evaluation > ul > li",
        "div[class*='review'] li",
    ]

    results = []
    used = None
    for sel in selectors:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if len(els) > 0:
            results = els
            used = sel
            break

    print(f"[DEBUG] review selector = {used}, count = {len(results)}")
    return results


def extract_reviews_from_page():
    """
    현재 로드된 HTML에서 리뷰 정보 파싱
    """
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    review_items = []
    selectors = [
        "ul.list_review > li",
        "ul[class*='review'] > li",
        "div.review_list > ul > li",
        "div.cont_evaluation > ul > li",
        "div[class*='review'] li",
    ]

    li_list = []
    for sel in selectors:
        li_list = soup.select(sel)
        if li_list:
            print(f"[DEBUG] soup selector = {sel}, count = {len(li_list)}")
            break

    for li in li_list:
        raw_text = li.get_text(" ", strip=True)
        if not raw_text:
            continue

        # 리뷰 내용 후보
        review_text = ""
        review_candidates = [
            li.select_one("p.txt_comment"),
            li.select_one("p.desc_review"),
            li.select_one("div.txt_review"),
            li.select_one("div.comment_info"),
            li.select_one("div[class*='comment']"),
            li.select_one("p"),
        ]
        for c in review_candidates:
            txt = safe_text(c)
            if txt and len(txt) >= 2:
                review_text = txt
                break
        review_text = clean_review_text(review_text)

        # 날짜 후보
        date_text = ""
        date_candidates = [
            li.select_one("span.txt_date"),
            li.select_one("span.time_write"),
            li.select_one("span.date"),
            li.select_one("span[class*='date']"),
            li.select_one("div.info_append span"),
        ]
        for c in date_candidates:
            txt = safe_text(c)
            if re.search(r"\d{4}\D+\d{1,2}\D+\d{1,2}", txt):
                date_text = txt
                break

        # fallback: li 전체 텍스트에서 날짜 찾기
        if not date_text:
            m = re.search(r"(\d{4}\D+\d{1,2}\D+\d{1,2})", raw_text)
            if m:
                date_text = m.group(1)

        dt = parse_date(date_text)

        # 작성자 후보
        user_text = ""
        user_candidates = [
            li.select_one("a.link_user"),
            li.select_one("span.name_user"),
            li.select_one("strong.name_user"),
            li.select_one("div.user_info"),
        ]
        for c in user_candidates:
            txt = safe_text(c)
            if txt:
                user_text = txt
                break

        # 별점 후보
        score_text = ""
        score_candidates = [
            li.select_one("span.num_grade"),
            li.select_one("em.num_rate"),
            li.select_one("span[class*='grade']"),
            li.select_one("span[class*='score']"),
        ]
        for c in score_candidates:
            txt = safe_text(c)
            if re.search(r"\d+(\.\d+)?", txt):
                score_text = txt
                break

        # 사진 유무 추정
        has_photo = "Y" if li.select("img") else "N"

        if review_text:
            review_items.append({
                "user": user_text,
                "date_text": date_text,
                "date_obj": dt,
                "review": review_text,
                "has_photo": has_photo,
                "score": score_text,
                "raw": raw_text
            })

    return review_items


# -----------------------------
# 메인
# -----------------------------
driver.get(URL)
time.sleep(2)

try_click_review_tab()

all_data = []
seen = set()

# 충분히 많이 로딩
for i in range(50):
    print(f"[DEBUG] load try {i+1}/50")

    current_items = extract_reviews_from_page()

    for item in current_items:
        key = (item["user"], item["date_text"], item["review"])
        if key not in seen:
            seen.add(key)
            all_data.append(item)

    # 화면 아래로 내리고 더보기 클릭 시도
    scroll_down()
    clicked = click_more_button()

    # 더보기 클릭 안 되면 한 번 더 스크롤 후 종료 판단
    if not clicked:
        prev_len = len(all_data)
        time.sleep(1.5)
        current_items = extract_reviews_from_page()
        for item in current_items:
            key = (item["user"], item["date_text"], item["review"])
            if key not in seen:
                seen.add(key)
                all_data.append(item)

        if len(all_data) == prev_len:
            print("[INFO] 더 이상 새 리뷰가 로드되지 않음")
            break

# 날짜 필터
filtered = []
for item in all_data:
    if item["date_obj"] and item["date_obj"] >= START_DATE:
        filtered.append(item)

# 날짜순 정렬(최신순)
filtered.sort(key=lambda x: x["date_obj"], reverse=True)

# CSV 저장
with open(SAVE_CSV, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["user", "date", "review", "has_photo", "score"])

    for item in filtered:
        writer.writerow([
            item["user"],
            item["date_obj"].strftime("%Y-%m-%d") if item["date_obj"] else item["date_text"],
            item["review"],
            item["has_photo"],
            item["score"]
        ])

# 터미널 미리보기
print("\n===== 2024-01-01 이후 리뷰 미리보기 =====")
for idx, item in enumerate(filtered[:20], start=1):
    d = item["date_obj"].strftime("%Y-%m-%d") if item["date_obj"] else item["date_text"]
    print(f"[{idx}] {d} | {item['user']} | 사진:{item['has_photo']} | 별점:{item['score']}")
    print(f"    {item['review']}")

print(f"\n[DONE] 저장 완료: {len(filtered)}개 -> {SAVE_CSV}")

driver.quit()