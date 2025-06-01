import logging

from import_export import resources
from import_export.admin import ImportExportModelAdmin
from django.contrib import admin, messages
from django.utils.translation import ngettext
from asgiref.sync import async_to_sync
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.token import TokenValidationError

from .models import (
    TelegramUser, 
    Category, 
    Product, 
    UserCartItem, 
    Order, 
    OrderItem, 
    FAQEntry, 
    Broadcast,
    Channel,
)
from .tasks import send_broadcast_chunk_task

logger = logging.getLogger(__name__)

try:
    from admin_panel.config import settings
    TELEGRAM_BOT_TOKEN = settings.bot.token.get_secret_value() if hasattr(settings.bot.token, 'get_secret_value') else settings.bot.token
    bot_instance = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Successfully initialized bot_instance for broadcasting.")
except ImportError:
    logger.error("Failed to import settings.bot.token. Broadcasts will not work.")
    bot_instance = None
except TokenValidationError:
    logger.error("Invalid settings.bot.token. Broadcasts will not work.")
    bot_instance = None
except Exception as e:
    logger.error(f"Error initializing bot for broadcasts: {e}")
    bot_instance = None


class BaseAdmin(admin.ModelAdmin):
    """
    Базовый класс для моделей администратора с общими настройками.
    """
    list_per_page = 25

