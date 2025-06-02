import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.scene import SceneRegistry
from aiogram.fsm.storage.memory import SimpleEventIsolation


logger = logging.getLogger(__name__)


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'admin_panel.merchandise_store.settings')
import django
try:
    logger.debug("Attempting Django setup at script initialization.")
    django.setup()
    logger.info("Django setup successful at script initialization.")
except Exception as e:
    logger.critical(f"Failed to set up Django at script initialization: {e}")
    exit(1)
# Django needs to be configured before importing modules that use Django models (e.g., handlers).


from bot.config import settings as bot_config
from bot.middlewares import CheckSubscription
from bot.handlers.private import private_router
from bot.handlers.common import common_router
from bot.handlers import (
    MainMenu,
    Catalog,
    Cart,
    FAQ
)



def setup_django():
    """
    Initializes and configures the Django environment for the bot.

    This function sets the `DJANGO_SETTINGS_MODULE` environment variable if not already set,
    and then calls `django.setup()` to load Django settings and applications.
    This is necessary for the bot to interact with Django models and other ORM features.

    Raises:
        ImportError: If Django is not installed or `DJANGO_SETTINGS_MODULE` points to an invalid path.
        Exception: For other errors during Django setup.
    """
    logger.info("Attempting to set up Django.")
    try:
        # DJANGO_SETTINGS_MODULE is already set globally, but this ensures it if called independently.
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin_panel.merchandise_store.settings")
        import django # Re-importing locally to ensure context, though already imported globally.
        logger.debug("Calling django.setup().")
        django.setup()
        logger.info("Django successfully configured for the bot.")
    except ImportError:
        logger.error("Failed to import Django. Ensure it is installed and PYTHONPATH is configured.")
        raise
    except Exception as e:
        logger.exception(f"An error occurred during Django setup: {e}")
        raise


def create_dispatcher() -> Dispatcher:
    """
    Creates and configures the Aiogram Dispatcher.

    Sets up event isolation (SimpleEventIsolation) to correctly handle fast user responses,
    registers routers for common and private handlers, initializes and registers scenes
    (MainMenu, Catalog, Cart, FAQ), and registers middleware like CheckSubscription.

    Returns:
        Dispatcher: The configured Aiogram Dispatcher instance.
    """
    logger.info("Creating Aiogram Dispatcher.")
    dispatcher = Dispatcher(
        events_isolation=SimpleEventIsolation(),
    )
    logger.debug("Dispatcher created with SimpleEventIsolation.")

    logger.debug("Including common and private routers.")
    dispatcher.include_routers(common_router, private_router)
    logger.info("Common and private routers included.")

    logger.debug("Initializing SceneRegistry.")
    scene_registry = SceneRegistry(dispatcher)
    
    logger.debug("Adding scenes: MainMenu, Catalog, Cart, FAQ.")
    scene_registry.add(
        MainMenu,
        Catalog,
        Cart,
        FAQ
    )
    logger.info("Scenes added to SceneRegistry.")

    logger.debug("Registering CheckSubscription outer middleware for updates.")
    dispatcher.update.outer_middleware.register(CheckSubscription())
    logger.info("CheckSubscription middleware registered.")

    logger.info("Dispatcher configuration complete.")
    return dispatcher

async def main() -> None:
    """
    The main asynchronous function to initialize and run the Telegram bot.

    It performs the following steps:
    1. Ensures Django is set up for ORM interaction.
    2. Retrieves the bot token from configuration.
    3. Creates an Aiogram Bot instance with HTML parse mode as default.
    4. Creates and configures the Dispatcher.
    5. Deletes any pending webhook updates (drop_pending_updates=True) to ensure
       the bot processes only new messages received after it starts.
    6. Starts polling for updates from Telegram.
    Handles graceful shutdown on KeyboardInterrupt or SystemExit.
    """
    logger.info("Starting main bot execution.")
    
    try:
        logger.debug("Calling setup_django() from main.")
        setup_django() # Called again to ensure it's logged within main context, though already done globally.
    except Exception:
        logger.critical("Failed to start bot due to Django setup error in main. Exiting.")
        return

    logger.debug("Retrieving bot token from configuration.")
    TOKEN = bot_config.bot.token.get_secret_value() if hasattr(bot_config.bot.token, 'get_secret_value') else bot_config.bot.token
    if not TOKEN:
        logger.critical("Telegram bot token not found in configuration! Bot cannot be started. Exiting.")
        return
    logger.info("Bot token retrieved successfully.")
    masked_token = f"{'*' * (len(TOKEN) - 4)}{TOKEN[-4:]}" if TOKEN and len(TOKEN) > 4 else "TOKEN_INVALID_LENGTH_OR_EMPTY"
    logger.debug(f"Using token: {masked_token}")


    logger.debug("Creating dispatcher.")
    dp = create_dispatcher()
    logger.info("Dispatcher created.")
    
    logger.debug("Creating Bot instance with default ParseMode.HTML.")
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    logger.info("Bot instance created.")

    try:
        logger.info("Attempting to delete webhook and drop pending updates.")
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted and pending updates dropped.")
        logger.info("Starting bot polling...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception(f"Error during bot polling: {e}")
    finally:
        logger.info("Closing bot session.")
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    logger.info("Script executed directly. Running main asynchronous function.")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested by user (KeyboardInterrupt/SystemExit).")
    except Exception as e:
        logger.critical(f"Critical error during bot execution: {e}")