import logging
from typing import Any, Dict, Callable, Awaitable

from aiogram import BaseMiddleware, Bot
from aiogram.types import Update, User
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from asgiref.sync import sync_to_async

from admin_panel.clients.models import Channel

logger = logging.getLogger(__name__)

@sync_to_async
def get_channel_uids() -> set[int]:
    """
    Asynchronously retrieves a set of active channel IDs from the database.

    Returns:
        A set of integer channel IDs that are marked as active.
    """
    logger.debug("Attempting to retrieve active channel UIDs from database.")
    channel_id = Channel.objects.filter(is_active=True).values_list('channel_id', flat=True)
    result_set = set(channel_id)
    logger.info(f"Retrieved {len(result_set)} active channel UIDs: {result_set}")
    return result_set

class CheckSubscription(BaseMiddleware):
    """
    Middleware to check if a user is subscribed to required channels.

    If the user is not subscribed to all active channels, it sends a message
    listing the channels they still need to join and stops further processing
    of the update for the current handler.
    """

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        """
        Processes the incoming update to check user's channel subscriptions.

        Args:
            handler: The next handler in the processing chain.
            event: The incoming Aiogram Update object.
            data: A dictionary containing data passed between middlewares and handlers.
                  Expected keys: 'event_from_user' (User object), 'bot' (Bot instance).

        Returns:
            The result of the next handler if the user is subscribed to all channels,
            or sends a message to the user and stops propagation if not.
        """
        logger.debug(f"CheckSubscription middleware called for update_id: {event.update_id}")
        
        if "event_from_user" not in data:
            logger.debug("'event_from_user' not in data, skipping subscription check.")
            return await handler(event, data)

        logger.debug("Fetching channel UIDs for subscription check.")
        chat_uid = await get_channel_uids()
        logger.info(f"Required channel UIDs for subscription: {chat_uid}")

        event_user: User = data['event_from_user']
        bot: Bot = data["bot"]
        logger.info(f"Checking subscription for user_id: {event_user.id}")

        left = set()
        for chat_id in chat_uid:
            logger.debug(f"Checking subscription for user_id: {event_user.id} in chat_id: {chat_id}")
            try:
                chat_member = await bot.get_chat_member(chat_id, event_user.id)
                logger.debug(f"User {event_user.id} status in chat {chat_id}: {chat_member.status}")
                if chat_member.status == ChatMemberStatus.LEFT:
                    logger.info(f"User {event_user.id} is not subscribed to chat_id: {chat_id} (status: LEFT).")
                    chat_info = await bot.get_chat(chat_id)
                    logger.debug(f"Retrieved chat info for chat_id: {chat_id}, title: {chat_info.title}")
                    chat_invite_link = await bot.create_chat_invite_link(chat_id)
                    logger.debug(f"Created invite link for chat_id: {chat_id}: {chat_invite_link.invite_link}")
                    left.add(f"* {f'{chat_info.title} - ' if chat_info.title else ''}{chat_invite_link.invite_link}")
            except TelegramBadRequest:
                logger.warning(f"Failed to get chat member info for chat_id {chat_id} or user {event_user.id} is not a member. This chat might be inaccessible or the bot lacks permissions.")
        
        if not left:
            logger.info(f"User {event_user.id} is subscribed to all required channels. Proceeding with handler.")
            return await handler(event, data)
        else:
            logger.info(f"User {event_user.id} is not subscribed to the following channels: {left}. Sending notification.")
            message_text = f"You need to subscribe to:\n{'\n\t'.join(left)}"
            if event.message: # Ensure message exists before trying to answer
                logger.debug(f"Sending subscription reminder to user {event_user.id} via message reply.")
                await event.message.answer(message_text)
            elif event.callback_query and event.callback_query.message: # Handle callback queries
                logger.debug(f"Sending subscription reminder to user {event_user.id} via callback query message reply.")
                await event.callback_query.message.answer(message_text)
                await event.callback_query.answer() # Answer callback query to remove "loading" state
                logger.debug(f"Answered callback query for user {event_user.id}.")
            else:
                logger.warning(f"Cannot send subscription reminder to user {event_user.id}: No suitable message or callback_query context found in the event.")
            logger.info(f"Subscription check failed for user {event_user.id}. Update processing stopped for this handler.")
            return # Stop processing this update for the current handler