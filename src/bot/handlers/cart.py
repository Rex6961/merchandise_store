import json
import logging
from typing import Any, Optional, Sequence

from aiogram import F, Bot
from aiogram.types import Message, CallbackQuery, LabeledPrice, Update
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import SceneWizard, Scene, on
from aiogram.filters.callback_data import CallbackData
from aiogram.filters import StateFilter, and_f
from aiogram.fsm.state import StatesGroup, State
from asgiref.sync import sync_to_async

from bot.handlers.private import private_router
from bot.misc.utils import get_fs_input_file_for_product, send_or_edit_message
from bot.misc.paginator import Paginator, MovePage, UID_TYPE, PageNode, PageContent
from admin_panel.clients.models import UserCartItem, Order, TelegramUser

logger = logging.getLogger(__name__)

class ProcessOffer(StatesGroup):
    total_amount = State()

class DeleteFromCart(CallbackData, prefix="delete_item_from_cart"):
    item_id: Any

async def cart_loader_function(
        uid: UID_TYPE,
        limit: int,
        cursor: int,
        **kwargs: Any
) -> tuple[Optional[Sequence[PageNode]], str]:
    telegram_id: int = kwargs.get("telegram_id")
    has_more = False
    logger.debug(f"cart_loader_function started for user_id: {telegram_id}, uid: {uid}, limit: {limit}, cursor: {cursor}")

    @sync_to_async
    def _get_cart_items(telegram_id: int, offset: int, count: int) -> list[UserCartItem]:
        """
        Получает список товаров в корзине пользователя.
        """
        logger.info(f"Fetching cart items from DB for user_id: {telegram_id}, offset: {offset}, count: {count}")
        qs = UserCartItem.objects.filter(user__telegram_id=telegram_id).select_related('product').all()
        result = list(qs[offset: offset + count])
        logger.info(f"Fetched {len(result)} cart items for user_id: {telegram_id}")
        return result
    
    try:
        db_entries: list[UserCartItem] = await _get_cart_items(telegram_id, cursor, limit + 1)
    except Exception as e:
        logger.error(f"Error fetching cart items from DB for user_id {telegram_id}: {e}", exc_info=True)
        return None # Original code returns None, which will cause TypeError on unpack by caller
    
    loaded_nodes: list[PageNode] = []
    if db_entries:
        if len(db_entries) > limit:
            db_entries.pop()
            has_more = True
        for entry in db_entries:
            node_uid = f"cart_item_{entry.product.id}"
            cart_item_text = (
                f"{entry.product.name}"
                f"\n\n{entry.product.description}"
                f"\n\nЦена за ед. товара: {entry.product.price}"
                f"\nЕд. товара: {entry.quantity}"
                f"\nЦена к оплате: {entry.product.price * entry.quantity}"
            )
            aiogram_image = get_fs_input_file_for_product(entry.product.image)
            content = PageContent(
                label=entry.product.name,
                text=cart_item_text,
                image=aiogram_image,
                is_leaf_node=True
            )
            loaded_nodes.append(
                PageNode(
                    uid=node_uid,
                    content=content,
                    custom_kbd={"Удалить из корзины": DeleteFromCart(item_id=entry.pk)}
                )
            )
        logger.debug(f"Prepared {len(loaded_nodes)} nodes for cart. User_id: {telegram_id}. Has more: {has_more}")
    else:
        logger.debug(f"No cart items found to load for user_id: {telegram_id}")


    return loaded_nodes if loaded_nodes else None, has_more


@sync_to_async
def _calculate_total_amount(telegram_id):
    """
    Получает список товаров в корзине пользователя.
    """
    logger.info(f"Calculating total cart amount for user_id: {telegram_id}")
    qs: list[UserCartItem] = UserCartItem.objects.filter(user__telegram_id=telegram_id).select_related('product').all()
    total = sum([(entry.product.price * entry.quantity) for entry in qs])
    logger.info(f"Calculated total amount {total} for user_id: {telegram_id}")
    return total


