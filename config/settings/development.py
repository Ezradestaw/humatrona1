"""Development settings."""
from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']

# Run tasks synchronously in development for instant, reliable processing
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
