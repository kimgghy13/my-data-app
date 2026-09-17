# -*- coding: utf-8 -*-
"""
어제의 일별 박스오피스 순위를 보여주는 스트림릿(Streamlit) 앱

- 데이터 출처: 영화진흥위원회(KOBIS) 오픈API - 일별 박스오피스
- 인증키는 절대 코드에 직접 쓰지 않고, 스트림릿의 '비밀 금고(secrets)'에서 불러옵니다.
  (Streamlit Cloud에서는 앱 설정 > Secrets 메뉴에
   KOBIS_KEY = "발급받은_인증키"
   형태로 한 줄 넣어주면 됩니다.)
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 기본 내장 시간대 모듈 (한국 시간 계산용)

# -----------------------------
# 1) 기본 설정
# -----------------------------
# KOBIS 일별 박스오피스 조회 주소 (공식 문서에 나온 그대로)
API_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")


# -----------------------------
# 2) '어제 날짜' 계산 (한국 시간 기준)
# -----------------------------
def get_yesterday_kst() -> str:
    """
    지금이 몇 시든 상관없이, '한국 시간 기준으로 어제 날짜'를
    'yyyymmdd' 여덟 자리 문자열로 돌려주는 함수입니다.

    배포 서버(예: 스트림릿 클라우드)는 한국 시간이 아닐 수 있으므로,
    서버의 현재 시각을 그대로 쓰지 않고 'Asia/Seoul' 시간대로 변환한 뒤
    하루를 빼서 계산합니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


