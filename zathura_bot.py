import logging
import os
import requests
import json
import asyncio
import http.server
import socketserver
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from urllib.parse import urlparse, parse_qs

# --- Configuration and Constants ---
# Use environment variables for sensitive data
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") 

# Gemini API URLs
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TEXT_MODEL = "gemini-2.5-flash-preview-09-2025"
GEMINI_IMAGE_MODEL = "imagen-3.0-generate-002:predict"

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Application Instance (Global) ---
# Declare application globally to be accessible by the webhook handler
application: Application = None 

# --- AI API Functions (Contents remain the same) ---

async def generate_gemini_response(prompt: str) -> str:
    """Sends a text prompt to the Gemini API with Google Search grounding."""
    url = f"{GEMINI_API_BASE}/{GEMINI_TEXT_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    system_prompt = "You are Zathura Companion, a helpful AI assistant in a Telegram chat. Answer questions concisely, drawing from your knowledge and the provided search results. If asked for image generation, instruct the user to use the /generate command."

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }

    try:
        response = await asyncio.to_thread(
            requests.post, 
            url, 
            headers={"Content-Type": "application/json"}, 
            json=payload, 
            timeout=15
        )
        response.raise_for_status()
        
        data = response.json()
        
        text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', "Sorry, I couldn't process that request.")
        sources = data.get('candidates', [{}])[0].get('groundingMetadata', {}).get('groundingAttributions', [])
        
        if sources:
            source_list = "\n\nSources:\n"
            for i, source in enumerate(sources[:3]):
                title = source.get('web', {}).get('title', 'Link')
                uri = source.get('web', {}).get('uri', '#')
                source_list += f"{i+1}. [{title}]({uri})\n"
            text += source_list
            
        return text

    except requests.exceptions.RequestException as e:
        logger.error(f"Gemini API Request failed: {e}")
        return "I'm having trouble connecting to the AI service right now."

async def generate_imagen_image(prompt: str) -> str:
    """Sends a prompt to the Imagen API and returns a base64 image URL."""
    url = f"{GEMINI_API_BASE}/{GEMINI_IMAGE_MODEL}?key={GEMINI_API_KEY}"
    
    payload = {
        "instances": {
            "prompt": f"Professional digital art, highly detailed, sci-fi: {prompt}"
        },
        "parameters": {"sampleCount": 1}
    }

    try:
        response = await asyncio.to_thread(
            requests.post, 
            url, 
            headers={"Content-Type": "application/json"}, 
            json=payload, 
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        
        base64_data = data.get('predictions', [{}])[0].get('bytesBase64Encoded')

        if base64_data:
            return f"data:image/png;base64,{base64_data}"
        else:
            logger.error(f"Imagen API returned no image data: {data}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Imagen API Request failed: {e}")
        return None

# --- Telegram Handlers (Contents remain the same) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the command /start is issued."""
    welcome_message = (
        "Hello! I am **Zathura Companion**, your AI assistant for this chat.\n\n"
        "**Ask me questions** about anything, and I'll use Google Search to answer.\n\n"
        "**To generate an image**, use the command: `/generate [your creative prompt]`\n\n"
        "Example: `/generate a floating cyberpunk city at sunset`"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text messages and responds using the Gemini API."""
    user_prompt = update.message.text
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    logger.info(f"Received text prompt from {update.effective_user.username}: {user_prompt}")
    
    response_text = await generate_gemini_response(user_prompt)
    
    await update.message.reply_text(response_text, parse_mode='Markdown')

async def generate_image_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /generate command for image creation."""
    if not context.args:
        await update.message.reply_text("Please provide a description for the image. Example: `/generate a neon blue dragon`")
        return

    image_prompt = " ".join(context.args)
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    
    logger.info(f"Received image generation prompt: {image_prompt}")

    image_url = await generate_imagen_image(image_prompt)

    if image_url:
        await update.message.reply_text(
            f"Image generation successful for: *{image_prompt}*\n\n"
            f"[View Generated Image (External Link)]({image_url})",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("Image generation failed. Please try a different prompt.")

# --- Custom Webhook Handler ---

class CustomWebhookHandler(http.server.BaseHTTPRequestHandler):
    """Handles incoming HTTP requests for Telegram webhooks."""
    
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        update_json = self.rfile.read(content_length).decode('utf-8')
        
        try:
            update_data = json.loads(update_json)
            update = Update.de_json(update_data, application.bot)
            
            # Process the update using the application's update queue
            asyncio.run(application.process_update(update))

            self.send_response(200)
            self.end_headers()
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            self.send_response(500)
            self.end_headers()

    def do_GET(self):
        # Respond to GET requests (used for health checks)
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Zathura Companion Bot is running.")


def main() -> None:
    """Starts the bot."""
    global application # Use the global application instance

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set. Exiting.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers setup
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("generate", generate_image_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # --- Webhook Startup ---
    PORT = int(os.environ.get('PORT', 8080))
    WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

    if WEBHOOK_URL:
        # Running via custom Webhook Server
        
        # 1. Set the webhook URL on Telegram's side
        # NOTE: Using the BOT_TOKEN as the secret path for security
        webhook_path = f"/{BOT_TOKEN}"
        full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"

        logger.info(f"Setting webhook to: {full_webhook_url}")
        application.bot.set_webhook(full_webhook_url)

        # 2. Start the custom HTTP server
        with socketserver.TCPServer(("0.0.0.0", PORT), CustomWebhookHandler) as httpd:
            logger.info(f"Serving webhook handler on port {PORT}...")
            httpd.serve_forever()

    else:
        # Running via polling for local development
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot started successfully via polling for local development.")


if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY is not set. AI functionalities will not work!")
    main()
