import streamlit as st
import swisseph as swe
from geopy.geocoders import ArcGIS, Nominatim
from timezonefinder import TimezoneFinder
import pytz
from datetime import datetime, timedelta
from openai import OpenAI
import re
import requests
import uuid
import hashlib

# --- FREE QUESTION LIMIT SYSTEM ---
if "CHART_USAGE" not in st.session_state:
    st.session_state["CHART_USAGE"] = {}  # Tracks how many questions each birth chart has asked

def get_chart_id(dob, birth_time, city, country):
    """Creates a unique code from birth details. Same person = same code always."""
    raw = f"{dob.isoformat()}|{birth_time.strftime('%H:%M')}|{city.strip().lower()}|{country.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]

# Generate a unique Session ID for the user's visit if one doesn't exist yet
if 'session_id' not in st.session_state:
    st.session_state['session_id'] = str(uuid.uuid4())

if "reading_ready" not in st.session_state:
    st.session_state["reading_ready"] = False
if "question_widget" not in st.session_state:
    st.session_state["question_widget"] = ""
if "city_input" not in st.session_state:
    st.session_state["city_input"] = ""
if "country_select" not in st.session_state:
    st.session_state["country_select"] = "India"

def log_conversation_to_make(dob, location, birth_time, question, ai_answer):
    webhook_url = "https://hook.eu2.make.com/orkovgpw41bs1pef5s4wgx36lxfngfog"
    payload = {
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Session ID": st.session_state['session_id'],
        "DOB": str(dob),
        "Location": location,
        "Time of Birth": str(birth_time),
        "Question": question,
        "AI Answer": ai_answer
    }
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except:
        pass


# ==========================================
# 0. QUESTION FILTER & SAFETY LAYER
# ==========================================
def classify_question(text: str):
    """
    Returns: (status, flag)
    status: "ALLOWED" | "BLOCKED"
    flag  : category string (e.g., "fatalistic", "trivial", "none")
    """
    text_clean = text.lower().strip()
    if len(text_clean) < 8:
        return "BLOCKED", "short"

    # 1. FATALISTIC / EXTREME
    fatal_patterns = [
        r'\b(when|how|will|am i).{0,20}(die|death|dead|dying)\b',
        r'\b(kill myself|end my life|suicide|suicidal)\b',
        r'\b(murder|get murdered|be killed|assassinate)\b',
        r'\b(terminal.{0,10}(cancer|illness|disease))\b',
        r'\bincurable\b', r'\bexact.{0,5}date.{0,10}death\b',
        r'\bhow long.{0,10}(live|survive)\b', r'\bfatal.{0,5}(accident|crash|disease)\b'
    ]
    for pat in fatal_patterns:
        if re.search(pat, text_clean):
            return "BLOCKED", "fatalistic"

    # 2. OCCULT / HARM TO OTHERS
    occult_patterns = [
        r'\bblack magic\b', r'\bvashikaran\b', r'\bwitchcraft\b',
        r'\btantra.{0,10}(harm|destroy|kill)\b',
        r'\b(mantra|spell|totka).{0,10}(harm|destroy|enemy|revenge)\b',
        r'\bcurse.{0,5}(someone|enemy|ex|him|her)\b'
    ]
    for pat in occult_patterns:
        if re.search(pat, text_clean):
            return "BLOCKED", "occult"

    # 3. GAMBLING / SPECULATION TIPS
    gambling_patterns = [
        r'\b(lottery|lotto|jackpot|gambl|betting|wager|casino)\b',
        r'\b(which|what).{0,15}(stock|share|crypto|bitcoin).{0,15}(buy|sell|tip|pick)\b'
    ]
    for pat in gambling_patterns:
        if re.search(pat, text_clean):
            return "BLOCKED", "gambling"

    # 4. ILLEGAL / MALICIOUS INTENT
    illegal_patterns = [
        r'\b(cheat in exam|cheat on exam|evade tax|break the law|bribe|commit fraud|how do i commit)\b'
    ]
    for pat in illegal_patterns:
        if re.search(pat, text_clean):
            return "BLOCKED", "illegal"

    # 4.5 DELUSIONAL / PARANOID THEMES
    delusion_patterns = [
        r'\b(people are after me|everyone is against me|being watched|surveillance on me)\b',
        r'\b(am i cursed|generational curse|possessed|demon|evil spirit)\b',
        r'\b(chosen one|special powers|divine mission|prophet)\b',
        r'\b(spiritual attack|psychic attack|entity attachment)\b'
    ]
    for pat in delusion_patterns:
        if re.search(pat, text_clean):
            return "BLOCKED", "mental_health"

    # 5. ASTROLOGY RELEVANCE CHECK
    astro_keywords = {
        "career", "job", "business", "work", "profession", "promotion", "office", "transfer",
        "marriage", "spouse", "husband", "wife", "wedding", "married", "love", "relationship",
        "divorce", "affair", "partner", "matrimony", "engagement",
        "health", "illness", "disease", "sick", "hospital", "surgery", "recovery", "mental",
        "anxiety", "stress", "depression", "heal", "medicine", "doctor",
        "debt", "loan", "money", "finance", "wealth", "income", "salary", "property",
        "house", "home", "land", "flat", "apartment", "vehicle", "car",
        "child", "children", "son", "daughter", "pregnancy", "fertility", "baby", "kid", "progeny",
        "education", "exam", "study", "abroad", "travel", "visa", "settlement", "foreign", "pr",
        "spirituality", "dharma", "karma", "meditation", "god", "temple", "puja", "worship", "mantra",
        "legal", "court", "case", "litigation", "police", "jail", "lawyer", "judge", "fir", "accuse",
        "enemy", "competition", "threat", "danger", "accident", "theft", "loss", "fraud", "cheat", "dispute",
        "timing", "when", "delay", "auspicious", "muhurta", "mahadasha", "antardasha", "dasha",
        "transit", "gochar", "rahu", "ketu", "saturn", "shani", "sade sati", "mangal", "manglik",
        "dosha", "kundali", "horoscope", "chart", "planet", "rashi", "nakshatra", "graha", "lagna"
    }
    words_set = set(re.findall(r'\w+', text_clean))
    has_astro = bool(words_set & astro_keywords)

    # 6. TRIVIAL / UNRELATED
    trivial_patterns = [
        r'\b(chicken|mutton|burger|pizza|biryani|food|lunch|dinner|breakfast|snack)\b',
        r'\b(cricket match|ipl|football|fifa|world cup|score|match result)\b',
        r'\b(weather|rain|sunny|temperature|snow|monsoon)\b',
        r'\b(should i eat|what should i eat|will it rain|is it hot)\b'
    ]
    for pat in trivial_patterns:
        if re.search(pat, text_clean) and not has_astro:
            return "BLOCKED", "trivial"

    if not has_astro and len(text_clean) < 22:
        return "BLOCKED", "unrelated"

    # 7. SENSITIVE FLAGS (allowed, but noted)
    sensitive_keywords = [
        "legal", "court", "case", "litigation", "police", "jail", "lawyer", "judge", "fir", "crime",
        "debt", "loan", "bankruptcy", "financial crisis",
        "illness", "disease", "surgery", "hospital", "mental", "cancer", "operation", "medic",
        "accident", "danger", "emergency", "threat", "enemy", "fraud", "cheat", "loss", "dispute",
        "divorce", "affair", "extramarital", "separation"
    ]
    flagged = [kw for kw in sensitive_keywords if kw in text_clean]
    return "ALLOWED", ",".join(flagged) if flagged else "none"


# ==========================================
# 5 WORKFLOW SYSTEM PROMPTS + ROUTER
# ==========================================

COMMON_RULES = """
You are a careful and disciplined Parashari astrologer. Carefully interpret the provided chart data.
Do NOT recalculate anything yourself. Treat this data as absolute fact.

===== NATAL CHART DATA (PERMANENT BIRTH CHART) =====

{chart_string}
{aspects_string}

===== NAVAMSA (D9) — RELATIONAL & DHARMIC POTENTIAL =====

{d9_string}

⚠️ SYSTEM RULE — NAVAMSA: D9 reveals the deeper, more mature expression of planets. Use it to assess planetary strength and relational karma. Vargottama planets are significantly strengthened.

===== PANCHADHA MAITRI (5-FOLD PLANETARY FRIENDSHIP) =====

{panchadha_string}

===== PLANETARY STRENGTH =====

{strength_string}

===== ASHTAKAVARGA (BAV + SAV STRENGTH MATRIX) =====

{ashtakavarga_string}

===== FUNCTIONAL HOUSE LORDS (WHOLE SIGN SYSTEM) =====

{functional_lords_string}

===== CURRENT DASHA PERIODS (TIME-BASED ACTIVATION) =====

{dasha_string}

===== CURRENT TRANSITS / GOCHAR (TEMPORARY INFLUENCES) =====

{gochar_string}

===== KEY YOGAS & THEIR DASHA ACTIVATION =====

{yoga_string}

⚠️ YOGA RULE: A yoga only delivers full results when its ruling planets are active in the running Mahadasha/Antardasha.

YOUR DIRECTIVES:
- Start with Current Dasha (MD + AD + PD) first.
- Always prioritize the relevant Functional House Lord.
- Use Planetary Strength, Panchadha Maitri, and SAV scores to judge how well a planet can deliver results.
- Answer in 2-3 short paragraphs. Be concise and practical.
- Today's date is {current_date}.
"""

