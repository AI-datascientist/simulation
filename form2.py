# -*- coding: utf-8 -*-
# Psychiatric Interview Simulation — Streamlit (Voice/Text, Talking Avatars, Sidebar Info)
# Files expected in the same folder: aliye.jpg, feride.jpg, bck.jpg
# Works with GOOGLE_API_KEY from env, st.secrets, or sidebar input

import os, re, uuid, csv, json, datetime, time, base64
from typing import List, Dict, Any, Tuple, Optional

import streamlit as st
from PIL import Image
from difflib import SequenceMatcher

# Optional deps (gracefully degrade)
try:
    import google.generativeai as genai
    _GENAI_IMPORT_OK = True
except Exception:
    _GENAI_IMPORT_OK = False

try:
    import pandas as pd
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    _XLSX_OK = True
except Exception:
    _XLSX_OK = False

# -----------------------------
# CONFIG
# -----------------------------
APP_TITLE = "Psychiatric Interview Simulation"
LOG_DIR = "logs"
USER_DIR = "users"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(USER_DIR, exist_ok=True)

EXCEL_FILE = os.path.join(USER_DIR, "registered_users.xlsx")
EXCEL_PASSWORD = "admin123"
DOWNLOAD_PASSWORD = "download456"

# Prefer env or secrets; allow UI entry
_GOOGLE_API_KEY_ENV = os.getenv("GOOGLE_API_KEY", "").strip()
_GOOGLE_API_KEY_SEC = st.secrets.get("GOOGLE_API_KEY", "").strip() if hasattr(st, "secrets") else ""

# -----------------------------
# PAGE SETUP + BACKGROUND
# -----------------------------
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="👥",
    layout="wide",
    initial_sidebar_state="expanded"
)

