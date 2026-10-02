from django.conf import settings
from django.db import models


class BinanceManualPaymentSettings(models.Model):
    """
    Administrative configuration for manual Binance payment workflow.
    Configured dynamically in Django Admin.
    """
    IDENTIFIER_TYPE_PAY_ID = 'PAY_ID'
    IDENTIFIER_TYPE_UID = 'UID'
    IDENTIFIER_TYPE_USDT_TRC20 = 'USDT_TRC20'
    IDENTIFIER_TYPE_USDT_BEP20 = 'USDT_BEP20'
    IDENTIFIER_TYPE_OTHER = 'OTHER'

    IDENTIFIER_TYPE_CHOICES = [
        (IDENTIFIER_TYPE_PAY_ID, 'Binance Pay ID'),
        (IDENTIFIER_TYPE_UID, 'Binance UID'),
        (IDENTIFIER_TYPE_USDT_TRC20, 'USDT (TRC-20 Address)'),
        (IDENTIFIER_TYPE_USDT_BEP20, 'USDT (BEP-20 Address)'),
        (IDENTIFIER_TYPE_OTHER, 'Other Identifier / Address'),
    ]

    enabled = models.BooleanField(default=True, help_text="Enable Binance Manual Payment on checkout")
    receiving_identifier = models.CharField(
        max_length=128,
        default="1104715375",
        help_text="Receiving Binance Pay ID, Binance UID, or wallet address"
    )
    receiving_identifier_type = models.CharField(
        max_length=32,
        choices=IDENTIFIER_TYPE_CHOICES,
        default=IDENTIFIER_TYPE_UID,
        help_text="Type of identifier provided to the customer"
    )
    qr_code = models.ImageField(
        upload_to='payments/qr/',
        blank=True,
        null=True,
        help_text="Optional QR code image for customer scanning"
    )
    payment_instructions = models.TextField(
        blank=True,
        default=(
            "1. Open your Binance app or web portal.\n"
            "2. Send the exact required amount to our configured Binance identifier above.\n"
            "3. Obtain your transaction ID (or order ID / TxID) and Note your sender Binance UID.\n"
            "4. Return to Humatron and submit the transaction information below.\n"
            "5. A Humatron administrator will verify the receipt and activate your subscription."
        ),
        help_text="Clear step-by-step payment instructions for users."
    )
    support_message = models.TextField(
        blank=True,
        default="Need assistance with your transfer? Contact support@humatron.me with your transaction reference.",
        help_text="Support contact message displayed to the user."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Binance Manual Payment Settings"
        verbose_name_plural = "Binance Manual Payment Settings"

    def __str__(self):
        status_label = "Enabled" if self.enabled else "Disabled"
        return f"Binance Manual Payment Settings ({status_label}) - {self.get_receiving_identifier_type_display()}: {self.receiving_identifier}"

    @classmethod
    def get_settings(cls):
        settings_obj, _ = cls.objects.get_or_create(id=1)
        return settings_obj


class TelebirrPaymentSettings(models.Model):
    """
    Administrative configuration for Telebirr payments.
    Allows administrators to configure the receiver Name and Phone number in Django Admin.
    """
    enabled = models.BooleanField(
        default=True,
        help_text="Enable Telebirr payments for Ethiopian users"
    )
    receiver_name = models.CharField(
        max_length=150,
        default="Humatron Technologies",
        verbose_name="Name",
        help_text="Receiver / Merchant Name displayed to customers for Telebirr transfer"
    )
    phone_number = models.CharField(
        max_length=50,
        default="0911000000",
        verbose_name="Phone Number",
        help_text="Telebirr phone number where customers send payment"
    )
    instructions = models.TextField(
        blank=True,
        default=(
            "1. Open your Telebirr app or dial *127#.\n"
            "2. Transfer the exact plan amount to our Telebirr Phone Number and Name above.\n"
            "3. Upon completion, enter your Telebirr transaction number below."
        ),
        help_text="Payment instructions displayed to Ethiopian customers."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telebirr Payment Settings"
        verbose_name_plural = "Telebirr Payment Settings"

    def __str__(self):
        status_label = "Enabled" if self.enabled else "Disabled"
        return f"Telebirr Payment Settings ({status_label}) - Name: {self.receiver_name}, Phone: {self.phone_number}"

    @classmethod
    def get_settings(cls):
        settings_obj, _ = cls.objects.get_or_create(
            id=1,
            defaults={
                'receiver_name': getattr(settings, 'TELEBIRR_MERCHANT_NAME', 'Humatron Technologies'),
                'phone_number': getattr(settings, 'TELEBIRR_RECEIVER_PHONE', '0911000000'),
            }
        )
        return settings_obj


class Payment(models.Model):
    """
    Unified payment model for Telebirr and Binance (Manual & Automated).
    Features database-level unique constraints preventing double activation.
    """
    PROVIDER_TELEBIRR = 'telebirr'
    PROVIDER_BINANCE = 'binance'

    PROVIDER_CHOICES = [
        (PROVIDER_TELEBIRR, 'Telebirr'),
        (PROVIDER_BINANCE, 'Binance Pay'),
    ]

    METHOD_BINANCE_MANUAL = 'BINANCE_MANUAL'
    METHOD_BINANCE_PAY_API = 'BINANCE_PAY_API'
    METHOD_TELEBIRR = 'TELEBIRR'
    METHOD_OTHER = 'OTHER'

    PAYMENT_METHOD_CHOICES = [
        (METHOD_BINANCE_MANUAL, 'Binance Manual Payment'),
        (METHOD_BINANCE_PAY_API, 'Binance Pay API (Automated)'),
        (METHOD_TELEBIRR, 'Telebirr Manual SMS'),
        (METHOD_OTHER, 'Other'),
    ]

    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_VERIFIED = 'VERIFIED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_RECEIVED = 'RECEIVED'
    STATUS_DUPLICATE = 'DUPLICATE'
    STATUS_FAILED = 'FAILED'
    STATUS_EXPIRED = 'EXPIRED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_VERIFIED, 'Verified'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_RECEIVED, 'Received'),
        (STATUS_DUPLICATE, 'Duplicate'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, db_index=True)
    payment_method = models.CharField(
        max_length=32,
        choices=PAYMENT_METHOD_CHOICES,
        default=METHOD_BINANCE_MANUAL,
        db_index=True,
        help_text="Extensible payment method abstraction"
    )
    transaction_id = models.CharField(max_length=128, db_index=True)
    plan = models.ForeignKey(
        'subscriptions.SubscriptionPlan',
        on_delete=models.PROTECT,
        related_name='payments',
        null=True,
        blank=True
    )
    subscription = models.ForeignKey(
        'subscriptions.Subscription',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Amount paid/captured")
    currency = models.CharField(max_length=5, default='USD')
    payment_country = models.CharField(max_length=100, blank=True)
    original_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    final_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RECEIVED,
        db_index=True
    )
    raw_message = models.TextField(blank=True, help_text="Original Telebirr SMS or webhook payload")
    message_hash = models.CharField(max_length=64, blank=True, db_index=True)
    merchant_account = models.CharField(max_length=100, blank=True)
    sender_info = models.CharField(max_length=100, blank=True)
    rejection_reason = models.TextField(blank=True)
    sender_identifier = models.CharField(max_length=128, blank=True, help_text="Sender Binance UID or identifier")
    proof_file = models.FileField(upload_to='payments/proofs/%Y/%m/', blank=True, null=True, help_text="Optional payment screenshot or proof document")
    submitted_at = models.DateTimeField(null=True, blank=True, help_text="When user submitted the manual payment information")
    reviewed_at = models.DateTimeField(null=True, blank=True, help_text="When administrator approved or rejected the payment")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_payments',
        help_text="Administrator who reviewed this payment"
    )
    admin_notes = models.TextField(blank=True, help_text="Internal notes by administrator")
    updated_at = models.DateTimeField(auto_now=True)
    
    # Binance Pay specific fields
    merchant_trade_no = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="Unique merchant trade number for Binance Pay order tracking"
    )
    prepay_id = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
        help_text="Binance Pay prepay identifier"
    )
    binance_order_id = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
        help_text="Binance transaction or bizId identifier"
    )
    checkout_url = models.URLField(max_length=512, blank=True, help_text="Binance Pay web checkout URL")
    qr_code_url = models.URLField(max_length=512, blank=True, help_text="Binance Pay QR code image URL")
    qr_content = models.TextField(blank=True, help_text="Raw QR code payload for scanning")
    order_expire_time = models.DateTimeField(null=True, blank=True, help_text="Order expiration datetime")

    received_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-received_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'transaction_id'],
                name='unique_provider_transaction_id'
            ),
            models.UniqueConstraint(
                fields=['merchant_trade_no'],
                condition=models.Q(merchant_trade_no__isnull=False),
                name='unique_binance_merchant_trade_no'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'received_at']),
            models.Index(fields=['status', 'provider']),
            models.Index(fields=['payment_method', 'status']),
            models.Index(fields=['transaction_id']),
            models.Index(fields=['merchant_trade_no']),
            models.Index(fields=['prepay_id']),
        ]

    @property
    def subscription_plan(self):
        return self.plan

    @property
    def subscription_created(self):
        return self.subscription

    @property
    def is_approved_or_verified(self):
        return self.status in (self.STATUS_APPROVED, self.STATUS_VERIFIED)

    def __str__(self):
        method = self.payment_method or self.provider.upper()
        return f"{method} {self.transaction_id} - {self.currency} {self.amount} ({self.status})"


class BinanceManualPayment(Payment):
    """
    Dedicated Proxy model for 'Binance Manual Payments' in Django Admin (Section 7).
    """
    class Meta:
        proxy = True
        verbose_name = "Binance Manual Payment"
        verbose_name_plural = "Binance Manual Payments"


class TelebirrPayment(Payment):
    """
    Dedicated Proxy model for 'Telebirr Payments' in Django Admin.
    Allows administrators to inspect customer transaction number submissions
    and approve or reject transactions with atomic subscription activation.
    """
    class Meta:
        proxy = True
        verbose_name = "Telebirr Payment"
        verbose_name_plural = "Telebirr Payments"