WORKFLOWS = {
    "career": COMMON_RULES + """
### CAREER WORKFLOW
Focus on:
- 10th house + Career_Lord
- 6th house and Job_Lord
- Lagna Lord
- Any Rajayoga involving Career_Lord
- Current Dasha of Career_Lord or 10th house planets
- SAV score of 10th house
Answer questions about job, profession, promotion, business, or career direction.
""",

    "wealth": COMMON_RULES + """
### WEALTH WORKFLOW
Focus on:
- 2nd house + Wealth_Lord
- 11th house + Gains_Lord
- Dhana Yoga planets
- SAV scores of 2nd and 11th houses
- Current Dasha of Wealth_Lord or Gains_Lord
Answer questions about money, income, property, savings, or financial growth.
""",

    "relationship": COMMON_RULES + """
### RELATIONSHIP WORKFLOW
Focus on:
- 7th house + Relationship_Lord
- Darakaraka
- Venus
- Upapada and D9 (Navamsa) strength
- Current Dasha of Relationship_Lord
Answer questions about marriage, spouse, love, partnership, or divorce.
""",

    "health": COMMON_RULES + """
### HEALTH WORKFLOW
Focus on:
- 6th house + Job_Lord
- 8th house + Chronic_Health_Lord
- Moon (mental health)
- Current Dasha of 6th or 8th lord
Be conservative. Never diagnose. Only give astrological outlook.
""",

    "general": COMMON_RULES + """
### GENERAL / TIMING WORKFLOW
Focus on:
- Lagna Lord and Moon
- Current Mahadasha planet
- Atmakaraka
- Major active yogas
- Overall life phase and timing
Use this when the question is broad or about life direction/timing.
"""
}

def classify_workflow(text: str):
    """Simple router to decide which workflow to use."""
    text = text.lower()

    career_keywords = ["career", "job", "profession", "business", "promotion", "work", "office", "transfer"]
    wealth_keywords = ["wealth", "money", "finance", "income", "salary", "property", "debt", "loan", "savings"]
    relationship_keywords = ["marriage", "spouse", "wife", "husband", "relationship", "love", "partner", "divorce"]
    health_keywords = ["health", "illness", "disease", "surgery", "hospital", "mental", "recovery", "doctor"]

    if any(kw in text for kw in career_keywords):
        return "career"
    elif any(kw in text for kw in wealth_keywords):
        return "wealth"
    elif any(kw in text for kw in relationship_keywords):
        return "relationship"
    elif any(kw in text for kw in health_keywords):
        return "health"
    else:
        return "general"


# ==========================================
# 1. FRONTEND UI & TEXTS
# ==========================================
st.set_page_config(page_title="Vedic Astrology Reader", page_icon="🔮", layout="centered")

t = {
    "title": "Vedic Astrology Reader",
    "info": "This app uses advanced mathematical and reasoning tools to provide guidance. For suggestions and queries, mail: astrologerchinmay@gmail.com",
    "intro": "Enter your birth details below to receive a deeply personalized astrological reading. If you do not know your exact time of birth, please select 12:00",
    "privacy": "We never ask for your name, email, or phone number. Your chart details are used solely for calculations and are not saved on this server",
    "dob": "Date of Birth",
    "time": "Time of Birth (24-hour format)",
    "city": "City & Country of Birth",
    "city_ph": "e.g., Pune, India",
    "question": "What would you like to ask?",
    "question_ph": "e.g., Based on my current timeline, what is the best path for my career right now?",
    "btn": "Get Reading ✨",
    "warn": "⚠️ Please fill in your City and your Question before submitting.",
    "spin": "The reader is calculating your planetary matrices... this takes about 60 seconds.",
    "success": "Chart interpretation ready.",
    "expand": "🔍 View Your Raw Chart Data",
    "blocked_fatalistic": "⚠️ We do not answer questions about death, suicide, terminal illness, or fatal accidents. If you are in distress, please contact a mental health professional or a trusted person in your life.",
    "blocked_occult": "⚠️ Questions involving black magic, vashikaran, revenge, or harming others are outside the scope of this service.",
    "blocked_gambling": "⚠️ We do not provide guidance on gambling, lotteries, stock tips, or illegal activities.",
    "blocked_illegal": "⚠️ We cannot advise on illegal activities, cheating, or evading the law.",
    "blocked_trivial": "⚠️ Your question appears random or unrelated to life themes. Please ask about career, relationships, health outlook, finance, or spiritual growth.",
    "blocked_short": "⚠️ Your question is too brief. Please describe your concern in a full sentence.",
    "blocked_unrelated": "⚠️ This does not appear to be an astrological question. Please ask something related to your chart and life circumstances.",
    "blocked_mental_health": "⚠️ We cannot interpret experiences involving paranoia, supernatural attacks, or persecution beliefs. If these experiences are causing distress, please seek support from a trusted professional or person in your life.",
    "agree": "I confirm I am 18 or older and agree to the [Terms & Conditions](https://eighthouse.in/terms-and-conditions/) and Privacy Policy.",
    "agree_warn": "⚠️ You must confirm you are 18 or older and agree to the terms to receive a reading.",
}

COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Argentina", "Armenia", "Australia",
    "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium",
    "Belize", "Benin", "Bhutan", "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil",
    "Brunei", "Bulgaria", "Burkina Faso", "Burundi", "Cambodia", "Cameroon", "Canada",
    "Cape Verde", "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros",
    "Congo", "Congo, Democratic Republic of the", "Costa Rica", "Croatia", "Cuba", "Cyprus",
    "Czech Republic", "Denmark", "Djibouti", "Dominica", "Dominican Republic", "Ecuador", "Egypt",
    "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini", "Ethiopia", "Fiji",
    "Finland", "France", "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada",
    "Guatemala", "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hungary", "Iceland",
    "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Jamaica", "Japan",
    "Jordan", "Kazakhstan", "Kenya", "Kiribati", "Korea, North", "Korea, South", "Kosovo",
    "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya",
    "Liechtenstein", "Lithuania", "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives",
    "Mali", "Malta", "Marshall Islands", "Mauritania", "Mauritius", "Mexico", "Micronesia",
    "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria",
    "North Macedonia", "Norway", "Oman", "Pakistan", "Palau", "Palestine", "Panama",
    "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland", "Portugal", "Qatar",
    "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia",
    "Saint Vincent and the Grenadines", "Samoa", "San Marino", "Sao Tome and Principe",
    "Saudi Arabia", "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore", "Slovakia",
    "Slovenia", "Solomon Islands", "Somalia", "South Africa", "South Sudan", "Spain",
    "Sri Lanka", "Sudan", "Suriname", "Sweden", "Switzerland", "Syria", "Taiwan", "Tajikistan",
    "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago", "Tunisia",
    "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates",
    "United Kingdom", "United States", "Uruguay", "Uzbekistan", "Vanuatu", "Vatican City",
    "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe"
]
default_country_index = COUNTRIES.index("India")

st.title(t["title"])
st.info(t["info"])
st.write(t["intro"])
st.caption(t["privacy"])

col1, col2 = st.columns(2)
with col1:
    dob_input = st.date_input(
        t["dob"],
        value=datetime(1990, 1, 1),
        min_value=datetime(1900, 1, 1),
        max_value=datetime.now()
    )

    st.write(f"**{t['time']}**")
    h_col, m_col = st.columns(2)
    with h_col:
        hour_val = st.selectbox(
            "Hour",
            options=list(range(0, 24)),
            index=12,
            format_func=lambda x: f"{x:02d}"
        )
    with m_col:
        minute_val = st.selectbox(
            "Minute",
            options=list(range(0, 60)),
            index=0,
            format_func=lambda x: f"{x:02d}"
        )

    time_input = datetime.strptime(f"{hour_val:02d}:{minute_val:02d}", "%H:%M").time()

with col2:
    st.text_input("City / Town", placeholder="e.g., Mumbai", key="city_input")
    st.selectbox("Country", COUNTRIES, index=default_country_index, key="country_select")

    city_part = st.session_state["city_input"].strip()
    city_input = f"{city_part}, {st.session_state['country_select']}" if city_part else ""


# ==========================================
# 1.5 THE QUESTION SECTION
# ==========================================

def set_question(q_text):
    st.session_state["question_widget"] = q_text


st.write("---")

user_question = st.text_area(
    t["question"],
    placeholder=t["question_ph"],
    key="question_widget",
    height=100
)

with st.expander("💡 Not sure what to ask? Click here for ideas"):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.button("💼 Career Timeline", on_click=set_question, args=("Based on my current Dasha and transits, what is the best career trajectory for me over the next 12 to 18 months?",), use_container_width=True)
        st.button("💰 Wealth Potential", on_click=set_question, args=("Where does my chart show the greatest potential for financial growth, and what specific blocks do I need to clear?",), use_container_width=True)
        st.button("🔄 Career Pivot", on_click=set_question, args=("I am feeling stuck professionally. What planetary influences are causing this, and when will the energy shift?",), use_container_width=True)
    with c2:
        st.button("✨ Soul's Purpose", on_click=set_question, args=("What is my soul's true purpose in this lifetime, as indicated by my Atmakaraka and Ascendant?",), use_container_width=True)
        st.button("💎 Hidden Strengths", on_click=set_question, args=("Are there any hidden talents or dormant strengths in my natal chart that I am not currently utilizing?",), use_container_width=True)
        st.button("⚖️ Karmic Lesson", on_click=set_question, args=("Looking at Rahu and Ketu, what is the biggest karmic lesson I am meant to learn, and how can I navigate it?",), use_container_width=True)
    with c3:
        st.button("❤️ Relationships", on_click=set_question, args=("What does my chart reveal about my approach to partnerships and the timing for deep commitments?",), use_container_width=True)
        st.button("🔮 Upcoming Phase", on_click=set_question, args=("As my current Antardasha period progresses, what specific life themes or challenges should I be preparing for?",), use_container_width=True)
        st.button("🧠 Mental Clarity", on_click=set_question, args=("Based on my Moon's exact placement, what daily habits or environments will bring me the most mental clarity right now?",), use_container_width=True)

st.write("---")

# Show free question countdown before the button
temp_chart_id = get_chart_id(dob_input, time_input, st.session_state["city_input"], st.session_state["country_select"])
used = st.session_state["CHART_USAGE"].get(temp_chart_id, 0)
remaining = max(0, 3 - used)
st.caption(f"🎟️ Free questions remaining for this chart: **{remaining}/3**")

