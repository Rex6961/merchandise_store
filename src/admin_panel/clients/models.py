import logging
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)

class TelegramUser(models.Model):
    """
    Модель для хранения информации о пользователях Telegram,
    которые взаимодействуют с ботом. Эта информация используется
    для персонализации, связи заказов с пользователями и для
    формирования "Таблицы по всем клиентам" в админ-панели.
    """
    telegram_id = models.BigIntegerField(
        "Telegram ID",
        unique=True,
        primary_key=True,
        help_text="Уникальный идентификатор пользователя в Telegram."
    )
    username = models.CharField(
        "Имя пользователя Telegram",
        max_length=100,
        null=True,
        blank=True,
        help_text="Username пользователя в Telegram (может отсутствовать)."
    )
    first_name = models.CharField(
        "Имя",
        max_length=100,
        null=True,
        blank=True,
        help_text="Имя пользователя, указанное в Telegram."
    )

    def __str__(self):
        "Строковое представление объекта TelegramUser."
        return self.username or str(self.telegram_id)

    def save(self, *args, **kwargs):
        "Переопределение метода сохранения для логирования новых пользователей."
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            logger.info(f"Зарегистрирован новый пользователь Telegram: ID {self.telegram_id}, Имя пользователя: {self.username or 'N/A'}.")

    class Meta:
        verbose_name = "Пользователь Telegram"
        verbose_name_plural = "Пользователи Telegram"
        ordering = ['telegram_id']

class Category(models.Model):
    """
    Модель для категорий и подкатегорий товаров.
    Позволяет организовать иерархическую структуру каталога.
    Категории используются для навигации в боте с пагинацией.
    """
    name = models.CharField(
        "Название",
        max_length=255,
        help_text="Название категории или подкатегории."
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subcategories',
        verbose_name="Родительская категория",
        help_text="Если не указана, это категория верхнего уровня."
    )

    def __str__(self):
        """Строковое представление категории, учитывающее иерархию."""
        if self.parent:
            return f"{self.parent.name} -> {self.name}"
        return self.name

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ['name']

class Product(models.Model):
    """
    Модель для товаров в магазине.
    Каждый товар принадлежит к определенной категории и содержит
    описание, цену и изображение, как указано в задании
    ("Товары в формате: фото, описание").
    """
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=False,
        related_name='products',
        verbose_name="Категория",
        help_text="Категория, к которой принадлежит товар."
    )
    name = models.CharField(
        "Название",
        max_length=255,
        help_text="Полное название товара."
    )
    description = models.TextField(
        "Описание",
        help_text="Подробное описание товара."
    )
    price = models.DecimalField(
        "Цена",
        max_digits=10,
        decimal_places=2,
        help_text="Цена товара в рублях."
    )
    image = models.ImageField(
        "Фото",
        upload_to='product_images/',
        null=True,
        blank=True,
        help_text="Изображение товара."
    )
    stock = models.PositiveIntegerField(
        "На складе",
        default=0,
        help_text="Количество товара в наличии на складе."
    )

    def __str__(self):
        """Строковое представление товара."""
        return self.name

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ['name']

class UserCartItem(models.Model):
    """
    Модель для представления товара в корзине конкретного пользователя.
    Реализует функционал "Просмотр корзины", "Возможность удалить товар из корзины",
    "Добавить в корзину", "Указать кол-во".
    """
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='cart_items',
        verbose_name="Пользователь",
        help_text="Пользователь, к чьей корзине относится товар."
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        verbose_name="Товар",
        help_text="Товар, добавленный в корзину."
    )
    quantity = models.PositiveIntegerField(
        "Количество",
        default=1,
        help_text="Количество единиц данного товара в корзине."
    )

    def __str__(self):
        """Строковое представление позиции в корзине."""
        user_display = self.user.username or self.user.telegram_id
        return f"{self.quantity} x {self.product.name} (Корзина: {user_display})"

    class Meta:
        verbose_name = "Товар в корзине пользователя"
        verbose_name_plural = "Товары в корзинах пользователей"
        unique_together = ('user', 'product')

class Order(models.Model):
    """
    Модель для оформленных заказов.
    Содержит информацию о пользователе, заказанных товарах (через OrderItem),
    данных для доставки, сумме и статусе заказа.
    Все заказы должны выгружаться в Excel ("Все заказы падают в эксель таблицу").
    """
    STATUS_CHOICES = [
        ('pending_payment', 'Ожидает оплаты'),
        ('paid', 'Оплачен'),
        ('processing', 'В обработке'),
        ('shipped', 'Отправлен'),
        ('delivered', 'Доставлен'),
        ('cancelled', 'Отменен'),
    ]

    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='orders',
        verbose_name="Пользователь",
        help_text="Пользователь, оформивший заказ."
    )
    delivery_address = models.TextField(
        "Данные для доставки",
        blank=True,
        null=True,
        help_text="Адрес и другие детали, введенные пользователем для доставки."
    )
    total_amount = models.DecimalField(
        "Общая сумма заказа",
        max_digits=12,
        decimal_places=2,
        help_text="Итоговая стоимость всех товаров в заказе."
    )
    status = models.CharField(
        "Статус заказа",
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending_payment',
        help_text="Текущий этап обработки заказа."
    )
    created_at = models.DateTimeField(
        "Дата создания",
        default=timezone.now,
        help_text="Дата и время оформления заказа."
    )
    payment_details = models.TextField(
        "Детали платежа",
        blank=True,
        null=True,
        help_text="Информация от платежного шлюза (ID транзакции, статус и т.п.)."
    )

    _original_status = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_status = self.status

    def save(self, *args, **kwargs):
        """
        Переопределение метода сохранения для логирования создания и изменения статуса заказа.
        """
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            logger.info(f"Создан новый заказ #{self.id} для пользователя {self.user} на сумму {self.total_amount}. Статус: {self.get_status_display()}.")
        elif self.status != self._original_status:
            logger.info(f"Статус заказа #{self.id} изменен с '{dict(self.STATUS_CHOICES).get(self._original_status, self._original_status)}' на '{self.get_status_display()}'.")
            self._original_status = self.status

    def __str__(self):
        """Строковое представление заказа."""
        user_display = self.user.username if self.user else "Удаленный пользователь"
        return f"Заказ #{self.id} от {user_display} ({self.get_status_display()})"

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ['-created_at']

