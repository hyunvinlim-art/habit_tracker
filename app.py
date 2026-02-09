# app.py
import random
from datetime import datetime, timedelta

import requests
import streamlit as st

# OpenAI 최신 SDK
from openai import OpenAI


# =========================
# 기본 설정
# =========================
st.set_page_config(
    page_title="AI 습관 트래커",
    page_icon="📊",
    layout="wide",
)

st.title("📊 AI 습관 트래커")
st.caption("오늘의 습관 + 기분 + 날씨 + 강아지(??)를 모아서 AI 코치 리포트를 만들어줘요 🐶")


# =========================
# 유틸 함수
# =========================
def safe_pct(x, total):
    if total <= 0:
        return 0
    return int(round((x / total) * 100, 0))


def _timeout_get(url, params=None, headers=None, timeout=10):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


# =========================
# API 연동 함수
# =========================
def get_weather(city: str, api_key: str, debug: bool = False):
    """
    OpenWeatherMap 현재 날씨 조회.
    - 한국어
    - 섭씨
    실패 시 None 반환
    """

    api_key = (api_key or "").strip()
    if not api_key:
        return None

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,  # 예: "Seoul,KR"
        "appid": api_key,
        "units": "metric",
        "lang": "kr",
    }

    try:
        r = requests.get(url, params=params, timeout=10)

        # 디버그 모드면 사이드바에 원인 표시
        if debug:
            st.sidebar.write("🌦️ OpenWeather 응답 코드:", r.status_code)
            st.sidebar.write("🌦️ OpenWeather 응답 본문(일부):", r.text[:300])

        if r.status_code != 200:
            return None

        data = r.json()

        weather_desc = data["weather"][0]["description"]
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        humidity = data["main"]["humidity"]
        wind = data.get("wind", {}).get("speed", None)

        return {
            "city": city,
            "description": weather_desc,
            "temp_c": float(temp),
            "feels_like_c": float(feels_like),
            "humidity": int(humidity),
            "wind_mps": wind,
        }

    except Exception:
        return None


def get_dog_image():
    """
    Dog CEO API에서 랜덤 강아지 사진 URL + 품종 가져오기
    실패 시 None 반환
    """
    url = "https://dog.ceo/api/breeds/image/random"
    data = _timeout_get(url, timeout=10)
    if not data:
        return None

    try:
        image_url = data["message"]

        # 예: https://images.dog.ceo/breeds/hound-afghan/n02088094_1003.jpg
        breed = "unknown"
        if "/breeds/" in image_url:
            part = image_url.split("/breeds/")[1].split("/")[0]
            breed = part.replace("-", " ")

        return {"image_url": image_url, "breed": breed}
    except Exception:
        return None


# =========================
# AI 리포트 생성
# =========================
SYSTEM_PROMPTS = {
    "스파르타 코치": """너는 매우 엄격하고 현실적인 스파르타 코치다.
말투는 짧고 단호하며 변명은 허용하지 않는다.
하지만 공격적이거나 모욕적이면 안 된다. 냉정한 격려를 한다.""",
    "따뜻한 멘토": """너는 따뜻하고 다정한 멘토다.
사용자를 존중하고 공감하며, 작은 성취도 크게 인정해준다.
부드럽고 실용적인 조언을 준다.""",
    "게임 마스터": """너는 RPG 세계관의 게임 마스터다.
사용자는 플레이어이며, 습관은 퀘스트다.
날씨/기분/습관을 게임 요소로 해석해서 재미있게 말한다.
오글거림은 살짝 허용하지만 너무 길면 안 된다.""",
}

OUTPUT_FORMAT_GUIDE = """
출력은 반드시 아래 형식을 지켜라.

[컨디션 등급] S/A/B/C/D (딱 1개)

[습관 분석]
- (핵심 요약 3줄 이내)
- 달성한 습관과 놓친 습관을 구분해서 말해라.

[날씨 코멘트]
- 날씨가 있으면: 날씨 기반 조언 1~2문장
- 없으면: "날씨 정보 없음"이라고만 적어라.

[내일 미션]
- 구체적인 미션 3개 (체크박스 습관과 연결)

[오늘의 한마디]
- 한 문장
"""