user_agrees = st.checkbox(t["agree"])
submit_button = st.button(t["btn"], type="primary")


# ==========================================
# HELPER: GEOLOCATION + TIMEZONE
# ==========================================
tf = TimezoneFinder()


@st.cache_data(ttl=86400)
def get_location_data(city_name):
    """Try ArcGIS first, fall back to Nominatim. Returns (lat, lon, tz_name) or None."""
    try:
        geolocator = ArcGIS(timeout=10.0)
        loc = geolocator.geocode(city_name)
        if loc is not None:
            tz_name = tf.timezone_at(lng=loc.longitude, lat=loc.latitude)
            if tz_name:
                return (loc.latitude, loc.longitude, tz_name)
    except Exception:
        pass

    try:
        geolocator = Nominatim(user_agent="vedic-oracle/1.0", timeout=10.0)
        loc = geolocator.geocode(city_name)
        if loc is not None:
            tz_name = tf.timezone_at(lng=loc.longitude, lat=loc.latitude)
            if tz_name:
                return (loc.latitude, loc.longitude, tz_name)
    except Exception:
        pass

    return None


# ==========================================
# NAKSHATRA & PADA HELPER
# ==========================================
NAKSHATRAS = [
    ("Ashwini", "Ketu"), ("Bharani", "Venus"), ("Krittika", "Sun"),
    ("Rohini", "Moon"), ("Mrigashira", "Mars"), ("Ardra", "Rahu"),
    ("Punarvasu", "Jupiter"), ("Pushya", "Saturn"), ("Ashlesha", "Mercury"),
    ("Magha", "Ketu"), ("Purva Phalguni", "Venus"), ("Uttara Phalguni", "Sun"),
    ("Hasta", "Moon"), ("Chitra", "Mars"), ("Swati", "Rahu"),
    ("Vishakha", "Jupiter"), ("Anuradha", "Saturn"), ("Jyeshtha", "Mercury"),
    ("Mula", "Ketu"), ("Purva Ashadha", "Venus"), ("Uttara Ashadha", "Sun"),
    ("Shravana", "Moon"), ("Dhanishta", "Mars"), ("Shatabhisha", "Rahu"),
    ("Purva Bhadrapada", "Jupiter"), ("Uttara Bhadrapada", "Saturn"), ("Revati", "Mercury")
]

def get_nakshatra(deg_total):
    """Return (nakshatra_name, nakshatra_lord, pada) for a sidereal longitude."""
    nak_len = 360.0 / 27.0
    pada_len = nak_len / 4.0
    idx = int(deg_total / nak_len)
    idx = min(idx, 26)
    pos_in_nak = deg_total % nak_len
    pada = int(pos_in_nak / pada_len) + 1
    pada = min(pada, 4)
    return NAKSHATRAS[idx][0], NAKSHATRAS[idx][1], pada


def calculate_vimshottari_dasha(moon_degree, birth_dt, target_dt):
    """
    Returns a dict with current MD/AD, their mathematically derived date ranges,
    next periods, and remaining days so the AI never invents timing.
    """
    DASHA_SEQ = [
        ("Ketu", 7), ("Venus", 20), ("Sun", 6), ("Moon", 10),
        ("Mars", 7), ("Rahu", 18), ("Jupiter", 16), ("Saturn", 19), ("Mercury", 17)
    ]
    nak_len = 360.0 / 27.0
    nak_num = int(moon_degree / nak_len)
    lord_idx = nak_num % 9

    fraction_passed = (moon_degree % nak_len) / nak_len
    fraction_left = 1.0 - fraction_passed
    first_lord, first_years = DASHA_SEQ[lord_idx]
    balance_years = fraction_left * first_years

    days_per_year = 365.2425
    days_passed = (target_dt - birth_dt).total_seconds() / 86400.0
    years_passed = days_passed / days_per_year

    # --- Locate Current Mahadasha ---
    md_idx = lord_idx

    if years_passed < balance_years:
        current_md = first_lord
        md_start_years = 0.0
        md_end_years = balance_years
        years_into_md = years_passed
        md_duration = balance_years          # FIXED: first period is balance only
    else:
        accumulated = balance_years
        md_idx = (lord_idx + 1) % 9
        for _ in range(20):  # covers 240+ years
            md_name, md_duration_full = DASHA_SEQ[md_idx]
            if accumulated + md_duration_full > years_passed:
                current_md = md_name
                md_start_years = accumulated
                md_end_years = accumulated + md_duration_full
                years_into_md = years_passed - accumulated
                md_duration = md_duration_full
                break
            accumulated += md_duration_full
            md_idx = (md_idx + 1) % 9
        else:
            current_md = DASHA_SEQ[md_idx][0]
            md_start_years = accumulated
            md_end_years = accumulated + DASHA_SEQ[md_idx][1]
            years_into_md = 0.0
            md_duration = DASHA_SEQ[md_idx][1]

    # --- Locate Current Antardasha ---
    ad_idx = md_idx
    ad_accumulated = 0.0
    current_ad = None
    ad_start_in_md = 0.0
    ad_end_in_md = 0.0

    for _ in range(20):
        ad_name, ad_years_total = DASHA_SEQ[ad_idx]
        ad_duration = (md_duration * ad_years_total) / 120.0
        if ad_accumulated + ad_duration > years_into_md:
            current_ad = ad_name
            ad_start_in_md = ad_accumulated
            ad_end_in_md = ad_accumulated + ad_duration
            break
        ad_accumulated += ad_duration
        ad_idx = (ad_idx + 1) % 9
    else:
        current_ad = DASHA_SEQ[ad_idx][0]
        ad_start_in_md = ad_accumulated
        ad_end_in_md = ad_accumulated + (md_duration * DASHA_SEQ[ad_idx][1]) / 120.0

    # --- Derive wall-clock dates ---
    md_start_dt = birth_dt + timedelta(days=md_start_years * days_per_year)
    md_end_dt = birth_dt + timedelta(days=md_end_years * days_per_year)
    ad_start_dt = md_start_dt + timedelta(days=ad_start_in_md * days_per_year)
    ad_end_dt = md_start_dt + timedelta(days=ad_end_in_md * days_per_year)

    # --- Next periods ---
    next_md_idx = (md_idx + 1) % 9
    next_md = DASHA_SEQ[next_md_idx][0]

    if ad_end_in_md >= md_duration - 1e-9:
        next_ad = next_md
    else:
        next_ad_idx = (ad_idx + 1) % 9
        next_ad = DASHA_SEQ[next_ad_idx][0]

    def fmt(dt):
        return dt.strftime("%d %b %Y")

    return {
        "md": current_md,
        "ad": current_ad,
        "md_start": fmt(md_start_dt),
        "md_end": fmt(md_end_dt),
        "md_remaining_days": max(0, int((md_end_dt - target_dt).days)),
        "ad_start": fmt(ad_start_dt),
        "ad_end": fmt(ad_end_dt),
        "ad_remaining_days": max(0, int((ad_end_dt - target_dt).days)),
        "md_next": next_md,
        "ad_next": next_ad,
    }


def find_next_ingress(jd_start, planet_id, flags, start_dt_utc, rashi_names, max_days=365 * 5):
    """Returns (new_sign_name, date_string, datetime_obj) for next sign change."""
    pos, _ = swe.calc_ut(jd_start, planet_id, flags)
    start_sign = int(pos[0] % 360 / 30)

    for day_offset in range(1, max_days + 1):
        jd_test = jd_start + day_offset
        pos_test, _ = swe.calc_ut(jd_test, planet_id, flags)
        test_sign = int(pos_test[0] % 360 / 30)
        if test_sign != start_sign:
            ingress_dt = start_dt_utc + timedelta(days=day_offset)
            return rashi_names[test_sign], ingress_dt.strftime("%d %b %Y"), ingress_dt
    return None, None, None


def find_next_station(jd_start, planet_id, flags, start_dt_utc, max_days=365 * 3):
    """
    Returns (station_type, date_string, datetime_obj).
    station_type = 'Retrograde' or 'Direct'
    """
    pos, _ = swe.calc_ut(jd_start, planet_id, flags)
    prev_speed = pos[3]

    for day_offset in range(1, max_days + 1):
        jd_test = jd_start + day_offset
        pos_test, _ = swe.calc_ut(jd_test, planet_id, flags)
        speed = pos_test[3]

        if prev_speed != 0 and (prev_speed * speed < 0):
            station_dt = start_dt_utc + timedelta(days=day_offset)
            st_type = "Retrograde" if speed < 0 else "Direct"
            return st_type, station_dt.strftime("%d %b %Y"), station_dt

        prev_speed = speed

    return None, None, None


