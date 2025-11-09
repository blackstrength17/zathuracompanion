import logging
import os
import requests
import json
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Configuration and Constants ---
# Use environment variables for sensitive data
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") # Keep it as empty string if not provided

# Gemini API URLs
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TEXT_MODEL = "gemini-2.5-flash-preview-09-2025"
GEMINI_IMAGE_MODEL = "imagen-3.0-generate-002:predict"

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- AI API Functions ---

async def generate_gemini_response(prompt: str) -> str:
    """Sends a text prompt to the Gemini API with Google Search grounding."""
    url = f"{GEMINI_API_BASE}/{GEMINI_TEXT_MODEL}:generateContent?key={GEMINI_API_KEY}"
    
    # System instruction guides the assistant's behavior
    system_prompt = "You are Zathura Companion, a helpful AI assistant in a Telegram chat. Answer questions concisely, drawing from your knowledge and the provided search results. If asked for image generation, instruct the user to use the /generate command."

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],  # Enable Google Search grounding
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
        
        # Extract text
        text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', "Sorry, I couldn't process that request.")
        
        # Extract sources if available
        sources = data.get('candidates', [{}])[0].get('groundingMetadata', {}).get('groundingAttributions', [])
        
        if sources:
            source_list = "\n\nSources:\n"
            for i, source in enumerate(sources[:3]): # Limit to 3 sources
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
    
    # System instruction for image generation model
    # Note: Using the :predict endpoint as described in instructions
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

# --- Telegram Handlers ---

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
    
    # Show typing status immediately
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
    
    # Show upload photo status immediately
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    
    logger.info(f"Received image generation prompt: {image_prompt}")

    # Generate image data (base64 URL)
    image_url = await generate_imagen_image(image_prompt)

    if image_url:
        # For the Canvas environment, since direct file sending is tricky without a buffer,
        # we will use the generated URL in a markdown link so the user can verify the output.
        
        await update.message.reply_text(
            f"Image generation successful for: *{image_prompt}*\n\n"
            f"[View Generated Image (External Link)]({image_url})",
            parse_mode='Markdown'
        )

    else:
        await update.message.reply_text("Image generation failed. Please try a different prompt.")


def main() -> None:
    """Starts the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set. Exiting.")
        return

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("generate", generate_image_command))

    # on non-command messages - handle the text input
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Start the bot.
    
    # Check if we are in a deployment environment (like Render, which sets PORT)
    PORT = int(os.environ.get('PORT', 8080))
    WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

    if WEBHOOK_URL:
        # Running via explicit webhook setup to bypass ptb v20.x run_webhook conflicts.
        
        # 1. Set the webhook URL on Telegram's side
        application.bot.set_webhook(f"{WEBHOOK_URL}") # Use simple base URL for simple path fix

        # 2. Start the built-in HTTP server to listen for webhooks
        # FINAL FIX: Set url_path to an empty string to prevent the library from generating complex paths 
        # and referencing deprecated internal logic.
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="", 
            webhook_url=WEBHOOK_URL,
            # We explicitly set the secret token here for security best practices.
            secret_token=BOT_TOKEN
        )
        logger.info(f"Bot started successfully via webhook on port {PORT}. URL: {WEBHOOK_URL}")
    else:
        # Running via polling for local development
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot started successfully via polling for local development.")


if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY is not set. AI functionalities will not work!")
    main()
