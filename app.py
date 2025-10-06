from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
import os
import csv
import requests
from io import StringIO

app = Flask(__name__)

# --- Environment variables (configure these in Render) ---
ACCOUNT_SID = os.environ.get("ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")
FROM_NUMBER = os.environ.get("FROM_NUMBER")                # e.g., +19025551234
STUDIO_FLOW_SID = os.environ.get("STUDIO_FLOW_SID")        # e.g., FWxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BASE_URL = os.environ.get("PUBLIC_BASE_URL")               # e.g., https://ivr-mini-script.onrender.com
STATUS_CALLBACK_URL = os.environ.get("STATUS_CALLBACK_URL")# Google Apps Script /exec URL for call status
# Optional: secret to include when posting to Google Apps Script
SHEETS_SECRET = os.environ.get("SHEETS_SECRET", "")        # leave blank if not using secret

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# Utility: post a small form payload to Google Apps Script
def log_to_sheets(payload: dict):
    try:
        if not STATUS_CALLBACK_URL:
            return
        # add secret if configured
        if SHEETS_SECRET:
            payload = {**payload, "secret": SHEETS_SECRET}
        # Twilio-style form post
        requests.post(STATUS_CALLBACK_URL, data=payload, timeout=8)
    except Exception as e:
        # don't crash the call flow on logging issues; just print
        print(f"[SheetsLog] Error posting to Google Sheets: {e}")

# 1) Launch outbound calls from a CSV URL
@app.route('/start-calls', methods=['POST'])
def start_calls():
    data = request.get_json(silent=True) or {}
    csv_url = data.get("csv_url")
    if not csv_url:
        return jsonify({"error": "csv_url is required"}), 400

    try:
        resp = requests.get(csv_url, timeout=20)
        resp.raise_for_status()
        reader = csv.DictReader(StringIO(resp.text))

        results = []
        for row in reader:
            to_number = (row.get('phone_number') or "").strip()
            if not to_number:
                continue

            call = client.calls.create(
                to=to_number,
                from_=FROM_NUMBER,
                url=f'{BASE_URL}/initial-twiml',             # park silently while AMD runs
                machine_detection='DetectMessageEnd',
                async_amd=True,
                async_amd_status_callback=f'{BASE_URL}/amd-handler',
                async_amd_status_callback_method='POST',
                # Final call status → sent straight to Google Sheets
                status_callback=STATUS_CALLBACK_URL,
                status_callback_method='POST',
                status_callback_event=['completed']          # add 'initiated','ringing','answered' if desired
            )

            results.append({"to": to_number, "sid": call.sid})

        return jsonify({"calls_started": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# 2) Silent parking TwiML while AMD runs (prevents audio leaking into VM greeting)
@app.route('/initial-twiml', methods=['GET', 'POST'])
def initial_twiml():
    vr = VoiceResponse()
    vr.pause(length=60)  # plenty of time for DetectMessageEnd
    return str(vr), 200, {'Content-Type': 'text/xml'}


# 3) AMD callback: log the AMD verdict to Sheets; hang up machines; redirect humans into Studio
@app.route('/amd-handler', methods=['POST'])
def amd_handler():
    answered_by = (request.form.get('AnsweredBy') or "").lower()
    call_sid = request.form.get('CallSid') or ""
    to_number = request.form.get('To') or ""
    from_number = request.form.get('From') or ""

    print(f"[AMD] SID={call_sid} To={to_number} From={from_number} AnsweredBy={answered_by}")

    # Log the AMD verdict immediately to Sheets (so “Completed” won’t hide machine outcomes)
    log_to_sheets({
        "Event": "amd",
        "CallSid": call_sid,
        "To": to_number,
        "From": from_number,
        "CallStatus": "in-progress",
        "AnsweredBy": answered_by
    })

    vr = VoiceResponse()

    MACHINE_VALUES = {
        'machine', 'machine_start', 'machine_end_beep', 'machine_end_silence',
        'fax', 'sit', 'unknown'  # 'unknown' treated conservatively as machine
    }

    if answered_by in MACHINE_VALUES:
        # Voicemail / non-human → hang up and log a definitive outcome
        vr.hangup()
        log_to_sheets({
            "Event": "hangup_on_machine",
            "CallSid": call_sid,
            "To": to_number,
            "From": from_number,
            "CallStatus": "completed",      # Twilio will still mark 'completed'
            "AnsweredBy": answered_by
        })
    else:
        # Human → redirect into Studio Flow (Incoming Call trigger)
        # Pass orig_call_sid so Studio can include it in final survey logging
        vr.redirect(
            f'https://webhooks.twilio.com/v1/Accounts/{ACCOUNT_SID}/Flows/{STUDIO_FLOW_SID}'
            f'?orig_call_sid={call_sid}'
        )

    return str(vr), 200, {'Content-Type': 'text/xml'}


# Health check
@app.route('/', methods=['GET'])
def index():
    return "IVR caller app running", 200
