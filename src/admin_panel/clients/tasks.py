import logging
from celery import shared_task
# Импортируем основной экземпляр Celery приложения
from admin_panel.merchandise_store.celery import app as celery_app # Дадим другое имя, чтобы не путать

from admin_panel.clients.models import TelegramUser, Broadcast

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=2, default_retry_delay=180)
def send_broadcast_chunk_task(self, telegram_user_pks, broadcast_id):
    """
    Задача Celery для обработки части рассылки (отправки сообщений группе пользователей).

    Эта задача извлекает детали рассылки и список Telegram ID пользователей,
    а затем для каждого пользователя ставит отдельную задачу
    (`bot.tasks.send_single_telegram_message_task`) в другую очередь Celery
    (`telegram_sending_queue`) для фактической отправки сообщения через Telegram Bot API.

    Args:
        self (celery.Task): Экземпляр задачи (при bind=True).
        telegram_user_pks (list): Список первичных ключей (PK) объектов TelegramUser,
                                  которым нужно отправить сообщение.
        broadcast_id (int): ID объекта Broadcast, который содержит текст сообщения.

    Returns:
        str: Сводная информация о количестве поставленных задач на отправку.

    Raises:
        Broadcast.DoesNotExist: Если рассылка с указанным ID не найдена (приводит к retry).
        Exception: Любые другие исключения при получении рассылки или постановке задач
                   (могут привести к retry в зависимости от настроек Celery).
    """
    task_id = self.request.id
    logger.info(
        f"[Task ID: {task_id}] Task send_broadcast_chunk_task started for broadcast_id {broadcast_id} "
        f"and {len(telegram_user_pks)} users."
    )
    
    try:
        broadcast = Broadcast.objects.get(pk=broadcast_id)
        message_text = broadcast.message_text
        parse_mode = getattr(broadcast, 'parse_mode', None)
        logger.info(
            f"[Task ID: {task_id}] Broadcast #{broadcast_id} found. "
            f"Text: '{message_text[:70]}...'. Parse_mode: {parse_mode}"
        )
    except Broadcast.DoesNotExist:
        logger.error(f"[Task ID: {task_id}] Broadcast with ID {broadcast_id} not found.")
        raise
    except Exception as e:
        logger.exception(f"[Task ID: {task_id}] Error fetching broadcast data #{broadcast_id}: {e}")
        raise

    target_telegram_ids = TelegramUser.objects.filter(
        pk__in=telegram_user_pks
    ).distinct().values_list('telegram_id', flat=True)
    
    logger.info(f"[Task ID: {task_id}] Fetched {len(target_telegram_ids)} target Telegram IDs from {len(telegram_user_pks)} initial user PKs.")

    if not target_telegram_ids:
        logger.warning(f"[Task ID: {task_id}] No Telegram IDs found for the provided user PKs ({telegram_user_pks}). Task finishing.")
        return f"Рассылка #{broadcast_id}: Не найдено активных Telegram ID для PK {telegram_user_pks}."

    tasks_delegated_count = 0
    logger.info(f"[Task ID: {task_id}] Starting to delegate individual send tasks for {len(target_telegram_ids)} Telegram IDs to 'telegram_sending_queue'.")
    for tg_id in target_telegram_ids:
        if tg_id:
            try:
                logger.debug(f"[Task ID: {task_id}] Attempting to queue task for tg_id {tg_id} to 'telegram_sending_queue'.")
                celery_app.send_task(
                    name='src.bot.tasks.send_single_telegram_message_task',
                    args=[int(tg_id), message_text, broadcast_id],
                    kwargs={'parse_mode': parse_mode},
                    eta=broadcast.scheduled_at if broadcast.scheduled_at else None,
                    queue='telegram_sending_queue'
                )
                tasks_delegated_count += 1
                logger.debug(f"[Task ID: {task_id}] Task for tg_id {tg_id} successfully queued.")
            except ValueError as e:
                 logger.error(f"[Task ID: {task_id}] Invalid telegram_id '{tg_id}' (type: {type(tg_id)}): {e}. Skipping.")
            except Exception as e:
                logger.exception(f"[Task ID: {task_id}] Error queuing task for tg_id {tg_id} to 'telegram_sending_queue': {e}")
        else:
            logger.warning(f"[Task ID: {task_id}] Found empty telegram_id. Skipping.")

    summary = (
        f"Broadcast #{broadcast_id}: {tasks_delegated_count} out of {len(target_telegram_ids)} message sending tasks "
        f"queued to 'telegram_sending_queue'."
    )
    logger.info(f"[Task ID: {task_id}] Task finished. {summary}")
    return summary