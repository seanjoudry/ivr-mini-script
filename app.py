from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
import os
import csv
import requests
from io import StringIO

app = Flask(__name__)

# --- Environment variables (set these in Render) ---
ACCOUNT_SID = os.environ.get("ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")
FROM_NUMBER = os.environ.get("FROM_NUMBER")                # e.g., +19025551234
STUDIO_FLOW_SID = os.environ.get("STUDIO_FLOW_SID")        # e.g., FWxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BASE_URL = os.environ.get("PUBLIC_BASE_URL")               # e.g., https://ivr-mini-script.onrender.com or your custom domain
STATUS_CALLBACK_URL = os.environ.get("STATUS_CALLBACK_URL")# e.g., https://script.google.com/macros/s/.../exec

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# 1) Launch outbound calls from a CSV URL
@app.route('/start-calls', methods=['POST'])
def start_calls():
    data = request.get_json(silent=True) or {}
    csv_url = data.get("csv_url")
    if not csv_url:
        return jsonify({"error": "csv_url is required"}), 400

    try:
        resp = requests.get(csv_url)
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
                # Log call outcomes directly to Google Apps Script (no server load)
                status_callback=STATUS_CALLBACK_URL,
                status_callback_method='POST',
                status_callback_event=['completed']          # add 'initiated','ringing','answered' if you want more telemetry
            )

            results.append({"to": to_number, "sid": call.sid})

        return jsonify({"calls_started": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# 2) Silent parking TwiML while AMD runs (prevents leaking audio into greetings)
@app.route('/initial-twiml', methods=['GET', 'POST'])
def initial_twiml():
    vr = VoiceResponse()
    vr.pause(length=60)  # plenty of time for DetectMessageEnd
    return str(vr), 200, {'Content-Type': 'text/xml'}


# 3) AMD callback: hang up on machines; redirect humans into Studio Flow
@app.route('/amd-handler', methods=['POST'])
def amd_handler():
    answered_by = request.form.get('AnsweredBy')  # 'human', 'machine_start', 'machine_end_beep', etc.
    call_sid = request.form.get('CallSid')

    vr = VoiceResponse()
    if answered_by in ('machine_start', 'machine_end_beep'):
        # Voicemail detected → hang up (no message left)
        vr.hangup()
    else:
        # Human detected → redirect to Studio Flow; pass orig_call_sid for downstream logging
        vr.redirect(
            f'https://webhooks.twilio.com/v1/Accounts/{ACCOUNT_SID}/Flows/{STUDIO_FLOW_SID}'
            f'?FlowEvent=trigger&orig_call_sid={call_sid}'
        )
    return str(vr), 200, {'Content-Type': 'text/xml'}


# Health check
@app.route('/', methods=['GET'])
def index():
    return "IVR caller app running", 200
