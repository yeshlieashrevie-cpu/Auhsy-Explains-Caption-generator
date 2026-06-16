import streamlit as st
import google.generativeai as genai
import base64
import json
import os
import proglog
import subprocess

# --- CONFIGURATION ---
st.set_page_config(page_title="Caption Creator", layout="wide")

# --- API KEY CONFIGURATION ---
if "GEMINI_API_KEY" in st.secrets:
    API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    st.error("Please configure your GEMINI_API_KEY in the Streamlit Secrets.")
    st.stop()

genai.configure(api_key=API_KEY)

# --- HELPER FUNCTIONS ---
def get_base64_font(font_path):
    """Encodes the OTF font to base64 to inject into HTML/CSS."""
    with open(font_path, "rb") as font_file:
        encoded_string = base64.b64encode(font_file.read()).decode()
    return f"data:font/otf;base64,{encoded_string}"


class StreamlitProgressLogger(proglog.ProgressBarLogger):
    """Custom logger to pipe moviepy extraction percentages directly to Streamlit safely."""
    def __init__(self, st_progress_bar, st_text_widget):
        super().__init__()
        self.st_bar = st_progress_bar
        self.st_text = st_text_widget

    def callback(self, **kwargs):
        try:
            if self.state.get('bars'):
                for bar_name, bar_data in self.state['bars'].items():
                    if bar_data['total'] > 0:
                        percentage = int((bar_data['index'] / bar_data['total']) * 100)
                        self.st_bar.progress(bar_data['index'] / bar_data['total'])
                        self.st_text.markdown(f"**Stage 1/2:** Extracting audio track... **{percentage}%**")
        except Exception:
            pass  # Protect against background thread context sync issues


def transcribe_with_gemini(video_file_path, progress_bar, status_text):
    """
    Extracts audio with a live percentage tracker, 
    then uploads and monitors Gemini's transcription progress.
    """
    model = genai.GenerativeModel("models/gemini-1.5-flash")
    audio_temp_path = "temp_audio.mp3"
    
    try:
        status_text.markdown("**Stage 1/2:** Analyzing video frames...")
        from moviepy.editor import VideoFileClip
        
        custom_logger = StreamlitProgressLogger(progress_bar, status_text)
        
        video_clip = VideoFileClip(video_file_path)
        video_clip.audio.write_audiofile(audio_temp_path, logger=custom_logger)
        video_clip.close()
        
        progress_bar.progress(0.0)
        status_text.markdown("**Stage 2/2:** Beaming audio to Gemini API (0%)...")
        
        media_file = genai.upload_file(path=audio_temp_path)
        
        progress_bar.progress(0.50)
        status_text.markdown("**Stage 2/2:** Gemini is listening and building JSON timestamps (50%)...")
        
    except Exception as audio_err:
        status_text.warning("Fast audio extraction failed. Uploading the full video instead...")
        media_file = genai.upload_file(path=video_file_path)
    
    prompt = """
    Listen to this audio and provide a word-by-word transcription. 
    You MUST output ONLY a valid JSON array of objects. 
    Each object must have exactly three keys: "word" (the spoken word), "start" (start time in seconds as a float), and "end" (end time in seconds as a float).
    Example: [{"word": "Hello", "start": 0.0, "end": 0.5}, {"word": "world", "start": 0.5, "end": 1.0}]
    Do not include markdown blocks, just the raw JSON array.
    """
    
    try:
        response = model.generate_content([media_file, prompt])
        progress_bar.progress(1.0)
        status_text.markdown("**Success!** Parsing generated timestamps... (100%)")
    except Exception as api_err:
        st.error(f"Gemini API Error: {str(api_err)}")
        return []
    
    if os.path.exists(audio_temp_path):
        try:
            os.remove(audio_temp_path)
        except Exception:
            pass
            
    try:
        cleaned_json = response.text.replace('```json', '').replace('```', '').strip()
        words_data = json.loads(cleaned_json)
        return words_data
    except Exception as e:
        st.error(f"Failed to parse JSON from Gemini. Raw output: {response.text}")
        return []


# --- UI LAYOUT ---
st.title("🎬 Dynamic Caption Editor")

# Sidebar for uploads
with st.sidebar:
    st.header("Upload Media")
    uploaded_video = st.file_uploader("Upload Video (MP4)", type=["mp4"], max_upload_size=1024)
    font_path = "for captions.otf"

