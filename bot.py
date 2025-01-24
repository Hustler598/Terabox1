import logging
import time
import re
import requests
import os
import asyncio
from typing import List, Union
from urllib.parse import urlparse

import humanreadable as hr
from telethon import Button, types
from telethon.sync import TelegramClient, events
from telethon.tl.custom.message import Message
from telethon.types import UpdateNewMessage
import aiohttp
import platform
import sys

from config import (ADMINS, API_HASH, API_ID, BOT_TOKEN, BOT_USERNAME,
                    FORCE_LINK)
from redis_db import db
from send_media import VideoSender
from tools import generate_shortenedUrl, is_user_on_chat, remove_all_videos, get_urls_from_string, extract_code_from_url, check_url_patterns
from terabox import get_data
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
log = logging.getLogger(__name__)

bot = TelegramClient("bot", API_ID, API_HASH)

def start_web_server():
    port = int(os.environ.get('PORT', 8080))
    server_address = ('', port)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    print(f"Serving on port {port}")
    httpd.serve_forever()
# url_queues = defaultdict(asyncio.Queue)  # Queue per user
processing_tasks = {}  # Track processing tasks per user

# Set the event loop policy to SelectorEventLoop on Windows
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def get_urls_from_string(text: str) -> List[str]:
    """Extract valid URLs from text string"""
    pattern = r'(https?://\S+?/(?:s|share)/[a-zA-Z0-9_-]+)'
    urls = re.findall(pattern, text)
    # Filter URLs using the imported check_url_patterns function
    return [url for url in urls if check_url_patterns(url)]


