# viber_middleware.py (in viber-bot-middleware repository)
import os
from flask import Flask, request, Response, abort, jsonify
import requests
from datetime import datetime
import re

# Import Viberbot libraries
from viberbot import Api
from viberbot.api.bot_configuration import BotConfiguration
from viberbot.api.messages.text_message import TextMessage
from viberbot.api.messages.keyboard_message import KeyboardMessage
from viberbot.api.keyboards import Keyboard, Button

app = Flask(__name__)

# --- Configuration (Load from Environment Variables) ---
VIBER_AUTH_TOKEN = os.environ.get("VIBER_AUTH_TOKEN")
BACKEND_API_BASE_URL = os.environ.get("BACKEND_API_BASE_URL", "http://localhost:5000/api/v1") # Default for local testing
CUSTOMER_API_KEY_MIDDLEWARE = os.environ.get("CUSTOMER_API_KEY_MIDDLEWARE")
BILLING_API_KEY_MIDDLEWARE = os.environ.get("BILLING_API_KEY_MIDDLEWARE")
CHATLOG_API_KEY_MIDDLEWARE = os.environ.get("CHATLOG_API_KEY_MIDDLEWARE")
VIBER_WEBHOOK_URL = os.environ.get("VIBER_WEBHOOK_URL") # This will be the public URL of THIS Render service

# In-memory state for simple conversational flow (Use Redis/DB for production)
user_states = {} # {viber_id: {'step': 'initial', 'data': {}}}

viber = Api(BotConfiguration(
    name='Myanmar Link Bot',
    avatar='https://www.example.com/bot_avatar.png', # Provide a public URL for your bot's avatar
    auth_token=VIBER_AUTH_TOKEN
))

# --- Helper to call Backend API ---
def call_backend_api(endpoint, payload, api_key):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    url = f"{BACKEND_API_BASE_URL}{endpoint}"
    print(f"Middleware calling backend: {url} with payload: {payload}")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10) # Add timeout
        response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
        print(f"Backend response ({response.status_code}): {response.text}")
        return response.json()
    except requests.exceptions.Timeout:
        print(f"Backend API call to {url} timed out.")
        return {"status": "error", "message": "Backend service timed out. Please try again."}
    except requests.exceptions.RequestException as e:
        print(f"Backend API call failed to {url}: {e}")
        if response is not None:
            print(f"Backend API response content (error): {response.text}")
        return {"status": "error", "message": f"Backend service error: {e}"}

