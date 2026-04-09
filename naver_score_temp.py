import pandas as pd
import re

# =========================
# 1. 데이터 불러오기
# =========================
df = pd.read_csv("naver_reviews.csv")

# 결측값 처리
df["리뷰 내용"] = df["리뷰 내용"].fillna("")
df["방문 횟수"] = df["방문 횟수"].fillna("")
df["인증 수단"] = df["인증 수단"].fillna("")
df["리뷰 내 사진 유무"] = df["리뷰 내 사진 유무"].fillna(False)


# =========================
# 2. 신뢰도 점수 계산
# =========================
def calc_reliability(row):
    score = 0

    # 글자 수
    if row["리뷰 글자 수"] >= 100:
        score += 3
    elif row["리뷰 글자 수"] >= 50:
        score += 2
    elif row["리뷰 글자 수"] >= 20:
        score += 1

    # 사진 여부
    if row["리뷰 내 사진 유무"]:
        score += 2

    # 인증 여부
    if "영수증" in row["인증 수단"]:
        score += 3
    elif row["인증 수단"] != "":
        score += 1

    # 방문 횟수
    if "번째 방문" in row["방문 횟수"]:
        num = int(re.findall(r"\d+", row["방문 횟수"])[0])
        if num >= 2:
            score += 2
        else:
            score += 1

    return score


df["신뢰도 점수"] = df.apply(calc_reliability, axis=1)


# =========================
# 3. 감정 분석 (룰 기반)
# =========================
positive_words = [
    "맛있", "추천", "좋", "훌륭", "최고", "재방문",
    "친절", "깔끔", "만족", "행복", "굿", "완벽"
]

negative_words = [
    "별로", "실망", "비싸", "짜", "느끼", "불친절",
    "다시 안", "최악", "기다림", "오래 걸"
]


def sentiment_score(text):
    score = 0

    for word in positive_words:
        score += text.count(word)

    for word in negative_words:
        score -= text.count(word)

    return score


df["감정 점수"] = df["리뷰 내용"].apply(sentiment_score)


# =========================
# 4. 감정 점수 → 5점 스케일 변환
# =========================
def convert_to_star(score):
    if score >= 5:
        return 5
    elif score >= 3:
        return 4
    elif score >= 1:
        return 3
    elif score == 0:
        return 2.5
    else:
        return 1.5


df["감정 별점"] = df["감정 점수"].apply(convert_to_star)


# =========================
# 5. 신뢰도 반영 최종 점수
# =========================
def weighted_score(row):
    # 신뢰도 점수를 weight로 사용
    return row["감정 별점"] * (1 + row["신뢰도 점수"] / 10)


df["최종 점수"] = df.apply(weighted_score, axis=1)


# =========================
# 6. 식당 평균 점수
# =========================
final_score = df["최종 점수"].mean()

print("\n🔥 네이버 기반 계산 별점:", round(final_score, 2))


# =========================
# 7. 결과 저장
# =========================
df.to_csv("naver_analysis.csv", index=False, encoding="utf-8-sig")
print("분석 결과 저장 완료 → naver_analysis.csv")