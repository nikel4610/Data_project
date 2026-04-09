# kakao_crawler_10.py

import re
import time
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


URL = "https://place.map.kakao.com/27306859#review"
TARGET_COUNT = 10
OUTPUT_CSV = "kakao_reviews_10.csv"


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
    except:
        return ""


def parse_date(text):
    if not text:
        return ""
    patterns = [
        r"(\d{4}-\d{1,2}-\d{1,2})",
        r"(\d{4}\.\d{1,2}\.\d{1,2})",
        r"(\d{4}/\d{1,2}/\d{1,2})",
        r"(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)",
        r"(\d{2}\.\d{2}\.\w)",
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


def parse_level(text):
    if not text:
        return ""
    m = re.search(r"([가-힣A-Za-z]+\s*레벨)", text)
    return m.group(1).strip() if m else ""


def parse_avg_star(text):
    if not text:
        return ""
    patterns = [
        r"별점평균\s*([0-5](?:\.\d+)?)",
        r"별점\s*평균\s*([0-5](?:\.\d+)?)",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)
    return ""


def parse_review_count(text):
    if not text:
        return ""
    m = re.search(r"(?:후기|리뷰)\s*(\d+)", text)
    return m.group(1) if m else ""


def click_review_tab(driver):
    xpaths = [
        "//a[contains(@href, '#review')]",
        "//a[contains(., '리뷰')]",
        "//button[contains(., '리뷰')]",
    ]
    for xp in xpaths:
        try:
            elem = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            driver.execute_script("arguments[0].click();", elem)
            print(f"[OK] 리뷰탭 click: {xp}")
            time.sleep(2)
            return True
        except:
            pass
    print("[WARN] 리뷰탭 클릭 실패")
    return False


def click_latest_sort(driver):
    xpaths = [
        "//*[self::a or self::button][contains(., '최신순')]",
        "//*[contains(@class,'sort') and contains(., '최신순')]",
        "//*[contains(@class,'sort') or contains(@class,'Sort')]//*[contains(., '최신순')]",
    ]
    for xp in xpaths:
        try:
            elem = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, xp))
            )
            driver.execute_script("arguments[0].click();", elem)
            print(f"[OK] 최신순 click: {xp}")
            time.sleep(1.5)
            return True
        except:
            pass
    print("[WARN] 최신순 click failed")
    return False


def is_valid_review_card(li):
    txt = safe_text(li)
    if not txt:
        return False
    has_date = bool(parse_date(txt))
    has_long_text = len(txt) >= 15
    return has_date or has_long_text


def get_review_cards(driver):
    selectors = [
        (By.XPATH, "//*[@id='_review_list']/li"),
        (By.CSS_SELECTOR, "ul#_review_list > li"),
        (By.CSS_SELECTOR, "ul[class*='review'] > li"),
    ]

    best = []
    for by, sel in selectors:
        try:
            elems = driver.find_elements(by, sel)
            filtered = [e for e in elems if is_valid_review_card(e)]
            if len(filtered) > len(best):
                best = filtered
                print(f"[DEBUG] review selector={sel}, raw={len(elems)}, valid={len(filtered)}")
        except:
            pass
    return best


def load_until_target(driver, target=10, max_try=5):
    cards = get_review_cards(driver)
    print(f"[INFO] 현재 잡힌 카드 수: {len(cards)}")
    return cards[:target]


def expand_review_text(card, driver):
    xpaths = [
        ".//a[contains(., '더보기')]",
        ".//button[contains(., '더보기')]",
    ]

    for xp in xpaths:
        try:
            btns = card.find_elements(By.XPATH, xp)
            for btn in btns:
                txt = safe_text(btn)
                if not txt:
                    continue
                if "메뉴" in txt:
                    continue

                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.1)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.2)
        except:
            pass


def extract_account_id(card):
    selectors = [
        (By.CSS_SELECTOR, "a.link_user"),
        (By.CSS_SELECTOR, "strong.tit_user"),
        (By.CSS_SELECTOR, "span.txt_name"),
        (By.XPATH, ".//a[contains(@class,'link_user')]"),
        (By.XPATH, ".//strong[contains(@class,'tit_user')]"),
    ]

    for by, sel in selectors:
        try:
            elems = card.find_elements(by, sel)
            for e in elems:
                t = safe_text(e)
                if not t:
                    continue
                token = t.split()[0].strip()
                if not token:
                    continue
                if "레벨" in token or token.isdigit():
                    continue
                if token in {"팔로워", "후기", "리뷰", "메뉴", "더보기"}:
                    continue
                return token
        except:
            pass

    return ""


