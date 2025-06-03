import logging
from typing import Optional, Sequence, Any, Union

from aiogram import F
from aiogram.types import Message, CallbackQuery
from aiogram.filters.callback_data import CallbackData
from aiogram.filters import StateFilter, and_f
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import SceneWizard, Scene, on
from aiogram.fsm.state import State, StatesGroup
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist

from bot.handlers.private import private_router
from bot.misc.utils import send_or_edit_message, get_fs_input_file_for_product
from bot.misc.paginator import Paginator, MovePage, PageNode, PageContent, UID_TYPE
from admin_panel.clients.models import Category, Product, UserCartItem, TelegramUser

logger = logging.getLogger(__name__)

class AddToCart(CallbackData, prefix="add_to_cart"):
    product_id: int
    
class ProductProcessing(StatesGroup):
    set_quantity = State()
    confirm = State()


async def catalog_loader_function(
    uid: UID_TYPE,
    limit: int,
    cursor: int,
    **kwargs: Any
) -> tuple[Optional[Sequence[PageNode]], bool]:
    """
    Asynchronously loads catalog items (categories and products) for pagination.

    This function fetches data from the database based on the provided UID (unique identifier),
    limit, and cursor. It handles different types of UIDs, such as "catalog_root" for
    top-level categories, and "category_X" for subcategories and products within a category.

    Args:
        uid: The unique identifier for the current catalog level.
             Can be "catalog_root" or "category_<id>".
        limit: The maximum number of items to fetch for the current page.
        cursor: The starting point (offset) for fetching items.
        **kwargs: Additional keyword arguments (not used in this function).

    Returns:
        A tuple containing:
        - An optional sequence of PageNode objects representing the fetched catalog items.
          Returns None if an error occurs.
        - A boolean indicating whether there are more items to load (True) or not (False).
    """
    logger.debug(f"catalog_loader_function called. UID: {uid}, Limit: {limit}, Cursor: {cursor}, Kwargs: {kwargs}")
    
    try:
        BASE_MEDIA_PATH_FOR_BOT_FILESYSTEM = settings.MEDIA_ROOT
        if not BASE_MEDIA_PATH_FOR_BOT_FILESYSTEM:
             logger.critical("CRITICAL WARNING: settings.MEDIA_ROOT is not set or empty! Falling back to /app/mediafiles/.")
             BASE_MEDIA_PATH_FOR_BOT_FILESYSTEM = "/app/mediafiles/" 
    except (NameError, AttributeError, ImportError): 
        logger.warning("WARNING: Django settings.MEDIA_ROOT not available or not configured. Using hardcoded path /app/mediafiles/ for media.")
        BASE_MEDIA_PATH_FOR_BOT_FILESYSTEM = "/app/mediafiles/"

    effective_limit_for_query = limit + 1
    parent_category_id: Optional[int] = None
    current_node_type: str

    if uid == "catalog_root":
        current_node_type = "root"
        logger.debug("UID is 'catalog_root', processing top-level categories.")
    elif isinstance(uid, str) and uid.startswith("category_"):
        try:
            parent_category_id = int(uid.split("_")[1])
            current_node_type = "category"
            logger.debug(f"UID is category specific: '{uid}', Parent Category ID: {parent_category_id}.")
        except (IndexError, ValueError):
            logger.error(f"Error: Invalid category UID format: {uid}")
            return None, False
    else:
        logger.error(f"Error: Unknown UID type for catalog_loader: {uid}")
        return None, False

    @sync_to_async
    def _fetch_data_from_db_sync():
        logger.debug(f"DB Query: Fetching data for node_type='{current_node_type}', parent_id={parent_category_id}, cursor={cursor}, effective_limit={effective_limit_for_query}")
        fetched_orm_items: list[Union[Category, Product]] = []

        if current_node_type == "root":
            categories_qs = Category.objects.filter(parent__isnull=True).order_by('name')
            fetched_orm_items.extend(list(categories_qs[cursor : cursor + effective_limit_for_query]))
            logger.debug(f"DB Query (root): Fetched {len(fetched_orm_items)} top-level categories.")
        
        elif current_node_type == "category" and parent_category_id is not None:
            num_subcategories_of_parent = Category.objects.filter(parent_id=parent_category_id).count()
            logger.debug(f"DB Query (category {parent_category_id}): Found {num_subcategories_of_parent} subcategories.")
            
            if cursor < num_subcategories_of_parent:
                subcategories_to_fetch_count = min(effective_limit_for_query, num_subcategories_of_parent - cursor)
                subcat_qs = Category.objects.filter(parent_id=parent_category_id).order_by('name')
                fetched_orm_items.extend(list(subcat_qs[cursor : cursor + subcategories_to_fetch_count]))
                logger.debug(f"DB Query (category {parent_category_id}): Fetched {len(fetched_orm_items)} subcategories (requested {subcategories_to_fetch_count}).")

            remaining_limit_for_products = effective_limit_for_query - len(fetched_orm_items)
            if remaining_limit_for_products > 0:
                product_cursor_offset = max(0, cursor - num_subcategories_of_parent)
                products_qs = Product.objects.filter(category_id=parent_category_id).order_by('name')
                products_fetched = list(products_qs[product_cursor_offset : product_cursor_offset + remaining_limit_for_products])
                fetched_orm_items.extend(products_fetched)
                logger.debug(f"DB Query (category {parent_category_id}): Fetched {len(products_fetched)} products (remaining_limit={remaining_limit_for_products}, offset={product_cursor_offset}).")
        
        logger.debug(f"DB Query: Total ORM items fetched: {len(fetched_orm_items)} for UID {uid}.")
        return fetched_orm_items

    try:
        orm_items_result = await _fetch_data_from_db_sync()
    except Exception as e:
        logger.error(f"Error fetching catalog data from DB for UID {uid}: {e}", exc_info=True)
        return None, False

    page_nodes_to_return: list[PageNode] = []
    has_more_items: bool = False

    if len(orm_items_result) == effective_limit_for_query:
        has_more_items = True
        items_to_convert_to_nodes = orm_items_result[:-1] # Exclude the extra item
        logger.debug(f"More items available beyond this page (has_more_items=True). Processing {len(items_to_convert_to_nodes)} items for nodes.")
    else:
        items_to_convert_to_nodes = orm_items_result
        logger.debug(f"No more items available beyond this page (has_more_items=False). Processing {len(items_to_convert_to_nodes)} items for nodes.")


    for item_idx, item in enumerate(items_to_convert_to_nodes):
        logger.debug(f"Processing item {item_idx + 1}/{len(items_to_convert_to_nodes)}: Type {type(item).__name__}, ID {item.id if hasattr(item, 'id') else 'N/A'}")
        if isinstance(item, Category):
            content = PageContent(
                label=item.name,
                text=f"Category: {item.name}", # "Категория: {item.name}"
                is_leaf_node=False 
            )
            page_nodes_to_return.append(
                PageNode(uid=f"category_{item.id}", content=content)
            )
            logger.debug(f"Created PageNode for Category ID {item.id}, Name: {item.name}")
        elif isinstance(item, Product):
            logger.debug(f"Attempting to get FSInputFile for Product ID {item.id}, Image field name: {getattr(item.image, 'name', 'N/A')}")
            aiogram_image = get_fs_input_file_for_product(
                item.image, 
                BASE_MEDIA_PATH_FOR_BOT_FILESYSTEM
            )
            if aiogram_image:
                logger.debug(f"FSInputFile created for Product ID {item.id}: {aiogram_image.path}")
            else:
                logger.warning(f"Could not create FSInputFile for Product ID {item.id}. Image might be missing or inaccessible.")

            product_text = (
                f"<b>{item.name}</b>\n\n"
                f"{item.description}\n\n"
                f"Price: {item.price} RUB\n" # "Цена: {item.price} руб.\n"
                f"In stock: {item.stock} pcs." # "На складе: {item.stock} шт."
            )
            content = PageContent(
                label=item.name,
                text=product_text,
                image=aiogram_image,
                is_leaf_node=True
            )
            page_nodes_to_return.append(
                PageNode(
                    uid=f"product_{item.id}",
                    content=content,
                    custom_kbd={"Add to cart 🛒": AddToCart(product_id=item.id)} # "Добавить в корзину 🛒"
                )
            )
            logger.debug(f"Created PageNode for Product ID {item.id}, Name: {item.name}")
            
    logger.info(f"catalog_loader_function for UID {uid} returning {len(page_nodes_to_return)} nodes, has_more: {has_more_items}.")
    return page_nodes_to_return, has_more_items


