from django import forms


class TelebirrVerificationForm(forms.Form):
    """
    Simplified Telebirr payment submission form.
    Only the transaction/reference number is required.
    """
    transaction_id = forms.CharField(
        max_length=128,
        required=True,
        label="Telebirr Transaction Number",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. CC74KL9012 or 10-digit transaction reference',
            'autocomplete': 'off',
            'autofocus': True,
        }),
        help_text="Enter the transaction number received from Telebirr upon completing payment."
    )

    def clean_transaction_id(self):
        tx_id = self.cleaned_data.get('transaction_id', '').strip()
        if not tx_id:
            raise forms.ValidationError("Please enter your Telebirr transaction number.")

        # Uniqueness check
        from .models import Payment
        duplicate = Payment.objects.filter(
            provider=Payment.PROVIDER_TELEBIRR,
            transaction_id=tx_id
        ).exclude(status__in=[Payment.STATUS_REJECTED, Payment.STATUS_CANCELLED]).exists()

        if duplicate:
            raise forms.ValidationError(
                "This Telebirr transaction number has already been submitted or processed."
            )

        return tx_id


class BinanceManualSubmissionForm(forms.Form):
    """
    Simplified Binance manual payment form.
    Only the transaction/order ID is required — no screenshot upload.
    """
    transaction_id = forms.CharField(
        max_length=128,
        required=True,
        label="Binance Transaction Number / Order ID",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. 294810293847 or internal transfer order ID',
            'autocomplete': 'off',
            'autofocus': True,
        }),
        help_text="Only your Binance transaction number is necessary. A screenshot is not required."
    )

    def __init__(self, *args, expected_amount=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_amount = expected_amount
        self.user = user

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
            raise forms.ValidationError(
                "This Binance transaction ID has already been submitted or processed."
            )

        return tx_id


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