def extract_level(card):
    return parse_level(safe_text(card))


def extract_visit_date(card):
    return parse_date(safe_text(card))


def extract_review_text(card):
    candidates = []

    selectors = [
        (By.CSS_SELECTOR, "p.desc_review"),
        (By.CSS_SELECTOR, "div.txt_comment"),
        (By.CSS_SELECTOR, "span.txt_comment"),
        (By.CSS_SELECTOR, "div.review_story"),
        (By.XPATH, ".//p"),
        (By.XPATH, ".//span"),
        (By.XPATH, ".//div"),
    ]

    for by, sel in selectors:
        try:
            elems = card.find_elements(by, sel)
            for e in elems:
                t = safe_text(e)
                if not t:
                    continue
                if "레벨" in t or "팔로워" in t:
                    continue
                if "별점평균" in t or "별점 평균" in t:
                    continue
                if "메뉴 더보기" in t:
                    continue
                if re.search(r"(후기|리뷰)\s*\d+", t):
                    continue
                if t in {"더보기", "사진", "메뉴", "위치기반"}:
                    continue
                if parse_date(t) == t:
                    continue
                if len(t) < 5:
                    continue
                candidates.append(t)
        except:
            pass

    if not candidates:
        return ""

    candidates = sorted(set(candidates), key=len, reverse=True)
    return candidates[0]


def extract_review_len(review_text):
    return len(review_text) if review_text else 0


def extract_photo_yn(card):
    try:
        imgs = card.find_elements(By.TAG_NAME, "img")
        real = [img.get_attribute("src") for img in imgs if (img.get_attribute("src") or "").strip()]
        return 1 if real else 0
    except:
        return 0


def extract_star(card):
    txt = safe_text(card)
    m = re.search(r"(?:별점|평점)\s*([0-5](?:\.\d+)?)", txt)
    if m:
        return m.group(1)
    return ""


def extract_profile_meta(card):
    txt = safe_text(card)
    return parse_avg_star(txt), parse_review_count(txt)


def crawl_kakao_reviews():
    driver = create_driver()
    rows = []
    seen_reviews = set()

    try:
        print("[STEP] open site")
        driver.get(URL)
        time.sleep(3)

        click_review_tab(driver)
        click_latest_sort(driver)

        cards = load_until_target(driver, TARGET_COUNT)
        print(f"[INFO] 최종 카드 수: {len(cards)}")

        valid_idx = 0

        for idx, card in enumerate(cards, start=1):
            try:
                expand_review_text(card, driver)

                account_id = extract_account_id(card)
                level = extract_level(card)
                visit_date = extract_visit_date(card)
                review_text = extract_review_text(card)
                review_len = extract_review_len(review_text)
                photo_yn = extract_photo_yn(card)
                star = extract_star(card)
                avg_star, review_count = extract_profile_meta(card)

                if not review_text:
                    print(f"[SKIP {idx}] 리뷰 텍스트 없음")
                    continue

                review_key = (account_id, visit_date, review_text)
                if review_key in seen_reviews:
                    print(f"[SKIP {idx}] 중복 리뷰")
                    continue
                seen_reviews.add(review_key)

                valid_idx += 1
                row = {
                    "계정 ID": account_id,
                    "리뷰 다는 사람 레벨": level,
                    "방문 날짜": visit_date,
                    "리뷰 내용": review_text,
                    "리뷰 글자 수": review_len,
                    "리뷰 내 사진 유무": photo_yn,
                    "별점": star,
                    "계정의 별점 평균": avg_star,
                    "계정의 리뷰 수": review_count,
                }
                rows.append(row)

                print(
                    f"[{valid_idx}/{TARGET_COUNT}] {account_id} | {level} | {visit_date} | "
                    f"별점:{star} | 평균:{avg_star} | 리뷰수:{review_count} | "
                    f"사진:{photo_yn} | 리뷰:{review_text[:100]}"
                )

                if len(rows) >= TARGET_COUNT:
                    break

            except Exception as e:
                print(f"[WARN] 카드 파싱 실패: {e}")

    finally:
        driver.quit()

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"\n[DONE] 저장 완료: {len(df)}개 -> {OUTPUT_CSV}")
    print(df.head(10))
    return df


if __name__ == "__main__":
    crawl_kakao_reviews()