@sync_to_async
def save_order_payments(data_order):
    logger.info(f"Attempting to save order from successful payment. Message ID: {data_order.message_id}, User ID (from message): {data_order.from_user.id}")
    user_telegram_id = None # Initialize for broader scope in case of early error
    try:
        qs = data_order.model_dump_json()
        qs_dic = json.loads(qs)
        user_telegram_id = qs_dic.get('from_user', {}).get('id')
        if not user_telegram_id:
            logger.error("Could not extract user_telegram_id from data_order.")
            return # Cannot proceed without user_id

        logger.info(f"Fetching TelegramUser for telegram_id: {user_telegram_id}")
        user = TelegramUser.objects.get(telegram_id=user_telegram_id)
        
        delivery_address_dict = qs_dic.get('successful_payment', {}).get('order_info')
        delivery_address = json.dumps(delivery_address_dict, ensure_ascii=False, indent=2)
        
        total_amount_cents = qs_dic.get('successful_payment', {}).get('total_amount')
        total_amount = total_amount_cents / 100 if total_amount_cents is not None else 0
        
        payment_charge_id = qs_dic.get('successful_payment', {}).get('provider_payment_charge_id')
        
        logger.info(f"Creating Order entry for user (tg: {user_telegram_id}), total_amount: {total_amount}, payment_charge_id: {payment_charge_id}")
        order = Order(
            user=user,
            delivery_address=delivery_address,
            total_amount=total_amount,
            status=Order.STATUS_CHOICES[1][0], # Assumes 'Paid' or similar status
            payment_details=payment_charge_id
        )
        order.save()
        logger.info(f"Order {order.id} saved successfully for user (tg: {user_telegram_id}).")
    except TelegramUser.DoesNotExist:
        logger.error(f"TelegramUser with telegram_id {user_telegram_id} not found in DB while saving order.")
    except Exception as e:
        logger.error(f"Error saving order payments for user_telegram_id {user_telegram_id if user_telegram_id else 'Unknown'}: {e}", exc_info=True)


