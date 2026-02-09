import os
import json
import uuid
from datetime import date, datetime, timedelta

import requests
import streamlit as st
import pandas as pd

# OpenAI 최신 SDK
from openai import OpenAI

# ---------------------------
# 기본 설정
# ---------------------------
st.set_page_config(
    page_title="AI Habit Tracker",
    page_icon="✅",
    layout="wide"
)

DATA_DIR = "data"
HABITS_FILE = os.path.join(DATA_DIR, "habits.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


# ---------------------------
# 유틸: 파일/데이터 로드/저장
# ---------------------------
def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)


def load_json(path, default):
    ensure_data_dir()
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    ensure_data_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_habits():
    return load_json(HABITS_FILE, [])


def load_logs():
    return load_json(LOGS_FILE, [])


def load_settings():
    return load_json(SETTINGS_FILE, {"city": "Seoul", "coach_tone": "다정한 코치"})


def save_habits(habits):
    save_json(HABITS_FILE, habits)


def save_logs(logs):
    save_json(LOGS_FILE, logs)


def save_settings(settings):
    save_json(SETTINGS_FILE, settings)


# ---------------------------
# 유틸: 날짜 처리
# ---------------------------
def today_str():
    return date.today().isoformat()


def last_n_days(n=7):
    return [(date.today() - timedelta(days=i)).isoformat() for i in range(n)][::-1]


# ---------------------------
# 로그/체크 처리
# ---------------------------
def get_log_map_for_date(logs, target_date):
    """
    {habit_id: checked_bool}
    """
    m = {}
    for r in logs:
        if r["date"] == target_date:
            m[r["habit_id"]] = r["checked"]
    return m


def upsert_log(logs, target_date, habit_id, checked):
    # 있으면 수정, 없으면 추가
    for r in logs:
        if r["date"] == target_date and r["habit_id"] == habit_id:
            r["checked"] = checked
            return logs
    logs.append({"date": target_date, "habit_id": habit_id, "checked": checked})
    return logs


# ---------------------------
# 통계 계산
# ---------------------------
def calc_streak(logs, habit_id):
    """
    오늘부터 거꾸로 연속 체크 streak 계산
    """
    logs_map = {(r["date"], r["habit_id"]): r["checked"] for r in logs}
    streak = 0
    d = date.today()
    while True:
        key = (d.isoformat(), habit_id)
        if logs_map.get(key, False):
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    return streak


def calc_7day_success_rate(logs, habits):
    """
    최근 7일 기준 전체 체크율 (습관 수 대비)
    """
    days = last_n_days(7)
    if len(habits) == 0:
        return 0.0

    logs_map = {(r["date"], r["habit_id"]): r["checked"] for r in logs}

    total = len(days) * len(habits)
    done = 0
    for d in days:
        for h in habits:
            if logs_map.get((d, h["id"]), False):
                done += 1
    return done / total


def calc_daily_progress(logs, habits, target_date):
    """
    오늘 체크 진행률 (done/total)
    """
    if len(habits) == 0:
        return (0, 0)

    m = get_log_map_for_date(logs, target_date)
    done = sum([1 for h in habits if m.get(h["id"], False)])
    return done, len(habits)


def habit_success_rate_7days(logs, habit_id):
    days = last_n_days(7)
    logs_map = {(r["date"], r["habit_id"]): r["checked"] for r in logs}
    total = len(days)
    done = sum([1 for d in days if logs_map.get((d, habit_id), False)])
    return done / total if total > 0 else 0.0


# ---------------------------
# API: 날씨 (OpenWeatherMap)
# ---------------------------
@st.cache_data(ttl=60 * 60 * 6)  # 6시간 캐시
def fetch_weather(city, api_key):
    if not api_key:
        return None

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": api_key, "units": "metric", "lang": "kr"}

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    return {
        "city": city,
        "temp": data["main"]["temp"],
        "feels_like": data["main"]["feels_like"],
        "weather": data["weather"][0]["description"],
        "main": data["weather"][0]["main"],
    }


# ---------------------------
# API: 강아지 이미지 (Dog API)
# ---------------------------
def fetch_dog_image():
    url = "https://dog.ceo/api/breeds/image/random"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data["message"]


# ---------------------------
# API: OpenAI (코치/추천)
# ---------------------------
def openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def generate_ai_message(prompt, temperature=0.7):
    client = openai_client()
    if not client:
        return "⚠️ OPENAI_API_KEY가 설정되지 않았어요. 설정 후 다시 시도해줘!"

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "너는 습관 트래커 앱의 AI 코치야. 한국어로 친절하고 실용적으로 답해."},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"⚠️ OpenAI 호출 중 오류가 발생했어요: {e}"