# Функии для работы с базой данных
@sync_to_async
def get_product(product_id) -> Product:
    """
    Asynchronously retrieves a product from the database by its ID.

    Args:
        product_id: The ID of the product to retrieve.

    Returns:
        The Product object.
    """
    logger.debug(f"Attempting to retrieve product with ID: {product_id}")
    try:
        product = Product.objects.get(id=product_id)
        logger.info(f"Product with ID {product_id} retrieved successfully: {product.name}")
        return product
    except ObjectDoesNotExist:
        logger.error(f"Product with ID {product_id} does not exist.")
        raise # Re-raise the exception to be handled by the caller
    except Exception as e:
        logger.error(f"Error retrieving product with ID {product_id}: {e}", exc_info=True)
        raise

@sync_to_async
def add_product_to_user_cart(telegram_user_id: int, quantity: int, product_id: Any):
    """
    Asynchronously adds a specified quantity of a product to a user's cart.

    Args:
        telegram_user_id: The Telegram ID of the user.
        quantity: The quantity of the product to add.
        product_id: The ID of the product to add.
    """
    logger.debug(f"Attempting to add product to cart. User ID: {telegram_user_id}, Product ID: {product_id}, Quantity: {quantity}")
    try:
        product = Product.objects.get(id=product_id)
        logger.debug(f"Retrieved product: {product.name} (ID: {product_id})")
        user = TelegramUser.objects.get(telegram_id=telegram_user_id)
        logger.debug(f"Retrieved user: {user.username or user.first_name} (Telegram ID: {telegram_user_id})")
        
        # Check if item already in cart, if so, update quantity or create new
        cart_item, created = UserCartItem.objects.get_or_create(
            user=user,
            product=product,
            defaults={'quantity': quantity}
        )
        if created:
            logger.info(f"New cart item created for User ID {telegram_user_id}, Product ID {product_id}, Quantity {quantity}.")
        else:
            cart_item.quantity += quantity # Or set to quantity, depending on desired logic. Assuming adding.
            cart_item.save(update_fields=['quantity'])
            logger.info(f"Updated cart item quantity for User ID {telegram_user_id}, Product ID {product_id}. New quantity: {cart_item.quantity}.")
        
    except ObjectDoesNotExist as e:
        logger.error(f"Failed to add product to cart: Object not found. User ID: {telegram_user_id}, Product ID: {product_id}. Error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error adding product to cart for User ID {telegram_user_id}, Product ID {product_id}: {e}", exc_info=True)
        raise


