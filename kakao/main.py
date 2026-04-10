import time
import pandas as pd

from config import KAKAO_MAP_URL, OUTPUT_CSV
from kakao_crawler import (
    create_driver, click_latest_sort, collect_all_reviews, get_place_name, click_load_more_reviews,
)


def main():
    driver = create_driver()

    try:
        print("[INFO] 페이지 접속 중...")
        driver.get(KAKAO_MAP_URL)
        time.sleep(3)

        # click_review_tab(driver)
        click_latest_sort(driver)
        click_load_more_reviews(driver)

        place_name = get_place_name(driver)
        data = collect_all_reviews(driver, place_name)
        print(f"\n[INFO] 수집 완료: {len(data)}개")

        df = pd.DataFrame(data)
        if not df.empty:
            df = (
                df.drop_duplicates(subset=["계정 ID", "방문 날짜", "리뷰 내용"], keep="first")
                .sort_values(by=["방문 날짜", "계정 ID"], ascending=[False, True])
            )

        df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"[DONE] 저장 완료: {len(df)}개 → {OUTPUT_CSV}")
        print(df.head())

    finally:
        driver.quit()


if __name__ == "__main__":
    main()