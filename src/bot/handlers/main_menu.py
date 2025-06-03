import logging
from aiogram import F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import Scene, on

from bot.misc.utils import send_or_edit_message

logger = logging.getLogger(__name__)

class MainMenu(Scene, state="main_menu"):
    
    @on.message.enter()
    @on.callback_query.enter()
    async def on_enter(self, event: Message | CallbackQuery, state: FSMContext):
        """
        Handles entry into the main menu scene.

        Sends a welcome message and displays the main menu buttons.

        Args:
            event: The Message or CallbackQuery that triggered the scene entry.
            state: The FSMContext for managing state data.
        """
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.info(f"MainMenu scene: 'on_enter' triggered by {event_type} for user_id: {user_id}.")
        
        if isinstance(event, CallbackQuery): # Critical: Answer callback query if it's an entry point
            await event.answer()
            logger.debug(f"MainMenu.on_enter: Answered callback query {event.id} for user_id: {user_id}.")

        await send_or_edit_message(
            event=event,
            text="Welcome to our CTH Store", # "Добро пожаловать в наш Магазин CTH"
            btns={
                "Catalog": "goto_catalog", # "Каталог"
                "Cart": "goto_cart", # "Корзина"
                "FAQ": "goto_faq"
            },
            sizes=(2, 1),
            deleting_rules={"message": True}, # This implies if event is Message, it will be deleted.
                                             # If event is CallbackQuery, its associated message might be deleted if send_or_edit decides to send new.
            robust=True
        )
        logger.debug(f"MainMenu.on_enter: Welcome message sent/edited for user_id: {user_id}.")

    @on.callback_query(F.data == "goto_catalog")
    async def goto_game_menu(self, callback: CallbackQuery, state: FSMContext):
        """
        Handles the callback query to navigate to the catalog scene.

        Args:
            callback: The CallbackQuery triggered by the "Каталог" button.
            state: The FSMContext for managing state data.
        """
        user_id = callback.from_user.id
        logger.info(f"MainMenu scene: 'goto_game_menu' (-> catalog) triggered by callback_query (data: {callback.data}) for user_id: {user_id}.")
        await callback.answer() # Critical: Answer callback query
        logger.debug(f"MainMenu.goto_game_menu: Answered callback query {callback.id} for user_id: {user_id}.")
        await self.wizard.goto("catalog")
        logger.info(f"MainMenu.goto_game_menu: User {user_id} navigated to 'catalog' scene.")

    @on.callback_query(F.data == "goto_cart")
    async def goto_statistics(self, callback: CallbackQuery, state: FSMContext):
        """
        Handles the callback query to navigate to the cart scene.

        Args:
            callback: The CallbackQuery triggered by the "Корзина" button.
            state: The FSMContext for managing state data.
        """
        user_id = callback.from_user.id
        logger.info(f"MainMenu scene: 'goto_statistics' (-> cart) triggered by callback_query (data: {callback.data}) for user_id: {user_id}.")
        await callback.answer() # Critical: Answer callback query
        logger.debug(f"MainMenu.goto_statistics: Answered callback query {callback.id} for user_id: {user_id}.")
        await self.wizard.goto("cart")
        logger.info(f"MainMenu.goto_statistics: User {user_id} navigated to 'cart' scene.")
    
    @on.callback_query(F.data == "goto_faq")
    async def goto_leader_board(self, callback: CallbackQuery, state: FSMContext):
        """
        Handles the callback query to navigate to the FAQ scene.

        Args:
            callback: The CallbackQuery triggered by the "FAQ" button.
            state: The FSMContext for managing state data.
        """
        user_id = callback.from_user.id
        logger.info(f"MainMenu scene: 'goto_leader_board' (-> faq) triggered by callback_query (data: {callback.data}) for user_id: {user_id}.")
        await callback.answer() # Critical: Answer callback query
        logger.debug(f"MainMenu.goto_leader_board: Answered callback query {callback.id} for user_id: {user_id}.")
        await self.wizard.goto("faq")
        logger.info(f"MainMenu.goto_leader_board: User {user_id} navigated to 'faq' scene.")


    @on.callback_query.exit()
    @on.message.exit()
    async def exit(self, event: Message | CallbackQuery, state: FSMContext):
        """Действие при выходе из сцены."""
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.debug(f"MainMenu scene: 'exit' hook triggered by {event_type} for user_id: {user_id}.")
        # No critical actions here, just logging.
        pass

    @on.callback_query.leave()
    @on.message.leave()
    async def leave(self, event: Message | CallbackQuery, state: FSMContext):
        """Действие при выходе из сцены."""
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.debug(f"MainMenu scene: 'leave' hook triggered by {event_type} for user_id: {user_id}.")
        # No critical actions here, just logging.
        pass