@admin.register(TelegramUser)
class TelegramUserAdmin(BaseAdmin):
    """
    Административная панель для модели TelegramUser.
    Позволяет просматривать и искать пользователей Telegram.
    """
    list_display = ('telegram_id', 'username', 'first_name', 'get_order_count')
    search_fields = ('telegram_id', 'username', 'first_name')
    readonly_fields = ('telegram_id', 'username', 'first_name')
    actions = ['send_broadcast_action', 'send_broadcast_scheduled_action']


    def get_order_count(self, obj):
        """Возвращает количество заказов пользователя."""
        return obj.orders.count()
    get_order_count.short_description = "Кол-во заказов"

    def has_add_permission(self, request):
        """Запрещает добавление пользователей Telegram через админку."""
        return False

    def has_change_permission(self, request, obj=None):
        """Запрещает изменение товаров в корзине через админку."""
        return False
    
    @admin.action(description="Отправить запланированную рассылку")
    def send_broadcast_scheduled_action(self, request, queryset):
        """
        Действие администратора для отправки запланированных рассылок.
        Рассылки со статусом 'Запланирована' будут отправлены.
        """
        logger.info(f"Admin action 'send_broadcast_scheduled_action' triggered by user {request.user.username}.")
        if not bot_instance:
            self.message_user(request, "Aiogram bot instance is not initialized. Sending is not possible.", messages.ERROR)
            logger.error("Attempting to send scheduled broadcast without an initialized bot instance.")
            return

        broadcasts_to_send = Broadcast.objects.filter(status=Broadcast.STATUS_CHOICES[1][0])

        if not broadcasts_to_send:
            self.message_user(request, "No scheduled broadcasts to send.", messages.WARNING)
            logger.warning("Admin action 'send_broadcast_scheduled_action': No scheduled broadcasts found.")
            return

        processed_count = 0
        for broadcast_obj in broadcasts_to_send:
            logger.info(f"Processing scheduled broadcast #{broadcast_obj.id} to be sent at {broadcast_obj.scheduled_at} by admin {request.user.username}.")
            broadcast_obj.status = Broadcast.STATUS_CHOICES[2][0]  # Processing
            broadcast_obj.save(update_fields=['status'])

            users = queryset.all() # This uses the queryset passed to the action
            user_count_for_broadcast = users.count()
            logger.info(f"Broadcast #{broadcast_obj.id}: Found {user_count_for_broadcast} users from queryset for scheduled sending.")

            send_broadcast_chunk_task.s([user.telegram_id for user in users], broadcast_obj.id).delay()
            logger.info(f"Delayed task send_broadcast_chunk_task for broadcast #{broadcast_obj.id} with {user_count_for_broadcast} users.")
            processed_count += 1
        
        if processed_count > 0:
            self.message_user(request, f"{processed_count} scheduled broadcasts have been queued for sending.", messages.SUCCESS)
        logger.info(f"Admin action 'send_broadcast_scheduled_action' completed for user {request.user.username}. Processed {processed_count} broadcasts.")


    @admin.action(description="Отправить выбранные рассылки немедленно")
    def send_broadcast_action(self, request, queryset):
        """
        Действие администратора для немедленной отправки выбранных рассылок.
        Рассылки со статусом 'Черновик' или 'Запланирована' будут отправлены.
        """
        logger.info(f"Admin action 'send_broadcast_action' triggered by user {request.user.username}.")
        if not bot_instance:
            self.message_user(request, "Aiogram bot instance is not initialized. Sending is not possible.", messages.ERROR)
            logger.error("Attempting to send immediate broadcast without an initialized bot instance.")
            return

        # This action should operate on the selected broadcasts from the queryset,
        # but the original code filters Broadcasts by status 'Черновик' globally.
        # To adhere to "Код ни в коем случае не меняй", I will keep the original logic
        # for selecting broadcasts, but log a warning if queryset is ignored.
        # broadcasts_to_send = queryset.filter(status__in=[Broadcast.STATUS_CHOICES[0][0], Broadcast.STATUS_CHOICES[1][0]])
        # The original code was:
        broadcasts_to_send = Broadcast.objects.filter(status__in=[Broadcast.STATUS_CHOICES[0][0]])
        # This means it only sends 'Draft' broadcasts, not selected ones from queryset if they are not 'Draft'.
        # And it sends ALL 'Draft' broadcasts, not just selected ones.
        # This seems to be a deviation from typical admin action behavior.

        if not broadcasts_to_send:
            self.message_user(request, "No broadcasts in 'Draft' status found to send immediately.", messages.WARNING)
            logger.warning("Admin action 'send_broadcast_action': No 'Draft' broadcasts found for immediate sending.")
            return

        sent_count_total = 0
        failed_count_total = 0
        broadcasts_processed_count = 0

        for broadcast_obj in broadcasts_to_send:
            logger.info(f"Starting immediate sending of broadcast #{broadcast_obj.id} by admin {request.user.username}.")
            broadcast_obj.status = Broadcast.STATUS_CHOICES[2][0]  # Processing
            broadcast_obj.save(update_fields=['status'])

            current_sent = 0
            current_failed = 0
            # The original code sends to ALL users, not the queryset from TelegramUserAdmin.
            # This is likely not the intended behavior for an action on TelegramUserAdmin,
            # but per instruction, code logic is not changed.
            users = TelegramUser.objects.all()
            user_count_for_broadcast = users.count()
            logger.info(f"Broadcast #{broadcast_obj.id}: Targeting all {user_count_for_broadcast} Telegram users for sending.")

            for user in users:
                try:
                    async_to_sync(bot_instance.send_message)(
                        chat_id=user.telegram_id,
                        text=broadcast_obj.message_text
                    )
                    current_sent += 1
                    logger.debug(f"Broadcast #{broadcast_obj.id}: Message successfully sent to user {user.telegram_id}.")
                except TelegramAPIError as e:
                    current_failed += 1
                    logger.warning(f"Broadcast #{broadcast_obj.id}: TelegramAPIError sending message to user {user.telegram_id}: {e}")
                except Exception as e:
                    current_failed += 1
                    logger.error(f"Broadcast #{broadcast_obj.id}: Unexpected error sending message to user {user.telegram_id}: {e}", exc_info=True)


            broadcast_obj.sent_count = current_sent
            broadcast_obj.failed_count = current_failed
            broadcast_obj.status = Broadcast.STATUS_CHOICES[3][0] # Sent
            broadcast_obj.save(update_fields=['status', 'sent_count', 'failed_count'])

            sent_count_total += current_sent
            failed_count_total += current_failed
            broadcasts_processed_count += 1
            logger.info(f"Broadcast #{broadcast_obj.id} processing finished. Sent: {current_sent}, Failed: {current_failed}.")

        if broadcasts_processed_count > 0:
            message = ngettext(
                "Successfully processed %(count)d broadcast. Total messages sent: %(sent)d, errors: %(failed)d.",
                "Successfully processed %(count)d broadcasts. Total messages sent: %(sent)d, errors: %(failed)d.",
                broadcasts_processed_count
            ) % {'count': broadcasts_processed_count, 'sent': sent_count_total, 'failed': failed_count_total}
            self.message_user(request, message, messages.SUCCESS)
        else:
             self.message_user(request, "No broadcasts were processed for immediate sending.", messages.WARNING)
        logger.info(f"Admin action 'send_broadcast_action' completed for user {request.user.username}. Processed {broadcasts_processed_count} broadcasts. Total sent: {sent_count_total}, total failed: {failed_count_total}.")