class OrderItem(models.Model):
    """
    Модель для хранения информации о конкретном товаре в составе заказа.
    Сохраняет копию названия и цены товара на момент покупки,
    чтобы обеспечить историческую точность данных заказа.
    """
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Заказ",
        help_text="Заказ, к которому относится данная позиция."
    )
    product_name = models.CharField(
        "Название товара",
        max_length=255,
        help_text="Название товара на момент оформления заказа."
    )
    price_at_purchase = models.DecimalField(
        "Цена на момент покупки",
        max_digits=10,
        decimal_places=2,
        help_text="Цена одной единицы товара на момент оформления заказа."
    )
    quantity = models.PositiveIntegerField(
        "Количество",
        help_text="Количество единиц данного товара в заказе."
    )

    @property
    def item_total_price(self):
        """Рассчитывает общую стоимость данной позиции в заказе."""
        return self.price_at_purchase * self.quantity

    def __str__(self):
        """Строковое представление позиции заказа."""
        return f"{self.quantity} x {self.product_name} в Заказе #{self.order.id}"

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"

class FAQEntry(models.Model):
    """
    Модель для записей в разделе "Часто задаваемые вопросы" (FAQ).
    Предназначена для отображения в инлайн-режиме в боте.
    """
    question = models.CharField(
        "Вопрос",
        max_length=500,
        unique=True,
        help_text="Текст часто задаваемого вопроса."
    )
    answer = models.TextField(
        "Ответ",
        help_text="Развернутый ответ на вопрос."
    )

    def __str__(self):
        """Строковое представление записи FAQ."""
        return self.question

    class Meta:
        verbose_name = "Запись FAQ"
        verbose_name_plural = "Записи FAQ"
        ordering = ['question']

class Broadcast(models.Model):
    """
    Модель для управления рассылками из админ-панели Django.
    Позволяет создавать, планировать и отслеживать статус рассылок пользователям бота.
    """
    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('scheduled', 'Запланирована'),
        ('sending', 'Отправляется'),
        ('sent', 'Отправлена'),
        ('failed', 'Ошибка'),
    ]
    message_text = models.TextField(
        "Текст сообщения для рассылки",
        help_text="Содержимое сообщения, которое будет отправлено пользователям."
    )
    scheduled_at = models.DateTimeField(
        "Время отправки (если запланирована)",
        null=True,
        blank=True,
        help_text="Если указано, рассылка будет отправлена автоматически в это время."
    )
    created_at = models.DateTimeField(
        "Дата создания",
        default=timezone.now,
        help_text="Дата и время создания записи о рассылке."
    )
    status = models.CharField(
        "Статус",
        max_length=10,
        choices=STATUS_CHOICES,
        default='draft',
        help_text="Текущий статус рассылки."
    )
    
    sent_count = models.PositiveIntegerField("Отправлено успешно", default=0, editable=False)
    failed_count = models.PositiveIntegerField("Не удалось отправить", default=0, editable=False)


    _original_status = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_status = self.status

    def save(self, *args, **kwargs):
        """
        Переопределение метода сохранения для логирования и обновления статуса.
        """
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            logger.info(f"Создана новая рассылка #{self.id} со статусом '{self.get_status_display()}'. Текст: '{self.message_text[:50]}...'.")
        elif self.status != self._original_status:
            logger.info(f"Статус рассылки #{self.id} изменен с '{dict(self.STATUS_CHOICES).get(self._original_status, self._original_status)}' на '{self.get_status_display()}'.")
            self._original_status = self.status

    def __str__(self):
        """Строковое представление рассылки."""
        return f"Рассылка #{self.id} ({self.get_status_display()}) - {self.message_text[:50] + '...' if len(self.message_text) > 50 else self.message_text}"

    class Meta:
        verbose_name = "Рассылка"
        verbose_name_plural = "Рассылки"
        ordering = ['-created_at']


class Channel(models.Model):
    """
    Модель для хранения информации о каналах и группах,
    на которые будут подписываться клиенты. Позволяет 
    администратору добавлять каналы и группы для подписки.
    Бот должен быть администратором в этих каналах для 
    отправки сообщений.
    """
    name = models.CharField(
        "Название канала",
        max_length=255,
        help_text="Название канала или группы."
    )
    channel_id = models.BigIntegerField(
        "Telegram ID канала",
        unique=True,
        help_text="Уникальный идентификатор канала в Telegram."
    )
    is_active = models.BooleanField(
        "Активен",
        default=False,
        help_text="Флаг, указывающий, какой канал или группу активировать для подписки."
    )

    def __str__(self):
        """Строковое представление канала."""
        return self.name

    class Meta:
        verbose_name = "Канал"
        verbose_name_plural = "Каналы"
        ordering = ['name']
