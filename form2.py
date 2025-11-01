# form2.py — Web-safe Streamlit app for GitHub/Streamlit Cloud
# - Images at repo ROOT (aliye.jpg, feride.jpg, bck.jpg) or images/ if moved later
# - No absolute OS paths, no server TTS/STT deps
# - Client-side TTS with Web Speech API
# - Optional Gemini fallback via GOOGLE_API_KEY (env)

import os, re, time, uuid, base64, datetime
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st
from PIL import Image

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Psychiatric Interview Simulation", page_icon="🧠", layout="wide")
BASE_DIR = Path(__file__).parent

# If you later move images into a folder, set LOCAL_IMAGE_DIR = BASE_DIR/"images"
LOCAL_IMAGE_DIR = BASE_DIR               # currently images are at repo ROOT
ALT_IMAGE_DIR   = BASE_DIR / "images"    # fallback if you move them into images/

GITHUB_OWNER   = "AI-datascientist"
GITHUB_REPO    = "simulation"
GITHUB_BRANCH  = "main"
RAW_BASE_URL   = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
GENAI_OK = False
try:
    if GOOGLE_API_KEY:
        import google.generativeai as genai
        genai.configure(api_key=GOOGLE_API_KEY)
        GENAI_OK = True
except Exception:
    GENAI_OK = False


# =========================
# IMAGE HELPERS
# =========================
def _local_path(fname: str) -> Path:
    p = LOCAL_IMAGE_DIR / fname
    if p.exists():
        return p
    q = ALT_IMAGE_DIR / fname
    return q

def load_image_bytes(fname: str) -> Optional[bytes]:
    # 1) local
    p = _local_path(fname)
    try:
        if p.exists():
            return p.read_bytes()
    except Exception:
        pass
    # 2) remote (GitHub RAW)
    try:
        url = f"{RAW_BASE_URL}/{fname}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None

def image_to_base64_uri(fname: str, mime="image/jpeg") -> str:
    data = load_image_bytes(fname)
    if not data:
        return ""
    b64 = base64.b64encode(data).decode()
    return f"data:{mime};base64,{b64}"

def show_img(fname: str, **st_kwargs) -> bool:
    data = load_image_bytes(fname)
    if not data:
        return False
    try:
        img = Image.open(BytesIO(data))
        st.image(img, **st_kwargs)
        return True
    except Exception:
        return False


# =========================
# SMALL Q&A DB (fallback)
# =========================
ALI_QA = [
    ("How are you feeling today?", "I feel like I'm in a dark hole. Everything seems pointless."),
    ("How's your appetite?", "Food has no taste. I don't feel hungry."),
    ("Do you have thoughts of harming yourself?", "Sometimes I think the world would be better without me."),
]
FERIDE_QA = [
    ("Why are you here?", "My mother brought me. She doesn't understand the voices."),
    ("Do you hear voices?", "Yes, they talk to me. They say I should be careful."),
    ("Will you take your medication?", "I don't trust those pills. Maybe they're poison."),
]

def simple_match(user_q: str, qa: List[Tuple[str,str]]) -> Optional[str]:
    if not user_q:
        return None
    qlow = re.sub(r"\W+", " ", user_q.lower()).strip()
    best, best_s = None, 0.0
    for k, v in qa:
        klow = re.sub(r"\W+", " ", k.lower()).strip()
        # Jaccard-ish quick score
        A, B = set(qlow.split()), set(klow.split())
        s = len(A & B) / max(1, len(A | B))
        if s > best_s:
            best_s = s
            best = v
    return best if best_s >= 0.2 else None


# =========================
# LLM (optional)
# =========================
def llm_reply(system_instruction: str, user_text: str) -> str:
    if not GENAI_OK:
        return ""
    try:
        model = genai.GenerativeModel("gemini-2.0-flash", system_instruction=system_instruction)
        resp = model.generate_content(user_text)
        txt = (getattr(resp, "text", None) or "").strip()
        # clean brackets that some models add
        txt = re.sub(r"\[.*?\]", "", txt)
        return txt[:500] if txt else ""
    except Exception:
        return ""