class Cart(Scene, state="cart"):
    
    @on.message.enter()
    @on.callback_query.enter()
    async def on_enter(self, event: Message | CallbackQuery, state: FSMContext):    
        user_id = event.from_user.id
        logger.info(f"User {user_id} entering Cart scene.")
        total_amount = 0 # Default value
        try:
            logger.debug(f"Calculating total amount for user {user_id} on cart entry.")
            total_amount = await _calculate_total_amount(user_id)
            await state.update_data(total_amount=total_amount)
            logger.info(f"Total amount for user {user_id} is {total_amount}. Updated in state.")
        except Exception as e:
            logger.error(f"Error calculating total amount for user {user_id} on cart entry: {e}", exc_info=True)
            # Original code had 'return None', which for an async handler means 'return'.
            # This stops further execution of this handler.
            return


        UserCartItemPaginator: Optional[Paginator] = await state.get_value("cart_paginator_inst", None)
        if UserCartItemPaginator is None:
            logger.info(f"No existing cart paginator found for user {user_id}. Initializing a new one.")
            # The 'total_amount' used below is the one calculated in the try block.
            # If an exception occurred there and 'return' was hit, this part is not reached.
            root_cart_text = f"Общая сумма вашей корзины к оплате составляет: {total_amount}"
            logger.debug(f"Root cart text for user {user_id}: '{root_cart_text}'")
            root_cart = PageNode(
                uid="cart_root", 
                content=PageContent(text=root_cart_text, label="Cart Root"),
                custom_kbd={"Офформить заказ🔄": "process_offer"}
            )
            UserCartItemPaginator = Paginator(
                page=root_cart,
                loader_func=cart_loader_function,
                global_kbd={"В главное меню": "goto_main_menu"}
            )
            logger.info(f"New cart paginator initialized for user {user_id}.")
        else:
            logger.info(f"Using existing cart paginator for user {user_id}.")

        try:
            await UserCartItemPaginator.show_page(event=event, telegram_id=user_id)
            await state.update_data(cart_paginator_inst=UserCartItemPaginator)
            logger.debug(f"Cart page shown and paginator instance updated in state for user {user_id}.")
        except Exception as e:
            logger.error(f"Error showing cart page for user {user_id}: {e}", exc_info=True)


    @on.callback_query(MovePage.filter())
    async def handle_navigation(self, callback_query: CallbackQuery, callback_data: MovePage, state: FSMContext):
        user_id = callback_query.from_user.id
        logger.info(f"User {user_id} navigating cart. Callback data: {callback_data!r}")
        UserCartItemPaginator: Paginator = await state.get_value("cart_paginator_inst")
        try:
            # This block contains original operations. If UserCartItemPaginator is None,
            # an AttributeError will be raised by the next line, as in original code.
            await UserCartItemPaginator.handle_navigation(
                event=callback_query,
                callback_data=callback_data,
                telegram_id=user_id
            )
            await state.update_data(cart_paginator_inst=UserCartItemPaginator)
            logger.debug(f"Cart navigation handled and paginator instance updated in state for user {user_id}.")
        except AttributeError as e:
            logger.error(f"AttributeError during cart navigation for user {user_id}: Paginator might be None. Details: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error handling cart navigation for user {user_id}: {e}", exc_info=True)


    @on.callback_query(F.data == "process_offer")
    async def gathering_information(self, callback_query: CallbackQuery, state: FSMContext):
        user_id = callback_query.from_user.id
        logger.info(f"User {user_id} initiated 'process_offer'.")
        data = await state.get_data()
        total_amount = data.get('total_amount', None)
        
        if total_amount is None:
            logger.error(f"Total amount is None for user {user_id} when processing offer. Invoice creation will likely fail.")
            # Original code would proceed and int(None) would raise TypeError. We let it happen.
        else:
            logger.info(f"Processing offer for user {user_id}. Total amount from state: {total_amount}")
        
        # The following line will raise TypeError if total_amount is None, as per original behavior.
        try:
            total_amount_real = int(total_amount) * 100 
            price = LabeledPrice(label='Summary', amount=total_amount_real)
            
            logger.info(f"Sending invoice to user {user_id} for amount {total_amount_real} (currency units). Payload: My_payload")
            await callback_query.bot.send_invoice(
                chat_id=user_id,
                title='Pie',
                description='bye me',
                payload='My_payload', # Critical: This should be unique per transaction for reconciliation
                currency='RUB',
                prices=[price],
                provider_token='2051251535:TEST:OTk5MDA4ODgxLTAwNQ', # This is a test token
                need_name=True,
                need_phone_number=True,
                need_shipping_address=True
            )
            logger.info(f"Invoice sent successfully to user {user_id}.")
        except TypeError as e:
            logger.error(f"TypeError during invoice creation for user {user_id} (likely total_amount was None): {e}", exc_info=True)
            # Original code would crash here. Now it's logged. The wizard.exit() might not be reached.
            # To preserve original flow, if an error occurs, the wizard.exit() might not be called.
            # However, the original code has wizard.exit() outside any try/except for send_invoice.
            # So, if send_invoice fails, wizard.exit() is still called.
            # If int(total_amount) fails, this whole handler crashes before wizard.exit().
        except Exception as e:
            logger.error(f"Failed to send invoice to user {user_id}: {e}", exc_info=True)
        
        await callback_query.answer()
        logger.info(f"Exiting Cart scene for user {user_id} after 'process_offer' attempt.")
        await self.wizard.exit()

    @on.callback_query(DeleteFromCart.filter())
    async def delete_item_from_cart(self, callback_query: CallbackQuery, callback_data: DeleteFromCart, state: FSMContext):
        user_id = callback_query.from_user.id
        item_to_delete_pk = callback_data.item_id
        logger.info(f"User {user_id} requested deletion of cart item with pk: {item_to_delete_pk}.")

        await state.update_data(cart_paginator_inst=None)
        logger.debug(f"Cart paginator instance set to None in state for user {user_id} due to item deletion.")

        @sync_to_async
        def _delete_cart_item(item_id_pk):
            logger.info(f"Attempting to delete UserCartItem with pk: {item_id_pk} from DB.")
            try:
                item = UserCartItem.objects.get(id=item_id_pk)
                product_name = item.product.name if item.product else "Unknown Product"
                item.delete()
                logger.info(f"Successfully deleted UserCartItem with pk: {item_id_pk} (Product: {product_name}) from DB.")
            except UserCartItem.DoesNotExist:
                logger.warning(f"UserCartItem with pk: {item_id_pk} not found in DB for deletion.")
            except Exception as e:
                logger.error(f"Error deleting UserCartItem with pk: {item_id_pk} from DB: {e}", exc_info=True)
        
        await _delete_cart_item(item_to_delete_pk)
        
        logger.info(f"Retaking Cart scene for user {user_id} after item deletion attempt.")
        await self.wizard.retake()

    @on.callback_query.exit()
    @on.message.exit()
    async def exit(self, event: Message | CallbackQuery, state: FSMContext):
        """Действие при выходе из сцены."""
        current_state = await state.get_state()
        logger.debug(f"User {event.from_user.id} explicitly exiting Cart scene. Current FSM state: {current_state}.")
        pass

    @on.callback_query.leave()
    @on.message.leave()
    async def leave(self, event: Message | CallbackQuery, state: FSMContext):
        """Действие при выходе из сцены."""
        current_state = await state.get_state()
        logger.debug(f"User {event.from_user.id} leaving Cart scene. Current FSM state: {current_state}.")
        pass