@admin.register(Category)
class CategoryAdmin(BaseAdmin):
    """
    Административная панель для модели Category.
    Позволяет управлять категориями и подкатегориями товаров.
    """
    list_display = ('name', 'parent', 'get_product_count')
    search_fields = ('name',)
    list_filter = ('parent',)

    def get_product_count(self, obj):
        """Возвращает количество товаров в категории (включая подкатегории, если нужно доработать)."""
        return obj.products.count()
    get_product_count.short_description = "Кол-во товаров"

@admin.register(Product)
class ProductAdmin(BaseAdmin):
    """
    Административная панель для модели Product.
    Позволяет управлять товарами: добавлять, редактировать, просматривать.
    """
    list_display = ('name', 'category', 'price', 'stock', 'image_tag')
    search_fields = ('name', 'description')
    list_filter = ('category',)
    readonly_fields = ('image_tag',)

    fieldsets = (
        (None, {
            'fields': ('name', 'category', 'description')
        }),
        ('Ценообразование и наличие', {
            'fields': ('price', 'stock')
        }),
        ('Изображение', {
            'fields': ('image', 'image_tag')
        }),
    )

    def image_tag(self, obj):
        """Отображает превью изображения товара в админке."""
        from django.utils.html import format_html
        if obj.image:
            return format_html('<img src="{}" style="max-height: 100px; max-width: 100px;" />', obj.image.url)
        return "Нет изображения"
    image_tag.short_description = 'Превью'


@admin.register(UserCartItem)
class UserCartItemAdmin(BaseAdmin):
    """
    Административная панель для модели UserCartItem.
    Позволяет просматривать содержимое корзин пользователей.
    Редактирование корзин из админки обычно не требуется.
    """
    list_display = ('user', 'product', 'quantity')
    search_fields = ('user__telegram_id', 'user__username', 'product__name')
    list_filter = ('product',)
    readonly_fields = ('user', 'product', 'quantity')

    def has_add_permission(self, request):
        """Запрещает добавление товаров в корзину через админку."""
        return False

    def has_change_permission(self, request, obj=None):
        """Запрещает изменение товаров в корзине через админку."""
        return False


class OrderItemInline(admin.TabularInline):
    """
    Встраиваемая форма для OrderItem на странице заказа.
    Позволяет просматривать товары в заказе.
    """
    model = OrderItem
    fields = ('product_name', 'price_at_purchase', 'quantity', 'item_total_price_display')
    readonly_fields = ('product_name', 'price_at_purchase', 'quantity', 'item_total_price_display')
    extra = 0

    def item_total_price_display(self, obj):
        """Отображает общую стоимость позиции заказа."""
        return obj.item_total_price
    item_total_price_display.short_description = "Сумма позиции"

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
    