# =========================
# TTS (Client-side Web Speech)
# =========================
def speak_client(text: str, rate: float = 1.0, pitch: float = 1.0, gender: str = "female", accent: str = "en-US"):
    if not text:
        return
    safe = (text or "").replace("\\", "\\\\").replace('"', '\\"').replace("`", "'")
    st.components.v1.html(
        f"""
        <script>
        (function(){{
          const TXT="{safe}";
          const RATE={rate};
          const PITCH={pitch};
          const GENDER="{gender}".toLowerCase();
          const ACCENT="{accent}";
          if(!("speechSynthesis" in window) || !TXT) return;

          const pickVoice=()=>{{
            const vs=speechSynthesis.getVoices()||[];
            const has=(v)=> (v.name+" "+(v.lang||"")).toLowerCase();
            const female=/Jenny|Samantha|Zira|Hazel|Emma|Olivia|Amy|Aria|Joanna|Kendra|Lucy|Karen|Tessa/i;
            const male=/David|Mark|Daniel|George|Brian|Justin|Matthew/i;
            let chosen=null;
            if(GENDER==="female"){{
              chosen=vs.find(v=>/en-?(us|gb)/i.test(v.lang)&&(female.test(v.name)||/female/i.test(has(v))))||
                     vs.find(v=>v.lang===ACCENT&&/female/i.test(has(v)))||
                     vs.find(v=>v.lang===ACCENT);
            }}else{{
              chosen=vs.find(v=>/en-?(us|gb)/i.test(v.lang)&&(male.test(v.name)||/male/i.test(has(v))))||
                     vs.find(v=>v.lang===ACCENT&&/male/i.test(has(v)))||
                     vs.find(v=>v.lang===ACCENT);
            }}
            if(!chosen) chosen=vs.find(v=>/en-?(us|gb)/i.test(v.lang))||vs[0]||null;
            const u=new SpeechSynthesisUtterance(TXT);
            u.rate=RATE; u.pitch=PITCH; u.lang=ACCENT;
            if(chosen) u.voice=chosen;
            speechSynthesis.cancel();
            speechSynthesis.speak(u);
          }};
          if(speechSynthesis.getVoices().length===0){{
            speechSynthesis.onvoiceschanged=pickVoice;
          }}else{{ pickVoice(); }}
        }})();
        </script>
        """,
        height=0
    )


# =========================
# PROMPTS (brief, in-character)
# =========================
ALI_SYS = """You are Aliye, a 40-year-old female with severe Major Depressive Disorder.
Speak briefly (1-3 sentences). Slow, withdrawn, hopeless tone. Avoid medical advice or methods."""
FERIDE_SYS = """You are Feride, a 25-year-old female with paranoid-type schizophrenia.
Speak briefly (1-3 sentences), sometimes guarded or tangential. Avoid medical advice or methods."""


# =========================
# UI
# =========================
def set_background():
    uri = image_to_base64_uri("bck.jpg")
    if not uri:
        # try fallback folder if later moved
        uri = image_to_base64_uri("images/bck.jpg")
    if uri:
        st.markdown(
            f"""
            <style>
            .stApp {{
                background-image: url("{uri}");
                background-size: cover; background-position: center;
                background-repeat: no-repeat; background-attachment: fixed;
            }}
            </style>
            """,
            unsafe_allow_html=True
        )

def patient_card(name: str, diag: str, photo_file: str, key_btn: str):
    col = st.container()
    with col:
        st.markdown(
            f"<div style='background:rgba(255,255,255,0.92);padding:14px;border-radius:12px;border:1px solid #e5e7eb;'>"
            f"<h3 style='margin:0;color:#111827;'>{name}</h3>"
            f"<p style='margin:4px 0 10px;color:#6b7280;'>{diag}</p>"
            f"</div>", unsafe_allow_html=True
        )
        show_img(photo_file, use_container_width=True)
        st.button(f"Select {name}", key=key_btn, use_container_width=True)


