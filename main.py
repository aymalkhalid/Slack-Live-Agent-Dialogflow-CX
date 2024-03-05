import os
import json
import time
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, Response
from flask_cors import CORS
from slack_sdk import WebClient
from flask_socketio import SocketIO, emit
import firebase_admin
from firebase_admin import credentials,firestore

load_dotenv()
# Firebase Credentials
cred = credentials.Certificate(os.getenv('SECRET_FireBase_Credentials'))
firebase_admin.initialize_app(cred)
db = firestore.client()
slack_client = WebClient(token=os.getenv('SLACK_BOT_TOKEN'))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")  # Initialize SocketIO with CORS allowed

#### Get Slack Thread id from Firebase
def get_slack_thread_id(df_session_id):
    doc_ref = db.collection("session_thread_management").document(str(df_session_id))
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict().get("thread_ts")
    return None
#### Save the thread and DF Session ID Mapping
def save_session_thread_mapping(df_session_id, thread_ts):
    doc_ref = db.collection("session_thread_management").document(str(df_session_id))
    doc_ref.set({"thread_ts": thread_ts})
#########
def get_df_session_id_by_thread_id(thread_ts):
    # Firestore query to find the document with the specified thread_ts
    docs = db.collection("session_thread_management").where("thread_ts", "==", thread_ts).stream()

    for doc in docs:
        # Return the first matching document's ID (Assuming thread_ts to df_session_id is 1-to-1)
        return doc.id
    return None

@app.route('/')
@app.route('/index')
def index():
    return render_template('indexio.html')

@app.route('/post_to_slack', methods=["POST"])
def post_to_slack():
    print("Triggered")
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        return jsonify({"error": "Server configuration error."}), 500
    # Extract the message from the incoming JSON payload
    data = request.json
    message = data.get("message")
    df_session_id=data.get("dfSessionId")
    newCustomerRequestedStatus=data.get("newCustomerRequestedStatus")
    print("message",message)
    print("df_session_id",df_session_id)
    print("newCustomerRequestedStatus",newCustomerRequestedStatus,type(newCustomerRequestedStatus))
    print("SessionID",df_session_id)
    thread_ts = get_slack_thread_id(df_session_id)
    if newCustomerRequestedStatus == "True":
        if message == "N/A":
            return jsonify({"error": "No message provided."}), 400
        if thread_ts:
            # Thread exists, reply to it
            response = slack_client.chat_postMessage(
                channel="testchatbot",
                text=message,
                thread_ts=thread_ts
            )
        else:
            # Create new thread
            response = slack_client.chat_postMessage(
                channel='testchatbot', 
                text=message
            )
            if response.data.get("ok"):
                thread_ts = response.data['ts']
                save_session_thread_mapping(df_session_id, thread_ts)
        #An Error Occured
        if response.status_code != 200:
            return jsonify({"error": "Failed to post message to Slack."}), 500
        #Return Status
        return jsonify({"Status":200})
    
    if newCustomerRequestedStatus == False:
        print("Customer Already Created the Ticket")
        print("Add to the Thread and Wait for the Human Agent Response")
        return jsonify({"Status":200})
    print("Failed")

# Slack Events
@app.route('/slack/events', methods=['POST'])
def slack_events():
    data = request.json
    # Log incoming data for debugging
    print("Incoming Slack data:", data)

    if 'thread_ts' in data['event']:
        thread_ts = data['event']['thread_ts']
        df_session_id = get_df_session_id_by_thread_id(thread_ts)
        
        if df_session_id:
            agent_response = data['event']['text']
            agent_id = data['event'].get('user')  # Get the user ID who posted the message
            
            # Check if the message is from your DF-CX agent by comparing user IDs
            # Replace 'U06N6STFPAM' with your actual DF-CX agent ID
            if agent_id == "U06N6STFPAM":
                print("Message from DF-CX Agent, ignoring...")
            else:
                print(f"Emitting message to the session {df_session_id}: {agent_response}")
                # Emit the message through WebSocket to front end
                socketio.emit('agent_response', {'message': agent_response, 'session_id': df_session_id})
                
    return Response(), 200

if __name__ == '__main__':
    socketio.run(app, host='127.0.0.1', port=5000, debug=True, use_reloader=False)