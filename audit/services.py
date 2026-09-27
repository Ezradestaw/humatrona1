import logging
from .models import AuditLog

logger = logging.getLogger('humatron')


def log_admin_action(request, action, target, metadata=None):
    """Utility function to record administrative audit events with IP and metadata."""
    if metadata is None:
        metadata = {}
    
    admin_user = request.user if (request and request.user.is_authenticated) else None
    
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')

    log_entry = AuditLog.objects.create(
        administrator=admin_user,
        action=action,
        target=str(target),
        metadata=metadata,
        ip_address=ip_address
    )
    logger.info("AUDIT: %s performed '%s' on '%s' (IP: %s)", admin_user, action, target, ip_address)
    return log_entry
