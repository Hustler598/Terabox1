import asyncio
import logging
import time
import traceback

import humanreadable as hr
from telethon.sync import TelegramClient, events
from telethon.tl.custom.message import Message

from config import ADMINS, API_HASH, API_ID, BOT_TOKEN, HOST, PASSWORD, PORT
from redis_db import db
from send_media import VideoSender
from terabox import get_data
from tools import extract_code_from_url, get_urls_from_string

bot = TelegramClient("main", API_ID, API_HASH)

log = logging.getLogger(__name__)


@bot.on(
    events.NewMessage(
        incoming=True,
        outgoing=False,
        func=lambda message: message.text
        and get_urls_from_string(message.text)
        and message.is_private,
    )
)
async def get_message(m: Message):
    asyncio.create_task(handle_message(m))


async def handle_message(m: Message):
    url = get_urls_from_string(m.text)
    if not url:
        print("No valid URL found")
        return await m.reply("Please enter a valid url.")
    
    print(f"Processing URL: {url}")
    hm = await m.reply("Sending you the media wait...")
    
    # Check spam status
    is_spam = db.get(m.sender_id)
    print(f"Spam check - is_spam: {is_spam}, user_id: {m.sender_id}, is_admin: {m.sender_id in ADMINS}")
    if is_spam and m.sender_id not in ADMINS:
        ttl = db.ttl(m.sender_id)
        t = hr.Time(str(ttl), default_unit=hr.Time.Unit.SECOND)
        return await hm.edit(
            f"You are spamming.\n**Please wait {t.to_humanreadable()} and try again.**",
            parse_mode="markdown",
        )

    # Check token status    
    if_token_avl = db.get(f"active_{m.sender_id}")
    print(f"Token check - token_available: {if_token_avl}, user_id: {m.sender_id}")
    if not if_token_avl and m.sender_id not in ADMINS:
        return await hm.edit(
            "Your account is deactivated. send /gen to get activate it again."
        )

    # Extract and check shorturl
    shorturl = extract_code_from_url(url)
    print(f"Extracted shorturl: {shorturl}")
    if not shorturl:
        return await hm.edit("Seems like your link is invalid.")

    # Check cached file
    fileid = db.get_key(shorturl)
    print(f"Checking cache - fileid: {fileid}")
    if fileid:
        uid = db.get_key(f"mid_{fileid}")
        if uid:
            print(f"Found cached file - attempting to forward. UID: {uid}")
            check = await VideoSender.forward_file(
                file_id=fileid, message=m, client=bot, edit_message=hm, uid=uid
            )
            if check:
                return

    # Get data from API
    print(f"Attempting to get data from API for URL: {url}")
    try:
        data = get_data(url)
        print(f"Data received from API: {data}")
    except Exception as e:
        print(f"Error getting data from API: {str(e)}")
        traceback.print_exc()  # This will print the full error traceback
        return await hm.edit("Sorry! API is dead or maybe your link is broken.")

    if not data:
        return await hm.edit("Sorry! API is dead or maybe your link is broken.")
    db.set(m.sender_id, time.monotonic(), ex=60)

    if int(data["sizebytes"]) > 524288000 and m.sender_id not in ADMINS:
        return await hm.edit(
            f"Sorry! File is too big.\n**I can download only 500MB and this file is of {
                data['size']}.**\nRather you can download this file from the link below:\n{data['url']}",
            parse_mode="markdown",
        )

    sender = VideoSender(
        client=bot,
        data=data,
        message=m,
        edit_message=hm,
        url=url,
    )
    asyncio.create_task(sender.send_video())


bot.start(bot_token=BOT_TOKEN)

bot.run_until_disconnected()