@bot.on(
    events.NewMessage(
        pattern="/start$",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def start(m: Message):
    try:
        reply_text = """
👋 *Welcome to Terabox Downloader Bot!*

I can help you with Terabox links in two ways:
1️⃣ Play videos online
2️⃣ Download videos directly

Choose your preferred method:
        """
        await m.reply(
            reply_text,
            link_preview=False,
            parse_mode="markdown",
            buttons=[
                [
                    Button.inline("▶️ Play Online", data="play_online"),
                    Button.inline("⬇️ Download", data="download_mode"),
                ],
                [
                    Button.url("📢 Backup", url="https://t.me/+3r_itVbkKHpjYTFh"),
                ],
            ],
        )
    except Exception as e:
        log.error(f"Error in start command: {e}")
        await m.reply("An error occurred. Please try again later.")


@bot.on(events.CallbackQuery(pattern="play_online"))
async def play_online_callback(event):
    await event.edit(
        "✅ *Play Online mode selected!*\n\nJust send me any Terabox link and I'll provide you with a direct play button.",
        parse_mode="markdown"
    )
    # Store user preference
    db.set(f"mode_{event.sender_id}", "play")


@bot.on(events.CallbackQuery(pattern="download_mode"))
async def download_mode_callback(event):
    await event.edit(
        "✅ *Download mode selected!*\n\nJust send me any Terabox link and I'll process it for downloading.",
        parse_mode="markdown"
    )
    # Store user preference
    db.set(f"mode_{event.sender_id}", "download")


@bot.on(
    events.NewMessage(
        pattern=r"/start (?!token_)([0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12})",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def start_ntoken(m: Message):
    if m.sender_id not in ADMINS:
        if_token_avl = db.get(f"active_{m.sender_id}")
        if not if_token_avl:
            return await m.reply(
                "Your account is deactivated. send /gen to get activate it again."
            )
    text = m.pattern_match.group(1)
    fileid = db.get(str(text))
    if fileid:
        return await VideoSender.forward_file(
            file_id=fileid, message=m, client=bot, uid=text.strip()
        )
    else:
        return await m.reply("""your requested file is not available.""")


@bot.on(
    events.NewMessage(
        pattern="/remove (.*)",
        incoming=True,
        outgoing=False,
        from_users=ADMINS,
    )
)
async def remove(m: UpdateNewMessage):
    user_id = m.pattern_match.group(1)
    if db.get(f"check_{user_id}"):
        db.delete(f"check_{user_id}")
        await m.reply(f"Removed {user_id} from the list.")
    else:
        await m.reply(f"{user_id} is not in the list.")


@bot.on(
    events.NewMessage(
        pattern="/removeall",
        incoming=True,
        outgoing=False,
        from_users=ADMINS,
    )
)
async def removeall(m: UpdateNewMessage):
    remove_all_videos()
    return await m.reply("Removed all videos from the list.")


@bot.on(
    events.NewMessage(
        pattern="/help$",
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private,
    )
)
async def help_command(m: Message):
    help_text = """
📚 *Bot Help Guide*

*How to use:*
1. Send Terabox video link
2. Wait for processing
3. Download your video!

*Commands:*
• /start - Start the bot
• /help - Show this help
    """
    await m.reply(help_text, parse_mode="markdown")


async def process_single_url(url: str, m: Message, hm: Message) -> Union[bool, str]:
    """Process a single URL with improved error handling and performance"""
    try:
        log.info(f"Processing URL: {url}")
        
        # Check user's preferred mode
        user_mode = db.get(f"mode_{m.sender_id}") or "play"  # Default to play mode
        
        # Get URL code for play online functionality
        url_code = extract_code_from_url(url)
        if not url_code:
            await hm.edit("❌ Invalid Terabox URL format")
            return False
            
        if user_mode == "play":
            # Simply return the play online button
            mini_app_url = f"https://t.me/MyTbox4ubot/mybotbest?startapp={url_code}"
            
            message_text = f"🎥 Here's your play online link:\n\nUser ID: {m.sender_id}\nURL: {url}"
            buttons = [[
                Button.url("▶️ Play Online", url=mini_app_url),
                Button.url("Support Chat", url="https://t.me/+3r_itVbkKHpjYTFh")
            ]]
            
            # Forward to FORCE_LINK channel with same format
            await bot.send_message(
                FORCE_LINK,
                message_text,
                buttons=buttons
            )
            
            # Send to user (without the User ID and URL info)
            await hm.edit(
                "🎥 Here's your play online link:",
                buttons=buttons
            )
            return "play_button_shown"
            
        # Continue with download mode
        try:
            await hm.edit("🔍 Fetching file information...")
        except Exception as e:
            hm = await m.reply("🔍 Fetching file information...")
        
        file_data = get_data(url)
        log.info(f"data1234: {file_data.get('direct_link')}")
        
        if not file_data or not file_data.get('direct_link'):
            error_msg = "❌ Failed to fetch valid file information"
            # Get URL code and create Mini App URL
            if url_code:
                mini_app_url = f"https://t.me/MyTbox4ubot/mybotbest?startapp={url_code}"
                support_buttons = [[
                    Button.url("▶️ Play Online", url=mini_app_url),
                    Button.url("Support Chat", url="https://t.me/+3r_itVbkKHpjYTFh")
                ]]
            else:
                support_buttons = [[
                    Button.url("Support Chat", url="https://t.me/+3r_itVbkKHpjYTFh")
                ]]
            
            try:
                await bot.send_message(
                    FORCE_LINK,
                    f"Error Report:\nUser ID: {m.sender_id}\nError: {error_msg}\nURL: {url}"
                )
                await hm.edit(f"{error_msg}\nYou can still try to play this online or report this in our support chat.", buttons=support_buttons)
            except:
                await m.reply(f"{error_msg}\nYou can still try to play this online or report this in our support chat.", buttons=support_buttons)
            return "play_button_shown"  # Return special flag instead of False

        # Since we don't have size information from new API, we'll skip size checks
        # Initialize VideoSender
        video_sender = VideoSender(
            client=bot,
            message=m,
            edit_message=hm,
            url=url,
            data=file_data
        )
        
        # Send the video
        try:
            await video_sender.send_video()
            return True
        except Exception as e:
            log.error(f"Video sending error: {str(e)}")
            try:
                await hm.edit(f"❌ Error sending video: {str(e)}")
            except:
                await m.reply(f"❌ Error sending video: {str(e)}")
            return False

    except Exception as e:
        log.error(f"Process error for {url}: {str(e)}")
        error_msg = f"❌ Error: {str(e)}"
        
        support_buttons = []
        
        # Create Mini App button if we have a valid URL code
        if url_code := extract_code_from_url(url):
            log.info(f"urlCode: {url_code}, url: {url}")
            
            mini_app_url = f"https://t.me/MyTbox4ubot/mybotbest?startapp={url_code}"
            
            support_buttons = [[
                Button.url("▶️ Play Online", url=mini_app_url),
                Button.url("💬 Support Chat", url="https://t.me/+3r_itVbkKHpjYTFh")
            ]]
        else:
            support_buttons = [[
                Button.url("💬 Support Chat", url="https://t.me/+3r_itVbkKHpjYTFh")
            ]]
        
        try:
            # Send error report to channel
            await bot.send_message(
                FORCE_LINK,
                f"Error Report:\nUser ID: {m.sender_id}\nError: {str(e)}\nURL: {url}"
            )
            # Send error message to user
            await hm.edit(
                f"{error_msg}\nYou can still try to play this online or report the issue in our support chat.",
                buttons=support_buttons
            )
        except:
            await m.reply(
                f"{error_msg}\nYou can still try to play this online or report the issue in our support chat.",
                buttons=support_buttons
            )
        return False


@bot.on(
    events.NewMessage(
        incoming=True,
        outgoing=False,
        func=lambda x: x.is_private and not x.text.startswith('/'),
    )
)
async def handle_messages(m: Message):
    """Handle incoming messages and process URLs"""
    try:
        # Process URLs in the current message
        await process_url(m)
        
        # If there are pending messages with links, process them too
        # Consider removing or modifying this section if it uses restricted methods
        # async for msg in bot.iter_messages(
        #     m.chat_id,
        #     limit=10,  # Limit to last 10 messages
        #     from_user=m.sender_id
        # ):
        #     if msg.id != m.id:  # Skip the current message
        #         urls = get_urls_from_string(msg.text)
        #         if urls:
        #             await process_url(msg)
                    
    except Exception as e:
        log.error(f"Message handling error: {str(e)}")
        await m.reply("❌ An error occurred while processing messages")


async def process_url(m: Message):
    try:
        urls = get_urls_from_string(m.text)
        if not urls:
            return await m.reply("❌ No valid Terabox links found in message")
            
        log.info(f"Found URLs: {urls}")
        hm = await m.reply("🔍 Processing your request...")
        
        # Check spam protection only for non-admins
        if m.sender_id not in ADMINS:
            # Check spam protection
            spam_key = f"spam_{m.sender_id}"
            spam_status = db.get(spam_key)
            
            if spam_status:
                ttl = db.redis.ttl(spam_key)
                if ttl > 0:  # Ensure TTL is greater than zero
                    t = hr.Time(str(ttl), default_unit=hr.Time.Unit.SECOND)
                    try:
                        return await hm.edit(
                            f"⚠️ Please wait {t.to_humanreadable()} before sending another link",
                            parse_mode="markdown"
                        )
                    except:
                        return await m.reply(
                            f"⚠️ Please wait {t.to_humanreadable()} before sending another link",
                            parse_mode="markdown"
                        )

            # Set spam protection timer (60 seconds)
            db.set(spam_key, "1", ex=60)

        total_urls = len(urls)
        successful = 0
        large_file_processed = False
        play_button_shown = False

        for idx, url in enumerate(urls, 1):
            try:
                if not large_file_processed and not play_button_shown:
                    try:
                        await hm.edit(f"🔄 Processing link {idx}/{total_urls}: {url}")
                    except:
                        hm = await m.reply(f"🔄 Processing link {idx}/{total_urls}: {url}")
                
                result = await process_single_url(url, m, hm)
                
                # If there was an error and user isn't admin, remove spam protection
                if not result and m.sender_id not in ADMINS:
                    spam_key = f"spam_{m.sender_id}"
                    db.redis.delete(spam_key)
                
                if result == "large_file":
                    large_file_processed = True
                elif result == "play_button_shown":
                    play_button_shown = True
                elif result:
                    successful += 1

                if not large_file_processed and not play_button_shown:
                    try:
                        await hm.edit(f"✅ Successfully processed link {idx}/{total_urls}")
                    except:
                        await m.reply(f"✅ Successfully processed link {idx}/{total_urls}")
                
                await asyncio.sleep(1)
                
            except Exception as e:
                log.error(f"Error processing URL {url}: {str(e)}")
                if not large_file_processed and not play_button_shown:
                    try:
                        await hm.edit(f"❌ Error processing link {idx}/{total_urls}: {str(e)}")
                    except:
                        await m.reply(f"❌ Error processing link {idx}/{total_urls}: {str(e)}")
                continue
        
        if not large_file_processed and not play_button_shown:
            final_message = "✅ All links processed successfully!" if successful == total_urls else f"⚠️ Completed: {successful}/{total_urls} links processed successfully"
            try:
                await hm.edit(final_message)
            except:
                await m.reply(final_message)

    except Exception as e:
        log.error(f"Main process error: {str(e)}")
        await m.reply(f"❌ Error: {str(e)}")


if __name__ == "__main__":
    try:
        # Configure logging first
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        log = logging.getLogger("bot")
        
        # Test Redis connection before starting the bot
        log.info("Testing Redis connection...")
        from redis_db import db
        if db.redis.ping():
            log.info("Redis connection successful!")
        else:
            raise ConnectionError("Redis connection failed")
            
        # Start the bot
        log.info("=== Bot starting ===")
        print("Bot is starting...")
        port = int(os.environ.get('PORT', 8080))
        web_thread = threading.Thread(target=start_web_server)
        web_thread.start()
        bot.start(bot_token=BOT_TOKEN)
        print("Bot is running...")
        bot.run_until_disconnected()
        
    except Exception as e:
        print(f"Error starting bot: {e}")
        log.error(f"Startup error: {str(e)}", exc_info=True)
        sys.exit(1)
