import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import ScenesManager

logger = logging.getLogger(__name__)
private_router = Router()


@private_router.message(Command("menu"))
@private_router.callback_query(F.data == "goto_main_menu")
async def start_menu(event: Message | CallbackQuery, state: FSMContext, scenes: ScenesManager):
    """
    Handles the /menu command and "goto_main_menu" callback query.

    Clears the current FSM state and transitions the user to the "main_menu" scene.

    Args:
        event: The incoming Message or CallbackQuery object.
        state: The FSMContext for managing finite state machine data.
        scenes: The ScenesManager for controlling scene transitions.
    """
    user_id = event.from_user.id if event.from_user else "UnknownUser"
    event_type = type(event).__name__
    
    if isinstance(event, Message):
        logger.info(f"Handler 'start_menu' triggered by {event_type} (command: /menu) from user_id: {user_id}.")
    elif isinstance(event, CallbackQuery):
        logger.info(f"Handler 'start_menu' triggered by {event_type} (data: {event.data}) from user_id: {user_id}.")
        await event.answer()
        logger.debug(f"Callback query {event.id} answered for user_id: {user_id}.")


    current_state = await state.get_state()
    logger.debug(f"User {user_id}: Current FSM state before clearing: {current_state}")
    await state.clear()
    logger.info(f"User {user_id}: FSM state cleared.")
    
    logger.debug(f"User {user_id}: Attempting to enter scene 'main_menu'.")
    await scenes.enter("main_menu")
    logger.info(f"User {user_id}: Successfully entered scene 'main_menu'.")