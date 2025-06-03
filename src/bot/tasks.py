import asyncio
import logging

from celery import shared_task

from bot.sender import send_telegram_message_via_aiogram
from bot.config import settings as bot_config
from admin_panel.clients.models import Broadcast

logger = logging.getLogger(__name__)

logger.debug("Attempting to load TELEGRAM_BOT_TOKEN for src.bot.tasks.")
try:
    TELEGRAM_BOT_TOKEN = bot_config.bot.token.get_secret_value() if hasattr(bot_config.bot.token, 'get_secret_value') else bot_config.bot.token
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not found in configuration (bot_config.bot.token).")
    else:
        logger.info("Telegram bot token successfully loaded for src.bot.tasks.")
except AttributeError as e:
    logger.error(f"Error accessing bot token configuration (bot_config.bot.token): {e}.")
    TELEGRAM_BOT_TOKEN = None
except Exception as e:
    logger.error(f"Unexpected error loading Telegram bot token: {e}.")
    TELEGRAM_BOT_TOKEN = None

@shared_task(bind=True, max_retries=3, default_retry_delay=60, acks_late=True)
def send_single_telegram_message_task(self, chat_id: int, text: str, broadcast_id: int, parse_mode: str = None):
    """
    Celery task to send a single Telegram message to a specified chat ID.

    This task uses `send_telegram_message_via_aiogram` to perform the actual sending.
    It updates the status of the corresponding `Broadcast` object in the database
    upon successful delivery. The task includes retry logic in case of failures.

    Args:
        self: The Celery task instance (bound by `bind=True`).
        chat_id: The integer ID of the Telegram chat to send the message to.
        text: The text content of the message.
        broadcast_id: The primary key of the `Broadcast` model instance
                      associated with this message.
        parse_mode: Optional string specifying the parse mode for the message
                    (e.g., 'HTML', 'MarkdownV2'). Defaults to None, which
                    typically means `send_telegram_message_via_aiogram` will
                    use its own default (often 'HTML').

    Returns:
        A string message indicating successful delivery.

    Raises:
        Exception: If the `TELEGRAM_BOT_TOKEN` is not configured.
        self.retry: The task will be retried if `send_telegram_message_via_aiogram`
                     returns False, or if a `RuntimeError` or other `Exception` occurs
                     during the sending process.
    """
    task_id = self.request.id
    logger.info(f"[Task ID: {task_id}] Received task to send message to chat_id {chat_id} for broadcast_id {broadcast_id}. Attempt: {self.request.retries + 1}/{self.max_retries if self.max_retries is not None else 'unlimited'}")

    if not TELEGRAM_BOT_TOKEN:
        logger.error(f"[Task ID: {task_id}] Telegram bot token is not configured. Cancelling task for chat_id {chat_id}, broadcast_id {broadcast_id}.")
        # Note: Raising an exception here will cause Celery to retry if max_retries not reached,
        # or mark as failed. This behavior is generally desired for unrecoverable config issues.
        raise Exception("Telegram bot token is not configured.")

    kwargs_for_sender = {}
    if parse_mode:
        kwargs_for_sender['parse_mode'] = parse_mode
        logger.debug(f"[Task ID: {task_id}] Using parse_mode: {parse_mode} for chat_id {chat_id}, broadcast_id {broadcast_id}.")
    else:
        logger.debug(f"[Task ID: {task_id}] No explicit parse_mode provided for chat_id {chat_id}, broadcast_id {broadcast_id}. Sender will use its default.")


    success_flag = False
    try:
        logger.debug(f"[Task ID: {task_id}] Attempting to call asyncio.run(send_telegram_message_via_aiogram) for chat_id {chat_id}, broadcast_id {broadcast_id}. Text preview: '{text[:70]}...'")
        success_flag = asyncio.run(
            send_telegram_message_via_aiogram(TELEGRAM_BOT_TOKEN, chat_id, text, **kwargs_for_sender)
        )
        logger.debug(f"[Task ID: {task_id}] send_telegram_message_via_aiogram call completed for chat_id {chat_id}, broadcast_id {broadcast_id}. Success: {success_flag}")

        if success_flag:
            logger.info(f"[Task ID: {task_id}] Message successfully sent to chat_id {chat_id} for broadcast_id {broadcast_id}.")
            logger.debug(f"[Task ID: {task_id}] Attempting to update Broadcast object with pk={broadcast_id} to status SENT.")
            try:
                broadcast = Broadcast.objects.get(pk=broadcast_id)
                logger.debug(f"[Task ID: {task_id}] Broadcast object pk={broadcast_id} retrieved. Current status: {broadcast.status}.")
                broadcast.status = Broadcast.STATUS_CHOICES[3][0] # Assuming STATUS_CHOICES[3] is 'SENT'
                broadcast.save(update_fields=['status'])
                logger.info(f"[Task ID: {task_id}] Broadcast object pk={broadcast_id} status updated to SENT.")
            except Broadcast.DoesNotExist:
                logger.error(f"[Task ID: {task_id}] Broadcast object with pk={broadcast_id} not found. Cannot update status.")
            except Exception as db_exc:
                logger.error(f"[Task ID: {task_id}] Error updating Broadcast object pk={broadcast_id}: {db_exc}", exc_info=True)
            return f"Message successfully sent to chat_id {chat_id} for broadcast_id {broadcast_id}."
        else:
            error_msg = (f"Function send_telegram_message_via_aiogram returned False "
                         f"for chat_id {chat_id}, broadcast_id {broadcast_id} (text: '{text[:50]}...').")
            logger.warning(f"[Task ID: {task_id}] {error_msg} Retrying if attempts left.")
            # self.retry will re-raise an exception that Celery catches
            raise self.retry(exc=Exception(error_msg), countdown=int(self.default_retry_delay * (2 ** self.request.retries))) # Exponential backoff

    except RuntimeError as e:
        # Specific handling for RuntimeError, e.g., event loop issues from asyncio.run if not handled properly inside
        logger.warning(f"[Task ID: {task_id}] RuntimeError occurred for chat_id {chat_id}, broadcast_id {broadcast_id}: {e}. Retrying if attempts left.", exc_info=True)
        raise self.retry(exc=e, countdown=int(self.default_retry_delay * (2 ** self.request.retries)))
    except Exception as e:
        # This will catch exceptions from send_telegram_message_via_aiogram or self.retry itself if it fails
        logger.error(f"[Task ID: {task_id}] Unexpected exception when sending message to chat_id {chat_id}, broadcast_id {broadcast_id}. Retrying if attempts left. Error: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=int(self.default_retry_delay * (2 ** self.request.retries)))