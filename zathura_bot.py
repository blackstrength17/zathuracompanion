# --- Imports ---
import os
import requests
import json
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import sys

# --- Configuration and Constants ---
# Use environment variables for sensitive data
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") 
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Gemini API URLs
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TEXT_MODEL = "gemini-2.5-flash-preview-09-2025"

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- AI Core Functions ---

def generate_gemini_response(prompt: str) -> str:
    """Sends a text prompt to Gemini and returns the response, with search grounding."""
    if not GEMINI_API_KEY:
        return "Error: Gemini API Key not configured."

    url = f"{GEMINI_API_BASE}/{GEMINI_TEXT_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    # Configure system instruction and tools for search grounding
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
            
            # Extract and format sources if grounding was used
            sources = []
            grounding = candidate.get('groundingMetadata')
            if grounding and grounding.get('groundingAttributions'):
                sources = [
                    f"[{attr['web']['title']}]({attr['web']['uri']})"
                    for attr in grounding['groundingAttributions']
                    if attr.get('web') and attr['web'].get('uri')
                ]
                if sources:
                    source_text = "\n\nSources:\n" + "\n".join(set(sources))
                    text += source_text
            
            return text
        else:
            return "Error: Received an empty or unexpected response from the Gemini API."

    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
        return f"An HTTP error occurred: {e.response.status_code}. Please check the server logs."
    except Exception as e:
        logger.error(f"General Error generating response: {e}")
        return "An unknown error occurred while generating the response."


# --- Telegram Handlers ---

def start(update: Update, context: CallbackContext) -> None:
    """Sends the welcome message."""
    welcome_message = (
        "🛰️ *Welcome to Zathura Companion!*\n\n"
        "Python Version: " + sys.version.split()[0] + "\n\n" # Debug Line
        "I am your text-based AI assistant for this chat. I can answer any question you have.\n\n"
        "**🤖 To Ask Me a Question:**\n"
        "Just send your message as plain text (e.g., 'What is the largest nebula?')."
    )
    update.message.reply_markdown_v2(welcome_message)


def text_handler(update: Update, context: CallbackContext) -> None:
    """Handles all plain text messages using the Gemini model."""
    user_text = update.message.text
    
    update.message.reply_text("Thinking...")
    
    response_text = generate_gemini_response(user_text)
    
    # Use reply_markdown_v2 for safe parsing of response and links
    update.message.reply_markdown_v2(
        response_text,
        disable_web_page_preview=True 
    )


# --- Main Function and Deployment Setup (PTB v13) ---

def main() -> None:
    """Starts the bot using webhook configuration for hosting."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set. Exiting.")
        return
        
    if not WEBHOOK_URL:
        logger.error("WEBHOOK_URL environment variable not set. Exiting.")
        return

    # Use a dummy URL path; required by old PTB webhook structure
    WEBHOOK_PATH = 'webhook' 
    
    # FIX: Corrected syntax and simplified port logic for Render/Env compatibility
    PORT = int(os.environ.get('PORT', 8080)) 

    # Create the Updater and pass it your bot's token.
    updater = Updater(BOT_TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # Register handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))
    
    # --- Start the Webhook ---
    
    # Set the webhook URL for Telegram
    updater.bot.setWebhook(f'{WEBHOOK_URL}/{WEBHOOK_PATH}')

    # Start the web server for handling updates
    updater.start_webhook(listen="0.0.0.0",
                          port=PORT,
                          url_path=WEBHOOK_PATH,
                          webhook_url=f'{WEBHOOK_URL}/{WEBHOOK_PATH}')

    logger.info(f"Bot started via webhook at {WEBHOOK_URL}/{WEBHOOK_PATH} on port {PORT}")
    
    # Run the bot until you press Ctrl-C or the process receives SIGINT, SIGTERM or SIGABRT.
    updater.idle()


if __name__ == '__main__':
    main()
