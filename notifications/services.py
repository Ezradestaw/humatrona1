import logging
import re
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.urls import reverse
from accounts.tokens import email_verification_token
from .models import Notification

logger = logging.getLogger('humatron')


def sanitize_email_error(error_message):
    """
    Strips passwords, secrets, or authentication headers from error strings
    to guarantee zero credential leakage in logs and database records (Section 13).
    """
    if not error_message:
        return ""
    err_str = str(error_message)

    # Redact any configured passwords if they happen to appear in error text
    passwords_to_scrub = [
        getattr(settings, 'SUPPORT_EMAIL_APP_PASSWORD', ''),
        getattr(settings, 'CONTACT_EMAIL_APP_PASSWORD', ''),
        getattr(settings, 'EMAIL_HOST_PASSWORD', ''),
    ]
    for pwd in passwords_to_scrub:
        if pwd and len(pwd) > 3:
            err_str = err_str.replace(pwd, '[REDACTED_SECRET]')

    # Scrub common basic auth / credential patterns
    err_str = re.sub(r'(password|pass|secret|auth)[=:]\s*([^\s,]+)', r'\1=[REDACTED]', err_str, flags=re.IGNORECASE)
    return err_str


def get_email_connection(mailbox='support'):
    """
    Factory creating controlled SMTP connections per mailbox (Section 5, 6).
    - 'support': Primary transactional mailbox (support@humatron.me)
    - 'contact': Business/contact mailbox (contact@humatron.me)
    Respects in-memory/console backends when running automated tests.
    """
    backend_path = getattr(settings, 'EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
    
    # In automated tests or local console mode, use the configured backend directly
    if 'locmem' in backend_path or 'console' in backend_path:
        return get_connection(backend_path)

    smtp_host = getattr(settings, 'SMTP_HOST', 'mail.privateemail.com')
    smtp_port = getattr(settings, 'SMTP_PORT', 587)
    smtp_use_tls = getattr(settings, 'SMTP_USE_TLS', True)

    if mailbox == 'contact':
        contact_email = getattr(settings, 'CONTACT_EMAIL', 'contact@humatron.me')
        contact_password = getattr(settings, 'CONTACT_EMAIL_APP_PASSWORD', '')
        return get_connection(
            backend=backend_path,
            host=smtp_host,
            port=smtp_port,
            username=contact_email,
            password=contact_password,
            use_tls=smtp_use_tls,
            timeout=5,
        )
    else:
        # Default support account
        support_email = getattr(settings, 'SUPPORT_EMAIL', 'support@humatron.me')
        support_password = getattr(settings, 'SUPPORT_EMAIL_APP_PASSWORD', '')
        return get_connection(
            backend=backend_path,
            host=smtp_host,
            port=smtp_port,
            username=support_email,
            password=support_password,
            use_tls=smtp_use_tls,
            timeout=5,
        )


class EmailService:
    """
    Centralized server-side email dispatch service for Humatron (Sections 1-18).
    Enforces server-controlled sender routing:
    - System/transactional -> support@humatron.me
    - Contact/business inquiries -> contact@humatron.me
    - Administrator notifications -> admin@humatron.me
    """

    @classmethod
    def _dispatch_email(cls, recipient_email, subject, message_text, notification_type,
                        html_message=None, user=None, mailbox='support', reply_to=None):
        """
        Dispatches multipart (text + HTML) email securely through the designated mailbox.
        Guarantees:
        - Never leaks credentials in logs or DB
        - Sets appropriate From header and Reply-To header
        - Records auditable delivery state
        """
        if mailbox == 'contact':
            from_email = getattr(settings, 'DEFAULT_CONTACT_FROM_EMAIL', 'Humatron Contact <contact@humatron.me>')
        else:
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Humatron Support <support@humatron.me>')

        notification = Notification.objects.create(
            user=user,
            recipient_email=recipient_email,
            notification_type=notification_type,
            subject=subject,
            body=message_text,
        )

        try:
            connection = get_email_connection(mailbox=mailbox)
            msg = EmailMultiAlternatives(
                subject=subject,
                body=message_text,
                from_email=from_email,
                to=[recipient_email],
                reply_to=reply_to or [],
                connection=connection,
            )
            if html_message:
                msg.attach_alternative(html_message, "text/html")

            msg.send(fail_silently=False)

            notification.is_sent = True
            notification.save(update_fields=['is_sent'])
            logger.info("Email '%s' successfully sent to %s via mailbox '%s'", subject, recipient_email, mailbox)
            return True, "Email sent successfully."

        except Exception as exc:
            sanitized_err = sanitize_email_error(exc)
            notification.error_message = sanitized_err
            notification.save(update_fields=['error_message'])
            logger.error("Failed to send email '%s' to %s via '%s': %s", subject, recipient_email, mailbox, sanitized_err)
            return False, "We could not send the email at this time. Please try again later."

    @classmethod
    def send_verification_email(cls, user, request=None):
        """Account registration email verification (Section 8)."""
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

        context = {
            'user': user,
            'verify_url': verify_url,
        }

        subject = render_to_string('email/verification/subject.txt', context).strip() or "Verify your Humatron account"
        text_message = render_to_string('email/verification/message.txt', context)
        html_message = render_to_string('email/verification/message.html', context)

        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=text_message,
            notification_type='email_verification',
            html_message=html_message,
            user=user,
            mailbox='support'
        )
        return success

    @classmethod
    def send_password_reset_email(cls, user, reset_url):
        """Password reset email with secure expiring link (Section 9)."""
        context = {
            'user': user,
            'reset_url': reset_url,
        }

        subject = render_to_string('email/password_reset/subject.txt', context).strip() or "Humatron Password Reset Request"
        text_message = render_to_string('email/password_reset/message.txt', context)
        html_message = render_to_string('email/password_reset/message.html', context)

        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=text_message,
            notification_type='password_reset',
            html_message=html_message,
            user=user,
            mailbox='support'
        )
        return success

    @classmethod
    def send_payment_received_email(cls, user, payment):
        """Payment confirmation and receipt summary (Section 10)."""
        context = {
            'user': user,
            'payment': payment,
        }

        subject = render_to_string('email/payment/subject.txt', context).strip() or f"Humatron Payment Receipt: {payment.currency} {payment.amount}"
        text_message = render_to_string('email/payment/message.txt', context)
        html_message = render_to_string('email/payment/message.html', context)

        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=text_message,
            notification_type='payment_received',
            html_message=html_message,
            user=user,
            mailbox='support'
        )
        return success

    @classmethod
    def send_payment_failed_email(cls, user, payment, reason):
        """Payment verification failure notification (Section 10)."""
        subject = "Humatron: Payment Verification Notice"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"We were unable to verify payment transaction '{payment.transaction_id}'.\n"
            f"Reason: {reason}\n\n"
            f"Please check your transaction details or contact support at support@humatron.me.\n\n"
            f"Regards,\nHumatron Billing Team"
        )
        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=message,
            notification_type='payment_failed',
            user=user,
            mailbox='support'
        )
        return success

    @classmethod
    def send_subscription_activated_email(cls, user, subscription):
        """Subscription activated notification (Section 10)."""
        context = {
            'user': user,
            'subscription': subscription,
            'status_headline': f"Your '{subscription.plan.name}' subscription is active",
            'status_message': f"Your subscription to the '{subscription.plan.name}' plan on Humatron has been activated successfully.",
        }

        subject = render_to_string('email/subscription/subject.txt', context).strip() or f"Humatron: Subscription Activated ({subscription.plan.name})"
        text_message = render_to_string('email/subscription/message.txt', context)
        html_message = render_to_string('email/subscription/message.html', context)

        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=text_message,
            notification_type='subscription_activated',
            html_message=html_message,
            user=user,
            mailbox='support'
        )
        return success

    @classmethod
    def send_subscription_expiring_email(cls, user, subscription, days_remaining):
        """Subscription expiring warning notification (Section 10)."""
        context = {
            'user': user,
            'subscription': subscription,
            'status_headline': f"Your subscription expires in {days_remaining} day(s)",
            'status_message': f"Your '{subscription.plan.name}' subscription will expire on {subscription.end_date.strftime('%B %d, %Y') if subscription.end_date else 'soon'}.",
        }

        subject = f"Humatron: Your subscription expires in {days_remaining} day(s)"
        text_message = render_to_string('email/subscription/message.txt', context)
        html_message = render_to_string('email/subscription/message.html', context)

        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=text_message,
            notification_type='subscription_expiring',
            html_message=html_message,
            user=user,
            mailbox='support'
        )
        return success

    @classmethod
    def send_subscription_expired_email(cls, user, subscription):
        """Subscription expired notification (Section 10)."""
        context = {
            'user': user,
            'subscription': subscription,
            'status_headline': "Your subscription has expired",
            'status_message': f"Your '{subscription.plan.name}' subscription on Humatron has expired. To continue processing PDF documents, please renew your plan.",
        }

        subject = "Humatron: Your subscription has expired"
        text_message = render_to_string('email/subscription/message.txt', context)
        html_message = render_to_string('email/subscription/message.html', context)

        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=text_message,
            notification_type='subscription_expired',
            html_message=html_message,
            user=user,
            mailbox='support'
        )
        return success


    @classmethod
    def send_pdf_completed_email(cls, user, job, download_url):
        """PDF processing completed notification (Section 10)."""
        context = {
            'user': user,
            'job': job,
            'download_url': download_url,
        }

        subject = render_to_string('email/pdf_processing/subject.txt', context).strip() or "Humatron: Your PDF is ready for download"
        text_message = render_to_string('email/pdf_processing/message.txt', context)
        html_message = render_to_string('email/pdf_processing/message.html', context)

        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=text_message,
            notification_type='pdf_completed',
            html_message=html_message,
            user=user,
            mailbox='support'
        )
        return success

    @classmethod
    def send_pdf_failed_email(cls, user, job, error_message=None):
        """PDF processing failed notification (Section 10)."""
        subject = "Humatron: PDF Processing Notice"
        message = (
            f"Dear {user.first_name or user.username},\n\n"
            f"We encountered an issue processing your document '{job.original_filename}'.\n\n"
            f"Our service encountered an error during image rasterization. Your processing quota has not been deducted.\n\n"
            f"Please verify that the PDF is valid and not password protected, or contact support@humatron.me.\n\n"
            f"Regards,\nHumatron PDF Service"
        )
        success, _ = cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=message,
            notification_type='payment_failed',
            user=user,
            mailbox='support'
        )
        return success

    @classmethod
    def send_admin_contact_notification(cls, contact_message):
        """
        Dispatches new contact form message to the administrator (Section 1, 7, 11).
        - Sent TO: admin@humatron.me
        - Sent FROM: Humatron Contact <contact@humatron.me>
        - Reply-To: [contact_message.email] (user-submitted email as Reply-To, never as SMTP sender)
        """
        admin_email = getattr(settings, 'ADMIN_EMAIL', 'admin@humatron.me')
        subject = f"[Humatron Contact] New message from {contact_message.name}: {contact_message.subject}"
        message = (
            f"A new contact inquiry has been submitted on Humatron:\n\n"
            f"From: {contact_message.name} <{contact_message.email}>\n"
            f"Subject: {contact_message.subject}\n"
            f"IP: {contact_message.ip_address}\n"
            f"Time: {contact_message.created_at:%Y-%m-%d %H:%M UTC}\n\n"
            f"Message:\n"
            f"{contact_message.message}\n"
        )
        success, _ = cls._dispatch_email(
            recipient_email=admin_email,
            subject=subject,
            message_text=message,
            notification_type='contact_message',
            mailbox='contact',
            reply_to=[contact_message.email]
        )
        return success

    @classmethod
    def send_smtp_test_email(cls, recipient_email, mailbox='support'):
        """
        Administrator-only SMTP verification test tool (Section 16).
        - Requires administrator authentication in admin interface
        - Validates recipient email
        - Dispatches test email using configured SMTP credentials
        - Reports only sanitized success or failure
        - Never logs or exposes App Passwords
        """
        if not recipient_email or '@' not in recipient_email:
            return False, "Invalid recipient email address."

        subject = "Humatron SMTP Test"
        message = (
            f"This is an automated test email confirming Namecheap Private Email SMTP configuration on Humatron.\n\n"
            f"Mailbox tested: {mailbox}\n"
            f"Server: {getattr(settings, 'SMTP_HOST', 'mail.privateemail.com')}:{getattr(settings, 'SMTP_PORT', 587)}\n"
            f"TLS: {getattr(settings, 'SMTP_USE_TLS', True)}\n\n"
            f"If you received this message, SMTP delivery is functioning properly."
        )

        return cls._dispatch_email(
            recipient_email=recipient_email,
            subject=subject,
            message_text=message,
            notification_type='contact_message',
            mailbox=mailbox
        )

    @classmethod
    def send_binance_manual_payment_submitted_email(cls, user, payment):
        """Notification sent when user submits Binance manual payment info (awaiting review)."""
        plan_name = payment.plan.name if payment.plan else 'Subscription'
        subject = f"Humatron: Binance Payment Submitted ({plan_name})"
        message_text = (
            f"Hello {user.email},\n\n"
            f"Your manual Binance payment submission for the {plan_name} plan has been received and is awaiting administrator verification.\n\n"
            f"Payment Details:\n"
            f"- Transaction ID: {payment.transaction_id}\n"
            f"- Amount: {payment.currency} {payment.amount}\n"
            f"- Sender Identifier: {payment.sender_identifier or 'N/A'}\n"
            f"- Current Status: Under Review (Pending)\n\n"
            f"Once our administration team verifies the transfer on Binance, your subscription will be activated automatically.\n\n"
            f"Best regards,\nHumatron Support Team\nsupport@humatron.me"
        )
        return cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=message_text,
            notification_type='payment_submitted',
            user=user,
            mailbox='support'
        )

    @classmethod
    def send_binance_manual_payment_approved_email(cls, user, payment):
        """Notification sent when administrator approves manual Binance payment."""
        plan_name = payment.plan.name if payment.plan else 'Subscription'
        subject = f"Humatron: Binance Payment Approved! ({plan_name})"
        end_date_str = payment.subscription.end_date.strftime('%B %d, %Y') if (payment.subscription and payment.subscription.end_date) else 'active'
        message_text = (
            f"Hello {user.email},\n\n"
            f"Great news! Your manual Binance payment has been verified and approved by a Humatron administrator.\n\n"
            f"Subscription Summary:\n"
            f"- Plan: {plan_name}\n"
            f"- Transaction ID: {payment.transaction_id}\n"
            f"- Amount Confirmed: {payment.currency} {payment.amount}\n"
            f"- Status: Active\n"
            f"- Valid Until: {end_date_str}\n\n"
            f"You can now begin processing PDF documents on Humatron.\n\n"
            f"Best regards,\nHumatron Support Team\nsupport@humatron.me"
        )
        return cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=message_text,
            notification_type='payment_approved',
            user=user,
            mailbox='support'
        )

    @classmethod
    def send_binance_manual_payment_rejected_email(cls, user, payment, reason=""):
        """Notification sent when administrator rejects manual Binance payment."""
        plan_name = payment.plan.name if payment.plan else 'Subscription'
        subject = "Humatron: Binance Payment Verification Update"
        reason_text = reason or payment.rejection_reason or "Verification details could not be matched."
        message_text = (
            f"Hello {user.email},\n\n"
            f"We are writing to let you know that your manual Binance payment for the {plan_name} plan could not be verified.\n\n"
            f"Transaction ID: {payment.transaction_id}\n"
            f"Reason for rejection:\n{reason_text}\n\n"
            f"If you believe this was an error or need assistance, please reply to this email or contact support@humatron.me with your Binance transfer receipt.\n\n"
            f"Best regards,\nHumatron Support Team\nsupport@humatron.me"
        )
        return cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=message_text,
            notification_type='payment_rejected',
            user=user,
            mailbox='support'
        )

    @classmethod
    def send_telebirr_payment_submitted_email(cls, user, payment):
        """Notification sent when user submits Telebirr transaction number (awaiting review)."""
        plan_name = payment.plan.name if payment.plan else 'Subscription'
        subject = f"Humatron: Telebirr Payment Submitted ({plan_name})"
        message_text = (
            f"Hello {user.email},\n\n"
            f"Your Telebirr payment submission for the {plan_name} plan has been received and is awaiting administrator verification.\n\n"
            f"Payment Details:\n"
            f"- Transaction Number: {payment.transaction_id}\n"
            f"- Amount: {payment.currency} {payment.amount}\n"
            f"- Current Status: Under Review (Pending)\n\n"
            f"Once our administration team verifies the transaction, your subscription will be activated automatically.\n\n"
            f"Best regards,\nHumatron Support Team\nsupport@humatron.me"
        )
        return cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=message_text,
            notification_type='payment_submitted',
            user=user,
            mailbox='support'
        )

    @classmethod
    def send_telebirr_payment_approved_email(cls, user, payment):
        """Notification sent when administrator approves Telebirr payment."""
        plan_name = payment.plan.name if payment.plan else 'Subscription'
        subject = f"Humatron: Telebirr Payment Approved! ({plan_name})"
        end_date_str = payment.subscription.end_date.strftime('%B %d, %Y') if (payment.subscription and payment.subscription.end_date) else 'active'
        message_text = (
            f"Hello {user.email},\n\n"
            f"Great news! Your Telebirr payment has been verified and approved by a Humatron administrator.\n\n"
            f"Subscription Summary:\n"
            f"- Plan: {plan_name}\n"
            f"- Transaction Number: {payment.transaction_id}\n"
            f"- Amount Confirmed: {payment.currency} {payment.amount}\n"
            f"- Status: Active\n"
            f"- Valid Until: {end_date_str}\n\n"
            f"You can now begin processing PDF documents on Humatron.\n\n"
            f"Best regards,\nHumatron Support Team\nsupport@humatron.me"
        )
        return cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=message_text,
            notification_type='payment_approved',
            user=user,
            mailbox='support'
        )

    @classmethod
    def send_telebirr_payment_rejected_email(cls, user, payment, reason=""):
        """Notification sent when administrator rejects Telebirr payment."""
        plan_name = payment.plan.name if payment.plan else 'Subscription'
        subject = "Humatron: Telebirr Payment Verification Update"
        reason_text = reason or payment.rejection_reason or "Verification details could not be matched."
        message_text = (
            f"Hello {user.email},\n\n"
            f"We are writing to let you know that your Telebirr payment for the {plan_name} plan could not be verified.\n\n"
            f"Transaction Number: {payment.transaction_id}\n"
            f"Reason for rejection:\n{reason_text}\n\n"
            f"If you believe this was an error or need assistance, please reply to this email or contact support@humatron.me.\n\n"
            f"Best regards,\nHumatron Support Team\nsupport@humatron.me"
        )
        return cls._dispatch_email(
            recipient_email=user.email,
            subject=subject,
            message_text=message_text,
            notification_type='payment_rejected',
            user=user,
            mailbox='support'
        )


