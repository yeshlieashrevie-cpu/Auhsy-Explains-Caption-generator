import os
import io
import time
import requests
import streamlit as st
from deepgram import DeepgramClient, PrerecordedOptions
from dotenv import load_dotenv

# Load local environment variables if present
load_dotenv()

# ==========================================
# 1. INITIAL SYSTEM CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="AI Meeting Assistant & Minutes Generator",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Fetch secure credentials safely
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY") or st.secrets.get("DEEPGRAM_API_KEY")

# ==========================================
# 2. CORE UTILITY & API FUNCTIONS
# ==========================================

def transcribe_audio_deepgram(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    """
    Sends raw audio bytes to the Deepgram Nova-3 API for highly precise,
    diarized, and fast transcription.
    """
    if not DEEPGRAM_API_KEY:
        st.error("❌ Deepgram API Key is missing. Please check your environment variables or secrets.")
        return ""
    
    url = "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&diarize=true"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": mime_type
    }
    
    try:
        response = requests.post(url, headers=headers, data=audio_bytes, timeout=120)
        response.raise_for_status()
        res_data = response.json()
        
        # Parse paragraphs or standard transcript chunks efficiently
        channels = res_data.get("results", {}).get("channels", [])
        if not channels:
            return "No transcript channels returned from Deepgram."
            
        alternatives = channels[0].get("alternatives", [])
        if not alternatives:
            return "No transcription alternatives found."
            
        # Prioritize pre-formatted paragraphs if available, fallback to raw transcript
        paragraphs_data = alternatives[0].get("paragraphs", {})
        paragraphs_list = paragraphs_data.get("paragraphs", [])
        
        if paragraphs_list:
            formatted_lines = []
            for p in paragraphs_list:
                speaker = f"Speaker {p.get('speaker', 0)}"
                sentences = [s.get("text", "") for s in p.get("sentences", [])]
                paragraph_text = " ".join(sentences)
                formatted_lines.append(f"**{speaker}**: {paragraph_text}")
            return "\n\n".join(formatted_lines)
        else:
            return alternatives[0].get("transcript", "Transcript field empty.")
            
    except requests.exceptions.RequestException as e:
        st.error(f"🔴 Deepgram API error encountered: {e}")
        return ""