def app():
    set_background()

    st.markdown(
        "<div style='padding:14px;border-radius:12px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;'>"
        "<h2 style='margin:0'>Psychiatric Interview Simulation</h2>"
        "<p style='margin:6px 0 0'>Short, web-safe demo with client-side TTS and optional Gemini.</p>"
        "</div>", unsafe_allow_html=True
    )

    if "persona" not in st.session_state:
        st.session_state.persona = None
    if "chat" not in st.session_state:
        st.session_state.chat = []  # list of (role, text, ts)

    with st.sidebar:
        st.markdown("### Settings")
        tts_on = st.checkbox("Enable patient voice (browser TTS)", value=True)
        gender = st.selectbox("Voice gender", ["female", "male"], index=0)
        accent = st.selectbox("Accent", ["en-US", "en-GB"], index=0)
        rate = st.slider("Rate", 0.5, 1.5, 1.0, 0.05)
        pitch = st.slider("Pitch", 0.5, 1.5, 1.0, 0.05)
        st.markdown("---")
        st.caption(f"Gemini: {'ON' if GENAI_OK else 'OFF'} (set GOOGLE_API_KEY)")

    # Patient chooser
    if not st.session_state.persona:
        c1, c2 = st.columns(2)
        with c1:
            patient_card("Aliye Seker", "Major Depressive Disorder (MDD)", "aliye.jpg", "pick_ali")
        with c2:
            patient_card("Feride Deniz", "Paranoid-type Schizophrenia", "feride.jpg", "pick_fer")

        if st.session_state.get("pick_ali"):
            st.session_state.persona = "ALIYE"
        if st.session_state.get("pick_fer"):
            st.session_state.persona = "FERIDE"
        st.stop()

    # Persona banner
    name = "Aliye Seker" if st.session_state.persona == "ALIYE" else "Feride Deniz"
    diag = "MDD" if st.session_state.persona == "ALIYE" else "Schizophrenia (paranoid)"
    st.markdown(
        f"<div style='margin-top:12px;background:rgba(255,255,255,0.95);padding:12px;border-radius:12px;border:1px solid #e5e7eb;'>"
        f"<strong>Patient:</strong> {name} &nbsp; | &nbsp; <strong>Diagnosis:</strong> {diag}"
        f"</div>", unsafe_allow_html=True
    )

    # Chat history
    for role, text, ts in st.session_state.chat:
        if role == "You":
            st.markdown(
                f"<div style='background:#e3f2fd;padding:10px;border-radius:10px;margin:6px 0;'>"
                f"<strong>You</strong><br>{text}<br>"
                f"<span style='color:gray;font-size:12px;'>{ts}</span></div>",
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"<div style='background:#f3e5f5;padding:10px;border-radius:10px;margin:6px 0;'>"
                f"<strong>{name}</strong><br>{text}<br>"
                f"<span style='color:gray;font-size:12px;'>{ts}</span></div>",
                unsafe_allow_html=True
            )

    # Input row
    col_in, col_btn = st.columns([5,1])
    with col_in:
        q = st.text_input("Type your question:", key="user_q")
    with col_btn:
        send = st.button("Send", type="primary", use_container_width=True)

    # Process turn
    if send and q.strip():
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        st.session_state.chat.append(("You", q.strip(), ts))

        # 1) DB match
        qa = ALI_QA if st.session_state.persona == "ALIYE" else FERIDE_QA
        resp = simple_match(q, qa)

        # 2) LLM fallback (optional)
        if not resp:
            sys = ALI_SYS if st.session_state.persona == "ALIYE" else FERIDE_SYS
            resp = llm_reply(sys, q) if GENAI_OK else ""

        # 3) final fallback
        if not resp:
            resp = "I’m not sure. Could you ask me in another way?"

        ts2 = datetime.datetime.now().strftime("%H:%M:%S")
        st.session_state.chat.append(("Patient", resp, ts2))
        st.rerun()

    # Speak last patient turn
    if st.session_state.chat and tts_on:
        # find last patient message
        for role, text, ts in reversed(st.session_state.chat):
            if role == "Patient":
                speak_client(text, rate=rate, pitch=pitch, gender=gender, accent=accent)
                break

    # Footer
    st.markdown(
        "<div style='margin-top:22px;background:#fff;padding:12px;border-radius:10px;border:1px solid #eee;text-align:center;'>"
        "<strong>by Dr. Volkan OBAN</strong> · 2025</div>",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    app()

