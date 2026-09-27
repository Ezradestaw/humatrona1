from django import forms


class TelebirrVerificationForm(forms.Form):
    raw_message = forms.CharField(
        label="Telebirr Confirmation SMS / Message",
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 4,
            'placeholder': 'Paste the confirmation message received from Telebirr (127) here...\nExample: "Dear customer, you have transferred ETB 6,750.00 to Humatron (0911000000). Your transaction number is CC74KL9012."'
        }),
        help_text="Paste the exact SMS text received from Telebirr upon completing payment."
    )
