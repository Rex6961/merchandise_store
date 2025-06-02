import logging
from dataclasses import dataclass
from typing import Any, Optional, TypedDict, TypeAlias, Union
import os

from aiogram import types, Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types.inline_keyboard_markup import InlineKeyboardMarkup
from aiogram.types.input_file import FSInputFile, BufferedInputFile, URLInputFile
from aiogram.types.input_media_photo import InputMediaPhoto
from django.conf import settings

from src.bot.kbd.inline import get_callback_btns


logger = logging.getLogger(__name__)

Image: TypeAlias = Union[FSInputFile, BufferedInputFile, URLInputFile]

class _DeletingRulesTypedDict(TypedDict, total=False):
    message: bool
    callback_query: bool

DeletingRulesType: TypeAlias = Union[_DeletingRulesTypedDict, "DeletingRules"]

@dataclass
class DeletingRules():
    """
    Defines rules for deleting messages associated with an event.

    Attributes:
        message: If True, the original message that triggered the event (if the event is a Message)
                 will be deleted.
        callback_query: If True, the message associated with a CallbackQuery event will be deleted.
    """
    message: bool = False
    callback_query: bool = False


async def send_or_edit_message(
    event: types.Message | types.CallbackQuery,
    text: str,
    image: Image | None = None,
    btns: dict[str, str | CallbackData] | None = None,
    sizes: tuple[int, ...] = (2,),
    markup: InlineKeyboardMarkup | None = None,
    deleting_rules: DeletingRulesType = DeletingRules(),
    previous_ids: list[int] | None = None,
    robust: bool = False
) -> types.Message:
    """
    Sends a new message or edits an existing one, optionally with an image and inline keyboard.

    Handles message deletion based on `deleting_rules` and `previous_ids`.
    If `robust` is True, it attempts to deliver the message even if initial
    edit/delete operations fail, typically by sending a new message.

    Args:
        event: The Aiogram Message or CallbackQuery event that triggers this action.
        text: The text for the message or caption for the image.
        image: An optional Aiogram image object (FSInputFile, BufferedInputFile, URLInputFile)
               to send or use for editing media.
        btns: An optional dictionary to create an inline keyboard. Keys are button text,
              values are callback data.
        sizes: A tuple defining the layout of buttons per row if `btns` is provided.
        markup: An optional pre-built InlineKeyboardMarkup. If provided, `btns` and `sizes`
                are ignored.
        deleting_rules: Rules for deleting messages. Can be a `DeletingRules` object or a
                        dictionary conforming to `_DeletingRulesTypedDict`. Determines if the
                        message associated with the `event` should be deleted.
        previous_ids: An optional list of message IDs to delete before sending/editing.
        robust: If True, the function will try to ensure a message is sent. For example,
                if editing fails due to the message being too old or content type mismatch,
                and `robust` is True, it may delete the old message and send a new one.

    Returns:
        The sent or edited Aiogram `types.Message` object.

    Raises:
        ValueError: If the function cannot determine a valid action based on the event type
                    and internal state (should generally not happen with correct usage).
        TelegramAPIError: Can be raised by Aiogram if Telegram API calls fail and are not
                          handled internally by the `robust` logic or specific error checks.
    """
    logger.info(
        "send_or_edit_message called. Event type: %s, Text: %.30s..., Image: %s, Robust: %s, Deleting rules: %s",
        type(event).__name__, text, "Provided" if image else "None", robust, deleting_rules
    )
    
    if isinstance(deleting_rules, dict):
        deleting_rules_obj = DeletingRules(
            message=deleting_rules.get('message', False),
            callback_query=deleting_rules.get('callback_query', False)
        )
        logger.debug("Deleting_rules provided as dict, converted to DeletingRules object: %s", deleting_rules_obj)
    elif isinstance(deleting_rules, DeletingRules):
        deleting_rules_obj = deleting_rules
        logger.debug("Deleting_rules provided as DeletingRules object: %s", deleting_rules_obj)
    else:
        deleting_rules_obj = DeletingRules()
        logger.debug("Deleting_rules not provided or invalid type, using default: %s", deleting_rules_obj)

    bot: Bot = event.bot

    keyboard: InlineKeyboardMarkup | None = None
    if btns:
        keyboard = get_callback_btns(btns=btns, sizes=sizes)
        logger.debug("Keyboard created from btns.")
    elif markup:
        keyboard = markup
        logger.debug("Keyboard provided via markup.")
    
    chat_id = event.chat.id if isinstance(event, types.Message) else event.message.chat.id
    message_id_to_edit: int | None = None
    
    if isinstance(event, types.CallbackQuery) and event.message:
        message_id_to_edit = event.message.message_id
        logger.debug("Event is CallbackQuery, initial message_id_to_edit set to: %s", message_id_to_edit)


    should_delete_current_event_message = False
    if isinstance(event, types.Message) and deleting_rules_obj.message:
        should_delete_current_event_message = True
        logger.debug("Rule: Current event message (Message type) will be deleted.")
    elif isinstance(event, types.CallbackQuery) and deleting_rules_obj.callback_query and event.message:
        should_delete_current_event_message = True
        logger.debug("Rule: Current event message (CallbackQuery's message) will be deleted.")
        if message_id_to_edit == event.message.message_id: 
            message_id_to_edit = None 
            logger.debug("Message_id_to_edit was the current callback query message, unsetting message_id_to_edit as it will be deleted.")

    if previous_ids:
        logger.debug("Attempting to delete previous messages with IDs: %s in chat %s", previous_ids, chat_id)
        try:
            await bot.delete_messages(chat_id=chat_id, message_ids=previous_ids)
            logger.info("Successfully deleted previous messages: %s in chat %s", previous_ids, chat_id)
            if message_id_to_edit and message_id_to_edit in previous_ids:
                logger.debug("Message_id_to_edit (%s) was in previous_ids, unsetting it.", message_id_to_edit)
                message_id_to_edit = None
        except TelegramAPIError as e:
            logger.error("Error deleting previous_ids messages %s in chat %s: %s", previous_ids, chat_id, e)
            if robust and message_id_to_edit and message_id_to_edit in previous_ids:
                logger.warning("Robust mode: Message_id_to_edit (%s) was in previous_ids that failed to delete, unsetting it.", message_id_to_edit)
                message_id_to_edit = None


    if should_delete_current_event_message:
        current_message_id_to_log = "N/A"
        if isinstance(event, types.Message):
            current_message_id_to_log = event.message_id
        elif isinstance(event, types.CallbackQuery) and event.message:
            current_message_id_to_log = event.message.message_id
        
        logger.debug("Attempting to delete current event message (ID: %s) in chat %s.", current_message_id_to_log, chat_id)
        try:
            if isinstance(event, types.Message):
                await event.delete()
                logger.info("Successfully deleted current event message (Message ID: %s) in chat %s.", event.message_id, chat_id)
            elif isinstance(event, types.CallbackQuery) and event.message:
                await event.message.delete()
                logger.info("Successfully deleted current event message (CallbackQuery's message ID: %s) in chat %s.", event.message.message_id, chat_id)
        except TelegramAPIError as e:
            logger.error("Error deleting current event message (ID: %s) in chat %s: %s", current_message_id_to_log, chat_id, e)
            if robust and message_id_to_edit and current_message_id_to_log == message_id_to_edit: # Only unset if it was the one we failed to delete
                 logger.warning("Robust mode: Failed to delete current event message which was also message_id_to_edit (%s), unsetting message_id_to_edit.", message_id_to_edit)
                 message_id_to_edit = None


    if isinstance(event, types.Message) or not message_id_to_edit:
        logger.info("Sending new message. Reason: Event is Message or no message_id_to_edit. Chat ID: %s", chat_id)
        sent_message: types.Message
        if image:
            logger.debug("Sending new photo message to chat_id: %s", chat_id)
            sent_message = await bot.send_photo(
                chat_id=chat_id,
                photo=image,
                caption=text,
                reply_markup=keyboard
            )
        else:
            logger.debug("Sending new text message to chat_id: %s", chat_id)
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard
            )
        if isinstance(event, types.CallbackQuery):
            await event.answer()
        logger.info("New message sent. Message ID: %s in chat %s", sent_message.message_id, chat_id)
        return sent_message

    elif isinstance(event, types.CallbackQuery) and message_id_to_edit and event.message:
        logger.info("Attempting to edit existing message. Message ID: %s in chat %s", message_id_to_edit, chat_id)
        original_message = event.message 
        try:
            if image:
                if original_message.photo:
                    logger.debug("Editing media (photo) for message ID: %s", message_id_to_edit)
                    media = InputMediaPhoto(media=image, caption=text)
                    await original_message.edit_media(media=media, reply_markup=keyboard)
                else:
                    logger.info("Content type mismatch (original: text, new: photo). Deleting message %s and sending new photo.", message_id_to_edit)
                    await original_message.delete()
                    new_message = await bot.send_photo(
                        chat_id=chat_id, photo=image, caption=text, reply_markup=keyboard
                    )
                    await event.answer()
                    logger.info("Sent new photo message ID: %s after deleting old text message %s.", new_message.message_id, message_id_to_edit)
                    return new_message
            else:
                if original_message.photo:
                    logger.info("Content type mismatch (original: photo, new: text). Deleting message %s and sending new text.", message_id_to_edit)
                    await original_message.delete()
                    new_message = await bot.send_message(
                        chat_id=chat_id, text=text, reply_markup=keyboard
                    )
                    await event.answer()
                    logger.info("Sent new text message ID: %s after deleting old photo message %s.", new_message.message_id, message_id_to_edit)
                    return new_message
                else:
                    logger.debug("Editing text for message ID: %s", message_id_to_edit)
                    await original_message.edit_text(text=text, reply_markup=keyboard)
            
            await event.answer()
            logger.info("Successfully edited message ID: %s", original_message.message_id)
            return original_message

        except TelegramBadRequest as e:
            logger.warning("TelegramBadRequest during edit for message ID %s: %s", message_id_to_edit, e)
            if "message is not modified" in str(e).lower():
                logger.info("Message %s was not modified, answering callback.", message_id_to_edit)
                await event.answer()
                return original_message
            
            error_triggers_resend = (
                "message can't be edited" in str(e).lower() or
                "message to edit not found" in str(e).lower() or
                (image and original_message.text and not original_message.photo) or
                (not image and original_message.photo)
            )

            if error_triggers_resend:
                logger.warning("Failed to edit message ID %s (BadRequest: %s), attempting to send new message instead.", message_id_to_edit, e)
                if robust or (deleting_rules_obj.callback_query and original_message): # Original message might have been deleted if it was the callback query message and rules said so
                    if original_message and original_message.message_id: # Check if original_message is still valid
                        logger.debug("Attempting to delete original message %s before resending due to edit failure.", original_message.message_id)
                        try:
                            await original_message.delete()
                            logger.info("Successfully deleted original message %s before resending.", original_message.message_id)
                        except TelegramAPIError as del_e:
                            logger.error("Error deleting message %s before resending: %s", original_message.message_id, del_e)
                    else:
                        logger.debug("Original message for ID %s was likely already deleted or unavailable, skipping deletion before resend.", message_id_to_edit)

                new_sent_message: types.Message
                if image:
                    logger.debug("Resending as new photo message to chat_id: %s", chat_id)
                    new_sent_message = await bot.send_photo(
                        chat_id=chat_id, photo=image, caption=text, reply_markup=keyboard
                    )
                else:
                    logger.debug("Resending as new text message to chat_id: %s", chat_id)
                    new_sent_message = await bot.send_message(
                        chat_id=chat_id, text=text, reply_markup=keyboard
                    )
                await event.answer()
                logger.info("Sent new message ID: %s after edit failure of message %s.", new_sent_message.message_id, message_id_to_edit)
                return new_sent_message
            else:
                await event.answer("Failed to update message.")
                logger.error("Unhandled TelegramBadRequest during edit for message ID %s: %s. Answered callback with failure.", message_id_to_edit, e)
                return original_message
        
        except TelegramAPIError as e:
            logger.error("TelegramAPIError during edit for message ID %s: %s", message_id_to_edit, e)
            if robust:
                logger.warning("Robust mode: TelegramAPIError during edit for message ID %s. Attempting to send new message.", message_id_to_edit)
                new_sent_message_robust: types.Message
                if image:
                    logger.debug("Robust resend: Sending new photo message to chat_id: %s", chat_id)
                    new_sent_message_robust = await bot.send_photo(
                        chat_id=chat_id, photo=image, caption=text, reply_markup=keyboard
                    )
                else:
                    logger.debug("Robust resend: Sending new text message to chat_id: %s", chat_id)
                    new_sent_message_robust = await bot.send_message(
                        chat_id=chat_id, text=text, reply_markup=keyboard
                    )
                await event.answer()
                logger.info("Robust resend: Sent new message ID: %s after TelegramAPIError on message %s.", new_sent_message_robust.message_id, message_id_to_edit)
                return new_sent_message_robust
            else:
                await event.answer("An error occurred during update.")
                logger.warning("TelegramAPIError during edit for message ID %s, not in robust mode. Answered callback with error.", message_id_to_edit)
                return original_message if original_message else None
    
    logger.warning("send_or_edit_message reached an unexpected state. Event type: %s, Chat ID: %s, Message ID to edit: %s", type(event), chat_id, message_id_to_edit)
    if isinstance(event, types.CallbackQuery):
        await event.answer("An internal error occurred.")
        logger.error("Answered callback with internal error due to unexpected state in send_or_edit_message.")
    if isinstance(event, types.CallbackQuery) and event.message:
        return event.message
    logger.critical("send_or_edit_message could not determine action and is raising ValueError. Event: %s", event)
    raise ValueError("send_or_edit_message could not determine action.")


