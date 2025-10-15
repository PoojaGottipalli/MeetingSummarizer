import os
import sqlite3
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename

# Import the Google GenAI client
from google import genai

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'flac', 'ogg'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', 'dev-secret')

# SQLite DB for meeting records
DB_PATH = os.path.join(os.path.dirname(__file__), 'meetings.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        attendees TEXT,
        transcript TEXT,
        summary TEXT,
        people TEXT,
        action_items TEXT,
        created_at TEXT
    )
    ''')
    conn.commit()
    conn.close()

init_db()
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def transcribe_with_gemini(filepath):
    client = genai.Client()
    uploaded = client.files.upload(file=filepath)
    prompt = "Generate a verbatim transcript of the audio."

    resp = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, uploaded]
    )

    text = getattr(resp, 'text', None) or str(resp)
    return text


def summarize_with_gemini(text, max_points: int = 5):
    client = genai.Client()
    prompt = (
        f"You are given a transcript. Produce at most {max_points} concise bullet points. Plain text only."
    )

    resp = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt, text]
    )

    summary = getattr(resp, 'text', None) or str(resp)

    # Simplify: just take first max_points lines
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    bullets = lines[:max_points]

    return '\n'.join(bullets)


def summarize_meeting_with_tags(text, attendees: str = '', max_points: int = 6):
    client = genai.Client()
    attendees_list = [a.strip() for a in attendees.split(',') if a.strip()]
    prompt = (
        f"Given a transcript, return plain text sections:\n"
        f"SUMMARY: up to {max_points} bullet points\n"
        f"PEOPLE: list attendees and mentioned people\n"
        f"ACTION_ITEMS: list clear action items\n"
        f"Use plain text only, with headers: SUMMARY:, PEOPLE:, ACTION_ITEMS:"
    )

    resp = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt + "\nATTENDEES: " + ', '.join(attendees_list) + "\nTRANSCRIPT:\n" + text]
    )

    out = getattr(resp, 'text', None) or str(resp)

    def extract_section(blob, header):
        idx = blob.find(header)
        if idx == -1:
            return None
        rest = blob[idx + len(header):]
        for h in ('SUMMARY:', 'PEOPLE:', 'ACTION_ITEMS:'):
            if h != header and h in rest:
                rest = rest[:rest.find(h)]
        return rest.strip()

    summary = extract_section(out, 'SUMMARY:') or summarize_with_gemini(text)
    people_text = extract_section(out, 'PEOPLE:')
    action_items_text = extract_section(out, 'ACTION_ITEMS:')

    return summary, people_text, action_items_text


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    if 'audio' not in request.files:
        flash('No file part')
        return redirect(url_for('index'))

    file = request.files['audio']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('index'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        try:
            transcript = transcribe_with_gemini(save_path)
        except Exception as e:
            flash(f'Error during transcription: {e}')
            return redirect(url_for('index'))

        attendees = request.form.get('attendees', '')
        try:
            summary, people, action_items = summarize_meeting_with_tags(transcript, attendees)
        except Exception:
            summary, people, action_items = (None, None, None)

        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO meetings (filename, attendees, transcript, summary, people, action_items, created_at) VALUES (?,?,?,?,?,?,?)',
                (filename, attendees, transcript, summary, people, action_items, datetime.utcnow().isoformat()),
            )
            meeting_id = cur.lastrowid
            conn.commit()
            conn.close()
            return redirect(url_for('view_meeting', meeting_id=meeting_id))
        except Exception:
            return render_template('index.html', transcript=transcript, summary=summary, people=people, action_items=action_items)
    else:
        flash('Unsupported file type')
        return redirect(url_for('index'))


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/meetings')
def list_meetings():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, filename, attendees, created_at FROM meetings ORDER BY id DESC')
    rows = cur.fetchall()
    conn.close()
    meetings = [{'id': r[0], 'filename': r[1], 'attendees': r[2], 'created_at': r[3]} for r in rows]
    return render_template('meetings.html', meetings=meetings)


@app.route('/meetings/<int:meeting_id>')
def view_meeting(meeting_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT id, filename, attendees, transcript, summary, people, action_items, created_at FROM meetings WHERE id = ?', (meeting_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        flash('Meeting not found')
        return redirect(url_for('list_meetings'))
    meeting = {
        'id': row[0], 'filename': row[1], 'attendees': row[2],
        'transcript': row[3], 'summary': row[4], 'people': row[5],
        'action_items': row[6], 'created_at': row[7]
    }
    return render_template('view_meeting.html', meeting=meeting)


@app.route('/meetings/<int:meeting_id>/download_transcript')
def download_transcript(meeting_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT transcript FROM meetings WHERE id = ?', (meeting_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        flash('Meeting not found')
        return redirect(url_for('list_meetings'))
    return (row[0] or '', 200, {
        'Content-Type': 'text/plain; charset=utf-8',
        'Content-Disposition': f'attachment; filename="transcript_{meeting_id}.txt"'
    })


@app.route('/meetings/<int:meeting_id>/download_actions')
def download_actions(meeting_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT action_items FROM meetings WHERE id = ?', (meeting_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        flash('Meeting not found')
        return redirect(url_for('list_meetings'))
    return (row[0] or '', 200, {
        'Content-Type': 'text/plain; charset=utf-8',
        'Content-Disposition': f'attachment; filename="actions_{meeting_id}.txt"'
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)