def build_coach_prompt(settings, habits, logs, target_date):
    tone = settings.get("coach_tone", "다정한 코치")

    log_map = get_log_map_for_date(logs, target_date)
    checked = [h["name"] for h in habits if log_map.get(h["id"], False)]
    unchecked = [h["name"] for h in habits if not log_map.get(h["id"], False)]

    # streak + 7일 성공률
    streak_info = []
    for h in habits:
        s = calc_streak(logs, h["id"])
        rate = habit_success_rate_7days(logs, h["id"])
        streak_info.append(f"- {h['name']}: streak={s}일, 최근7일 성공률={int(rate*100)}%")

    return f"""
너는 습관 트래커 앱의 AI 코치야.
코치 톤은 '{tone}' 스타일로 해줘.

오늘 날짜: {target_date}

[오늘 체크 완료한 습관]
{checked if checked else ["없음"]}

[오늘 체크 실패한 습관]
{unchecked if unchecked else ["없음"]}

[습관별 상태]
{chr(10).join(streak_info)}

요구사항:
1) 오늘 잘한 점 2~3개 (구체적으로)
2) 체크 못한 습관이 있다면 현실적인 조언 2개
3) 내일을 위한 '한 줄 미션' 1개
4) 너무 길지 않게, 보기 좋게 bullet로 정리
"""


def build_weather_prompt(weather):
    return f"""
너는 습관 트래커 앱의 AI 코치야.
오늘 날씨를 보고 사용자가 습관을 더 잘 지킬 수 있도록 추천해줘.

도시: {weather['city']}
현재 기온: {weather['temp']}°C
체감 온도: {weather['feels_like']}°C
날씨 설명: {weather['weather']}
날씨 상태(main): {weather['main']}

출력 형식:
- 오늘 날씨 한 줄 요약
- 날씨 기반 습관 추천 3개 (실천 가능한 수준으로)
- 마지막에 동기부여 한 줄
한국어로, 너무 과장하지 말고 현실적으로.
"""