def generate_report(
    openai_api_key: str,
    coach_style: str,
    habits_checked: list,
    habits_missed: list,
    mood: int,
    achievement_pct: int,
    weather: dict | None,
    dog: dict | None,
):
    """
    습관+기분+날씨+강아지 품종을 모아서 OpenAI에 전달
    모델: gpt-5-mini
    실패 시 None 반환
    """
    openai_api_key = (openai_api_key or "").strip()
    if not openai_api_key:
        return None

    system_prompt = SYSTEM_PROMPTS.get(coach_style, SYSTEM_PROMPTS["따뜻한 멘토"])

    weather_text = "날씨 정보 없음"
    if weather:
        wind_txt = f"{weather['wind_mps']}m/s" if weather.get("wind_mps") is not None else "정보 없음"
        weather_text = (
            f"- 도시: {weather['city']}\n"
            f"- 날씨: {weather['description']}\n"
            f"- 기온: {weather['temp_c']:.1f}°C (체감 {weather['feels_like_c']:.1f}°C)\n"
            f"- 습도: {weather['humidity']}%\n"
            f"- 바람: {wind_txt}"
        )

    dog_text = "강아지 정보 없음"
    if dog:
        dog_text = f"- 품종(추정): {dog.get('breed','unknown')}"

    user_prompt = f"""
오늘의 체크인 데이터는 다음과 같다.

[습관]
- 달성: {", ".join(habits_checked) if habits_checked else "없음"}
- 미달성: {", ".join(habits_missed) if habits_missed else "없음"}
- 달성률: {achievement_pct}%

[기분]
- 점수: {mood}/10

[날씨]
{weather_text}

[강아지]
{dog_text}

요구사항:
- 과장하지 말고 현실적인 조언을 해라.
- 너무 길지 않게, 총 12~18줄 정도로 작성해라.
- 사용자가 오늘 바로 행동을 바꿀 수 있게 구체적으로 말해라.

{OUTPUT_FORMAT_GUIDE}
""".strip()

    try:
        client = OpenAI(api_key=openai_api_key)

        res = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        return res.choices[0].message.content.strip()
    except Exception:
        return None


# =========================
# 사이드바: API 키 입력
# =========================
with st.sidebar:
    st.header("🔑 API 설정")

    openai_api_key = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="sk-...",
        help="AI 코치 리포트를 만들 때 필요해요.",
    )

    weather_api_key = st.text_input(
        "OpenWeatherMap API Key",
        type="password",
        placeholder="OpenWeatherMap key",
        help="날씨 정보를 가져올 때 필요해요.",
    )

    debug_weather = st.toggle("날씨 디버그 보기", value=False)

    st.divider()
    st.caption("⚙️ 팁: 키가 없으면 앱은 동작하지만, 날씨/AI 리포트는 제한돼요.")


# =========================
# 세션 상태 초기화
# =========================
HABITS = [
    ("🌅", "기상 미션"),
    ("💧", "물 마시기"),
    ("📚", "공부/독서"),
    ("🏃", "운동하기"),
    ("😴", "수면"),
]

# 🔥 핵심 수정: 도시를 "도시,KR" 형태로
CITY_LIST = [
    "Seoul,KR",
    "Busan,KR",
    "Incheon,KR",
    "Daegu,KR",
    "Daejeon,KR",
    "Gwangju,KR",
    "Suwon,KR",
    "Ulsan,KR",
    "Jeju,KR",
    "Changwon,KR",
]

COACH_STYLES = ["스파르타 코치", "따뜻한 멘토", "게임 마스터"]

if "history" not in st.session_state:
    st.session_state.history = []

if "today_saved" not in st.session_state:
    st.session_state.today_saved = False

if "last_report" not in st.session_state:
    st.session_state.last_report = None

