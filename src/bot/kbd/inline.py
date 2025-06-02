import logging
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)

def get_callback_btns(
    *,
    btns: dict[str, str | CallbackData],
    sizes: tuple[int, ...] = (2,)
) -> InlineKeyboardMarkup:
    """
    Creates an Aiogram InlineKeyboardMarkup from a dictionary of buttons and layout sizes.

    Args:
        btns: A dictionary where keys are button labels (str) and values are
              their corresponding callback data (str or CallbackData instance).
        sizes: A tuple of integers defining the number of buttons per row.
               For example, (2,) means 2 buttons per row. (1, 2) means
               1 button in the first row, 2 in the second, and then repeats
               this pattern for subsequent buttons. Defaults to (2,).

    Returns:
        An InlineKeyboardMarkup object configured with the specified buttons and layout.
    """
    logger.debug(f"get_callback_btns called. Number of buttons: {len(btns)}, Sizes: {sizes}")
    keyboard = InlineKeyboardBuilder()
    
    if not btns:
        logger.warning("get_callback_btns called with an empty 'btns' dictionary. Returning an empty keyboard markup.")
        # Return an empty markup if no buttons are provided, adjust might fail or be meaningless
        return keyboard.as_markup()


    for text, callback_data in btns.items():
        logger.debug(f"Adding button: Text='{text}', CallbackData='{callback_data}' (type: {type(callback_data)})")
        keyboard.button(text=text, callback_data=callback_data)
    
    logger.debug(f"Adjusting keyboard layout with sizes: {sizes}")
    adjusted_keyboard = keyboard.adjust(*sizes).as_markup()
    logger.info(f"InlineKeyboardMarkup created with {len(btns)} buttons and layout sizes {sizes}.")
    return adjusted_keyboard