def generate_meeting_minutes(transcript_text: str) -> str:
    """
    Uses OpenAI's GPT models to transform raw transcribed text into structured,
    executive-ready meeting minutes.
    """
    if not OPENAI_API_KEY:
        st.error("❌ OpenAI API Key is missing. Please check your environment variables or secrets.")
        return ""
        
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    system_prompt = (
        "You are an expert executive assistant. Analyze the provided meeting transcript "
        "and generate clean, comprehensive meeting minutes. Structure your response perfectly "
        "using the following Markdown sections:\n\n"
        "### 📌 Meeting Overview & Summary\n"
        "Provide a concise, high-level summary of what the meeting covered.\n\n"
        "### 📋 Key Discussion Points\n"
        "Bullet out main themes, insights shared, and arguments or perspectives brought up by speakers.\n\n"
        "### ⚡ Action Items & Ownership\n"
        "Explicitly list all actionable tasks, who is responsible for them (if named), and deadlines.\n\n"
        "### 📅 Next Steps & Decisions Made\n"
        "Highlight finalized organizational decisions and schedule updates for subsequent touchpoints."
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Here is the transcript:\n\n{transcript_text}"}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"🔴 OpenAI API error encountered: {e}")
        return ""

# ==========================================
# 3. STREAMLIT USER INTERFACE (UI)
# ==========================================

st.title("🎙️ AI Meeting Assistant & Executive Minutes Generator")
st.markdown(
    "Upload a recorded conversation or capture live input directly from your microphone. "
    "We use **Deepgram Nova-3** for lightning-fast, speaker-separated transcription and **OpenAI GPT-4o** "
    "to format your structured corporate summary instantly."
)

# Informative Sidebar Info & Diagnostics
with st.sidebar:
    st.header("⚙️ Configuration Diagnostics")
    
    # Check setup health status visually
    if OPENAI_API_KEY:
        st.success("🤖 OpenAI Key Detected")
    else:
        st.warning("⚠️ OpenAI Key Missing")
        
    if DEEPGRAM_API_KEY:
        st.success("⚡ Deepgram Key Detected")
    else:
        st.warning("⚠️ Deepgram Key Missing")
        
    st.markdown("---")
    st.markdown("### 💡 Best Practices")
    st.markdown(
        "1. For direct browser capture, speak clearly into your microphone.\n"
        "2. Multi-speaker uploads are automatically diarized into sequential conversation nodes."
    )

# Primary Tabs for capturing/uploading interaction data
tab_upload, tab_live = st.tabs(["📁 Upload Meeting Audio/Video", "🎤 Capture Live Dictation"])

raw_audio_bytes = None
detected_mime_type = "audio/wav"

# --- TAB 1: File Uploader ---
with tab_upload:
    uploaded_file = st.file_uploader(
        "Choose an existing meeting file (MP3, WAV, M4A, or MP4 video)",
        type=["mp3", "wav", "m4a", "mp4"]
    )
    if uploaded_file is not None:
        raw_audio_bytes = uploaded_file.read()
        detected_mime_type = uploaded_file.type
        st.audio(raw_audio_bytes, format=detected_mime_type)
        st.success(f"Successfully loaded '{uploaded_file.name}' into temporal processing state.")

# --- TAB 2: Live Browser Audio Capture ---
with tab_live:
    live_audio = st.audio_input("Record your meeting or live updates here")
    if live_audio is not None:
        raw_audio_bytes = live_audio.read()
        detected_mime_type = "audio/wav"
        st.success("Live browser audio fragment successfully locked.")

# --- PROCESSING ENGINE PIPELINE ---
if raw_audio_bytes is not None:
    st.markdown("---")
    if st.button("🚀 Process Conversation & Generate Artifacts", type="primary", use_container_width=True):
        
        # Processing Progress Spinners
        with st.status("Transforming speech to insights...", expanded=True) as status:
            
            st.write("🛰️ Dispatching binary payload safely to Deepgram Nova-3...")
            start_time = time.time()
            transcript_result = transcribe_audio_deepgram(raw_audio_bytes, detected_mime_type)
            
            if not transcript_result:
                status.update(label="Process halted due to transcription failures.", state="error")
                st.stop()
                
            st.write(f"✅ Transcription achieved cleanly in {time.time() - start_time:.2f} seconds.")
            st.write("🧠 Organizing summary layout with OpenAI GPT-4o...")
            
            minutes_result = generate_meeting_minutes(transcript_result)
            
            if not minutes_result:
                status.update(label="Process halted due to summarization failures.", state="error")
                st.stop()
                
            status.update(label="Analysis completed flawlessly!", state="complete")
            
        # Display side-by-side presentation columns for clean readability
        col_transcript, col_minutes = st.columns(2)
        
        with col_transcript:
            st.subheader("📝 Speaker Diarized Transcript")
            st.info("Raw multi-speaker map extracted via machine intelligence:")
            st.markdown(transcript_result)
            
            # Allow clean single-click archival of text artifacts
            st.download_button(
                label="📥 Download Raw Transcript (.txt)",
                data=transcript_result,
                file_name="meeting_transcript.txt",
                mime="text/plain"
            )
            
        with col_minutes:
            st.subheader("📋 Executive Executive Summary")
            st.success("Targeted corporate action steps and summary matrix:")
            st.markdown(minutes_result)
            
            st.download_button(
                label="📥 Download Meeting Minutes (.md)",
                data=minutes_result,
                file_name="meeting_minutes.md",
                mime="text/markdown"
            )
else:
    st.info("💡 Standby. Please upload a file or record audio above to unlock the processing pipeline.")