if "last_weather" not in st.session_state:
    st.session_state.last_weather = None

if "last_dog" not in st.session_state:
    st.session_state.last_dog = None


# =========================
# 데모용 6일 샘플 데이터 (초기 1회만)
# =========================
def init_demo_history_if_empty():
    if st.session_state.history:
        return

    today = datetime.now().date()
    base = today - timedelta(days=6)

    demo = []
    for i in range(6):
        d = base + timedelta(days=i)
        checked = random.randint(1, 5)
        mood = random.randint(4, 9)
        pct = safe_pct(checked, 5)
        demo.append(
            {
                "date": d.isoformat(),
                "pct": pct,
                "mood": mood,
                "checked_count": checked,
            }
        )
    st.session_state.history = demo


init_demo_history_if_empty()


# =========================
# UI: 체크인
# =========================
st.subheader("✅ 오늘의 습관 체크인")

colA, colB = st.columns([1.2, 1.0], gap="large")

with colA:
    st.markdown("#### 🧾 습관 체크")

    left, right = st.columns(2, gap="medium")

    checked_map = {}

    for idx, (emoji, name) in enumerate(HABITS):
        target_col = left if idx % 2 == 0 else right
        with target_col:
            checked_map[name] = st.checkbox(f"{emoji} {name}", value=False)

    st.markdown("---")
    mood = st.slider("🙂 오늘 기분은 어때요?", min_value=1, max_value=10, value=7, step=1)

with colB:
    st.markdown("#### 🌍 환경 설정")

    city = st.selectbox("도시 선택", CITY_LIST, index=0)
    coach_style = st.radio("코치 스타일", COACH_STYLES, index=1, horizontal=False)

    st.markdown("---")
    st.info("체크인 후 아래에서 **컨디션 리포트 생성**을 눌러보세요!")


# =========================
# 달성률 계산 + 메트릭
# =========================
checked_habits = [h for h in checked_map if checked_map[h]]
missed_habits = [h for h in checked_map if not checked_map[h]]
checked_count = len(checked_habits)
achievement_pct = safe_pct(checked_count, len(HABITS))

st.markdown("---")
st.subheader("📈 오늘의 달성률")

m1, m2, m3 = st.columns(3, gap="medium")
with m1:
    st.metric("달성률", f"{achievement_pct}%")
with m2:
    st.metric("달성 습관", f"{checked_count}/5")
with m3:
    st.metric("기분", f"{mood}/10")


# =========================
# 기록 저장 (session_state)
# =========================
def save_today():
    today = datetime.now().date().isoformat()

    found = False
    for row in st.session_state.history:
        if row["date"] == today:
            row["pct"] = achievement_pct
            row["mood"] = mood
            row["checked_count"] = checked_count
            found = True
            break

    if not found:
        st.session_state.history.append(
            {
                "date": today,
                "pct": achievement_pct,
                "mood": mood,
                "checked_count": checked_count,
            }
        )

    st.session_state.history = sorted(st.session_state.history, key=lambda x: x["date"])[-7:]
    st.session_state.today_saved = True


# 차트 반영용으로 오늘 데이터 저장
save_today()


# =========================
# 7일 바 차트
# =========================
st.subheader("🗓️ 최근 7일 달성률")

chart_rows = []
for row in st.session_state.history:
    try:
        dt = datetime.fromisoformat(row["date"]).strftime("%m/%d")
    except Exception:
        dt = row["date"]
    chart_rows.append({"날짜": dt, "달성률(%)": row["pct"]})

st.bar_chart(chart_rows, x="날짜", y="달성률(%)", height=260)


# =========================
# 결과 표시: 버튼 + 카드 + 리포트
# =========================
st.markdown("---")
st.subheader("🧠 AI 코치 리포트")

btn_col1, btn_col2 = st.columns([1, 2], gap="large")
with btn_col1:
    generate_btn = st.button("🚀 컨디션 리포트 생성", type="primary", use_container_width=True)

