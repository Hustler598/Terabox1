import asyncio
import os
import time
from pathlib import Path
from uuid import uuid4
import logging
import traceback
from urllib.parse import quote

import telethon
from telethon import Button, TelegramClient, events, utils
from telethon.events.newmessage import NewMessage
from telethon.tl.functions.channels import GetMessagesRequest
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.patched import Message
from telethon.tl.types import Document
from telethon.types import UpdateEditMessage

from cansend import CanSend
from config import BOT_USERNAME, PRIVATE_CHAT_ID,FORCE_LINK
from FastTelethon import upload_file
from redis_db import db
from tools import (
    convert_seconds,
    download_file,
    download_image_to_bytesio,
    extract_code_from_url,
    get_formatted_size,
)

logger = logging.getLogger(__name__)

class VideoSender:

    def __init__(
        self,
        client: TelegramClient,
        message: NewMessage.Event,
        edit_message: Message,
        url: str,
        data,
    ):
        self.client = client
        self.data = data
        self.url = url
        self.edit_message = edit_message
        self.message = message
        self.uuid = str(uuid4())
        self.stop_sending = False
        self.thumbnail = None
        self.can_send = CanSend()
        self.start_time = time.time()
        self.task = None
        self.client.add_event_handler(
            self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
        )
        
        # Extract play URL once during initialization
        url_code = extract_code_from_url(self.url)
        if url_code:
            self.play_url = f"https://t.me/MyTbox4ubot/mybotbest?startapp={url_code}"
        else:
            self.play_url = None
        
        # Simplified caption since we don't have size information
        self.caption = f"""
File: `{self.data['file_name']}`

@itsurboydean
        """
        self.caption2 = f"""
Downloading `{self.data['file_name']}`

@itsurboydean
        """

    async def progress_bar(self, current_downloaded, total_downloaded, state="Sending"):
        if not self.can_send.can_send():
            return

        bar_length = 20
        percent = current_downloaded / total_downloaded
        arrow = "█" * int(percent * bar_length)
        spaces = "░" * (bar_length - len(arrow))

        elapsed_time = time.time() - self.start_time

        head_text = f"{state} `{self.data['file_name']}`"
        progress_bar = f"[{arrow + spaces}] {percent:.2%}"
        upload_speed = current_downloaded / elapsed_time if elapsed_time > 0 else 0
        speed_line = f"Speed: **{get_formatted_size(upload_speed)}/s**"

        time_remaining = (
            (total_downloaded - current_downloaded) / upload_speed
            if upload_speed > 0
            else 0
        )
        time_line = f"Time Remaining: `{convert_seconds(time_remaining)}`"
        size_line = f"Size: **{get_formatted_size(current_downloaded)}** / **{get_formatted_size(total_downloaded)}**"

        await self.edit_message.edit(
            f"{head_text}\n{progress_bar}\n{speed_line}\n{time_line}\n{size_line}",
            parse_mode="markdown",
            buttons=[
                [Button.url("Play Online", url=self.play_url)] if self.play_url else [],
                [Button.inline("Stop", data=f"stop{self.uuid}")]
            ]
        )

    async def send_media(self, shorturl):
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                logger.info(f"Attempt {retry_count + 1}/{max_retries} to send media: {self.data['file_name']}")
                self.thumbnail.seek(0) if self.thumbnail else None
                
                # Try direct media send first
                try:
                    file = await self._try_direct_send()
                    if file:
                        return await self.save_forward_file(file, shorturl)
                except Exception as e:
                    logger.warning(f"Direct send failed: {e}")
                    
                # Fall back to download and upload
                file = await self._try_download_and_upload()
                if file:
                    return await self.save_forward_file(file, shorturl)
                    
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"All attempts failed: {e}")
                    return await self.handle_failed_download()
                    
                logger.warning(f"Attempt {retry_count} failed, retrying in 5 seconds...")
                await asyncio.sleep(5)

    async def _try_direct_send(self):
        """Attempt to send media directly with fallback URLs"""
        errors = []
        
        # Try primary URL first
        try:
            spoiler_media = await self.client._file_to_media(
                self.data["direct_link"],
                supports_streaming=True,
                progress_callback=self.progress_bar,
                thumb=self.thumbnail,
            )
            
            file = await self.client.send_file(
                self.message.chat.id,
                file=spoiler_media[1],
                caption=self.caption,
                allow_cache=True,
                force_document=False,
                parse_mode="markdown",
                reply_to=self.message.id,
                supports_streaming=True,
                background=True,
                upload_timeout=3600,
                buttons=self._get_buttons()
            )
            return file
        except Exception as e:
            errors.append(f"Primary URL error: {str(e)}")
            logger.warning(f"Primary URL failed, trying backups: {e}")
        
        # Try backup URLs if primary fails
        for i, backup_url in enumerate(self.data.get("backup_links", []), 1):
            try:
                logger.info(f"Trying backup URL {i}")
                spoiler_media = await self.client._file_to_media(
                    backup_url,
                    supports_streaming=True,
                    progress_callback=self.progress_bar,
                    thumb=self.thumbnail,
                )
                
                file = await self.client.send_file(
                    self.message.chat.id,
                    file=spoiler_media[1],
                    caption=self.caption,
                    allow_cache=True,
                    force_document=False,
                    parse_mode="markdown",
                    reply_to=self.message.id,
                    supports_streaming=True,
                    background=True,
                    upload_timeout=3600,
                    buttons=self._get_buttons()
                )
                return file
            except Exception as e:
                errors.append(f"Backup URL {i} error: {str(e)}")
                logger.warning(f"Backup URL {i} failed: {e}")
                continue
        
        # If all URLs failed, raise the last error
        raise Exception(f"All download attempts failed: {'; '.join(errors)}")

    async def _try_download_and_upload(self):
        """Download and then upload the file with fallback URLs"""
        errors = []
        
        # Try primary URL first
        try:
            path = Path(self.data["file_name"])
            if path.exists():
                path.unlink()
                
            await download_file(
                self.data["direct_link"],
                self.data["file_name"],
                self.progress_bar
            )
            
            if path.exists() and path.stat().st_size > 0:
                return await self._upload_file(path)
        except Exception as e:
            errors.append(f"Primary URL error: {str(e)}")
            logger.warning(f"Primary URL failed, trying backups: {e}")
        
        # Try backup URLs if primary fails
        for i, backup_url in enumerate(self.data.get("backup_links", []), 1):
            try:
                logger.info(f"Trying backup URL {i}")
                if path.exists():
                    path.unlink()
                    
                await download_file(
                    backup_url,
                    self.data["file_name"],
                    self.progress_bar
                )
                
                if path.exists() and path.stat().st_size > 0:
                    return await self._upload_file(path)
            except Exception as e:
                errors.append(f"Backup URL {i} error: {str(e)}")
                logger.warning(f"Backup URL {i} failed: {e}")
                continue
        
        # If all URLs failed, raise the last error
        raise Exception(f"All download attempts failed: {'; '.join(errors)}")

    async def _upload_file(self, path: Path):
        """Helper method to upload a file"""
        return await self.client.send_file(
            self.message.chat.id,
            file=str(path),
            caption=self.caption,
            thumb=self.thumbnail,
            allow_cache=True,
            force_document=False,
            parse_mode="markdown",
            reply_to=self.message.id,
            supports_streaming=True,
            progress_callback=self.progress_bar,
            upload_timeout=3600,
            buttons=self._get_buttons()
        )

    def _get_buttons(self):
        """Return standard button layout with Play Online button"""
        buttons = []
        
        if self.play_url:
            buttons.append([
                Button.url("Play Online", url=self.play_url),
                Button.url("Backup", url="https://t.me/+3r_itVbkKHpjYTFh"),
            ])
        else:
            buttons.append([
                Button.url("Backup", url="https://t.me/+3r_itVbkKHpjYTFh"),
            ])
        
        return buttons

    async def handle_failed_download(self):
        try:
            os.unlink(self.data["file_name"])
        except Exception:
            pass
        try:
            os.unlink(self.download)
        except Exception:
            pass
        try:
            await self.edit_message.edit(
                f"Sorry! Download Failed but you can download it from [here]({self.data['direct_link']}) or [here]({self.data['link']}).",
                parse_mode="markdown",
                buttons=[Button.url("Download", data=self.data["direct_link"])],
                
            )
        except Exception:
            pass

    async def save_forward_file(self, file, shorturl):
        # Add keys for tracking forwards
        private_forward_key = f"private_forward_{shorturl}"
        force_link_key = f"force_link_{shorturl}"
        
        try:
            # Handle FORCE_LINK forward first
            if not db.get(force_link_key):
                logger.info(f"Forwarding to FORCE_LINK channel: {FORCE_LINK}")
                force_forwarded = await self.client.forward_messages(
                    FORCE_LINK,
                    messages=[file],
                    from_peer=self.message.chat.id,
                    background=True
                )
                
                if force_forwarded and force_forwarded[0].id:
                    db.set(force_link_key, 1)  # Mark as forwarded
                    logger.info(f"Successfully forwarded to FORCE_LINK channel")
                else:
                    logger.error("Failed to forward to FORCE_LINK channel")

            # Handle private storage forward
            if not db.get(private_forward_key):
                forwarded_message = await self.client.forward_messages(
                    PRIVATE_CHAT_ID,
                    messages=[file],
                    from_peer=self.message.chat.id,
                    background=True
                )
                
                if forwarded_message and forwarded_message[0].id:
                    msg_id = forwarded_message[0].id
                    # Set all necessary keys
                    db.set_key(self.uuid, msg_id)
                    db.set_key(f"mid_{msg_id}", self.uuid)
                    db.set_key(shorturl, msg_id)
                    db.set(private_forward_key, 1)
                    logger.info(f"Successfully forwarded to private storage: {msg_id}")

        except Exception as e:
            logger.error(f"Error in forwarding: {str(e)}\n{traceback.format_exc()}")
        
        # Cleanup
        self.client.remove_event_handler(
            self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
        )
        try:
            await self.edit_message.delete()
        except Exception:
            pass
        try:
            os.unlink(self.data["file_name"])
        except Exception:
            pass
        try:
            os.unlink(self.download)
        except Exception:
            pass
        
        db.set(self.message.sender_id, time.monotonic(), ex=60)

    async def send_video(self):
        self.thumbnail = download_image_to_bytesio(self.data["thumb"], "thumbnail.png")
        shorturl = extract_code_from_url(self.url)
        if not shorturl:
            return await self.edit_message.edit("Seems like your link is invalid.")

        try:
            if self.edit_message:
                await self.edit_message.delete()
        except Exception as e:
            pass
        db.set(self.message.sender_id, time.monotonic(), ex=60)
        self.edit_message = await self.message.reply(
            self.caption2, file=self.thumbnail, parse_mode="markdown"
        )
        self.task = asyncio.create_task(self.send_media(shorturl))

    async def stop(self, event):
        self.task.cancel()
        self.client.remove_event_handler(
            self.stop, events.CallbackQuery(pattern=f"^stop{self.uuid}")
        )
        await event.answer("Process stopped.")
        try:
            os.unlink(self.data["file_name"])
        except Exception:
            pass
        try:
            os.unlink(self.download)
        except Exception:
            pass
        try:
            await self.edit_message.delete()
        except Exception:
            pass

    def get_thumbnail(self):
        return download_image_to_bytesio(self.data["thumb"], "thumbnail.png")

    @staticmethod
    async def forward_file(
        client: TelegramClient,
        file_id: int,
        message: Message,
        edit_message: UpdateEditMessage = None,
        uid: str = None,
    ):
        if edit_message:
            try:
                await edit_message.delete()
            except Exception:
                pass
        result = await client(
            GetMessagesRequest(channel=PRIVATE_CHAT_ID, id=[int(file_id)])
        )
        msg: Message = result.messages[0] if result and result.messages else None
        if not msg:
            return False
        media: Document = (
            msg.media.document if hasattr(msg, "media") and msg.media.document else None
        )
        try:
            await message.reply(
                message=msg.message,
                file=media,
                # entity=msg.entities,
                background=True,
                reply_to=message.id,
                force_document=False,
                buttons=[
                    [
                        Button.url(
                            "Direct Link",
                            url=f"https://{BOT_USERNAME}.t.me?start={uid}",
                        ),
                    ],
                    # [
                    #     Button.url("Channel ", url="https://t.me/itsurboydean"),
                    #     Button.url("Group ", url="https://t.me/itsurboydeanChats"),
                    # ],
                ],
                parse_mode="markdown",
            )
            db.set(message.sender_id, time.monotonic(), ex=60)
            db.incr(
                f"check_{message.sender_id}",
                1,
            )
            return True
        except Exception:
            return False

__all__ = ['VideoSender']
