import streamlit as st
import google.generativeai as genai
import base64
import json  
import os    

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

def get_base64_video(video_bytes, mime_type="video/mp4"):
    """Encodes video bytes to play in the custom HTML player."""
    encoded_string = base64.b64encode(video_bytes).decode()
    return f"data:{mime_type};base64,{encoded_string}"

def transcribe_with_gemini(video_file_path):
    """
    Extracts a lightweight audio file from the heavy video, 
    and sends ONLY the audio to Gemini for lightning-fast processing.
    """
    model = genai.GenerativeModel("models/gemini-1.5-flash")
    audio_temp_path = "temp_audio.mp3"
    
    try:
        # Extract audio from video using moviepy (saves massive bandwidth)
        from moviepy.editor import VideoFileClip
        video_clip = VideoFileClip(video_file_path)
        video_clip.audio.write_audiofile(audio_temp_path, logger=None)
        video_clip.close()
        
        # Upload ONLY the tiny audio file to Gemini's API
        media_file = genai.upload_file(path=audio_temp_path)
    except Exception as audio_err:
        st.warning("Fast audio extraction failed. Falling back to uploading the full video (this will take longer)...")
        # Fallback to uploading the whole video if moviepy hits an unexpected glitch
        media_file = genai.upload_file(path=video_file_path)
    
    prompt = """
    Listen to this audio and provide a word-by-word transcription. 
    You MUST output ONLY a valid JSON array of objects. 
    Each object must have exactly three keys: "word" (the spoken word), "start" (start time in seconds as a float), and "end" (end time in seconds as a float).
    Example: [{"word": "Hello", "start": 0.0, "end": 0.5}, {"word": "world", "start": 0.5, "end": 1.0}]
    Do not include markdown blocks, just the raw JSON array.
    """
    
    response = model.generate_content([media_file, prompt])
    
    # Clean up the temporary audio file from the server
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
    # Increases the limit for this specific uploader to 1GB (1024MB)
    uploaded_video = st.file_uploader("Upload Video (MP4)", type=["mp4"], max_upload_size=1024)
    # Note: For this demo, we assume 'for captions.otf' is in the same folder.
    font_path = "for captions.otf"

if uploaded_video:
    video_bytes = uploaded_video.read()
    
    if "words_data" not in st.session_state:
        st.session_state.words_data = []

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("1. Generate & Edit Captions")
        if st.button("Generate Captions via Gemini"):
            with st.spinner("Analyzing audio..."):
                # Save temp file for Gemini API
                temp_path = "temp_video.mp4"
                with open(temp_path, "wb") as f:
                    f.write(video_bytes)
                
                # Call Gemini
                st.session_state.words_data = transcribe_with_gemini(temp_path)
                try:
                    os.remove(temp_path) # Clean up
                except Exception:
                    pass
                st.success("Transcription complete!")

        # Allow user to manually edit words and timestamps
        if st.session_state.words_data:
            st.session_state.words_data = st.data_editor(
                st.session_state.words_data,
                num_rows="dynamic",
                use_container_width=True
            )

    with col2:
        st.subheader("2. Video Preview")
        if st.session_state.words_data and os.path.exists(font_path):
            
            # Prepare data for HTML injection
            b64_font = get_base64_font(font_path)
            b64_video = get_base64_video(video_bytes)
            words_json = json.dumps(st.session_state.words_data)
            
            # --- CUSTOM HTML/JS/CSS PLAYER ---
            # This handles the custom font, 2 colors, dark glow, and draggable boundaries
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
                    max-width: 400px; /* Mobile aspect ratio simulation */
                    border-radius: 10px;
                    overflow: hidden;
                }}
                video {{
                    width: 100%;
                    display: block;
                }}
                /* Draggable and Resizable Caption Box */
                #caption-box {{
                    position: absolute;
                    bottom: 20%;
                    left: 10%;
                    width: 80%;
                    cursor: move;
                    text-align: center;
                    /* Hide excess words */
                    white-space: nowrap;
                    overflow: hidden; 
                    resize: horizontal;
                    padding: 10px;
                    box-sizing: border-box;
                    border: 1px dashed rgba(255,255,255,0.3); /* Visual guide for resizing */
                }}
                .word {{
                    font-family: 'CustomCaptionFont', sans-serif;
                    font-size: 24px;
                    color: #B57EDC; /* Base Color */
                    text-shadow: 2px 2px 8px rgba(0, 0, 0, 0.9); /* Dark Glow */
                    margin: 0 4px;
                    transition: all 0.1s ease-in-out;
                    display: inline-block;
                }}
                .word.active {{
                    color: #CFFF04; /* Spoken Word Color */
                    font-size: 32px; /* Larger Size */
                    transform: scale(1.1);
                }}
            </style>
            </head>
            <body>

            <div id="video-container">
                <video id="vid" controls src="{b64_video}"></video>
                <div id="caption-box"></div>
            </div>

            <script>
                const wordsData = {words_json};
                const video = document.getElementById('vid');
                const captionBox = document.getElementById('caption-box');
                
                // Dragging Logic
                let isDragging = false;
                let offsetX, offsetY;

                captionBox.addEventListener('mousedown', (e) => {{
                    // Prevent dragging if resizing from the right edge
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

                // Caption Syncing Logic
                video.addEventListener('timeupdate', () => {{
                    const currentTime = video.currentTime;
                    let htmlContent = '';
                    
                    // Define a window to keep it 1-line length (e.g., showing 5 words total)
                    let activeIndex = wordsData.findIndex(w => currentTime >= w.start && currentTime <= w.end);
                    
                    if(activeIndex !== -1) {{
                        // Create a sliding window to hide excess words
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
    st.info("Please upload a video to get started.")
