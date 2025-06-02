import logging
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from asgiref.sync import sync_to_async

from admin_panel.clients.models import TelegramUser

logger = logging.getLogger(__name__)
common_router = Router()

@sync_to_async
def get_or_create_user(telegram_id: int, username: str | None, first_name: str | None):
    """
    Asynchronously gets or creates a TelegramUser in the Django database.

    If the user exists, it checks if their username or first_name has changed
    and updates the record if necessary.

    Args:
        telegram_id: The Telegram ID of the user.
        username: The Telegram username of the user (can be None).
        first_name: The Telegram first name of the user (can be None).

    Returns:
        A tuple containing:
        - The TelegramUser object (either retrieved or newly created).
        - A boolean indicating whether the user was created (True) or retrieved (False).
    """
    logger.debug(f"Attempting to get or create user. Telegram ID: {telegram_id}, Username: {username}, First Name: {first_name}")
    user, created = TelegramUser.objects.get_or_create(
        telegram_id=telegram_id,
        defaults={
            'username': username,
            'first_name': first_name,
        }
    )
    if created:
        logger.info(f"New user saved to DB: ID {telegram_id}, Username: {username}, First Name: {first_name}")
    elif user.username != username or user.first_name != first_name:
        logger.info(f"User data for ID {telegram_id} needs update. Old: username='{user.username}', first_name='{user.first_name}'. New: username='{username}', first_name='{first_name}'.")
        user.username = username
        user.first_name = first_name
        user.save(update_fields=['username', 'first_name'])
        logger.info(f"User data for ID {telegram_id} updated in DB.")
    else:
        logger.debug(f"User ID {telegram_id} found in DB. No data changes detected.")
    return user, created

@common_router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Handles the /start command.

    Greets the user and saves or updates their information in the database.
    Logs the interaction and handles potential errors during database operations.

    Args:
        message: The Aiogram Message object representing the incoming /start command.
    """
    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    logger.info(f"Command /start received from user_id: {telegram_id}, username: {username}, first_name: {first_name}.")

    try:
        logger.debug(f"Calling get_or_create_user for user_id: {telegram_id}.")
        user_obj, created = await get_or_create_user(telegram_id, username, first_name)
        logger.debug(f"get_or_create_user returned: created={created} for user_id: {telegram_id}.")
        
        greeting_name = first_name or username or "User" # Fallback name

        if created:
            logger.info(f"New user {telegram_id} ({username}) processed by /start. Sending welcome message.")
            await message.answer(f"Hello, {greeting_name}! Nice to meet you. You are registered.") # "Привет, {first_name or username}! Рад знакомству. Вы зарегистрированы."
        else:
            logger.info(f"Existing user {telegram_id} ({username}) processed by /start. Sending welcome back message.")
            await message.answer(f"Welcome back, {greeting_name}!") # "Снова здравствуйте, {first_name or username}!"
        
        logger.info(f"User {telegram_id} ({username}) executed /start command successfully.")

    except Exception as e:
        logger.exception(f"Error processing /start for user {telegram_id}: {e}")
        await message.answer("An error occurred during registration. Please try again later.") # "Произошла ошибка при регистрации. Пожалуйста, попробуйте позже."