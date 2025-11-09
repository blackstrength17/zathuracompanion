# --- Imports ---
import os
import requests
import json
import logging
from flask import Flask, request, jsonify
import sys

# --- Configuration and Constants ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Telegram API URL
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Gemini API URLs
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TEXT_MODEL = "gemini-2.5-flash-preview-09-2025"

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask App Initialization
app = Flask(__name__)

# --- AI Core Functions ---

def generate_gemini_response(prompt: str) -> str:
    """Sends a text prompt to Gemini and returns the response, with search grounding."""
    if not GEMINI_API_KEY:
        return "Error: Gemini API Key not configured."

    url = f"{GEMINI_API_BASE}/{GEMINI_TEXT_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    system_prompt = "You are Zathura Companion, an intelligent AI assistant. Respond concisely and professionally. If the request requires up-to-date knowledge or real-time information, use Google Search grounding."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }

    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        
        result = response.json()
        candidate = result.get('candidates', [{}])[0]
        
        if candidate and candidate.get('content') and candidate['content'].get('parts'):
            text = candidate['content']['parts'][0].get('text', "Could not generate a textual response.")
            
            return text
        else:
            return "Error: Received an empty or unexpected response from the Gemini API."

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        return f"An HTTP error occurred: {e.response.status_code}. Please check the server logs."
    except Exception as e:
        logger.error(f"General Error generating response: {e}")
        return "An unknown error occurred while generating the response."

# --- Telegram Helper ---

def send_telegram_message(chat_id, text, parse_mode="MarkdownV2"):
    """Sends a message back to Telegram."""
    send_url = f"{TELEGRAM_API_URL}sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    requests.post(send_url, json=payload)

# --- Flask Webhook Route ---

@app.route('/')
def hello():
    return "Zathura Companion Bot is running."

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    if not BOT_TOKEN:
        return jsonify({'status': 'BOT_TOKEN not configured'}), 503

    try:
        update = request.get_json()
        
        if not update or 'message' not in update:
            return jsonify({'status': 'No message in update'}), 200

        message = update['message']
        chat_id = message['chat']['id']
        text = message.get('text', '')

        if not text:
            return jsonify({'status': 'No text in message'}), 200

        # Command Handling
        if text.startswith('/start'):
            welcome_message = (
                "🛰️ *Welcome to Zathura Companion!* (Flask Stable)\n\n"
                "I am your text-based AI assistant. I can answer any question you have.\n\n"
                "*Python System Info:* " + sys.version.split()[0] + "\n\n"
                "**🤖 To Ask Me a Question:**\n"
                "Just send your message as plain text."
            )
            send_telegram_message(chat_id, welcome_message)
        
        # Text Handling
        else:
            response_text = generate_gemini_response(text)
            send_telegram_message(chat_id, response_text)

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return jsonify({'status': 'error'}), 500

# --- Deployment Setup ---

def set_telegram_webhook():
    """Sets the Telegram webhook URL."""
    if not WEBHOOK_URL or not BOT_TOKEN:
        logger.error("WEBHOOK_URL or BOT_TOKEN not set for webhook.")
        return

    webhook_url = f"{TELEGRAM_API_URL}setWebhook"
    payload = {"url": f"{WEBHOOK_URL}/webhook"}
    
    response = requests.post(webhook_url, json=payload)
    logger.info(f"SetWebhook response: {response.status_code} - {response.text}")
    
    if response.status_code != 200:
        logger.error(f"Failed to set webhook: {response.text}")

if __name__ == '__main__':
    # Set the webhook URL when the bot starts
    set_telegram_webhook()
    
    # Render uses the PORT environment variable
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