# --- Viber Webhook Endpoint ---
@app.route('/', methods=['POST'])
def incoming():
    try:
        viber_request = viber.parse_request(request.get_data())
    except Exception as e:
        print(f"Error parsing Viber request: {e}")
        return Response(status=400) # Bad Request if parsing fails

    if viber_request.event_type == 'message':
        message = viber_request.message
        sender_id = viber_request.sender.id
        sender_name = viber_request.sender.name

        print(f"Received message from {sender_name} ({sender_id}): {message.text}")

        user_state = user_states.get(sender_id, {'step': 'initial', 'data': {}})

        # Conversational flow logic
        if user_state['step'] == 'initial':
            if "register" in message.text.lower():
                user_states[sender_id] = {'step': 'awaiting_name', 'data': {}}
                viber.send_messages(sender_id, [TextMessage(text="မှတ်ပုံတင်ရန် နာမည်ကို ရိုက်ထည့်ပေးပါ")])
            elif "bill" in message.text.lower() or "payment" in message.text.lower():
                # For simple demo, ask all details at once. In real, guide step-by-step.
                viber.send_messages(sender_id, [TextMessage(text="Bill Payment လုပ်ရန် Viber User ID, Amount, Method, Reference ID တို့ကို ဤပုံစံအတိုင်း ပေးပါ (ဥပမာ: id:viber:abc amount:123 method:KBZpay ref:XYZ)")])
            elif "support" in message.text.lower() or "complaint" in message.text.lower():
                user_states[sender_id] = {'step': 'awaiting_chat_message', 'data': {}}
                viber.send_messages(sender_id, [TextMessage(text="Support အတွက် မေးလိုသော မေးခွန်း သို့မဟုတ် Complaint ကို ရိုက်ထည့်ပေးပါ")])
            else:
                viber.send_messages(sender_id, [
                    TextMessage(text="Myanmar Link Bot မှ ကြိုဆိုပါတယ်ဗျာ။ ဘာများ ကူညီပေးရမလဲ? (Register / Bill Payment / Support)")
                ])

        elif user_state['step'] == 'awaiting_name':
            user_state['data']['name'] = message.text
            user_state['step'] = 'awaiting_phone'
            viber.send_messages(sender_id, [TextMessage(text=f"ဖုန်းနံပါတ် (ဥပမာ: 09xxxxxxxxx) ကို ရိုက်ထည့်ပေးပါ")])

        elif user_state['step'] == 'awaiting_phone':
            phone = message.text
            if not re.match(r"^09[0-9]{7,9}$", phone):
                viber.send_messages(sender_id, [TextMessage(text="ဖုန်းနံပါတ် format မမှန်ပါဘူးဗျ။ 09 နဲ့ စပြီး ဂဏန်း 7 လုံးကနေ 9 လုံး ပါရပါမယ်။")])
                return Response(status=200) # Keep awaiting phone

            user_state['data']['phone'] = phone
            user_state['step'] = 'awaiting_region'
            viber.send_messages(sender_id, [TextMessage(text="နေထိုင်ရာ ဒေသ (ဥပမာ: Yangon, Mandalay) ကို ရိုက်ထည့်ပေးပါ")])

        elif user_state['step'] == 'awaiting_region':
            user_state['data']['region'] = message.text

            # Call Customer Create API
            register_payload = user_state['data']
            api_response = call_backend_api("/customers/create", register_payload, CUSTOMER_API_KEY_MIDDLEWARE)

            if api_response and api_response.get("status") == "success":
                viber.send_messages(sender_id, [TextMessage(text=api_response.get("message", "မှတ်ပုံတင်ခြင်း အောင်မြင်ပါတယ်ဗျာ။"))])
            else:
                viber.send_messages(sender_id, [TextMessage(text=f"မှတ်ပုံတင်ခြင်း မအောင်မြင်ပါဘူးဗျာ။ {api_response.get('message', 'Service error')}")])
            user_states[sender_id] = {'step': 'initial', 'data': {}} # Reset state

        elif user_state['step'] == 'awaiting_chat_message':
            chat_message = message.text
            chat_payload = {
                "viber_id": sender_id,
                "message": chat_message,
                "timestamp": datetime.now().isoformat(timespec='seconds') + 'Z',
                "type": "user_query"
            }
            api_response = call_backend_api("/chat-logs", chat_payload, CHATLOG_API_KEY_MIDDLEWARE)

            if api_response and api_response.get("status") == "success":
                viber.send_messages(sender_id, [TextMessage(text=api_response.get("message", "သင့်မက်ဆေ့ခ်ျကို လက်ခံရရှိပါပြီ။"))])
            else:
                viber.send_messages(sender_id, [TextMessage(text=f"မက်ဆေ့ခ်ျပို့ခြင်း မအောင်မြင်ပါဘူးဗျာ။ {api_response.get('message', 'Service error')}")])
            user_states[sender_id] = {'step': 'initial', 'data': {}} # Reset state

    elif viber_request.event_type == 'subscribed':
        viber.send_messages(viber_request.user.id, [
            TextMessage(text=f"Hello {viber_request.user.name}! Myanmar Link Bot မှ ကြိုဆိုပါတယ်ဗျာ။ ဘာများ ကူညီပေးရမလဲ? (Register / Bill Payment / Support)")
        ])
    elif viber_request.event_type == 'conversation_started':
         viber.send_messages(viber_request.user.id, [
            TextMessage(text=f"Hello {viber_request.user.name}! Myanmar Link Bot မှ ကြိုဆိုပါတယ်ဗျာ။ ဘာများ ကူညီပေးရမလဲ? (Register / Bill Payment / Support)")
        ])

    return Response(status=200)

# --- Viber Webhook Setup Endpoint ---
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    if not VIBER_WEBHOOK_URL:
        return jsonify({"status": "error", "message": "VIBER_WEBHOOK_URL environment variable not set."}), 500
    try:
        viber.set_webhook(VIBER_WEBHOOK_URL)
        return jsonify({"status": "success", "message": f"Webhook set to {VIBER_WEBHOOK_URL}"})
    except Exception as e:
        print(f"Failed to set webhook: {e}")
        return jsonify({"status": "error", "message": f"Failed to set webhook: {str(e)}"}), 500

# --- Health Check ---
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Viber Bot Middleware is running"}), 200
