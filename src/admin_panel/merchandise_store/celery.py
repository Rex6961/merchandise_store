import os
from celery import Celery
import logging

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'merchandise_store.settings')

logger = logging.getLogger(__name__)

app = Celery('merchandise_store') # Имя Celery приложения
logger.info(f"Celery (Django Project): Celery app instance 'merchandise_store' created.")

# Используем src.admin_panel.merchandise_store.settings, так как PYTHONPATH=/app
app.config_from_object('django.conf:settings', namespace='CELERY')
logger.info("Celery (Django Project): Configuration loaded from Django settings (namespace 'CELERY').")

app.autodiscover_tasks(['src.bot.tasks', 'src.admin_panel.clients.tasks'])
logger.info("Celery: Autodiscover tasks initiated.")

@app.task(bind=True)
def debug_task(self):
    logger.info(f'[Debug Task ID: {self.request.id}] Django Celery Debug Request: {self.request!r}')
    return f"Django Celery Debug task executed. Request ID: {self.request.id}"