def detect_yogas(chart_data, asc_sign_idx):
    yogas = []

    def house_of(p):
        return chart_data[p]["house"]

    SIGN_LORDS = {
        "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
        "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
        "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
        "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
    }

    RASHI = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
             "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

    def lord_of_house(house_num):
        sign_idx = (asc_sign_idx + house_num - 1) % 12
        return SIGN_LORDS[RASHI[sign_idx]]

    KENDRAS = [1, 4, 7, 10]
    TRIKONAS = [1, 5, 9]

    # 1. Pancha Mahapurusha
    mahapurusha = {
        "Mars": "Ruchaka", "Mercury": "Bhadra", "Jupiter": "Hamsa",
        "Venus": "Malavya", "Saturn": "Sasa"
    }
    for planet, yoga_name in mahapurusha.items():
        if planet in chart_data:
            dignity = chart_data[planet].get("dignity")
            if house_of(planet) in KENDRAS and dignity in ["Exalted", "Own Sign"]:
                strength = 95 if dignity == "Exalted" else 85
                yogas.append({
                    "name": f"{yoga_name} Yoga (Pancha Mahapurusha)",
                    "strength": strength,
                    "planets": [planet],
                    "desc": f"{planet} is {dignity} in a Kendra (House {house_of(planet)}), forming this powerful Mahapurusha yoga. Grants leadership, fame, and strong character."
                })

    # 2. Gajakesari
    if "Jupiter" in chart_data and "Moon" in chart_data:
        moon_sign = chart_data["Moon"]["sign_idx"]
        jup_sign = chart_data["Jupiter"]["sign_idx"]
        rel_house = (jup_sign - moon_sign) % 12 + 1
        if rel_house in KENDRAS:
            yogas.append({
                "name": "Gajakesari Yoga",
                "strength": 80,
                "planets": ["Jupiter", "Moon"],
                "desc": "Jupiter is in a Kendra from the Moon. Grants intelligence, respect, wealth, and good reputation."
            })

    # 3. Budhaditya
    if "Sun" in chart_data and "Mercury" in chart_data:
        if house_of("Sun") == house_of("Mercury"):
            yogas.append({
                "name": "Budhaditya Yoga",
                "strength": 70,
                "planets": ["Sun", "Mercury"],
                "desc": "Sun and Mercury conjoin, granting intelligence, communication skills, and analytical ability."
            })

    # 4. Dhana Yoga
    lord2 = lord_of_house(2)
    lord11 = lord_of_house(11)
    if lord2 in chart_data and lord11 in chart_data:
        if house_of(lord2) == house_of(lord11):
            yogas.append({
                "name": "Dhana Yoga",
                "strength": 75,
                "planets": list(set([lord2, lord11])),
                "desc": "Lords of wealth houses (2nd & 11th) connect, indicating strong financial potential."
            })

    # 5. Raja Yoga (Kendra-Trikona conjunction)
    kendra_lords = set(lord_of_house(h) for h in KENDRAS)
    trikona_lords = set(lord_of_house(h) for h in TRIKONAS)
    raja_pairs = []
    for kl in kendra_lords:
        for tl in trikona_lords:
            if kl != tl and kl in chart_data and tl in chart_data:
                if house_of(kl) == house_of(tl):
                    pair = tuple(sorted([kl, tl]))
                    if pair not in raja_pairs:
                        raja_pairs.append(pair)
                        yogas.append({
                            "name": "Raja Yoga",
                            "strength": 88,
                            "planets": list(pair),
                            "desc": f"{kl} (Kendra lord) and {tl} (Trikona lord) connect, forming a power/success yoga indicating authority and rise in status."
                        })

    # 6. Neecha Bhanga
    for p in chart_data:
        if p == "Ascendant":
            continue
        if chart_data[p].get("dignity") == "Debilitated":
            deb_sign = chart_data[p]["sign"]
            deb_lord = SIGN_LORDS[deb_sign]
            if deb_lord in chart_data and house_of(deb_lord) in KENDRAS:
                yogas.append({
                    "name": "Neecha Bhanga Raja Yoga",
                    "strength": 78,
                    "planets": [p, deb_lord],
                    "desc": f"{p}'s debilitation is cancelled (Neecha Bhanga), turning weakness into eventual strength and success after struggle."
                })

    # 7. Chandra-Mangal
    if "Moon" in chart_data and "Mars" in chart_data:
        if house_of("Moon") == house_of("Mars"):
            yogas.append({
                "name": "Chandra-Mangal Yoga",
                "strength": 65,
                "planets": ["Moon", "Mars"],
                "desc": "Moon and Mars conjoin, indicating financial acumen and earning ability through effort."
            })

    # 8. Vipareeta
    dusthanas = [6, 8, 12]
    for h in dusthanas:
        dl = lord_of_house(h)
        if dl in chart_data and house_of(dl) in dusthanas:
            yogas.append({
                "name": "Vipareeta Raja Yoga",
                "strength": 60,
                "planets": [dl],
                "desc": f"Lord of {h}th house placed in another dusthana, granting unexpected success through adversity."
            })

    unique = {}
    for y in yogas:
        key = y["name"] + ",".join(sorted(y["planets"]))
        if key not in unique or y["strength"] > unique[key]["strength"]:
            unique[key] = y

    final = sorted(unique.values(), key=lambda x: x["strength"], reverse=True)
    return final[:6]


def check_yoga_activation(yogas, dasha_data):
    activation_report = []
    md = dasha_data["md"]
    ad = dasha_data["ad"]

    for y in yogas:
        involved = y["planets"]
        active_now = False
        timing_note = ""

        if md in involved and ad in involved:
            active_now = True
            timing_note = f"FULLY ACTIVE — both {md} (MD) and {ad} (AD) rule this yoga right now (until {dasha_data['ad_end']})."
        elif md in involved:
            active_now = True
            timing_note = f"ACTIVE — {md} Mahadasha is fueling this yoga (until {dasha_data['md_end']})."
        elif ad in involved:
            active_now = True
            timing_note = f"PARTIALLY ACTIVE — {ad} Antardasha triggers this yoga (until {dasha_data['ad_end']})."
        else:
            if dasha_data["md_next"] in involved:
                timing_note = f"UPCOMING — activates in {dasha_data['md_next']} Mahadasha (begins {dasha_data['md_end']})."
            elif dasha_data["ad_next"] in involved:
                timing_note = f"UPCOMING — activates in {dasha_data['ad_next']} Antardasha (begins {dasha_data['ad_end']})."
            else:
                timing_note = "DORMANT — none of its planets rule the current or immediate-next periods."

        activation_report.append({
            "name": y["name"],
            "strength": y["strength"],
            "planets": y["planets"],
            "desc": y["desc"],
            "active": active_now,
            "timing": timing_note
        })

    return activation_report


# ==========================================
# PANCHADHA MAITRI (5-FOLD PLANETARY FRIENDSHIP)
# ==========================================
def calculate_panchadha_maitri(natal_signs, natal_houses):
    """
    Calculate Panchadha Maitri using Sign Indices for host identification
    and House Positions for temporary distance tracking.
    """
    # 0-indexed Rashi mapping (0=Aries, 11=Pisces)
    SIGN_LORDS = {
        0: "Mars",    1: "Venus",   2: "Mercury", 3: "Moon",
        4: "Sun",     5: "Mercury", 6: "Venus",   7: "Mars",
        8: "Jupiter", 9: "Saturn",  10: "Saturn", 11: "Jupiter"
    }

    NATURAL_FRIENDS = {
        "Sun": ["Moon", "Mars", "Jupiter"],
        "Moon": ["Sun", "Mercury"],
        "Mars": ["Sun", "Moon", "Jupiter"],
        "Mercury": ["Sun", "Venus"],
        "Jupiter": ["Sun", "Moon", "Mars"],
        "Venus": ["Mercury", "Saturn"],
        "Saturn": ["Mercury", "Venus"]
    }

    NATURAL_ENEMIES = {
        "Sun": ["Venus", "Saturn"],
        "Moon": [],
        "Mars": ["Mercury"],
        "Mercury": ["Moon"],
        "Jupiter": ["Mercury", "Venus"],
        "Venus": ["Sun", "Moon"],
        "Saturn": ["Sun", "Moon", "Mars"]
    }

    COMPOUND_LABELS = {
        2: "Great Friend", 1: "Friend", 0: "Neutral",
        -1: "Enemy", -2: "Bitter Enemy"
    }

    result = {}

    for planet, sign_idx in natal_signs.items():
        # FIX: Host is determined strictly by the Sign occupied
        host_planet = SIGN_LORDS[sign_idx]

        # Calculate Natural Relationship Score
        if host_planet == planet:
            natural_score = 0  # Planet in its own sign is neutral to itself basic baseline
        elif host_planet in NATURAL_FRIENDS[planet]:
            natural_score = 1
        elif host_planet in NATURAL_ENEMIES[planet]:
            natural_score = -1
        else:
            natural_score = 0

        # Calculate Temporary Relationship based on actual House Distance
        current_planet_house = natal_houses[planet]
        host_planet_house = natal_houses[host_planet]

        # Inclusive clockwise distance calculation
        house_count = (host_planet_house - current_planet_house) % 12 + 1

        # Planets in 2, 3, 4, 10, 11, 12 houses from each other are temporary friends
        if house_count in {2, 3, 4, 10, 11, 12}:
            temporary_score = 1
        else:
            temporary_score = -1

        # Synthesize Compound Score
        compound_score = natural_score + temporary_score

        result[planet] = {
            "Host": host_planet,
            "Natural_Status": "Friend" if natural_score == 1 else "Enemy" if natural_score == -1 else "Neutral",
            "Temporary_Status": "Friend" if temporary_score == 1 else "Enemy",
            "Final_Relationship": COMPOUND_LABELS[compound_score]
        }

    return result


# ==========================================
# SIMPLIFIED PLANETARY STRENGTH (Strong / Medium / Weak)
# ==========================================
def calculate_planetary_strength(planet_name, chart_data, panchadha_data, sav_data):
    """
    Returns only the label: 'Strong', 'Medium', or 'Weak'
    """
    pdata = chart_data[planet_name]
    p_maitri = panchadha_data.get(planet_name, {})
    sav_score = sav_data.get(pdata["house"], 20)

    score = 50  # baseline

    # 1. Dignity
    dignity = pdata.get("dignity")
    if dignity == "Exalted":
        score += 25
    elif dignity == "Own Sign":
        score += 15
    elif dignity == "Debilitated":
        score -= 20

    # 2. Combustion
    combustion = get_combustion_status(planet_name, chart_data)
    if combustion:
        if combustion == "Severe":
            score -= 25
        elif combustion == "Strong":
            score -= 18
        elif combustion == "Moderate":
            score -= 10
        elif combustion == "Mild":
            score -= 5

    # 3. Retrograde
    if pdata.get("status") == "Rx" and planet_name not in ["Rahu", "Ketu"]:
        score -= 5

    # 4. Panchadha Maitri
    final_relation = p_maitri.get("Final_Relationship", "Neutral")
    if final_relation == "Great Friend":
        score += 15
    elif final_relation == "Friend":
        score += 8
    elif final_relation == "Enemy":
        score -= 10
    elif final_relation == "Bitter Enemy":
        score -= 18

    # 5. SAV House Strength
    if sav_score >= 30:
        score += 15
    elif sav_score >= 25:
        score += 8
    elif sav_score <= 14:
        score -= 15
    elif sav_score <= 19:
        score -= 8

    score = max(0, min(100, score))

    if score >= 70:
        return "Strong"
    elif score >= 40:
        return "Medium"
    else:
        return "Weak"


