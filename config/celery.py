"""Celery configuration for Humatron."""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('humatron')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Periodic cleanup schedule (daily at 03:00 UTC)
app.conf.beat_schedule = {
    'cleanup-expired-files-daily': {
        'task': 'pdf_processor.tasks.cleanup_expired_files_task',
        'schedule': crontab(hour=3, minute=0),
    },
    'check-expiring-subscriptions-daily': {
        'task': 'subscriptions.tasks.check_expiring_subscriptions_task',
        'schedule': crontab(hour=4, minute=0),
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
