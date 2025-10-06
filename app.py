from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
import os
import csv
import requests
from io import StringIO

app = Flask(__name__)

# Load environment variables
ACCOUNT_SID = os.environ.get("ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")
FROM_NUMBER = os.environ.get("FROM_NUMBER")  
STUDIO_FLOW_SID = os.environ.get("STUDIO_FLOW_SID")  # Your Twilio Studio Flow SID
BASE_URL = os.environ.get("PUBLIC_BASE_URL")  

client = Client(ACCOUNT_SID, AUTH_TOKEN)

# ✅ 1. Start Calls from CSV
@app.route('/start-calls', methods=['POST'])
def start_calls():
    data = request.get_json()
    csv_url = data.get("csv_url")

    if not csv_url:
        return jsonify({"error": "csv_url is required"}), 400

    try:
        response = requests.get(csv_url)
        csv_file = StringIO(response.text)
        reader = csv.DictReader(csv_file)

        results = []
        for row in reader:
            to_number = row.get('phone_number')
            if not to_number:
                continue

            call = client.calls.create(
                to=to_number,
                from_=FROM_NUMBER,
                url=f'{BASE_URL}/initial-twiml',
                machine_detection='DetectMessageEnd',
                async_amd=True,
                async_amd_status_callback=f'{BASE_URL}/amd-handler'
            )

            results.append({
                "to": to_number,
                "sid": call.sid
            })

        return jsonify({"calls_started": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ✅ 2. Provide a Silent TwiML Response while AMD runs
@app.route('/initial-twiml', methods=['GET', 'POST'])
def initial_twiml():
    response = VoiceResponse()
    response.pause(length=60)
    return str(response), 200, {'Content-Type': 'text/xml'}

# ✅ 3. Handle AMD Callback from Twilio
@app.route('/amd-handler', methods=['POST'])
def amd_handler():
    answered_by = request.form.get('AnsweredBy')
    call_sid = request.form.get('CallSid')
    to_number = request.form.get('To')

    print(f"[AMD] Call SID: {call_sid}, To: {to_number}, Answered By: {answered_by}")

    response = VoiceResponse()

    if answered_by in ['machine_start', 'machine_end_beep']:
        print("→ Voicemail detected. Hanging up.")
        response.hangup()
    else:
        print("→ Human detected. Redirecting to Studio Flow.")
        response.redirect(
            f'https://webhooks.twilio.com/v1/Accounts/{ACCOUNT_SID}/Flows/{STUDIO_FLOW_SID}?FlowEvent=trigger'
        )

    return str(response), 200, {'Content-Type': 'text/xml'}

# Optional health check route
@app.route('/', methods=['GET'])
def index():
    return "IVR caller app running", 200
