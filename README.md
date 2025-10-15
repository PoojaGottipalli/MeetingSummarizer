# Gemini Audio Transcription (Flask)

Simple Flask app that uploads an audio file, sends it to Google Gemini (GenAI) using the Python SDK, and returns a transcript on the same page.

Requirements
- Python 3.9+
- A Google GenAI API key set up according to the `google-genai` package instructions.

Setup (PowerShell)

```powershell
# create and activate venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# install deps
pip install -r requirements.txt

# set env vars
$env:GOOGLE_API_KEY = 'API'
# optional flask secret
$env:FLASK_SECRET = 'a-secret-for-flash'

# run
python app.py
```

Notes
- The app uses `google.genai.Client()` as shown in the example. Make sure your environment is configured so the client can authenticate (API key or ADC depending on the genai SDK).
- If you need streaming or partial results, the SDK and model may provide different endpoints—this example uses a simple generate_content call.