class Catalog(Scene, state="catalog"):
    
    @on.message.enter()
    @on.callback_query.enter()
    async def on_enter(self, event: Message | CallbackQuery, state: FSMContext):
        """
        Handles the entry into the catalog scene.

        Initializes the Paginator for catalog navigation if it doesn't exist
        in the FSM context, or retrieves the existing one. Then, displays
        the current page of the catalog.

        Args:
            event: The Message or CallbackQuery that triggered the scene entry.
            state: The FSMContext for managing state data.
        """
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.info(f"Catalog scene: 'on_enter' triggered by {event_type} for user_id: {user_id}.")

        if isinstance(event, CallbackQuery):
            await event.answer()
            logger.debug(f"Catalog.on_enter: Answered callback query {event.id} for user_id: {user_id}.")

        CatalogPaginator: Optional[Paginator] = await state.get_value("catalog_paginator_inst", None)
        if CatalogPaginator is None:
            logger.info(f"User {user_id}: No existing Catalog Paginator found in state. Initializing new one.")
            root_catalog = PageNode(
                uid="catalog_root",
                content=PageContent(text="Welcome to the catalog!", label="Catalog Root") # "Добро пожаловать в каталог!"
            )
            CatalogPaginator = Paginator(
                page=root_catalog,
                loader_func=catalog_loader_function,
                global_kbd={"To Main Menu": "goto_main_menu"} # "В главное меню"
            )
            logger.debug(f"User {user_id}: New Catalog Paginator initialized with root UID 'catalog_root'.")
        else:
            logger.info(f"User {user_id}: Existing Catalog Paginator found in state.")
        
        await CatalogPaginator.show_page(event=event)
        await state.update_data(catalog_paginator_inst=CatalogPaginator)
        logger.debug(f"User {user_id}: Catalog Paginator instance saved/updated in FSM state.")


    @on.callback_query(MovePage.filter())
    async def handle_navigation(self, callback_query: CallbackQuery, callback_data: MovePage, state: FSMContext):
        """
        Handles navigation callbacks within the catalog (e.g., next/previous page).

        Retrieves the Paginator instance from FSM context and uses it to handle
        the navigation action based on the callback data.

        Args:
            callback_query: The CallbackQuery that triggered the navigation.
            callback_data: The MovePage callback data containing navigation details.
            state: The FSMContext for managing state data.
        """
        user_id = callback_query.from_user.id
        logger.info(f"Catalog scene: 'handle_navigation' triggered. User_id: {user_id}, Action: {callback_data.action}, UID: {callback_data.uid}")
        # Paginator's show_page will answer the callback query

        CatalogPaginator: Paginator = await state.get_value("catalog_paginator_inst")
        if not CatalogPaginator:
            logger.error(f"User {user_id}: Catalog Paginator instance not found in state during navigation. This is critical. Re-initializing.")
            # Fallback: re-initialize and show root.
            root_catalog = PageNode(uid="catalog_root", content=PageContent(text="Welcome to the catalog!", label="Catalog Root"))
            CatalogPaginator = Paginator(page=root_catalog, loader_func=catalog_loader_function, global_kbd={"To Main Menu": "goto_main_menu"})
            # No await state.update_data here yet, will be done after show_page
        
        await CatalogPaginator.handle_navigation(
            event=callback_query,
            callback_data=callback_data
        )
        await state.update_data(catalog_paginator_inst=CatalogPaginator) # Save potentially modified Paginator
        logger.debug(f"User {user_id}: Catalog Paginator instance updated in FSM state after navigation.")


    @on.callback_query(AddToCart.filter())
    async def add_to_cart(self, callback_query: CallbackQuery, callback_data: AddToCart, state: FSMContext):
        """
        Handles the "Add to Cart" button press for a product.

        Exits the current catalog scene and transitions to the product processing
        state to set the quantity. Retrieves product information and prompts the user
        to enter the desired quantity.

        Args:
            callback_query: The CallbackQuery from the "Add to Cart" button.
            callback_data: The AddToCart callback data containing the product_id.
            state: The FSMContext for managing state data.
        """
        user_id = callback_query.from_user.id
        product_id_to_add = callback_data.product_id
        logger.info(f"Catalog scene: 'add_to_cart' triggered. User_id: {user_id}, Product ID: {product_id_to_add}.")
        # send_or_edit_message will answer the callback_query

        await self.wizard.exit()
        logger.debug(f"User {user_id}: Exited 'catalog' scene.")
        await state.set_state(ProductProcessing.set_quantity)
        logger.info(f"User {user_id}: State set to ProductProcessing.set_quantity.")

        try:
            product = await get_product(product_id_to_add)
            product_in_stock = product.stock
            await state.update_data(product_processing={"product_id": product_id_to_add})
            logger.debug(f"User {user_id}: Product ID {product_id_to_add} stored in state for processing.")
            
            await send_or_edit_message(
                event=callback_query,
                text=f"Product in stock: {product_in_stock}\n\nEnter the quantity you want to add to cart:", # "Товара в наличии: {product_in_stock}\n\nВведите количество товара которое хотите добавить в корзину:"
                btns={"Cancel❌": "deny", "To Main Menu": "goto_main_menu"}, # "Отменить❌" "В главное меню"
                deleting_rules={"callback_query": True} # Delete the catalog message
            )
            logger.debug(f"User {user_id}: Quantity prompt sent for product ID {product_id_to_add}.")
        except ObjectDoesNotExist:
            logger.error(f"User {user_id}: Product ID {product_id_to_add} not found when trying to add to cart. Returning to catalog.")
            await callback_query.answer("Error: Product not found.", show_alert=True)
            await self.wizard.enter("catalog") # Go back to catalog
            # No need to call show_page here, on_enter of catalog will handle it.
        except Exception as e:
            logger.error(f"User {user_id}: Unexpected error processing add_to_cart for product ID {product_id_to_add}: {e}", exc_info=True)
            await callback_query.answer("An unexpected error occurred.", show_alert=True)
            await self.wizard.enter("catalog")


    @on.callback_query.exit()
    @on.message.exit()
    async def exit(self, event: Message | CallbackQuery, state: FSMContext):
        """Действие при выходе из сцены."""
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.debug(f"Catalog scene: 'exit' hook triggered by {event_type} for user_id: {user_id}.")
        pass

    @on.callback_query.leave()
    @on.message.leave()
    async def leave(self, event: Message | CallbackQuery, state: FSMContext):
        """Действие при выходе из сцены."""
        user_id = event.from_user.id if event.from_user else "UnknownUser"
        event_type = type(event).__name__
        logger.debug(f"Catalog scene: 'leave' hook triggered by {event_type} for user_id: {user_id}.")
        pass



