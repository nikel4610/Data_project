from datetime import datetime

# =====================================
# 수집 대상 설정
# =====================================
KAKAO_MAP_URL = "https://place.map.kakao.com/27306859#review"

# 이 날짜 이전 리뷰가 나오면 수집 중단
START_DATE = datetime(2025, 1, 1)

# =====================================
# 크롤링 동작 설정
# =====================================
SLEEP             = 1.2  # 스크롤 후 대기 시간 (초)
MAX_IDLE_ROUNDS   = 8    # 신규 리뷰 없을 때 허용 횟수 (초과 시 종료)
SAFETY_MAX_ROUNDS = 300  # 무한루프 방지용 최대 라운드

# =====================================
# 출력 파일 경로
# =====================================
OUTPUT_CSV = "kakao_reviews.csv"
TEMP_CSV   = "kakao_reviews_temp.csv"  # 크롤링 중간 임시 저장