def get_fs_input_file_for_product(
    image_field: Any,
    base_media_path_in_bot_env: str = settings.MEDIA_ROOT
) -> Optional[FSInputFile]:
    """
    Creates an FSInputFile object for a product image stored on the filesystem.

    This function takes a Django image field (or any object with a `name` attribute
    representing the relative path to the image within the media directory) and
    constructs an absolute path to the image file that the bot can access.
    It checks for the file's existence and readability.

    Args:
        image_field: A Django ImageField or FileField instance, or any object
                     that has a `.name` attribute containing the relative path
                     of the image file from the `MEDIA_ROOT`.
        base_media_path_in_bot_env: The absolute base path to the media directory
                                    as accessible by the bot's environment.
                                    Defaults to `settings.MEDIA_ROOT`.

    Returns:
        An `FSInputFile` object if the image file is found and accessible,
        otherwise `None`.
    """
    logger.debug(
        "get_fs_input_file_for_product called. Image_field name: %s, Base media path: %s",
        getattr(image_field, 'name', 'N/A'), base_media_path_in_bot_env
    )
    if not image_field or not image_field.name:
        logger.debug("get_fs_input_file_for_product: image_field is None or image_field.name is empty.")
        return None

    relative_path_to_image = image_field.name
    absolute_path_for_bot = os.path.join(base_media_path_in_bot_env, relative_path_to_image)

    logger.debug(
        "get_fs_input_file_for_product: Attempting to access file at (for bot): '%s' (Base: '%s', Relative: '%s')",
        absolute_path_for_bot, base_media_path_in_bot_env, relative_path_to_image
    )

    try:
        if os.path.exists(absolute_path_for_bot):
            if os.access(absolute_path_for_bot, os.R_OK):
                logger.info("get_fs_input_file_for_product: File found and readable: '%s'", absolute_path_for_bot)
                return FSInputFile(absolute_path_for_bot)
            else:
                logger.warning("get_fs_input_file_for_product: File found but not readable (permission issue?): '%s'", absolute_path_for_bot)
                return None
        else:
            logger.warning("get_fs_input_file_for_product: File NOT FOUND at (for bot): '%s'", absolute_path_for_bot)
            return None
    except Exception as e:
        logger.error("get_fs_input_file_for_product: Error creating FSInputFile for '%s': %s", absolute_path_for_bot, e)
        return None
    