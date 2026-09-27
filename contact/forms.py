from django import forms
from .models import ContactMessage


class ContactForm(forms.ModelForm):
    # Spam honeypot field - must remain empty
    website = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'style': 'display:none !important;', 'tabindex': '-1', 'autocomplete': 'off'})
    )

    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Your full name'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'name@example.com'}),
            'subject': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Summary of your inquiry'}),
            'message': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 5, 'placeholder': 'Type your message here...'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        honeypot = cleaned_data.get('website')
        if honeypot:
            # Silently reject bot submission
            raise forms.ValidationError("Invalid submission detected.")
        return cleaned_data