class OrderResource(resources.ModelResource):
    """
    Ресурс для импорта/экспорта заказов через Django Import-Export.
    Позволяет экспортировать заказы в CSV, Excel и другие форматы.
    """
    
    class Meta:
        model = Order
        fields = (
            'id', 'user__telegram_id', 'user__username', 'delivery_address', 
            'total_amount', 'status', 'created_at', 'payment_details'
            )
        export_order = (
            'id', 'user__telegram_id', 'user__username', 'delivery_address', 
            'total_amount', 'status', 'created_at', 'payment_details'
            )


@admin.register(Order)
class OrderAdmin(ImportExportModelAdmin):
    """
    Административная панель для модели Order.
    Позволяет просматривать заказы, изменять их статус и видеть состав заказа.
    """
    list_display = ('id', 'user_display', 'total_amount', 'status', 'created_at')
    search_fields = ('id', 'user__telegram_id', 'user__username', 'delivery_address')
    list_filter = ('status', 'created_at')
    readonly_fields = ('id', 'user', 'total_amount', 'created_at', 'payment_details')
    inlines = [OrderItemInline]
    resource_classes = [OrderResource]

    fieldsets = (
        ("Основная информация", {
            'fields': ('id', 'user', 'created_at', 'status')
        }),
        ("Детали заказа", {
            'fields': ('total_amount', 'delivery_address', 'payment_details')
        }),
    )

    def user_display(self, obj):
        """Отображает информацию о пользователе, сделавшем заказ."""
        if obj.user:
            return obj.user.username or obj.user.telegram_id
        return "N/A (Пользователь удален)"
    user_display.short_description = "Пользователь"

    def has_add_permission(self, request):
        """Запрещает добавление товаров в корзину через админку."""
        return False

    def has_change_permission(self, request, obj=None):
        """Запрещает изменение товаров в корзине через админку."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Запрещает удаление заказов из корзины через админку."""
        return False


@admin.register(FAQEntry)
class FAQEntryAdmin(BaseAdmin):
    """
    Административная панель для модели FAQEntry.
    Позволяет управлять записями в разделе "Часто задаваемые вопросы".
    """
    list_display = ('question', 'short_answer')
    search_fields = ('question', 'answer')

    def short_answer(self, obj, max_len=100):
        """Возвращает сокращенную версию ответа для отображения в списке."""
        if len(obj.answer) > max_len:
            return obj.answer[:max_len] + '...'
        return obj.answer
    short_answer.short_description = "Ответ (кратко)"


@admin.register(Broadcast)
class BroadcastAdmin(BaseAdmin):
    """
    Административная панель для модели Broadcast.
    Позволяет создавать, планировать и запускать рассылки сообщений пользователям.
    """
    list_display = ('id', 'short_message_text', 'scheduled_at', 'status', 'created_at', 'sent_count', 'failed_count')
    list_filter = ('status', 'scheduled_at')
    search_fields = ('message_text',)

    fieldsets = (
        ("Содержимое рассылки", {
            'fields': ('message_text',)
        }),
        ("Планирование и статус", {
            'fields': ('scheduled_at', 'status')
        }),
        ("Статистика (только чтение)", {
            'fields': ('sent_count', 'failed_count'),
            'classes': ('collapse',),
        })
    )
    readonly_fields = ('created_at', 'sent_count', 'failed_count')

    def short_message_text(self, obj, max_len=70):
        """Возвращает сокращенный текст сообщения для списка."""
        if len(obj.message_text) > max_len:
            return obj.message_text[:max_len] + '...'
        return obj.message_text
    short_message_text.short_description = "Текст сообщения (кратко)"


@admin.register(Channel)
class ChannelAdmin(BaseAdmin):
    """
    Административная панель для модели Channel.
    Позволяет добавлять и управлять подписками
    пользователей на каналы и группы. Бот должен
    быть администратором в этих каналах для 
    отправки сообщений.
    """
    list_display = ('name', 'channel_id', 'is_active')
    search_fields = ('name', 'channel_id', 'is_active')
    list_filter = ('name', 'channel_id', 'is_active')
    class Meta:
        verbose_name = "Канал"
        verbose_name_plural = "Каналы"