@private_router.callback_query(and_f(StateFilter(ProductProcessing), F.data == "deny"))
async def deny(callback_query: CallbackQuery, state: FSMContext, scenes: SceneWizard):
    """
    Handles the 'deny' callback during product processing (e.g., canceling add to cart).

    Clears any temporary product processing data from the FSM state and
    transitions the user back to the main catalog scene.

    Args:
        callback_query: The CallbackQuery triggered by the 'deny' button.
        state: The FSMContext for managing state data.
        scenes: The SceneWizard for controlling scene transitions.
    """
    user_id = callback_query.from_user.id
    logger.info(f"ProductProcessing: 'deny' action triggered by user_id: {user_id}.")
    await callback_query.answer("Action cancelled.") # Explicitly answer
    logger.debug(f"ProductProcessing.deny: Answered callback query {callback_query.id} for user_id: {user_id}.")

    data = await state.get_data()
    if "product_processing" in data:
        del data["product_processing"]
        await state.set_data(data)
        logger.debug(f"User {user_id}: 'product_processing' data cleared from state.")
    else:
        logger.debug(f"User {user_id}: No 'product_processing' data found in state to clear.")

    logger.debug(f"User {user_id}: Attempting to enter 'catalog' scene from deny action.")
    await scenes.enter("catalog")
    # The on_enter of "catalog" will handle sending the message.