if uploaded_video:
    # Setup directory for static file serving
    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    video_static_path = os.path.join(static_dir, "preview_video.mp4")
    
    # MEMORY OPTIMIZATION: Stream upload to disk in chunks instead of reading all into RAM at once
    if 'file_saved' not in st.session_state or st.session_state.get('last_uploaded_name') != uploaded_video.name:
        with st.spinner("Saving video to server disk safely..."):
            with open(video_static_path, "wb") as f:
                while chunk := uploaded_video.read(10 * 1024 * 1024):  # Read in 10MB increments
                    f.write(chunk)
            st.session_state.file_saved = True
            st.session_state.last_uploaded_name = uploaded_video.name

    if "words_data" not in st.session_state:
        st.session_state.words_data = []

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("1. Generate & Edit Captions")
        if st.button("Generate Captions via Gemini"):
            status_text = st.empty()
            progress_bar = st.progress(0.0)
            
            st.session_state.words_data = transcribe_with_gemini(video_static_path, progress_bar, status_text)
            
            status_text.empty()
            progress_bar.empty()
            if st.session_state.words_data:
                st.success("🎉 Transcription complete!")

        if st.session_state.words_data:
            st.session_state.words_data = st.data_editor(
                st.session_state.words_data,
                num_rows="dynamic",
                use_container_width=True
            )

    with col2:
        st.subheader("2. Video Preview")
        if st.session_state.words_data and os.path.exists(font_path):
            
            # Resolve absolute server URL so the isolated component iframe can access it
            host_domain = st.context.headers.get("host", "localhost:8501")
            protocol = "https" if "streamlit.app" in host_domain else "http"
            video_streaming_url = f"{protocol}://{host_domain}/static/preview_video.mp4"
            
            b64_font = get_base64_font(font_path)
            words_json = json.dumps(st.session_state.words_data)
            
            # --- CUSTOM HTML/JS/CSS PLAYER ---
            html_code = f"""
            <!DOCTYPE html>
            <html>
            <head>
            <style>
                @font-face {{
                    font-family: 'CustomCaptionFont';
                    src: url('{b64_font}') format('opentype');
                }}
                body {{
                    margin: 0; padding: 0; background: #0e1117; display: flex; justify-content: center;
                }}
                #video-container {{
                    position: relative;
                    width: 100%;
                    max-width: 400px;
                    border-radius: 10px;
                    overflow: hidden;
                }}
                video {{
                    width: 100%;
                    display: block;
                }}
                #caption-box {{
                    position: absolute;
                    bottom: 20%;
                    left: 10%;
                    width: 80%;
                    cursor: move;
                    text-align: center;
                    white-space: nowrap;
                    overflow: hidden; 
                    resize: horizontal;
                    padding: 10px;
                    box-sizing: border-box;
                    border: 1px dashed rgba(255,255,255,0.3);
                }}
                .word {{
                    font-family: 'CustomCaptionFont', sans-serif;
                    font-size: 24px;
                    color: #B57EDC;
                    text-shadow: 2px 2px 8px rgba(0, 0, 0, 0.9);
                    margin: 0 4px;
                    transition: all 0.1s ease-in-out;
                    display: inline-block;
                }}
                .word.active {{
                    color: #CFFF04;
                    font-size: 32px;
                    transform: scale(1.1);
                }}
            </style>
            </head>
            <body>

            <div id="video-container">
                <video id="vid" controls src="{video_streaming_url}"></video>
                <div id="caption-box"></div>
            </div>

            <script>
                const wordsData = {words_json};
                const video = document.getElementById('vid');
                const captionBox = document.getElementById('caption-box');
                
                let isDragging = false;
                let offsetX, offsetY;

                captionBox.addEventListener('mousedown', (e) => {{
                    if (e.offsetX > captionBox.clientWidth - 20) return; 
                    isDragging = true;
                    offsetX = e.clientX - captionBox.getBoundingClientRect().left;
                    offsetY = e.clientY - captionBox.getBoundingClientRect().top;
                }});

                document.addEventListener('mousemove', (e) => {{
                    if (!isDragging) return;
                    const containerRect = document.getElementById('video-container').getBoundingClientRect();
                    let newLeft = e.clientX - containerRect.left - offsetX;
                    let newTop = e.clientY - containerRect.top - offsetY;
                    
                    captionBox.style.left = newLeft + 'px';
                    captionBox.style.top = newTop + 'px';
                    captionBox.style.bottom = 'auto';
                }});

                document.addEventListener('mouseup', () => {{ isDragging = false; }});

                video.addEventListener('timeupdate', () => {{
                    const currentTime = video.currentTime;
                    let htmlContent = '';
                    
                    let activeIndex = wordsData.findIndex(w => currentTime >= w.start && currentTime <= w.end);
                    
                    if(activeIndex !== -1) {{
                        let startIdx = Math.max(0, activeIndex - 2);
                        let endIdx = Math.min(wordsData.length, activeIndex + 3);
                        
                        for (let i = startIdx; i < endIdx; i++) {{
                            let w = wordsData[i];
                            let isActive = (i === activeIndex) ? 'active' : '';
                            htmlContent += `<span class="word ${{isActive}}">${{w.word}}</span>`;
                        }}
                    }}
                    captionBox.innerHTML = htmlContent;
                }});
            </script>
            </body>
            </html>
            """
            st.components.v1.html(html_code, height=600)
else:
    st.info("Please upload a video to get started💫🌟💫.")
