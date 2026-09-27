import logging
from django.conf import settings
from django.core.mail import send_mail
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.urls import reverse
from accounts.tokens import email_verification_token
from .models import Notification

logger = logging.getLogger('humatron')


class EmailService:
    """Centralized email notification service for Humatron."""

    @classmethod
    def _dispatch_email(cls, recipient_email, subject, message_text, notification_type, user=None):
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Humatron PDF <noreply@humatron.me>')
        notification = Notification.objects.create(
            user=user,
            recipient_email=recipient_email,
            notification_type=notification_type,
            subject=subject,
            body=message_text,
        )
        try:
            send_mail(
                subject=subject,
                message=message_text,
                from_email=from_email,
                recipient_list=[recipient_email],
                fail_silently=False,
            )
            notification.is_sent = True
            notification.save(update_fields=['is_sent'])
            logger.info("Email '%s' sent to %s", subject, recipient_email)
            return True
        except Exception as exc:
            notification.error_message = str(exc)
            notification.save(update_fields=['error_message'])
            logger.error("Failed to send email '%s' to %s: %s", subject, recipient_email, exc)
            return False

    @classmethod
    def send_verification_email(cls, user, request=None):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token.make_token(user)
        
        if request:
            verify_url = request.build_absolute_uri(
                reverse('accounts:verify_email', kwargs={'uidb64': uid, 'token': token})
            )
        else:
            domain = getattr(settings, 'SITE_DOMAIN', 'humatron.me')
            path = reverse('accounts:verify_email', kwargs={'uidb64': uid, 'token': token})
            verify_url = f"https://{domain}{path}"

        subject = "Verify your Humatron account"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"Thank you for registering on Humatron (https://humatron.me).\n\n"
            f"Please click the link below to verify your email address and activate your account:\n"
            f"{verify_url}\n\n"
            f"This link is single-use and will expire for your security.\n\n"
            f"If you did not register for an account on Humatron, please ignore this email.\n\n"
            f"Regards,\nHumatron Support Team\nhttps://humatron.me"
        )
        return cls._dispatch_email(user.email, subject, message, 'email_verification', user=user)

    @classmethod
    def send_password_reset_email(cls, user, reset_url):
        subject = "Humatron Password Reset Request"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"We received a request to reset your password on Humatron.\n\n"
            f"You can set a new password by following this secure link:\n"
            f"{reset_url}\n\n"
            f"If you did not request this, no action is needed. Your current password remains secure.\n\n"
            f"Regards,\nHumatron Support Team"
        )
        return cls._dispatch_email(user.email, subject, message, 'password_reset', user=user)

    @classmethod
    def send_subscription_activated_email(cls, user, subscription):
        subject = f"Humatron: Subscription Activated ({subscription.plan.name})"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"Your subscription to the '{subscription.plan.name}' plan is now active.\n\n"
            f"Plan Details:\n"
            f"- Allowed PDFs: {subscription.pdf_limit}\n"
            f"- Valid Until: {subscription.end_date.strftime('%B %d, %Y') if subscription.end_date else 'Permanent'}\n\n"
            f"You can access your dashboard and process documents at:\n"
            f"https://humatron.me/dashboard/\n\n"
            f"Thank you for choosing Humatron.\n\n"
            f"Regards,\nHumatron Billing Team"
        )
        return cls._dispatch_email(user.email, subject, message, 'subscription_activated', user=user)

    @classmethod
    def send_subscription_expiring_email(cls, user, subscription, days_remaining):
        subject = f"Humatron: Your subscription expires in {days_remaining} day(s)"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"Your '{subscription.plan.name}' subscription will expire on "
            f"{subscription.end_date.strftime('%B %d, %Y')}.\n\n"
            f"To avoid disruption, please renew your subscription here:\n"
            f"https://humatron.me/subscriptions/\n\n"
            f"Regards,\nHumatron Billing Team"
        )
        return cls._dispatch_email(user.email, subject, message, 'subscription_expiring', user=user)

    @classmethod
    def send_subscription_expired_email(cls, user, subscription):
        subject = "Humatron: Your subscription has expired"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"Your '{subscription.plan.name}' subscription on Humatron has expired.\n\n"
            f"To continue processing PDF documents, please renew your plan:\n"
            f"https://humatron.me/subscriptions/\n\n"
            f"Regards,\nHumatron Billing Team"
        )
        return cls._dispatch_email(user.email, subject, message, 'subscription_expired', user=user)

    @classmethod
    def send_payment_received_email(cls, user, payment):
        subject = f"Humatron Payment Receipt: {payment.currency} {payment.amount}"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"We have verified your payment for your Humatron subscription.\n\n"
            f"Receipt Summary:\n"
            f"- Payment Provider: {payment.provider.upper()}\n"
            f"- Transaction ID: {payment.transaction_id}\n"
            f"- Amount: {payment.currency} {payment.amount}\n"
            f"- Date: {payment.verified_at.strftime('%Y-%m-%d %H:%M UTC') if payment.verified_at else 'Recent'}\n\n"
            f"View your payment history at https://humatron.me/payments/history/\n\n"
            f"Regards,\nHumatron Accounts Team"
        )
        return cls._dispatch_email(user.email, subject, message, 'payment_received', user=user)

    @classmethod
    def send_payment_failed_email(cls, user, payment, reason):
        subject = "Humatron: Payment Verification Notice"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"We were unable to verify payment transaction '{payment.transaction_id}'.\n"
            f"Reason: {reason}\n\n"
            f"Please check your transaction details or contact support at {getattr(settings, 'ADMIN_EMAIL', 'admin@humatron.me')}.\n\n"
            f"Regards,\nHumatron Billing Team"
        )
        return cls._dispatch_email(user.email, subject, message, 'payment_failed', user=user)

    @classmethod
    def send_pdf_completed_email(cls, user, job, download_url):
        subject = "Humatron: Your PDF is ready for download"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"Your document '{job.original_filename}' has been converted into an image-based PDF successfully.\n\n"
            f"Total Pages: {job.page_count}\n"
            f"Download your document here (requires login):\n"
            f"{download_url}\n\n"
            f"Note: Processed files are retained for {getattr(settings, 'FILE_RETENTION_DAYS', 7)} days.\n\n"
            f"Regards,\nHumatron PDF Service"
        )
        return cls._dispatch_email(user.email, subject, message, 'pdf_completed', user=user)

    @classmethod
    def send_admin_contact_notification(cls, contact_message):
        admin_email = getattr(settings, 'ADMIN_EMAIL', 'admin@humatron.me')
        subject = f"[Humatron Contact] New message from {contact_message.name}: {contact_message.subject}"
        message = (
            f"A new contact inquiry has been submitted:\n\n"
            f"From: {contact_message.name} <{contact_message.email}>\n"
            f"Subject: {contact_message.subject}\n"
            f"IP: {contact_message.ip_address}\n"
            f"Time: {contact_message.created_at:%Y-%m-%d %H:%M UTC}\n\n"
            f"Message:\n"
            f"{contact_message.message}\n"
        )
        return cls._dispatch_email(admin_email, subject, message, 'contact_message')

    @classmethod
    def send_educational_verification_email(cls, user, educational_email, request=None):
        from accounts.tokens import educational_email_token
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = educational_email_token.make_token(user)

        if request:
            verify_url = request.build_absolute_uri(
                reverse('accounts:verify_educational_email', kwargs={'uidb64': uid, 'token': token})
            )
        else:
            domain = getattr(settings, 'SITE_DOMAIN', 'humatron.me')
            path = reverse('accounts:verify_educational_email', kwargs={'uidb64': uid, 'token': token})
            verify_url = f"https://{domain}{path}"

        subject = "Humatron: Verify your student educational email"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"We received a request to verify this educational email address ({educational_email}) "
            f"for your Humatron student discount (25% off).\n\n"
            f"Please click the link below to verify your educational email:\n"
            f"{verify_url}\n\n"
            f"This link is single-use and will expire for your security.\n\n"
            f"Regards,\nHumatron Verification Team\nhttps://humatron.me"
        )
        return cls._dispatch_email(educational_email, subject, message, 'email_verification', user=user)

    @classmethod
    def send_student_verification_approved_email(cls, user):
        subject = "Humatron: Your 25% Student Discount Has Been Approved!"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"Congratulations! Your student status has been reviewed and verified by our administration team.\n\n"
            f"A 25% discount is now active on your account and will automatically apply to your subscription checkout.\n\n"
            f"View subscription plans here:\n"
            f"https://humatron.me/subscriptions/\n\n"
            f"Regards,\nHumatron Billing Team"
        )
        return cls._dispatch_email(user.email, subject, message, 'subscription_activated', user=user)

    @classmethod
    def send_student_verification_rejected_email(cls, user, reason):
        subject = "Humatron: Student Verification Status Update"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"Thank you for submitting your student verification. Unfortunately, your submission could not be approved at this time.\n\n"
            f"Reason: {reason}\n\n"
            f"You may submit an updated, valid student ID with current expiration date via your profile:\n"
            f"https://humatron.me/accounts/student-verification/\n\n"
            f"Regards,\nHumatron Verification Team"
        )
        return cls._dispatch_email(user.email, subject, message, 'payment_failed', user=user)