@private_router.message(ProductProcessing.set_quantity, F.text.regexp(r"\d+"))
async def set_quantity(message: Message, state: FSMContext):
    """
    Handles the user's input for the quantity of a product to add to the cart.

    Validates the entered quantity against the available stock. If valid,
    updates the FSM state with the quantity and prompts the user for confirmation.
    If invalid, informs the user about the error.

    Args:
        message: The Message containing the user's quantity input.
        state: The FSMContext for managing state data.
    """
    user_id = message.from_user.id
    try:
        quantity = int(message.text)
        logger.info(f"ProductProcessing.set_quantity: User_id {user_id} entered quantity: {quantity}.")
    except ValueError: # Should not happen due to regexp, but as a safeguard
        logger.warning(f"ProductProcessing.set_quantity: User_id {user_id} entered invalid (non-integer) quantity: '{message.text}'.")
        await send_or_edit_message(
            event=message,
            text="Invalid quantity format. Please enter a number.",
            btns={"Cancel❌": "deny", "To Main Menu": "goto_main_menu"}, # "Отменить❌" "В главное меню"
            deleting_rules={"message": True} # Delete the invalid quantity message
        )
        return


    data = await state.get_data()
    product_processing_data = data.get("product_processing")

    if not product_processing_data or "product_id" not in product_processing_data:
        logger.error(f"User {user_id}: Critical error - 'product_processing' data or 'product_id' missing in state at set_quantity. State: {data}")
        await send_or_edit_message(
            event=message,
            text="An error occurred. Please try adding the product again from the catalog.",
            btns={"To Main Menu": "goto_main_menu"}, # "В главное меню"
            deleting_rules={"message": True}
        )
        # Consider transitioning to a safe state, e.g., catalog or main_menu
        # For now, just informs user. A scene transition might be better.
        # await state.clear() # or scenes.enter("catalog")
        return

    product_id = product_processing_data["product_id"]
    
    try:
        product = await get_product(product_id)
        product_in_stock = product.stock
    except ObjectDoesNotExist:
        logger.error(f"User {user_id}: Product ID {product_id} (from state) not found in DB at set_quantity.")
        await send_or_edit_message(
            event=message,
            text="Error: The product you were processing could not be found. Please try again.",
            btns={"To Main Menu": "goto_main_menu"}, # "В главное меню"
            deleting_rules={"message": True}
        )
        # await state.clear() # or scenes.enter("catalog")
        return


    if not (0 < quantity <= product_in_stock):
        logger.warning(f"User {user_id}: Invalid quantity {quantity} for product ID {product_id}. Stock: {product_in_stock}.")
        await send_or_edit_message(
            event=message,
            text=f"Quantity must be between 1 and {product_in_stock} inclusive.", # "Количество должно быть в диапозоне больше 0 и до {product_in_stock} включительно)"
            btns={"Cancel❌": "deny", "To Main Menu": "goto_main_menu"}, # "Отменить❌" "В главное меню"
            deleting_rules={"message": True} # Delete the invalid quantity message
        )
        return
    
    data["product_processing"]["quantity"] = quantity
    await state.set_data(data)
    logger.info(f"User {user_id}: Quantity {quantity} for product ID {product_id} validated and stored in state.")

    confirm_text = (
        "Please confirm to add the product to your cart." # "Подтвердите чтобы добавить товар в корзину."
        "\n\nDetails:" # "\n\nДанные:"
        f"\n{product.name}"
        f"\n\n{product.description[:50] if len(product.description) <= 50 else product.description[:50] + '...'}"
        f"\n\nPrice per unit: {product.price}" # "\n\nЦена за ед. товара: {product.price}"
        f"\nUnits: {quantity}" # "\nЕд. товара: {quantity}"
        f"\nTotal price: {product.price * quantity}" # "\nЦена к оплате: {product.price * quantity}"
    )
    aiogram_image = get_fs_input_file_for_product(product.image) # Assuming MEDIA_ROOT is correctly set
    await send_or_edit_message(
        event=message,
        text=confirm_text,
        image=aiogram_image,
        btns={"Cancel❌": "deny", "Confirm✅": "confirm", "To Main Menu": "goto_main_menu"}, # "Отменить❌" "Подтвердить✅" "В главное меню"
        sizes=(2,1),
        deleting_rules={"message": True} # Delete the quantity message
    )
    logger.debug(f"User {user_id}: Confirmation prompt sent for product ID {product_id}, quantity {quantity}.")