# -----------------------------
# 3) API 호출 (1시간 동안 결과를 기억함 = 캐시)
# -----------------------------
@st.cache_data(ttl=3600)  # ttl=3600초 = 1시간. 같은 날짜로 다시 요청하면 API를 또 부르지 않음
def fetch_box_office(target_dt: str):
    """
    KOBIS 오픈API에 요청을 보내서 해당 날짜의 박스오피스 데이터를 받아옵니다.

    반환값은 항상 아래 두 가지 중 하나입니다.
    - (True, 영화 목록 리스트)   : 성공한 경우
    - (False, 사람이 읽을 안내 메시지) : 실패한 경우 (오류/빈 목록 포함)
    """
    try:
        # secrets에서 인증키를 불러옴 (코드에는 키 값을 절대 적지 않음)
        api_key = st.secrets["KOBIS_KEY"]
    except Exception:
        return False, (
            "인증키(KOBIS_KEY)를 찾을 수 없습니다.\n"
            "Streamlit Cloud의 앱 설정(Settings) > Secrets 메뉴에\n"
            'KOBIS_KEY = "발급받은_인증키" 형태로 등록했는지 확인해 주세요.'
        )

    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    # 3-1) 네트워크 요청 자체가 실패하는 경우 (인터넷 문제, 타임아웃 등)
    try:
        response = requests.get(API_URL, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return False, (
            "박스오피스 서버에 접속하지 못했습니다.\n"
            "인터넷 연결 상태를 확인하시거나, 잠시 후 다시 시도해 주세요."
        )

    # 3-2) 상태 코드가 200이 아닌 경우 (드물지만 만약을 대비)
    if response.status_code != 200:
        return False, (
            f"박스오피스 서버가 오류를 응답했습니다. (상태 코드: {response.status_code})\n"
            "잠시 후 다시 시도해 주세요."
        )

    # 3-3) 응답이 JSON 형식이 아닌 경우 (예: 서버 점검 안내 페이지가 돌아오는 경우)
    try:
        data = response.json()
    except ValueError:
        return False, (
            "박스오피스 서버 응답을 해석할 수 없습니다.\n"
            "KOBIS 서버 점검 중이거나 요청 방식이 바뀌었을 수 있습니다."
        )

    # 3-4) 인증키가 틀렸을 때 등: 상태 코드는 200이지만 faultInfo 상자가 오는 경우
    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, (
            f"KOBIS API가 오류를 반환했습니다: {message}\n"
            "인증키(KOBIS_KEY)가 정확한지, 사용량 한도를 넘지 않았는지 확인해 주세요."
        )

    # 3-5) 정상 구조가 아닌 경우 (boxOfficeResult가 아예 없는 경우 등)
    try:
        movie_list = data["boxOfficeResult"]["dailyBoxOfficeList"]
    except (KeyError, TypeError):
        return False, (
            "응답에서 박스오피스 목록을 찾을 수 없습니다.\n"
            "API 응답 형식이 문서와 달라졌을 수 있으니, KOBIS 공지사항을 확인해 주세요."
        )

    # 3-6) 목록은 있는데 비어 있는 경우 (예: 조회 날짜가 너무 미래이거나 데이터 미집계)
    if not movie_list:
        return False, (
            f"{target_dt} 날짜의 박스오피스 데이터가 비어 있습니다.\n"
            "아직 해당 날짜의 집계가 완료되지 않았을 수 있습니다."
        )

    return True, movie_list


# -----------------------------
# 4) 문자열 숫자를 진짜 숫자로 바꿔주는 함수
# -----------------------------
def to_int(value: str) -> int:
    """'1,234' 같은 문자열도 안전하게 정수로 바꿔줍니다."""
    try:
        return int(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return 0


# -----------------------------
# 5) 화면 그리기
# -----------------------------
st.title("🎬 어제의 박스오피스")

target_date = get_yesterday_kst()
# 화면에 보여줄 때는 보기 좋게 yyyy-mm-dd 형태로 바꿔줌
pretty_date = f"{target_date[0:4]}-{target_date[4:6]}-{target_date[6:8]}"
st.caption(f"조회 날짜(한국 시간 기준 어제): {pretty_date}")

ok, result = fetch_box_office(target_date)

if not ok:
    # 실패했을 때는 화면을 비워두지 않고, 무엇을 확인해야 하는지 안내함
    st.error(result)
    st.stop()  # 여기서 실행을 멈춰서 아래 코드가 실행되지 않도록 함

movies = result

# ---- 5-1) 표로 보여주기 위해 필요한 데이터만 뽑아서 정리 ----
rows = []
for m in movies:
    rows.append(
        {
            "순위": to_int(m.get("rank")),
            "영화명": m.get("movieNm", ""),
            "개봉일": m.get("openDt", ""),
            "관객수": to_int(m.get("audiCnt")),
            "누적관객": to_int(m.get("audiAcc")),
            "스크린수": to_int(m.get("scrnCnt")),
        }
    )

df = pd.DataFrame(rows)
df = df.sort_values("순위").reset_index(drop=True)

# ---- 5-2) 1위 영화 정보를 지표 카드 3장으로 크게 보여주기 ----
top_movie = df.iloc[0]

st.subheader(f"🥇 1위: {top_movie['영화명']}")
card1, card2, card3 = st.columns(3)
card1.metric("어제 관객수", f"{top_movie['관객수']:,}명")
card2.metric("누적 관객수", f"{top_movie['누적관객']:,}명")
card3.metric("스크린수", f"{top_movie['스크린수']:,}개")

st.divider()

# ---- 5-3) 전체 순위표 ----
st.subheader("📋 전체 순위표")
st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "관객수": st.column_config.NumberColumn(format="%d"),
        "누적관객": st.column_config.NumberColumn(format="%d"),
        "스크린수": st.column_config.NumberColumn(format="%d"),
    },
)

# ---- 5-4) 관객수 상위 5편 막대그래프 ----
st.subheader("📊 관객수 상위 5편")
top5 = df.sort_values("관객수", ascending=False).head(5)
# st.bar_chart는 인덱스를 x축(가로축)으로 사용하므로 영화명을 인덱스로 지정
chart_data = top5.set_index("영화명")[["관객수"]]
st.bar_chart(chart_data)