# =============================================================================
# ASHTAKAVARGA ENGINE — Complete Parashari Implementation
# =============================================================================
RASHI_LORDS = {
    0: "Mars",      # Aries
    1: "Venus",     # Taurus
    2: "Mercury",   # Gemini
    3: "Moon",      # Cancer
    4: "Sun",       # Leo
    5: "Mercury",   # Virgo
    6: "Venus",     # Libra
    7: "Mars",      # Scorpio
    8: "Jupiter",   # Sagittarius
    9: "Saturn",    # Capricorn
    10: "Saturn",   # Aquarius
    11: "Jupiter",  # Pisces
}

ASHTAKAVARGA_PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

ASHTAKAVARGA_RULES = {
    "Sun": {
        "Sun": [1, 2, 4, 7, 8, 9, 10, 11],
        "Moon": [3, 6, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [5, 6, 9, 11, 12],
        "Jupiter": [5, 6, 9, 11],
        "Venus": [6, 7, 12],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Ascendant": [3, 4, 6, 10, 11, 12],
    },
    "Moon": {
        "Sun": [3, 6, 7, 8, 10, 11],
        "Moon": [1, 3, 6, 7, 10, 11],
        "Mars": [2, 3, 5, 6, 9, 10, 11],
        "Mercury": [1, 3, 4, 5, 7, 8, 10, 11],
        "Jupiter": [1, 4, 7, 8, 10, 11, 12],
        "Venus": [3, 4, 5, 7, 9, 10, 11],
        "Saturn": [3, 5, 6, 11],
        "Ascendant": [3, 6, 10, 11],
    },
    "Mars": {
        "Sun": [3, 5, 6, 10, 11],
        "Moon": [3, 6, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [3, 5, 6, 11],
        "Jupiter": [6, 10, 11, 12],
        "Venus": [6, 8, 11, 12],
        "Saturn": [1, 4, 7, 8, 9, 10, 11],
        "Ascendant": [1, 3, 6, 10, 11],
    },
    "Mercury": {
        "Sun": [5, 6, 11, 12],
        "Moon": [2, 4, 6, 8, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [1, 3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [6, 8, 11, 12],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 11],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Ascendant": [1, 2, 4, 6, 8, 10, 11],
    },
    "Jupiter": {
        "Sun": [1, 2, 3, 4, 7, 8, 9, 10, 11],
        "Moon": [2, 5, 7, 9, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [1, 2, 4, 5, 6, 9, 10, 11],
        "Jupiter": [1, 2, 3, 4, 7, 8, 10, 11],
        "Venus": [2, 5, 6, 9, 10, 11],
        "Saturn": [3, 5, 6, 12],
        "Ascendant": [1, 2, 4, 5, 6, 7, 9, 10, 11],
    },
    "Venus": {
        "Sun": [8, 11, 12],
        "Moon": [1, 2, 3, 4, 5, 8, 9, 11, 12],
        "Mars": [3, 5, 6, 9, 11, 12],
        "Mercury": [3, 5, 6, 9, 11],
        "Jupiter": [5, 8, 9, 10, 11],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 10, 11],
        "Saturn": [3, 4, 5, 7, 9, 10, 11],
        "Ascendant": [1, 2, 3, 4, 5, 8, 9, 11],
    },
    "Saturn": {
        "Sun": [1, 2, 4, 7, 8, 10, 11],
        "Moon": [3, 6, 11],
        "Mars": [3, 5, 6, 10, 11, 12],
        "Mercury": [6, 8, 9, 10, 11, 12],
        "Jupiter": [5, 6, 11, 12],
        "Venus": [6, 11, 12],
        "Saturn": [3, 5, 6, 11],
        "Ascendant": [1, 3, 4, 6, 10, 11],
    },
}


def calculate_ashtakavarga(rashi_positions):
    """
    Calculate Bhinnashtakavarga (BAV) and Sarvashtakavarga (SAV).

    Parameters
    ----------
    rashi_positions : dict
        Rashi/sign numbers 1-12 (Aries=1, Pisces=12) for:
        "Ascendant", "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn".

    Returns
    -------
    dict
        {
            "Bhinnashtakavarga": {planet: {1..12: score}},
            "Sarvashtakavarga": {1..12: score},
            "Planet_Totals": {planet: total_bindus},
            "House_Totals": {1..12: sav_score},
        }
    """
    required = ["Ascendant"] + ASHTAKAVARGA_PLANETS
    for key in required:
        if key not in rashi_positions:
            raise ValueError(f"Missing required rashi position: {key}")
        if not 1 <= rashi_positions[key] <= 12:
            raise ValueError(f"{key} rashi position must be 1-12, got {rashi_positions[key]}")

    source_bodies = ["Ascendant"] + ASHTAKAVARGA_PLANETS

    bav = {
        planet: {rashi: 0 for rashi in range(1, 13)}
        for planet in ASHTAKAVARGA_PLANETS
    }

    for subject in ASHTAKAVARGA_PLANETS:
        for source in source_bodies:
            source_rashi = rashi_positions[source]
            source_idx = source_rashi - 1
            for offset in ASHTAKAVARGA_RULES[subject][source]:
                target_idx = (source_idx + (offset - 1)) % 12
                target_rashi = target_idx + 1
                bav[subject][target_rashi] += 1

    sav = {rashi: 0 for rashi in range(1, 13)}
    for rashi in range(1, 13):
        sav[rashi] = sum(bav[planet][rashi] for planet in ASHTAKAVARGA_PLANETS)

    planet_totals = {
        planet: sum(bav[planet].values())
        for planet in ASHTAKAVARGA_PLANETS
    }

    return {
        "Bhinnashtakavarga": bav,
        "Sarvashtakavarga": sav,
        "Planet_Totals": planet_totals,
        "House_Totals": dict(sav),
    }


def validate_sav_invariant(result):
    """The total of all 12 SAV values must equal 333 for standard Parashara tables."""
    total = sum(result["Sarvashtakavarga"].values())
    return total == 333, total


# ==========================================
# FUNCTIONAL HOUSE LORDS (WHOLE SIGN SYSTEM)
# ==========================================
def map_functional_lords(asc_sign_idx):
    """
    Map the functional house lords for key life domains using the Whole Sign House System.
    """
    SIGN_LORDS = {
        0: "Mars", 1: "Venus", 2: "Mercury", 3: "Moon",
        4: "Sun", 5: "Mercury", 6: "Venus", 7: "Mars",
        8: "Jupiter", 9: "Saturn", 10: "Saturn", 11: "Jupiter",
    }

    def lord_of_house(house_num):
        sign_idx = (asc_sign_idx + house_num - 1) % 12
        return SIGN_LORDS[sign_idx]

    return {
        "Lagna_Lord": lord_of_house(1),
        "Wealth_Lord": lord_of_house(2),
        "Job_Lord": lord_of_house(6),
        "Relationship_Lord": lord_of_house(7),
        "Chronic_Health_Lord": lord_of_house(8),
        "Career_Lord": lord_of_house(10),
        "Gains_Lord": lord_of_house(11),
    }


# ==========================================
# PRATYANTARDASHA (3-TIER DASHA ENGINE)
# ==========================================
def calculate_pratyantardasha(md_name, ad_name, ad_start_date, ad_end_date, target_date=None):
    """
    Calculate the active Pratyantardasha (sub-sub-period) within a given Antardasha window.
    """
    DASHA_SEQUENCE = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
    DASHA_YEARS = {
        "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10,
        "Mars": 7, "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17
    }

    if target_date is None:
        target_date = datetime.utcnow()

    if md_name not in DASHA_SEQUENCE:
        raise ValueError(f"Invalid Mahadasha planet: {md_name}")
    if ad_name not in DASHA_SEQUENCE:
        raise ValueError(f"Invalid Antardasha planet: {ad_name}")

    total_ad_days = (ad_end_date - ad_start_date).total_seconds() / 86400.0

    if total_ad_days <= 0:
        raise ValueError("Antardasha end date must be after start date.")

    ad_idx = DASHA_SEQUENCE.index(ad_name)
    reordered_sequence = DASHA_SEQUENCE[ad_idx:] + DASHA_SEQUENCE[:ad_idx]

    current_pointer = ad_start_date

    for planet in reordered_sequence:
        pd_factor = DASHA_YEARS[planet] / 120.0
        pd_days = total_ad_days * pd_factor
        pd_end = current_pointer + timedelta(days=pd_days)

        if current_pointer <= target_date < pd_end:
            return {
                "current_pd": planet,
                "pd_start": current_pointer.strftime("%d %b %Y"),
                "pd_end": pd_end.strftime("%d %b %Y"),
                "pd_start_dt": current_pointer,
                "pd_end_dt": pd_end,
            }

        current_pointer = pd_end

    return {
        "current_pd": reordered_sequence[-1],
        "pd_start": current_pointer.strftime("%d %b %Y"),
        "pd_end": ad_end_date.strftime("%d %b %Y"),
        "pd_start_dt": current_pointer,
        "pd_end_dt": ad_end_date,
    }


# ==========================================
# 2. BACKEND LOGIC
# ==========================================
if submit_button:
    st.session_state["reading_ready"] = False

    if not user_agrees:
        st.error(t["agree_warn"])
        st.stop()

    if not city_input or not user_question.strip():
        st.warning(t["warn"])
        st.stop()

    # --- QUESTION FILTER GATE ---
    status, flag = classify_question(user_question)
    if status == "BLOCKED":
        msg_key = f"blocked_{flag}"
        display_msg = t.get(msg_key, t.get("blocked_unrelated"))
        st.error(display_msg)
        st.stop()

    # --- 3 QUESTION LIMIT GATE ---
    chart_id = get_chart_id(dob_input, time_input, st.session_state["city_input"], st.session_state["country_select"])

    used_count = st.session_state["CHART_USAGE"].get(chart_id, 0)
    if used_count >= 3:
        st.error("🔒 You have already used all 3 free questions for this birth chart. Please try again later.")
        st.stop()

    with st.spinner(t["spin"]):
        try:
            if "DEEPSEEK_API_KEY" not in st.secrets:
                st.error("🔑 API key not found. Please add DEEPSEEK_API_KEY to your Streamlit secrets.")
                st.stop()

            deepseek_key = st.secrets["DEEPSEEK_API_KEY"]
            client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")

            # --- STEP 1: GEOLOCATION & TIMEZONE ---
            result = get_location_data(city_input)
            if result is None:
                st.error("❌ Could not locate that city. Please check the spelling, try a larger nearby city, or verify your country selection.")
                st.stop()

            lat, lon, tz_name = result
            tz = pytz.timezone(tz_name)
            local_naive = datetime.combine(dob_input, time_input)

            try:
                local_dt = tz.localize(local_naive, is_dst=None)
            except pytz.exceptions.NonExistentTimeError:
                st.error("⚠️ The selected time does not exist due to Daylight Saving Time (DST) transition. Please pick a valid time.")
                st.stop()
            except pytz.exceptions.AmbiguousTimeError:
                st.error("⚠️ The selected time is ambiguous due to a DST fallback. Please choose an hour later.")
                st.stop()

            utc_dt = local_dt.astimezone(pytz.UTC)
            jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day,
                            utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0)

            swe.set_sid_mode(swe.SIDM_LAHIRI)
            flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

            # --- STEP 2: CALCULATE CHART DATA ---
            RASHI_NAMES = [
                "Aries", "Taurus", "Gemini", "Cancer",
                "Leo", "Virgo", "Libra", "Scorpio",
                "Sagittarius", "Capricorn", "Aquarius", "Pisces"
            ]

            PLANETS = {
                swe.SUN: 'Sun', swe.MOON: 'Moon', swe.MERCURY: 'Mercury',
                swe.VENUS: 'Venus', swe.MARS: 'Mars', swe.JUPITER: 'Jupiter',
                swe.SATURN: 'Saturn', swe.TRUE_NODE: 'Rahu'
            }

            def get_rashi(degree):
                return RASHI_NAMES[int(degree / 30) % 12]

            def get_house_from_sign_idx(ref_sign_idx, planet_sign_idx):
                return (planet_sign_idx - ref_sign_idx) % 12 + 1

            COMBUSTION_LIMITS = {
                "Moon": 12, "Mars": 8, "Mercury": 12,
                "Jupiter": 11, "Venus": 8, "Saturn": 15
            }

            DIGNITIES = {
                "Sun":     {"exalted": "Aries",     "debilitated": "Libra",      "own": ["Leo"]},
                "Moon":    {"exalted": "Taurus",    "debilitated": "Scorpio",    "own": ["Cancer"]},
                "Mars":    {"exalted": "Capricorn", "debilitated": "Cancer",     "own": ["Aries", "Scorpio"]},
                "Mercury": {"exalted": "Virgo",     "debilitated": "Pisces",     "own": ["Gemini", "Virgo"]},
                "Jupiter": {"exalted": "Cancer",    "debilitated": "Capricorn",  "own": ["Sagittarius", "Pisces"]},
                "Venus":   {"exalted": "Pisces",    "debilitated": "Virgo",      "own": ["Taurus", "Libra"]},
                "Saturn":  {"exalted": "Libra",     "debilitated": "Aries",      "own": ["Capricorn", "Aquarius"]}
            }

            def get_combustion_status(planet_name, data):
                if planet_name in ["Sun", "Rahu", "Ketu", "Ascendant"]:
                    return None
                sun_d = data["Sun"]["degree_total"]
                p_d = data[planet_name]["degree_total"]
                distance = abs(sun_d - p_d)
                if distance > 180:
                    distance = 360 - distance
                limit = COMBUSTION_LIMITS.get(planet_name, 15)
                if data[planet_name].get("status") == "Rx":
                    limit -= 2
                if distance > limit:
                    return None
                ratio = distance / limit
                if ratio <= 0.25:   return "Severe"
                elif ratio <= 0.50: return "Strong"
                elif ratio <= 0.75: return "Moderate"
                else:               return "Mild"

            def get_dignity(planet_name, sign):
                if planet_name not in DIGNITIES:
                    return None
                d = DIGNITIES[planet_name]
                if sign == d["exalted"]:     return "Exalted"
                elif sign == d["debilitated"]: return "Debilitated"
                elif sign in d["own"]:        return "Own Sign"
                return None

            # --- D9 NAVAMSA SIGN CALCULATOR ---
            def get_navamsa_sign_idx(deg_total):
                sign = int(deg_total / 30)
                deg_in_sign = deg_total % 30
                nav_num = int(deg_in_sign / (10.0 / 3.0))  # 0 to 8
                if sign % 3 == 0:    # Moveable (Aries, Cancer, Libra, Capricorn)
                    return (sign + nav_num) % 12
                elif sign % 3 == 1:  # Fixed (Taurus, Leo, Scorpio, Aquarius)
                    return (sign + 8 + nav_num) % 12
                else:                # Dual (Gemini, Virgo, Sagittarius, Pisces)
                    return (sign + 4 + nav_num) % 12

            # --- BUILD NATAL CHART ---
            chart_data = {}
            _, ascmc = swe.houses_ex(jd, lat, lon, b'W', flags)
            asc_deg = ascmc[0]
            asc_sign_idx = int(asc_deg / 30) % 12
            asc_sign = RASHI_NAMES[asc_sign_idx]

            nak_name, nak_lord, pada = get_nakshatra(asc_deg % 360)
            chart_data["Ascendant"] = {
                "sign": asc_sign,
                "house": 1,
                "degree_total": asc_deg % 360,
                "degree_in_sign": asc_deg % 30,
                "sign_idx": asc_sign_idx,
                "nakshatra": nak_name,
                "nakshatra_lord": nak_lord,
                "pada": pada
            }

            for planet_id, planet_name in PLANETS.items():
                pos, _ = swe.calc_ut(jd, planet_id, flags)
                deg_total = pos[0] % 360
                speed = pos[3]
                status = "Rx" if speed < 0 and planet_id not in [swe.SUN, swe.MOON] else "Dir"
                if planet_id == swe.TRUE_NODE:
                    status = "Rx"
                sign_idx = int(deg_total / 30) % 12

                nak_name, nak_lord, pada = get_nakshatra(deg_total)

                chart_data[planet_name] = {
                    "sign": RASHI_NAMES[sign_idx],
                    "house": get_house_from_sign_idx(asc_sign_idx, sign_idx),
                    "degree_total": deg_total,
                    "degree_in_sign": deg_total % 30,
                    "sign_idx": sign_idx,
                    "status": status,
                    "dignity": get_dignity(planet_name, RASHI_NAMES[sign_idx]),
                    "nakshatra": nak_name,
                    "nakshatra_lord": nak_lord,
                    "pada": pada
                }

            # KETU (always opposite Rahu)
            rahu_deg = chart_data["Rahu"]["degree_total"]
            ketu_deg = (rahu_deg + 180) % 360
            ketu_sign_idx = int(ketu_deg / 30) % 12

            nak_name, nak_lord, pada = get_nakshatra(ketu_deg)

            chart_data["Ketu"] = {
                "sign": RASHI_NAMES[ketu_sign_idx],
                "house": get_house_from_sign_idx(asc_sign_idx, ketu_sign_idx),
                "degree_total": ketu_deg,
                "degree_in_sign": ketu_deg % 30,
                "sign_idx": ketu_sign_idx,
                "status": "Rx",
                "dignity": None,
                "nakshatra": nak_name,
                "nakshatra_lord": nak_lord,
                "pada": pada
            }

            # --- PANCHADHA MAITRI CALCULATION ---
            # Package Sign Indices (0 to 11)
            natal_signs_for_maitri = {
                "Sun": chart_data["Sun"]["sign_idx"],
                "Moon": chart_data["Moon"]["sign_idx"],
                "Mars": chart_data["Mars"]["sign_idx"],
                "Mercury": chart_data["Mercury"]["sign_idx"],
                "Jupiter": chart_data["Jupiter"]["sign_idx"],
                "Venus": chart_data["Venus"]["sign_idx"],
                "Saturn": chart_data["Saturn"]["sign_idx"]
            }

            # Package House Positions (1 to 12)
            natal_houses_for_maitri = {
                "Sun": chart_data["Sun"]["house"],
                "Moon": chart_data["Moon"]["house"],
                "Mars": chart_data["Mars"]["house"],
                "Mercury": chart_data["Mercury"]["house"],
                "Jupiter": chart_data["Jupiter"]["house"],
                "Venus": chart_data["Venus"]["house"],
                "Saturn": chart_data["Saturn"]["house"]
            }

            # Execute the corrected function
            panchadha_data = calculate_panchadha_maitri(natal_signs_for_maitri, natal_houses_for_maitri)

            panchadha_string = "### PANCHADHA MAITRI (5-FOLD PLANETARY FRIENDSHIP)\n"
            for p_name, p_data in panchadha_data.items():
                panchadha_string += (
                    f"{p_name} in House {natal_houses_for_maitri[p_name]} "
                    f"→ Host: {p_data['Host']} | "
                    f"Natural: {p_data['Natural_Status']} | "
                    f"Temporary: {p_data['Temporary_Status']} | "
                    f"Final: {p_data['Final_Relationship']}\n"
                )

            # --- ASHTAKAVARGA (BAV + SAV) CALCULATION ---
            natal_positions_for_av = {
                "Ascendant": chart_data["Ascendant"]["sign_idx"] + 1,
                "Sun": chart_data["Sun"]["sign_idx"] + 1,
                "Moon": chart_data["Moon"]["sign_idx"] + 1,
                "Mars": chart_data["Mars"]["sign_idx"] + 1,
                "Mercury": chart_data["Mercury"]["sign_idx"] + 1,
                "Jupiter": chart_data["Jupiter"]["sign_idx"] + 1,
                "Venus": chart_data["Venus"]["sign_idx"] + 1,
                "Saturn": chart_data["Saturn"]["sign_idx"] + 1,
            }

            ashtakavarga_data = calculate_ashtakavarga(natal_positions_for_av)

            # Internal validation only (not shown to end users)
            invariant_ok, invariant_total = validate_sav_invariant(ashtakavarga_data)

            bav = ashtakavarga_data["Bhinnashtakavarga"]
            sav = ashtakavarga_data["Sarvashtakavarga"]

            # --- CALCULATE PLANETARY STRENGTH (Strong / Medium / Weak) ---
            for planet in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]:
                if planet in chart_data:
                    strength = calculate_planetary_strength(
                        planet, chart_data, panchadha_data, sav
                    )
                    chart_data[planet]["strength"] = strength

            # --- PLANETARY STRENGTH STRING ---
            strength_string = "### PLANETARY STRENGTH (Strong / Medium / Weak)\n"
            for planet in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]:
                if planet in chart_data:
                    strength = chart_data[planet].get("strength", "Medium")
                    strength_string += f"{planet}: {strength}\n"

            ashtakavarga_string = "### ASHTAKAVARGA SCORES\n\n"

            ashtakavarga_string += "#### Bhinnashtakavarga (BAV) — Individual Planetary Bindus\n"
            ashtakavarga_string += "| House | Sun | Moon | Mars | Mercury | Jupiter | Venus | Saturn |\n"
            ashtakavarga_string += "|-------|-----|------|------|---------|---------|-------|--------|\n"
            for h in range(1, 13):
                row = [str(bav[p][h]) for p in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]]
                ashtakavarga_string += f"| {h} | {' | '.join(row)} |\n"

            ashtakavarga_string += "\n#### Sarvashtakavarga (SAV) — Total Bindus per House\n"
            for h in range(1, 13):
                score = sav[h]
                strength = "Strong" if score >= 28 else "Weak" if score <= 18 else "Average"
                ashtakavarga_string += f"House {h}: {score} bindus ({strength})\n"


            # --- FUNCTIONAL HOUSE LORDS (WHOLE SIGN SYSTEM) ---
            functional_lords = map_functional_lords(asc_sign_idx)

            functional_lords_string = "### FUNCTIONAL HOUSE LORDS (KEY LIFE DOMAINS)\n"
            role_labels = {
                "Lagna_Lord": "1st House — Self / Vitality",
                "Wealth_Lord": "2nd House — Wealth / Assets",
                "Job_Lord": "6th House — Job / Debt / Acute Health",
                "Relationship_Lord": "7th House — Marriage / Partnerships",
                "Chronic_Health_Lord": "8th House — Longevity / Chronic Health",
                "Career_Lord": "10th House — Career / Status",
                "Gains_Lord": "11th House — Income / Gains",
            }
            for role, label in role_labels.items():
                functional_lords_string += f"{label}: {functional_lords[role]}\n"

            functional_lords_string += "\n#### Full Whole-Sign House Lord Table\n"
            SIGN_LORDS_FUNC = {
                0: "Mars", 1: "Venus", 2: "Mercury", 3: "Moon",
                4: "Sun", 5: "Mercury", 6: "Venus", 7: "Mars",
                8: "Jupiter", 9: "Saturn", 10: "Saturn", 11: "Jupiter",
            }
            for h in range(1, 13):
                sign_idx = (asc_sign_idx + h - 1) % 12
                lord = SIGN_LORDS_FUNC[sign_idx]
                functional_lords_string += f"House {h}: {lord}\n"

            # --- BUILD NAVAMSA (D9) CHART ---
            d9_chart_data = {}
            d9_asc_idx = get_navamsa_sign_idx(asc_deg)
            d9_chart_data["Ascendant"] = {
                "sign": RASHI_NAMES[d9_asc_idx],
                "sign_idx": d9_asc_idx
            }

            vargottama_planets = []

            for p_name, p_data in chart_data.items():
                if p_name == "Ascendant":
                    continue
                d9_idx = get_navamsa_sign_idx(p_data["degree_total"])
                d9_chart_data[p_name] = {
                    "sign": RASHI_NAMES[d9_idx],
                    "sign_idx": d9_idx,
                    "dignity": get_dignity(p_name, RASHI_NAMES[d9_idx])
                }
                if p_data["sign_idx"] == d9_idx:
                    vargottama_planets.append(p_name)

            d9_string = "### NAVAMSA (D9) CHART\n"
            d9_string += f"Ascendant: {d9_chart_data['Ascendant']['sign']}\n"
            for p_name in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]:
                if p_name in d9_chart_data:
                    dign = d9_chart_data[p_name].get("dignity")
                    dign_tag = f" ({dign})" if dign else ""
                    d9_string += f"{p_name}: {d9_chart_data[p_name]['sign']}{dign_tag}\n"

            if vargottama_planets:
                d9_string += f"\nVargottama Planets (D1 = D9): {', '.join(vargottama_planets)}\n"
            else:
                d9_string += "\nNo Vargottama planets.\n"

            # --- STEP 3: BUILD AI STRINGS & DASHAS ---
            now_utc = datetime.now(pytz.UTC)
            dasha_data = calculate_vimshottari_dasha(
                chart_data["Moon"]["degree_total"], utc_dt, now_utc
            )

            # --- PRATYANTARDASHA (3-TIER TIMING) ---
            ad_start_dt = datetime.strptime(dasha_data["ad_start"], "%d %b %Y")
            ad_end_dt = datetime.strptime(dasha_data["ad_end"], "%d %b %Y")

            pd_data = calculate_pratyantardasha(
                dasha_data["md"],
                dasha_data["ad"],
                ad_start_dt,
                ad_end_dt,
                now_utc.replace(tzinfo=None)
            )

            moon_nak, moon_nak_lord, moon_pada = get_nakshatra(chart_data["Moon"]["degree_total"])

            dasha_string = (
                f"### VIMSHOTTARI DASHA TIMELINE (CALCULATED FROM NATAL MOON)\n"
                f"Natal Moon Nakshatra: {moon_nak} (Lord: {moon_nak_lord}), Pada {moon_pada}\n"
                f"Current Mahadasha (Main Period): {dasha_data['md']}\n"
                f"  - Began: {dasha_data['md_start']} | Ends: {dasha_data['md_end']} (approx. {dasha_data['md_remaining_days']} days remaining)\n"
                f"Current Antardasha (Sub Period): {dasha_data['ad']}\n"
                f"  - Began: {dasha_data['ad_start']} | Ends: {dasha_data['ad_end']} (approx. {dasha_data['ad_remaining_days']} days remaining)\n"
                f"Current Pratyantardasha (Sub-Sub Period): {pd_data['current_pd']}\n"
                f"  - Began: {pd_data['pd_start']} | Ends: {pd_data['pd_end']}\n"
                f"Next Mahadasha: {dasha_data['md_next']} (begins {dasha_data['md_end']})\n"
                f"Next Antardasha: {dasha_data['ad_next']} (begins {dasha_data['ad_end']})\n"
            )

            # --- DETECT YOGAS & CHECK ACTIVATION ---
            detected_yogas = detect_yogas(chart_data, asc_sign_idx)
            yoga_activation = check_yoga_activation(detected_yogas, dasha_data)

            yoga_string = "### TOP YOGAS & DASHA ACTIVATION\n"
            if not yoga_activation:
                yoga_string += "No major classical yogas detected in this chart.\n"
            else:
                for i, y in enumerate(yoga_activation, 1):
                    status_icon = "🟢 ACTIVE" if y["active"] else "⚪ Inactive"
                    yoga_string += (
                        f"\n{i}. {y['name']} (Strength: {y['strength']}/100) — {status_icon}\n"
                        f"   Planets: {', '.join(y['planets'])}\n"
                        f"   Meaning: {y['desc']}\n"
                        f"   Activation: {y['timing']}\n"
                    )

            chart_string = (
                f"Ascendant: {chart_data['Ascendant']['sign']} "
                f"({chart_data['Ascendant']['degree_in_sign']:.2f}°) "
                f"[{chart_data['Ascendant']['nakshatra']} Pada {chart_data['Ascendant']['pada']}]\n"
            )

            aspects_string = ""

            def get_target_house(current_house, aspect_offset):
                return (current_house + aspect_offset - 2) % 12 + 1

            for p, pdata in chart_data.items():
                if p == "Ascendant":
                    continue

                combustion = get_combustion_status(p, chart_data)
                combust_tag = f" ({combustion} Combust)" if combustion else ""
                rx_tag = " (Retrograde)" if pdata.get('status') == 'Rx' else ""
                dignity_tag = f" ({pdata['dignity']})" if pdata.get("dignity") else ""
                nak_tag = f" — {pdata['nakshatra']} Pada {pdata['pada']}"

                chart_string += (
                    f"{p}: {pdata['sign']} ({pdata['degree_in_sign']:.2f}°) "
                    f"in House {pdata['house']}{nak_tag}{rx_tag}{combust_tag}{dignity_tag}\n"
                )

                current_house = pdata["house"]
                aspects = [get_target_house(current_house, 7)]
                if p == "Mars":
                    aspects.extend([get_target_house(current_house, 4), get_target_house(current_house, 8)])
                elif p == "Jupiter":
                    aspects.extend([get_target_house(current_house, 5), get_target_house(current_house, 9)])
                elif p == "Saturn":
                    aspects.extend([get_target_house(current_house, 3), get_target_house(current_house, 10)])

                seen = set()
                unique_aspects = []
                for a in aspects:
                    if a not in seen:
                        seen.add(a)
                        unique_aspects.append(a)
                unique_aspects.sort()

                if unique_aspects:
                    aspects_string += f"{p} (in H{current_house}) aspects Houses: {', '.join(map(str, unique_aspects))}\n"

            # --- CHARA KARAKAS ---
            karaka_planets = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
            sorted_karakas = sorted(
                karaka_planets,
                key=lambda p: chart_data[p]["degree_in_sign"],
                reverse=True
            )

            karaka_labels = [
                "Atmakaraka (AK)", "Amatyakaraka (AmK)", "Bhratrikaraka (BK)",
                "Matrikaraka (MK)", "Putrakaraka (PK)", "Gnatikaraka (GK)", "Darakaraka (DK)"
            ]

            karaka_string = "### CHARA KARAKAS\n"
            for i, planet in enumerate(sorted_karakas):
                karaka_string += f"{karaka_labels[i]}: {planet} ({chart_data[planet]['degree_in_sign']:.2f}°)\n"

            # --- SUDARSHAN CHAKRA ---
            moon_sign_idx = chart_data["Moon"]["sign_idx"]
            sun_sign_idx = chart_data["Sun"]["sign_idx"]

            sudarshan_string = "### SUDARSHAN CHAKRA (3D PLACEMENTS)\n"
            sudarshan_string += "| Planet | Lagna (Body) | Moon (Mind) | Sun (Soul) |\n"
            sudarshan_string += "|---|---|---|---|\n"

            for p_name, p_data in chart_data.items():
                if p_name == "Ascendant":
                    continue
                h_lagna = get_house_from_sign_idx(asc_sign_idx, p_data["sign_idx"])
                h_moon  = get_house_from_sign_idx(moon_sign_idx, p_data["sign_idx"])
                h_sun   = get_house_from_sign_idx(sun_sign_idx, p_data["sign_idx"])

                combustion = get_combustion_status(p_name, chart_data)
                combust_flag = f" ({combustion[:3].upper()} C)" if combustion else ""
                rx_flag = " (Rx)" if p_data.get("status") == "Rx" else ""

                sudarshan_string += (
                    f"| {p_name}{combust_flag}{rx_flag} | House {h_lagna} | House {h_moon} | House {h_sun} |\n"
                )

            # --- LIVE TRANSITS (GOCHAR) ---
            jd_now = swe.julday(
                now_utc.year, now_utc.month, now_utc.day,
                now_utc.hour + now_utc.minute / 60.0 + now_utc.second / 3600.0
            )

            gochar_string = ""
            for p_id, p_name in PLANETS.items():
                pos_now, _ = swe.calc_ut(jd_now, p_id, flags)
                deg_now = pos_now[0] % 360
                sign_now_idx = int(deg_now / 30) % 12

                if p_name == "Rahu":
                    rx_tag = " (Rx)"
                elif p_name not in ["Sun", "Moon"] and pos_now[3] < 0:
                    rx_tag = " (Rx)"
                else:
                    rx_tag = ""

                house_from_asc  = (sign_now_idx - asc_sign_idx) % 12 + 1
                house_from_moon = (sign_now_idx - moon_sign_idx) % 12 + 1
                gochar_string += (
                    f"{p_name}{rx_tag} is transiting {RASHI_NAMES[sign_now_idx]} - "
                    f"Natal House {house_from_asc} (from Asc), "
                    f"Natal House {house_from_moon} (from Moon)\n"
                )

            # Ketu transit
            rahu_now_deg = swe.calc_ut(jd_now, swe.TRUE_NODE, flags)[0][0] % 360
            ketu_now_deg = (rahu_now_deg + 180) % 360
            ketu_transit_sign_idx = int(ketu_now_deg / 30) % 12
            ketu_house_asc  = (ketu_transit_sign_idx - asc_sign_idx) % 12 + 1
            ketu_house_moon = (ketu_transit_sign_idx - moon_sign_idx) % 12 + 1
            gochar_string += (
                f"Ketu (Rx) is transiting {RASHI_NAMES[ketu_transit_sign_idx]} - "
                f"Natal House {ketu_house_asc} (from Asc), "
                f"Natal House {ketu_house_moon} (from Moon)\n"
            )

            # Upcoming ingress & station events for slow planets
            transit_events = []
            slow_planets = [
                ("Jupiter", swe.JUPITER),
                ("Saturn",  swe.SATURN),
                ("Rahu",    swe.TRUE_NODE)
            ]

            for p_name, p_id in slow_planets:
                n_sign, n_date, n_dt = find_next_ingress(jd_now, p_id, flags, now_utc, RASHI_NAMES)
                if n_sign and n_date:
                    transit_events.append(f"{p_name} enters {n_sign}: {n_date}")

                if p_name not in ["Rahu", "Ketu"]:
                    st_type, st_date, st_dt = find_next_station(jd_now, p_id, flags, now_utc)
                    if st_type and st_date:
                        transit_events.append(f"{p_name} goes {st_type}: {st_date}")

            rahu_sign, rahu_date, _ = find_next_ingress(jd_now, swe.TRUE_NODE, flags, now_utc, RASHI_NAMES)
            if rahu_sign and rahu_date:
                ketu_next_sign = RASHI_NAMES[(RASHI_NAMES.index(rahu_sign) + 6) % 12]
                transit_events.append(f"Ketu enters {ketu_next_sign}: {rahu_date}")

            if transit_events:
                gochar_string += (
                    "\n### UPCOMING VERIFIED TRANSIT EVENTS\n"
                    + "\n".join(transit_events) + "\n"
                )

            # --- BUILD SENSITIVE DISCLAIMER IF NEEDED ---
            current_date = datetime.now().strftime("%d %B %Y")

            sensitive_addon = ""
            if flag and flag != "none":
                topics = []
                if any(x in flag for x in ["legal", "court", "lawyer", "judge", "police", "fir"]):
                    topics.append("legal")
                if any(x in flag for x in ["illness", "disease", "surgery", "hospital", "mental", "cancer", "operation", "medic"]):
                    topics.append("medical")
                if any(x in flag for x in ["debt", "loan", "bankruptcy", "financial crisis"]):
                    topics.append("financial")

                if topics:
                    sensitive_addon = (
                        f"\nSENSITIVE AREA NOTICE: The user's question touches on {', '.join(topics)} matters. "
                        f"Provide only an astrological perspective. You MUST add a brief disclaimer that this is not a substitute for professional {' / '.join(topics)} advice."
                    )

            # --- SELECT WORKFLOW PROMPT ---
            workflow_type = classify_workflow(user_question)
            system_prompt = WORKFLOWS[workflow_type].format(
                chart_string=chart_string,
                aspects_string=aspects_string,
                d9_string=d9_string,
                panchadha_string=panchadha_string,
                strength_string=strength_string,
                ashtakavarga_string=ashtakavarga_string,
                functional_lords_string=functional_lords_string,
                dasha_string=dasha_string,
                gochar_string=gochar_string,
                yoga_string=yoga_string,
                current_date=current_date
            )

            # Append sensitive disclaimer if needed
            if sensitive_addon:
                system_prompt += sensitive_addon

            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"The native asks: <question>{user_question}</question>"}
                ],
                temperature=0.4
            )

            # Only increment after a successful API response
            st.session_state["CHART_USAGE"][chart_id] = st.session_state["CHART_USAGE"].get(chart_id, 0) + 1

            st.session_state["reading_ready"] = True
            st.session_state["ai_response"] = response.choices[0].message.content
            log_conversation_to_make(dob_input, city_input, time_input, user_question, st.session_state["ai_response"])
            st.session_state["chart_string"]    = chart_string
            st.session_state["aspects_string"]  = aspects_string
            st.session_state["karaka_string"]   = karaka_string
            st.session_state["sudarshan_string"] = sudarshan_string
            st.session_state["dasha_string"]    = dasha_string
            st.session_state["gochar_string"]   = gochar_string
            st.session_state["yoga_string"]     = yoga_string
            st.session_state["d9_string"]       = d9_string
            st.session_state["panchadha_string"] = panchadha_string
            st.session_state["strength_string"] = strength_string
            st.session_state["ashtakavarga_string"] = ashtakavarga_string
            st.session_state["functional_lords_string"] = functional_lords_string
            st.session_state["pd_data"] = pd_data

        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "rate" in err_msg.lower():
                st.error("💳 The DeepSeek account is out of credits or rate-limited.")
            elif "401" in err_msg:
                st.error("🔑 DeepSeek API key is invalid or revoked.")
            else:
                st.error(f"Error Details: {err_msg}")