@private_router.callback_query(F.data == "confirm")
async def confirm(callback_query: CallbackQuery, state: FSMContext, scenes: SceneWizard):
    """
    Handles the 'confirm' callback to finalize adding a product to the cart.

    Retrieves product and quantity information from the FSM state, adds the
    product to the user's cart in the database, and notifies the user.
    Clears temporary processing data and transitions back to the catalog.

    Args:
        callback_query: The CallbackQuery triggered by the 'confirm' button.
        state: The FSMContext for managing state data.
        scenes: The SceneWizard for controlling scene transitions.
    """
    user_id = callback_query.from_user.id
    logger.info(f"ProductProcessing: 'confirm' action triggered by user_id: {user_id}.")

    data = await state.get_data()
    product_processing = data.get("product_processing")

    if not product_processing or "product_id" not in product_processing or "quantity" not in product_processing:
        logger.error(f"User {user_id}: Critical error - 'product_processing' data or its keys missing in state at confirm. State: {data}")
        await callback_query.answer("An error occurred. Please try adding the product again.", show_alert=True)
        # Consider transitioning to a safe state
        if "product_processing" in data: del data["product_processing"] # Clean up partial data
        await state.set_data(data)
        await scenes.enter("catalog")
        return

    product_id_to_confirm = product_processing["product_id"]
    quantity_to_confirm = product_processing["quantity"]
    
    try:
        logger.debug(f"User {user_id}: Attempting to add product ID {product_id_to_confirm} (quantity: {quantity_to_confirm}) to cart via DB function.")
        await add_product_to_user_cart(user_id, quantity_to_confirm, product_id_to_confirm)
        await callback_query.answer(text="Product added to your cart", show_alert=True) # "Продукт добавлен в вашу корзину"
        logger.info(f"User {user_id}: Product ID {product_id_to_confirm} (quantity: {quantity_to_confirm}) successfully added to cart.")
    except Exception as e: # Catching broad exception from add_product_to_user_cart
        logger.error(f"User {user_id}: Failed to add product ID {product_id_to_confirm} to cart. Error: {e}", exc_info=True)
        await callback_query.answer(text="Failed to add product to your cart. Please try again.", show_alert=True) # "Не удалось добавить продукт в вашу корзину"
    finally:
        if "product_processing" in data:
            del data["product_processing"]
            await state.set_data(data)
            logger.debug(f"User {user_id}: 'product_processing' data cleared from state after confirm/failure.")
        
        logger.debug(f"User {user_id}: Attempting to enter 'catalog' scene after confirm action.")
        await scenes.enter("catalog")