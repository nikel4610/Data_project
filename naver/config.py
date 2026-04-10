from datetime import datetime

# =====================================
# 수집 대상 설정
# =====================================
NAVER_MAP_URL = (
    "https://map.naver.com/p/entry/place/37126807"
    "?c=15.00,0,0,0,dh&placePath=/review"
    "&additionalHeight=76&fromPanelNum=1&locale=ko&svcName=map_pcv5"
)

# 수집할 리뷰 날짜 범위 (이 날짜 이전 리뷰가 나오면 수집 중단)
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
OUTPUT_CSV = "naver_reviews.csv"
TEMP_CSV   = "naver_reviews_temp.csv"  # 크롤링 중간 임시 저장