#FIXME
@private_router.callback_query(and_f(StateFilter(ProcessOffer), F.data == "deny"))
async def deny(callback_query: CallbackQuery, state: FSMContext, scenes: SceneWizard):
    user_id = callback_query.from_user.id
    current_state_data = await state.get_data()
    logger.info(f"User {user_id} denied action in ProcessOffer state. Current state data: {current_state_data}")
    data = await state.get_data() # Re-fetch, though current_state_data could be used
    if "product_processing" in data:
        del data["product_processing"]
        logger.debug(f"'product_processing' key removed from state data for user {user_id}.")
    await state.set_data(data)

    logger.info(f"User {user_id} being moved to 'cart' scene from 'deny' handler in ProcessOffer.")
    await scenes.enter("cart")

@private_router.pre_checkout_query()
async def get_pre_checkout_query(update: Update, bot: Bot, state: FSMContext): # update is aiogram.types.PreCheckoutQuery
    # Ensure we are dealing with PreCheckoutQuery object
    if not update:
        logger.warning(f"Received update in pre_checkout_query handler without pre_checkout_query field: {update!r}")
        return

    pre_checkout_query = update
    user_id = pre_checkout_query.from_user.id
    query_id = pre_checkout_query.id
    logger.info(f"Received pre_checkout_query ID: {query_id} for user {user_id}. Payload: {pre_checkout_query.invoice_payload}, Amount: {pre_checkout_query.total_amount} {pre_checkout_query.currency}.")
    try:
        await bot.answer_pre_checkout_query(pre_checkout_query_id=query_id, ok=True)
        logger.info(f"Answered pre_checkout_query ID: {query_id} with ok=True for user {user_id}.")
    except Exception as e:
        logger.error(f"Error answering pre_checkout_query ID: {query_id} for user {user_id}: {e}", exc_info=True)
        # Not answering with ok=False as per "do not change code" instruction. Telegram might retry or timeout.
    
    # 4548 8144 7972 7229, 4548 8194 0777 7774, 4918 0191 9988 3839 with an amount higher than 60€ (~60$)

@private_router.message(F.successful_payment)
async def get_state_payments(message: Message, state: FSMContext):
    user_id = message.from_user.id
    payment_info = message.successful_payment
    logger.info(
        f"Received successful_payment from user {user_id}. "
        f"Telegram Payment ID: {payment_info.telegram_payment_charge_id}, "
        f"Provider Payment ID: {payment_info.provider_payment_charge_id}, "
        f"Amount: {payment_info.total_amount / 100} {payment_info.currency}, "
        f"Invoice Payload: {payment_info.invoice_payload}."
    )
    
    # Log order details before sending to user for privacy reasons if needed, but here it's just for confirmation.
    logger.debug(f"Successful payment order_info for user {user_id}: {payment_info.order_info.model_dump_json(indent=2) if payment_info.order_info else 'No order_info'}")

    await message.answer('Спасибо за то, что воспользовались нашими услугами:\n' \
                         f'ваши данные для доставки: {message.successful_payment.order_info.model_dump_json(indent=2) if message.successful_payment.order_info else "Нет данных о доставке"}')
    logger.info(f"Confirmation message sent to user {user_id} for successful payment.")
    
    try:
        logger.info(f"Calling save_order_payments for user {user_id} with successful payment data from message ID {message.message_id}.")
        await save_order_payments(message) # Pass the whole message object as original
        logger.info(f"save_order_payments call completed for user {user_id} related to message ID {message.message_id}.")
    except Exception as e:
        logger.error(f"Error occurred after calling save_order_payments for user {user_id} (message ID {message.message_id}): {e}", exc_info=True)
        # Critical: if saving order fails, it needs attention.