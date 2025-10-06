from flask import Flask, request, jsonify
from twilio.rest import Client
import csv
import requests
from io import StringIO
import os

app = Flask(__name__)

# Environment variables (set these in Render dashboard)
ACCOUNT_SID = os.environ.get("ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")
FROM_NUMBER = os.environ.get("FROM_NUMBER")  # Your Twilio number
STUDIO_FLOW_SID = os.environ.get("STUDIO_FLOW_SID")

client = Client(ACCOUNT_SID, AUTH_TOKEN)

@app.route('/start-calls', methods=['POST'])
def start_calls():
    data = request.get_json()
    csv_url = data.get("csv_url")

    if not csv_url:
        return jsonify({"error": "csv_url is required"}), 400

    try:
        csv_response = requests.get(csv_url)
        csv_text = StringIO(csv_response.text)
        reader = csv.DictReader(csv_text)

        results = []
        for row in reader:
            to_number = row['phone_number']
            call = client.studio.flows(STUDIO_FLOW_SID).executions.create(
                to=to_number,
                from_=FROM_NUMBER
            )
            results.append({"to": to_number, "sid": call.sid})

        return jsonify({"calls": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
