import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


async def send_telegram_message_via_aiogram(token: str, chat_id: int, text: str, **kwargs) -> bool:
    """
    Asynchronously sends a message to a specified Telegram chat ID using Aiogram.

    This function initializes an Aiogram Bot instance, attempts to send the message,
    and handles potential errors such as `TelegramAPIError`, `RuntimeError` (specifically
    checking for "event loop is closed"), and `ValueError` for `chat_id`.
    The bot session is closed in a finally block.

    Args:
        token: The Telegram Bot API token.
        chat_id: The target chat ID to send the message to.
        text: The text content of the message.
        **kwargs: Additional keyword arguments that will be passed to the
                  `bot.send_message` method (e.g., `parse_mode`, `reply_markup`).
                  If `parse_mode` is not provided, it defaults to 'HTML'.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    logger.debug(f"send_telegram_message_via_aiogram called. chat_id: {chat_id}, text preview: '{text[:50]}...'")

    if not token:
        logger.error("ERROR (sender.py): Telegram bot token not provided.")
        return False
    
    if not chat_id:
        logger.error(f"ERROR (sender.py): chat_id not specified for message: {text[:50]}...")
        return False

    masked_token = f"{'*' * (len(token) - 4)}{token[-4:]}" if token and len(token) > 4 else "TOKEN_INVALID_LENGTH_OR_EMPTY"
    logger.debug(f"Initializing Bot instance with token: {masked_token}. Original kwargs before parse_mode pop: {kwargs}")
    
    # The following line modifies kwargs by popping 'parse_mode'
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=kwargs.pop('parse_mode', 'HTML')))
    logger.debug(f"Bot instance initialized. Effective default parse_mode for this bot instance: {bot.default.parse_mode}.")
    
    success = False
    try:
        logger.debug(f"Attempting to use chat_id: '{chat_id}' (type: {type(chat_id)}) for int conversion.")
        chat_id_int = int(chat_id)
        logger.info(f"Attempting to send message to chat_id: {chat_id_int}. Text: '{text[:70]}...'. Remaining kwargs after parse_mode pop: {kwargs}")
        await bot.send_message(chat_id=chat_id_int, text=text, **kwargs)
        logger.info(f"Message successfully sent to chat_id: {chat_id_int}.")
        success = True
    except RuntimeError as e:
        logger.error(f"RUNTIME ERROR (sender.py) when sending to chat_id {chat_id}: {e}", exc_info=True)
        if "event loop is closed" in str(e).lower():
            logger.critical("RuntimeError: Event loop is closed. Re-raising exception as per original logic.")
            raise
        success = False 
    except TelegramAPIError as e:
        logger.error(f"Telegram API ERROR (sender.py) when sending to chat_id {chat_id}: {e}", exc_info=True)
        success = False
    except ValueError: # Catches ValueError from int(chat_id)
        logger.warning(f"VALUE ERROR (sender.py): Invalid chat_id (could not convert to int): '{chat_id}'", exc_info=True)
        success = False
    except Exception as e:
        logger.error(f"UNKNOWN ERROR (sender.py) when sending to chat_id {chat_id}: {e}", exc_info=True)
        success = False
    finally:
        logger.debug(f"Attempting to close bot session for request related to chat_id: {chat_id}.")
        try:
            await bot.session.close()
            logger.debug(f"Bot session closed successfully for request related to chat_id: {chat_id}.")
        except Exception as e:
            logger.error(f"ERROR (sender.py) when closing bot session for request related to chat_id {chat_id}: {e}", exc_info=True)

    logger.debug(f"send_telegram_message_via_aiogram finished for chat_id: {chat_id}. Success: {success}.")
    return success