# ---------------------------
# UI 컴포넌트
# ---------------------------
def render_header():
    st.markdown(
        """
        <div style="padding: 0.5rem 0; margin-bottom: 0.5rem;">
            <h1 style="margin:0;">✅ AI Habit Tracker</h1>
            <p style="margin:0; opacity:0.7;">OpenAI + Weather + Dog Rewards</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar(settings):
    st.sidebar.title("🐶 메뉴")

    page = st.sidebar.radio(
        "이동",
        ["🏠 홈", "✅ 오늘 체크", "📊 통계", "➕ 습관 관리", "⚙️ 설정"],
        index=0,
    )

    st.sidebar.divider()
    st.sidebar.subheader("⚙️ 빠른 설정")

    city = st.sidebar.text_input("도시", value=settings.get("city", "Seoul"))
    tone = st.sidebar.selectbox(
        "코치 톤",
        ["다정한 코치", "엄격한 코치", "친구 같은 코치"],
        index=["다정한 코치", "엄격한 코치", "친구 같은 코치"].index(settings.get("coach_tone", "다정한 코치")),
    )

    settings["city"] = city
    settings["coach_tone"] = tone
    save_settings(settings)

    st.sidebar.divider()

    if st.sidebar.button("🧨 데이터 초기화", use_container_width=True):
        save_habits([])
        save_logs([])
        save_settings({"city": "Seoul", "coach_tone": "다정한 코치"})
        st.sidebar.success("초기화 완료! 새로고침하면 반영돼요.")

    return page


# ---------------------------
# 페이지: 홈
# ---------------------------
def page_home(habits, logs, settings):
    st.subheader(f"📅 오늘: {date.today().strftime('%Y-%m-%d (%a)')}")

    done, total = calc_daily_progress(logs, habits, today_str())
    progress_ratio = (done / total) if total > 0 else 0.0

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("오늘 체크 진행률", f"{done}/{total}")

        st.progress(progress_ratio)

    with col2:
        st.markdown("### 🌦️ 현재 날씨")
        weather_key = os.getenv("OPENWEATHER_API_KEY")
        try:
            w = fetch_weather(settings.get("city", "Seoul"), weather_key)
            if w:
                st.write(f"**{w['city']}**")
                st.write(f"🌡️ {w['temp']}°C (체감 {w['feels_like']}°C)")
                st.write(f"☁️ {w['weather']}")
            else:
                st.info("OPENWEATHER_API_KEY가 없어서 날씨를 못 불러왔어요.")
        except Exception as e:
            st.warning(f"날씨 불러오기 실패: {e}")

    with col3:
        st.markdown("### 💬 오늘의 AI 한마디")

        prompt = f"""
너는 습관 트래커 앱의 AI 코치야.
사용자가 앱을 열었을 때 오늘 하루를 시작하기 좋은 한마디를 해줘.
코치 톤: {settings.get('coach_tone', '다정한 코치')}
너무 길지 않게 2~3문장.
"""
        msg = generate_ai_message(prompt, temperature=0.8)
        st.write(msg)


# ---------------------------
# 페이지: 오늘 체크
# ---------------------------
def page_daily_checkin(habits, logs, settings):
    st.subheader("✅ 오늘 체크")

    if len(habits) == 0:
        st.info("아직 습관이 없어요! ➕ 습관 관리에서 먼저 추가해줘.")
        return

    target_date = today_str()
    log_map = get_log_map_for_date(logs, target_date)

    st.write("오늘 수행한 습관을 체크해줘!")

    checked_state = {}
    for h in habits:
        checked_state[h["id"]] = st.checkbox(
            f"{h['name']}  ·  ({h.get('category','기타')})",
            value=log_map.get(h["id"], False),
        )

    st.divider()

    if st.button("💾 오늘 체크 저장", use_container_width=True):
        for hid, checked in checked_state.items():
            logs = upsert_log(logs, target_date, hid, checked)

        save_logs(logs)
        st.success("저장 완료! 🎉")

        # 저장 후 결과 출력
        done, total = calc_daily_progress(logs, habits, target_date)

        st.divider()
        st.subheader("🐶 오늘의 보상")

        # 강아지 이미지 개수 룰
        dog_count = 0
        if done >= 5:
            dog_count = 3
        elif done >= 3:
            dog_count = 2
        elif done >= 1:
            dog_count = 1

        if dog_count == 0:
            st.info("오늘은 체크한 습관이 없어서 강아지가 못 나와요 🥲")
        else:
            cols = st.columns(dog_count)
            for i in range(dog_count):
                try:
                    img = fetch_dog_image()
                    with cols[i]:
                        st.image(img, use_container_width=True)
                except Exception as e:
                    st.warning(f"강아지 이미지 불러오기 실패: {e}")

        st.divider()
        st.subheader("🧠 AI 코치 피드백")
        coach_prompt = build_coach_prompt(settings, habits, logs, target_date)
        coach_msg = generate_ai_message(coach_prompt, temperature=0.7)
        st.write(coach_msg)

        st.divider()
        st.subheader("🌦️ 날씨 기반 추천")

        weather_key = os.getenv("OPENWEATHER_API_KEY")
        try:
            w = fetch_weather(settings.get("city", "Seoul"), weather_key)
            if w:
                st.caption(f"{w['city']} · {w['temp']}°C · {w['weather']}")
                weather_prompt = build_weather_prompt(w)
                weather_msg = generate_ai_message(weather_prompt, temperature=0.7)
                st.write(weather_msg)
            else:
                st.info("OPENWEATHER_API_KEY가 없어서 날씨 추천을 못 만들어요.")
        except Exception as e:
            st.warning(f"날씨 추천 생성 실패: {e}")


# ---------------------------
# 페이지: 통계
# ---------------------------
def page_stats(habits, logs):
    st.subheader("📊 통계")

    if len(habits) == 0:
        st.info("습관이 없어서 통계를 낼 수 없어요. 먼저 습관을 추가해줘!")
        return

    # 최근 7일 전체 체크율
    rate = calc_7day_success_rate(logs, habits)
    st.metric("최근 7일 전체 체크율", f"{int(rate * 100)}%")

    st.divider()

    # 최근 7일 날짜별 체크 수
    days = last_n_days(7)
    logs_map = {(r["date"], r["habit_id"]): r["checked"] for r in logs}

    daily_done = []
    for d in days:
        done = sum([1 for h in habits if logs_map.get((d, h["id"]), False)])
        daily_done.append({"date": d, "done": done})

    df_daily = pd.DataFrame(daily_done)
    st.markdown("### 📈 최근 7일 체크 추이")
    st.line_chart(df_daily.set_index("date"))

    st.divider()

    # 습관별 streak + 성공률
    rows = []
    for h in habits:
        s = calc_streak(logs, h["id"])
        r = habit_success_rate_7days(logs, h["id"])
        rows.append(
            {
                "습관": h["name"],
                "카테고리": h.get("category", "기타"),
                "streak(일)": s,
                "최근7일 성공률": f"{int(r * 100)}%",
            }
        )

    df = pd.DataFrame(rows).sort_values(by="streak(일)", ascending=False)
    st.markdown("### 🧾 습관별 상태")
    st.dataframe(df, use_container_width=True)

    st.divider()

    # TOP / BOTTOM 3
    df_rate = pd.DataFrame(
        [{"habit": h["name"], "rate": habit_success_rate_7days(logs, h["id"])} for h in habits]
    ).sort_values(by="rate", ascending=False)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🥇 잘 되는 습관 TOP3")
        top3 = df_rate.head(3)
        for _, r in top3.iterrows():
            st.write(f"- {r['habit']} ({int(r['rate']*100)}%)")

    with col2:
        st.markdown("### 🧱 어려운 습관 TOP3")
        bottom3 = df_rate.tail(3).sort_values(by="rate", ascending=True)
        for _, r in bottom3.iterrows():
            st.write(f"- {r['habit']} ({int(r['rate']*100)}%)")


# ---------------------------
# 페이지: 습관 관리
# ---------------------------
def page_manage_habits(habits):
    st.subheader("➕ 습관 관리")

    st.markdown("### ✍️ 새 습관 추가")
    with st.form("add_habit_form"):
        name = st.text_input("습관 이름", placeholder="예: 물 2L 마시기")
        desc = st.text_area("설명 (선택)", placeholder="예: 하루 동안 물병 2번 비우기")
        category = st.selectbox("카테고리", ["건강", "공부", "운동", "마음", "생활", "기타"])
        target_per_week = st.slider("주 목표 횟수", 1, 7, 5)
        start_date = st.date_input("시작일", value=date.today())

        submitted = st.form_submit_button("추가하기")

        if submitted:
            if not name.strip():
                st.warning("습관 이름은 필수야!")
            else:
                habits.append(
                    {
                        "id": str(uuid.uuid4()),
                        "name": name.strip(),
                        "desc": desc.strip(),
                        "category": category,
                        "target_per_week": target_per_week,
                        "start_date": start_date.isoformat(),
                    }
                )
                save_habits(habits)
                st.success("습관이 추가됐어! 🎉 새로고침하면 목록에 보여.")

    st.divider()

    st.markdown("### 📋 현재 습관 목록")
    if len(habits) == 0:
        st.info("아직 습관이 없어요.")
        return

    # 습관 리스트 표시 + 삭제
    for h in habits:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{h['name']}**  ·  {h.get('category','기타')}")
                if h.get("desc"):
                    st.caption(h["desc"])
                st.caption(f"주 {h.get('target_per_week', 5)}회 목표 · 시작일 {h.get('start_date')}")

            with c2:
                if st.button("🗑️ 삭제", key=f"del_{h['id']}", use_container_width=True):
                    habits = [x for x in habits if x["id"] != h["id"]]
                    save_habits(habits)
                    st.success("삭제 완료! 새로고침하면 반영돼요.")

    st.info("※ 수정 기능은 다음 버전에서 추가 가능! (원하면 바로 넣어줄게)")


# ---------------------------
# 페이지: 설정
# ---------------------------
def page_settings(settings):
    st.subheader("⚙️ 설정")

    st.markdown("### 🔑 API 키 상태")

    openai_key = os.getenv("OPENAI_API_KEY")
    weather_key = os.getenv("OPENWEATHER_API_KEY")

    st.write(f"- OPENAI_API_KEY: {'✅ 설정됨' if openai_key else '❌ 없음'}")
    st.write(f"- OPENWEATHER_API_KEY: {'✅ 설정됨' if weather_key else '❌ 없음'}")

    st.divider()

    st.markdown("### 🏙️ 도시 / 코치 톤")
    st.write(f"- 도시: **{settings.get('city', 'Seoul')}**")
    st.write(f"- 코치 톤: **{settings.get('coach_tone', '다정한 코치')}**")

    st.divider()

    st.markdown("### 🧠 참고")
    st.info(
        """
- OpenAI 키가 없으면 AI 코치 기능이 동작하지 않습니다.
- OpenWeatherMap 키가 없으면 날씨 기반 추천이 동작하지 않습니다.
- Dog API는 키 없이 무료로 사용됩니다.
"""
    )


# ---------------------------
# 메인 실행
# ---------------------------
def main():
    render_header()

    habits = load_habits()
    logs = load_logs()
    settings = load_settings()

    page = sidebar(settings)

    if page == "🏠 홈":
        page_home(habits, logs, settings)
    elif page == "✅ 오늘 체크":
        page_daily_checkin(habits, logs, settings)
    elif page == "📊 통계":
        page_stats(habits, logs)
    elif page == "➕ 습관 관리":
        page_manage_habits(habits)
    elif page == "⚙️ 설정":
        page_settings(settings)


if __name__ == "__main__":
    main()
