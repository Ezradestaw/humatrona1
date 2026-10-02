from django import forms


class TelebirrVerificationForm(forms.Form):
    transaction_id = forms.CharField(
        max_length=128,
        required=False,
        label="Telebirr Transaction Number",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. CC74KL9012 or 10-digit transaction reference',
            'autocomplete': 'off',
        }),
        help_text="Enter the transaction number received from Telebirr upon completing payment."
    )
    raw_message = forms.CharField(
        required=False,
        label="Or paste Telebirr Confirmation SMS Text",
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 3,
            'placeholder': 'Paste confirmation message received from Telebirr here (optional)...\nExample: "Dear customer, you have transferred ETB 200.00 to Humatron (0911000000). Your transaction number is CC74KL9012."',
        }),
        help_text="You can enter either your transaction number above or paste the full SMS."
    )

    def clean(self):
        cleaned_data = super().clean()
        tx_id = cleaned_data.get('transaction_id', '').strip()
        raw_msg = cleaned_data.get('raw_message', '').strip()

        if not tx_id and not raw_msg:
            raise forms.ValidationError("Please enter your Telebirr transaction number upon completion.")

        if not tx_id and raw_msg:
            from .telebirr_parser import TelebirrMessageParser
            parsed = TelebirrMessageParser.parse(raw_msg)
            if parsed['is_valid'] and parsed.get('transaction_id'):
                cleaned_data['transaction_id'] = parsed['transaction_id']
            else:
                cleaned_data['transaction_id'] = raw_msg[:128]

        return cleaned_data


class BinanceManualSubmissionForm(forms.Form):
    """
    User submission form for Binance Manual Payment workflow.
    In Binance, only transaction number is necessary (screenshot is not required).
    """
    ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.pdf'}
    ALLOWED_CONTENT_TYPES = {
        'image/png',
        'image/jpeg',
        'image/pjpeg',
        'image/webp',
        'application/pdf',
    }
    MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

    transaction_id = forms.CharField(
        max_length=128,
        required=True,
        label="Binance Transaction Number / TxID / Order ID",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. 294810293847 or internal transfer order ID',
            'autocomplete': 'off',
        }),
        help_text="Only your Binance transaction number is necessary."
    )
    sender_identifier = forms.CharField(
        max_length=128,
        required=False,
        label="Your Sender Binance UID / Pay ID (Optional)",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. 89217342 (optional)',
            'autocomplete': 'off',
        }),
        help_text="Optional sender Binance User ID (UID)."
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Amount Sent (USDT)",
        widget=forms.NumberInput(attrs={
            'class': 'form-input',
            'step': '0.01',
            'placeholder': '0.00',
        }),
        help_text="The amount sent in USDT (prefilled with plan price)."
    )
    sent_at = forms.DateTimeField(
        required=False,
        label="Date & Time of Transfer (Optional)",
        widget=forms.DateTimeInput(attrs={
            'class': 'form-input',
            'type': 'datetime-local',
        }),
        help_text="Approximate time of payment (optional)."
    )
    proof_file = forms.FileField(
        required=False,
        label="Payment Screenshot / Proof Document (Not Required)",
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-input',
            'accept': '.png,.jpg,.jpeg,.webp,.pdf',
        }),
        help_text="Screenshot is NOT required — only your transaction number is necessary."
    )
    note = forms.CharField(
        required=False,
        max_length=500,
        label="Additional Note (Optional)",
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 2,
            'placeholder': 'Optional remarks or payment details for the administrator...',
        })
    )

    def __init__(self, *args, expected_amount=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_amount = expected_amount
        self.user = user
        if expected_amount is not None:
            self.fields['amount'].initial = expected_amount

    def clean_transaction_id(self):
        tx_id = self.cleaned_data.get('transaction_id', '').strip()
        if not tx_id:
            raise forms.ValidationError("Binance Transaction ID is required.")
        
        # Uniqueness check: reject duplicate active submissions
        from .models import Payment
        duplicate = Payment.objects.filter(
            provider=Payment.PROVIDER_BINANCE,
            transaction_id=tx_id
        ).exclude(status__in=[Payment.STATUS_REJECTED, Payment.STATUS_CANCELLED]).exists()

        if duplicate:
            raise forms.ValidationError("This Binance transaction ID has already been submitted or processed.")

        return tx_id

    def clean_sender_identifier(self):
        sender = self.cleaned_data.get('sender_identifier', '').strip()
        if not sender and hasattr(self, 'user') and self.user and self.user.is_authenticated:
            sender = getattr(self.user, 'username', '') or getattr(self.user, 'email', '')
        return sender

    def clean_amount(self):
        from decimal import Decimal
        amount = self.cleaned_data.get('amount')
        if amount is None:
            if self.expected_amount is not None:
                return self.expected_amount
            return Decimal('0.00')

        if amount <= 0:
            raise forms.ValidationError("Please provide a valid positive payment amount.")

        if self.expected_amount is not None:
            if amount < self.expected_amount:
                raise forms.ValidationError(
                    f"The submitted amount ({amount} USDT) is less than the required plan amount ({self.expected_amount} USDT)."
                )
        return amount

    def clean_proof_file(self):
        file = self.cleaned_data.get('proof_file')
        if not file:
            return None

        # 1. Size verification (max 5 MB)
        if file.size > self.MAX_FILE_SIZE_BYTES:
            raise forms.ValidationError("Uploaded proof file exceeds maximum allowed size of 5 MB.")

        # 2. Extension verification
        import os
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise forms.ValidationError(
                f"File format '{ext}' is not permitted. Allowed formats: PNG, JPG, JPEG, WEBP, PDF."
            )

        # 3. MIME type inspection
        content_type = getattr(file, 'content_type', '')
        if content_type and content_type.lower() not in self.ALLOWED_CONTENT_TYPES:
            raise forms.ValidationError(f"Invalid file MIME type: {content_type}.")

        return file


class PaymentRejectionForm(forms.Form):
    """Admin rejection modal/form requiring a justification."""
    rejection_reason = forms.CharField(
        required=True,
        label="Reason for Rejection",
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 3,
            'placeholder': 'Explain why this payment was rejected (e.g. Transaction ID not found on Binance, underpaid amount, incorrect sender)...'
        }),
        help_text="This message will be emailed to the customer."
    )