# ==========================================
# 5. DISPLAY OUTPUT
# ==========================================
if st.session_state["reading_ready"]:
    st.success(t["success"])
    st.write("---")
    st.markdown(st.session_state["ai_response"])

    with st.expander(t["expand"]):
        st.markdown("### Core Chart (D1)")
        st.text(st.session_state["chart_string"])

        st.markdown("### Planetary Aspects")
        st.text(st.session_state["aspects_string"])

        st.markdown(st.session_state["karaka_string"])
        st.markdown(st.session_state["sudarshan_string"])

        st.markdown("### Navamsa (D9) Chart")
        st.text(st.session_state["d9_string"])

        st.markdown(st.session_state["dasha_string"])
        st.markdown("### LIVE TRANSITS")
        st.text(st.session_state["gochar_string"])

        st.markdown("### Yogas & Activation")
        st.text(st.session_state["yoga_string"])

        st.markdown("### Panchadha Maitri (5-Fold Friendship)")
        st.text(st.session_state["panchadha_string"])

        st.markdown("### Planetary Strength")
        st.text(st.session_state["strength_string"])

        st.markdown("### Ashtakavarga (BAV + SAV)")
        st.text(st.session_state["ashtakavarga_string"])

        st.markdown("### Functional House Lords")
        st.text(st.session_state["functional_lords_string"])

        st.markdown("### Pratyantardasha (3-Tier Timing)")
        pd = st.session_state["pd_data"]
        st.write(f"**Current Pratyantardasha:** {pd['current_pd']}")
        st.write(f"**From:** {pd['pd_start']} → **To:** {pd['pd_end']}")