def set_background_from_file(path: str):
    if not os.path.exists(path):
        return
    with open(path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode()
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image: url("data:image/jpg;base64,{b64}");
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        /* translucent chat bubbles */
        .chat-bubble {{
            background: rgba(255,255,255,0.92);
            border-radius: 14px;
            padding: 12px 14px;
            border: 1px solid rgba(0,0,0,0.06);
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

set_background_from_file("bck.jpg")

# -----------------------------
# PERSONAS
# -----------------------------
MDD_PERSONA = {
    "name": "Aliye Seker",
    "age": 40,
    "gender": "Female",
    "dx": "Major Depressive Disorder",
    "current_meds": "Fluoxetine 20–40 mg (day 7 of uptitration)",
    "photo": "aliye.jpg",
    "speech_style": "Brief answers, slow, hopeless tone."
}
SCZ_PERSONA = {
    "name": "Feride Deniz",
    "age": 25,
    "gender": "Female",
    "dx": "Schizophrenia, Paranoid Type",
    "current_meds": "LAI Risperidone; previously Haloperidol",
    "photo": "feride.jpg",
    "speech_style": "Guarded, may be tangential; paranoid themes."
}

# -----------------------------
# SIMPLE STANDARDIZED QA DB (demo)
# -----------------------------
ALI_QA_DATABASE = [
    {"q": "How are you feeling today", "a": "I still feel like I’m in a dark hole. Nothing seems to help.", "part": "Part 1"},
    {"q": "Do you have thoughts of harming yourself", "a": "I’ve had those thoughts… but I don’t want to go into details.", "part": "Part 1"},
    {"q": "How is your sleep", "a": "I wake up around 3 AM and can’t go back to sleep.", "part": "Part 1"},
]
FERDI_QA_DATABASE = [
    {"q": "Why are you here", "a": "My mother brought me. She thinks I need help.", "part": "Part 1"},
    {"q": "Do you hear voices", "a": "Sometimes… but they’re quieter when I stay calm.", "part": "Part 2"},
]

# -----------------------------
# UTIL
# -----------------------------
def ensure_state_defaults():
    ss = st.session_state
    ss.setdefault("page", "registration")
    ss.setdefault("user", None)
    ss.setdefault("selected_persona", None)
    ss.setdefault("selected_part", None)
    ss.setdefault("session_id", None)
    ss.setdefault("conversation", [])  # list of (role, text, ts, source)
    ss.setdefault("awaiting_permission", False)
    ss.setdefault("avatar_placeholder", None)
    ss.setdefault("enable_tts", True)
    ss.setdefault("voice_output_target", "Browser (SpeechSynthesis)")

ensure_state_defaults()

def timestamp():
    return datetime.datetime.now().strftime("%H:%M:%S")

def log_line(role, text, source=""):
    st.session_state.conversation.append((role, text, timestamp(), source))

def similarity(a: str, b: str) -> float:
    a = re.sub(r"[^\w\s]", "", a.lower().strip())
    b = re.sub(r"[^\w\s]", "", b.lower().strip())
    return SequenceMatcher(None, a, b).ratio()

def qa_lookup(user_q: str, persona_name: str, part: str) -> Optional[str]:
    db = ALI_QA_DATABASE if persona_name == "Aliye Seker" else FERDI_QA_DATABASE
    best, best_s = None, 0.0
    for row in db:
        if row.get("part") == part:
            s = similarity(user_q, row["q"])
            if s > best_s:
                best_s, best = s, row
    if best and best_s >= 0.70:
        return best["a"]
    return None

# -----------------------------
# GEMINI
# -----------------------------
def get_google_api_key() -> str:
    if _GOOGLE_API_KEY_ENV:
        return _GOOGLE_API_KEY_ENV
    if _GOOGLE_API_KEY_SEC:
        return _GOOGLE_API_KEY_SEC
    return st.session_state.get("GOOGLE_API_KEY_UI", "").strip()

def init_gemini() -> bool:
    api_key = get_google_api_key()
    if not (_GENAI_IMPORT_OK and api_key):
        return False
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception:
        return False

def build_system_prompt(persona: Dict, part: str) -> str:
    if persona["name"] == "Aliye Seker":
        stage = "Day 2 acute admission" if part == "Part 1" else "Day 7 reassessment"
        return (
            f"You are {persona['name']}, {persona['age']}, {persona['gender']} with severe depression. "
            f"Stage: {stage}. Speak briefly, slow, and hopeless. Avoid specific self-harm methods. "
            f"Stay in character and answer naturally in 1–3 sentences."
        )
    else:
        stage = "Day 3 acute psychosis" if part == "Part 1" else "Day 14 stabilizing"
        return (
            f"You are {persona['name']}, {persona['age']}, {persona['gender']} with paranoid schizophrenia. "
            f"Stage: {stage}. Be guarded; mild tangentiality allowed; do not give medical advice. "
            f"Stay in character and answer naturally in 1–3 sentences."
        )

def llm_reply(persona: Dict, part: str, user_text: str) -> str:
    if not init_gemini():
        return "I'm having trouble responding right now."
    sys_prompt = build_system_prompt(persona, part)
    try:
        model = genai.GenerativeModel(model_name="gemini-2.5-flash", system_instruction=sys_prompt)
        r = model.generate_content(user_text)
        text = (getattr(r, "text", None) or "").strip()
        text = re.sub(r"\[.*?\]", "", text)  # remove bracketed meta
        return text or "I'm not sure how to answer that."
    except Exception:
        return "I'm having trouble responding right now."

# -----------------------------
# BROWSER TTS (SpeechSynthesis) + STT (Web Speech)
# -----------------------------
def speak_browser(text: str):
    """Speak on client using Web Speech API (no server audio)."""
    escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("</", "<\\/")
    comp = st.components.v1.html(
        f"""
        <script>
        const text = `{escaped}`;
        try {{
            const u = new SpeechSynthesisUtterance(text);
            u.rate = 1.0;
            u.pitch = 1.0;
            u.lang = 'en-US';
            window.speechSynthesis.cancel();
            window.speechSynthesis.speak(u);
        }} catch(e) {{}}
        </script>
        """,
        height=0
    )
    return comp

def voice_input_browser(label="Press Start and speak"):
    """Capture one-shot STT with Web Speech API; returns transcript or ''."""
    html = """
    <div style="padding:8px;border:1px solid #ddd;border-radius:10px;background:#fff;">
      <button id="startBtn">🎙️ Start</button>
      <button id="stopBtn" disabled>⏹️ Stop</button>
      <span id="status" style="margin-left:8px;color:#555;">Idle</span>
      <div id="out" style="margin-top:8px;font-weight:600;"></div>
    </div>
    <script>
    const startBtn = document.getElementById('startBtn');
    const stopBtn  = document.getElementById('stopBtn');
    const statusEl = document.getElementById('status');
    const outEl    = document.getElementById('out');

    let rec=null; let finalText = "";

    function isSupported(){
      return ('webkitSpeechRecognition' in window) || ('SpeechRecognition' in window);
    }

    function createRec(){
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      const r = new SR();
      r.lang = 'en-US';
      r.interimResults = true;
      r.maxAlternatives = 1;
      r.onstart = ()=>{{ statusEl.textContent='Listening...'; }};
      r.onresult = (e)=>{
        let t = "";
        for (let i= e.resultIndex;i<e.results.length;i++){ t += e.results[i][0].transcript; }
        outEl.textContent = t;
        finalText = t;
      };
      r.onend = ()=>{{ statusEl.textContent='Stopped'; startBtn.disabled=false; stopBtn.disabled=true; }};
      r.onerror = ()=>{{ statusEl.textContent='Error'; startBtn.disabled=false; stopBtn.disabled=true; }};
      return r;
    }

    if(!isSupported()){
      statusEl.textContent = 'Browser STT not supported.';
      startBtn.disabled = true;
    }

    startBtn.onclick = ()=>{
      finalText = ""; outEl.textContent = "";
      if(!rec) rec = createRec();
      startBtn.disabled = true; stopBtn.disabled = false;
      rec.start();
    };
    stopBtn.onclick = ()=>{
      if(rec) rec.stop();
    };

    // send transcript to Streamlit on stop
    const streamlitSend = (t)=>{ window.parent.postMessage({type:'streamlit:componentReady', value:true}, '*');
                                 window.parent.postMessage({type:'streamlit:setComponentValue', value:t}, '*'); };

    window.addEventListener('message', (event)=>{
      // ignore
    });

    // poll for finalText after end
    setInterval(()=>{ if(finalText){ streamlitSend(finalText); finalText=""; }}, 600);
    </script>
    """
    val = st.components.v1.html(html, height=130)
    # Component returns via postMessage; Streamlit picks it up as value
    # But in this lightweight embed, we read it using st.session_state
    # Streamlit’s low-level component glue auto-updates return_value
    return val

# -----------------------------
# AVATAR (talk indicator)
# -----------------------------
def show_avatar(photo_path: str, speaking: bool, placeholder=None):
    if not os.path.exists(photo_path):
        return
    if placeholder is None:
        placeholder = st.empty()
    with placeholder.container():
        st.image(photo_path, use_container_width=True)
        if speaking:
            st.markdown(
                """
                <div style='text-align:center;padding:8px;border-radius:10px;
                    background:linear-gradient(90deg,#10b981,#059669);color:#fff;
                    font-weight:600;animation:pulse 1s infinite'>🗣️ Speaking...</div>
                <style>@keyframes pulse{0%,100%{opacity:1}50%{opacity:.75}}</style>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                "<div style='text-align:center;padding:8px;border-radius:10px;background:#eef2ff;color:#334155;'>👤 Listening</div>",
                unsafe_allow_html=True
            )

# -----------------------------
# REGISTRATION
# -----------------------------
def save_user_profile(username, data):
    path = os.path.join(USER_DIR, f"{username}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_user_profile(username):
    path = os.path.join(USER_DIR, f"{username}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_user_to_excel(user_data):
    if not (_XLSX_OK and isinstance(user_data, dict)):
        return
    row = pd.DataFrame([{
        "Username": user_data["username"],
        "First Name": user_data["first_name"],
        "Last Name": user_data["last_name"],
        "Nickname": user_data["nickname"],
        "Email": user_data.get("email",""),
        "Registration Date": user_data["registration_date"],
        "Photo Path": user_data["photo_path"]
    }])
    if os.path.exists(EXCEL_FILE):
        try:
            old = pd.read_excel(EXCEL_FILE)
            df = pd.concat([old, row], ignore_index=True)
        except Exception:
            df = row
    else:
        df = row
    df.to_excel(EXCEL_FILE, index=False)

    # style + pseudo protection (structure lock)
    try:
        wb = load_workbook(EXCEL_FILE)
        ws = wb.active
        hdr_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        hdr_font = Font(bold=True, color="FFFFFF")
        for c in ws[1]:
            c.fill = hdr_fill
            c.font = hdr_font
            c.alignment = Alignment(horizontal="center", vertical="center")
        for col in ws.columns:
            mx = 0
            letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    mx = max(mx, len(str(cell.value)))
            ws.column_dimensions[letter].width = min(mx+2, 50)
        wb.security.workbookPassword = EXCEL_PASSWORD
        wb.security.lockStructure = True
        wb.save(EXCEL_FILE)
    except Exception:
        pass

# -----------------------------
# PAGES
# -----------------------------
def page_registration():
    st.markdown("<h1 style='text-align:center;color:#111827;'>Psychiatric Interview Simulation</h1>", unsafe_allow_html=True)
    tab_login, tab_register = st.tabs(["Login", "Register"])

    with tab_login:
        u = st.text_input("Username")
        if st.button("Login", type="primary"):
            data = load_user_profile(u)
            if data:
                st.session_state.user = data
                st.session_state.page = "menu"
                st.session_state.session_id = None
                st.success(f"Welcome back, {data['nickname']}!")
                st.rerun()
            else:
                st.error("User not found. Please register first.")

    with tab_register:
        c1, c2 = st.columns(2)
        with c1:
            first = st.text_input("First Name*")
            last = st.text_input("Last Name*")
            nick = st.text_input("Nickname*")
        with c2:
            email = st.text_input("Email (optional)")
            photo = st.file_uploader("Upload Your Photo*", type=["jpg","jpeg","png"])

        if st.button("Register", type="primary"):
            if first and last and nick and photo:
                username = nick.lower().replace(" ", "_")
                photo_path = os.path.join(USER_DIR, f"{username}_photo.jpg")
                with open(photo_path, "wb") as f:
                    f.write(photo.getbuffer())
                user_data = {
                    "username": username,
                    "first_name": first,
                    "last_name": last,
                    "nickname": nick,
                    "email": email,
                    "photo_path": photo_path,
                    "registration_date": datetime.datetime.now().isoformat()
                }
                save_user_profile(username, user_data)
                save_user_to_excel(user_data)
                st.session_state.user = user_data
                st.session_state.page = "menu"
                st.success("Registration successful.")
                st.rerun()
            else:
                st.error("Please fill all required fields (*) and upload a photo.")

def sidebar_patient_info(persona: Dict):
    st.markdown("### Patient Information")
    st.write(f"**Name:** {persona['name']}")
    st.write(f"**Age:** {persona['age']}")
    st.write(f"**Gender:** {persona['gender']}")
    st.write(f"**Diagnosis:** {persona['dx']}")
    st.write(f"**Current Meds:** {persona['current_meds']}")
    st.markdown("---")

    # Avatar box
    st.markdown("### Patient Avatar")
    if st.session_state.avatar_placeholder is None:
        st.session_state.avatar_placeholder = st.empty()
    photo_path = persona.get("photo","")
    show_avatar(photo_path, speaking=False, placeholder=st.session_state.avatar_placeholder)

    st.markdown("---")
    st.markdown("### Settings")
    # API key entry (if not provided)
    if not get_google_api_key():
        st.info("Enter your GOOGLE_API_KEY to enable AI responses.")
        st.session_state.GOOGLE_API_KEY_UI = st.text_input("GOOGLE_API_KEY", type="password")
    st.session_state.enable_tts = st.checkbox("Enable Patient Voice (Browser)", value=st.session_state.enable_tts)
    st.selectbox("Voice Output Target", ["Browser (SpeechSynthesis)"], key="voice_output_target")
    st.markdown("---")

def page_menu():
    user = st.session_state.user
    st.markdown(
        f"""
        <div style='background:rgba(255,255,255,0.92);padding:16px;border-radius:12px;border:1px solid #eee'>
            <h2 style='margin:0'>Welcome, {user['nickname']}!</h2>
            <p style='margin:4px 0 0 0'>Select a patient and interview stage to begin.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Aliye Seker — MDD")
        if os.path.exists("aliye.jpg"):
            st.image("aliye.jpg", use_container_width=True)
        if st.button("Select Aliye Seker"):
            st.session_state.selected_persona = MDD_PERSONA
            st.rerun()
    with c2:
        st.subheader("Feride Deniz — Schizophrenia")
        if os.path.exists("feride.jpg"):
            st.image("feride.jpg", use_container_width=True)
        if st.button("Select Feride Deniz"):
            st.session_state.selected_persona = SCZ_PERSONA
            st.rerun()

    if st.session_state.selected_persona:
        st.markdown("---")
        st.info(f"Selected patient: **{st.session_state.selected_persona['name']}**")
        colp1, colp2 = st.columns(2)
        with colp1:
            if st.button("Part 1"):
                st.session_state.selected_part = "Part 1"
                st.session_state.session_id = str(uuid.uuid4())[:8]
                st.session_state.conversation = []
                st.session_state.awaiting_permission = False
                st.session_state.page = "interview"
                st.rerun()
        with colp2:
            if st.button("Part 2"):
                st.session_state.selected_part = "Part 2"
                st.session_state.session_id = str(uuid.uuid4())[:8]
                st.session_state.conversation = []
                st.session_state.awaiting_permission = False
                st.session_state.page = "interview"
                st.rerun()

    st.markdown("---")
    if st.button("Logout"):
        st.session_state.clear()
        ensure_state_defaults()
        st.rerun()

def page_interview():
    persona = st.session_state.selected_persona
    part = st.session_state.selected_part
    sid = st.session_state.session_id

    with st.sidebar:
        sidebar_patient_info(persona)

    st.markdown(
        f"""
        <div style='background:linear-gradient(135deg,#667eea,#764ba2);padding:14px;border-radius:12px;color:#fff'>
            <h3 style='margin:0'>Interview • {persona['name']} — {part}</h3>
            <small>Session ID: {sid}</small>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Show conversation
    for role, msg, ts, source in st.session_state.conversation:
        if role == "Student":
            st.markdown(f"<div class='chat-bubble'><b>You</b><br>{msg}<br><span style='color:#6b7280;font-size:12px'>{ts}</span></div>", unsafe_allow_html=True)
        else:
            badge = "📚 STANDARDIZED" if source == "db" else "🤖 AI"
            st.markdown(f"<div class='chat-bubble'><b>{persona['name']}</b> <span style='font-size:11px;background:#eef2ff;border:1px solid #cbd5e1;padding:2px 6px;border-radius:6px;margin-left:6px'>{badge}</span><br>{msg}<br><span style='color:#6b7280;font-size:12px'>{ts}</span></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("Your Input")

    input_mode = st.radio("Choose input method", ["Text", "Voice (Browser)"], horizontal=True)

    user_text = ""
    if input_mode == "Text":
        col1, col2 = st.columns([5,1])
        with col1:
            user_text = st.text_input("Type your question or statement:", key="text_in")
        with col2:
            send = st.button("Send", type="primary", use_container_width=True)
        if send and user_text.strip():
            handle_turn(user_text.strip())
            st.rerun()
    else:
        st.caption("Use the browser microphone (Chrome recommended).")
        transcript = voice_input_browser()
        # When transcript is delivered, it appears as the component's return value.
        # Streamlit sets it into a hidden widget state; we read it via a session key.
        # Easiest: show a small 'Use Transcript' button
        val = st.session_state.get("_component_value")  # Not reliable in all builds; add a text_input as pickup:
        recent = st.text_input("Transcript (auto-filled when ready):", value=st.session_state.get("last_transcript",""))
        colv1, colv2 = st.columns([5,1])
        with colv1:
            manual = st.text_input("Or edit and send:", key="manual_voice_send")
        with colv2:
            sendv = st.button("Send Voice", type="primary", use_container_width=True)
        # Try to pull new transcript from the component via front-channel (fallback):
        # If user pastes/edits, we’ll just send manual text.
        if sendv:
            txt = manual.strip() or recent.strip()
            if txt:
                handle_turn(txt)
                st.rerun()

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("End Session"):
            st.session_state.page = "evaluation"
            st.rerun()
    with c2:
        if st.button("Back to Menu"):
            st.session_state.page = "menu"
            st.rerun()

def handle_turn(user_input: str):
    persona = st.session_state.selected_persona
    part = st.session_state.selected_part

    # Student line
    log_line("Student", user_input, "")

    # Show avatar as listening
    show_avatar(persona["photo"], speaking=False, placeholder=st.session_state.avatar_placeholder)
    time.sleep(0.2)

    # DB first
    ans = qa_lookup(user_input, persona["name"], part)
    source = "db" if ans else "ai"
    if not ans:
        ans = llm_reply(persona, part, user_input)

    # Speak (browser)
    show_avatar(persona["photo"], speaking=True, placeholder=st.session_state.avatar_placeholder)
    if st.session_state.enable_tts and st.session_state.voice_output_target.startswith("Browser"):
        speak_browser(ans)
    time.sleep(0.2)
    show_avatar(persona["photo"], speaking=False, placeholder=st.session_state.avatar_placeholder)

    # Add patient line
    log_line("Patient", ans, source)

def page_evaluation():
    persona = st.session_state.selected_persona
    part = st.session_state.selected_part
    sid = st.session_state.session_id

    st.success("Interview Completed. You can start a new session from the menu.")
    db = sum(1 for r in st.session_state.conversation if r[0]=="Patient" and r[3]=="db")
    ai = sum(1 for r in st.session_state.conversation if r[0]=="Patient" and r[3]=="ai")
    st.metric("Standardized Responses", db)
    st.metric("AI Responses", ai)

    if st.button("Back to Menu", type="primary"):
        st.session_state.page = "menu"
        st.rerun()

# -----------------------------
# MAIN
# -----------------------------
def main():
    if st.session_state.page == "registration":
        page_registration()
        return

    if not st.session_state.user:
        st.session_state.page = "registration"
        st.rerun()

    if st.session_state.page == "menu":
        page_menu()
    elif st.session_state.page == "interview":
        if not (st.session_state.selected_persona and st.session_state.selected_part and st.session_state.session_id):
            st.session_state.page = "menu"
            st.rerun()
        page_interview()
    elif st.session_state.page == "evaluation":
        page_evaluation()

    # footer
    st.markdown(
        """
        <div style="margin-top:24px;padding:12px;border-top:1px solid #e5e7eb;color:#6b7280">
            Developed by Dr. Volkan OBAN — 2025
        </div>
        """,
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