with btn_col2:
    st.caption("※ OpenAI 키가 없으면 리포트 생성이 안 돼요. 날씨 키가 없으면 날씨는 생략돼요.")


if generate_btn:
    with st.spinner("날씨와 강아지를 불러오고, AI가 리포트를 작성 중..."):

        # 날씨
        weather = get_weather(city, weather_api_key, debug=debug_weather)
        st.session_state.last_weather = weather

        # 강아지
        dog = get_dog_image()
        st.session_state.last_dog = dog

        # 리포트
        report = generate_report(
            openai_api_key=openai_api_key,
            coach_style=coach_style,
            habits_checked=checked_habits,
            habits_missed=missed_habits,
            mood=mood,
            achievement_pct=achievement_pct,
            weather=weather,
            dog=dog,
        )
        st.session_state.last_report = report


# 출력 영역
weather = st.session_state.last_weather
dog = st.session_state.last_dog
report = st.session_state.last_report

if report or weather or dog:
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.markdown("#### 🌦️ 오늘의 날씨")
        if weather:
            st.write(f"**도시:** {weather['city']}")
            st.write(f"**날씨:** {weather['description']}")
            st.write(f"**기온:** {weather['temp_c']:.1f}°C (체감 {weather['feels_like_c']:.1f}°C)")
            st.write(f"**습도:** {weather['humidity']}%")
            if weather.get("wind_mps") is not None:
                st.write(f"**바람:** {weather['wind_mps']} m/s")
        else:
            st.warning("날씨 정보를 가져오지 못했어요. (API Key 또는 네트워크 확인)")

    with c2:
        st.markdown("#### 🐶 오늘의 강아지")
        if dog:
            st.write(f"**품종(추정):** {dog.get('breed', 'unknown')}")
            st.image(dog["image_url"], use_container_width=True)
        else:
            st.warning("강아지 이미지를 가져오지 못했어요. (네트워크 확인)")

    st.markdown("---")
    st.markdown("#### 📝 AI 코치 리포트")

    if report:
        st.markdown(report)
    else:
        st.error("AI 리포트를 생성하지 못했어요. (OpenAI API Key 확인)")


# =========================
# 공유용 텍스트
# =========================
if report:
    share_text = f"""
[AI 습관 트래커 공유]

- 날짜: {datetime.now().date().isoformat()}
- 도시: {city}
- 코치: {coach_style}
- 달성률: {achievement_pct}%
- 달성: {", ".join(checked_habits) if checked_habits else "없음"}
- 미달성: {", ".join(missed_habits) if missed_habits else "없음"}
- 기분: {mood}/10

--- AI 리포트 ---
{report}
""".strip()

    st.markdown("---")
    st.subheader("📤 공유용 텍스트")
    st.code(share_text, language="text")


# =========================
# 하단: API 안내
# =========================
st.markdown("---")
with st.expander("📌 API 안내 / 설정 방법"):
    st.markdown(
        """
**1) OpenAI API Key**
- AI 코치 리포트 생성에 필요합니다.
- OpenAI 대시보드에서 발급한 키를 사용하세요.

**2) OpenWeatherMap API Key**
- 현재 날씨 정보를 가져오는데 필요합니다.
- https://openweathermap.org/ 에서 가입 후 API Key를 발급받을 수 있어요.
- 도시 검색이 불안정할 수 있어 **Seoul,KR** 형태로 보내는 것이 가장 안정적입니다.

**3) Dog CEO API**
- 무료 공개 API라 키가 필요 없습니다.
- 네트워크 상황에 따라 실패할 수 있습니다.

**문제 해결**
- 리포트가 안 나오면: OpenAI Key 확인
- 날씨가 안 나오면:
  - OpenWeatherMap Key 확인
  - 도시가 "Seoul,KR" 형태인지 확인
  - 사이드바의 "날씨 디버그 보기"를 켜고 401/404/429 확인
- 강아지가 안 나오면: 잠깐 후 다시 시도
        """.strip()
    )
