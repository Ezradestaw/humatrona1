import hashlib
from django import forms
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class RegistrationForm(forms.ModelForm):
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'}),
        help_text='At least 10 characters with numbers and letters.'
    )
    password_confirm = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'new-password'})
    )

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'phone_number',
            'country',
            'job_title',
            'job_title_other',
            'sex',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '+251 9... or +1 ...'}),
            'country': forms.Select(attrs={'class': 'form-select'}),
            'job_title': forms.Select(attrs={'class': 'form-select', 'id': 'id_job_title'}),
            'job_title_other': forms.TextInput(attrs={'class': 'form-input', 'id': 'id_job_title_other', 'placeholder': 'Specify job title'}),
            'sex': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email address already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        job_title = cleaned_data.get('job_title')
        job_title_other = cleaned_data.get('job_title_other')

        if password and password_confirm:
            if password != password_confirm:
                self.add_error('password_confirm', 'Passwords do not match.')
            else:
                # Use Django's configured password validators
                try:
                    validate_password(password)
                except ValidationError as e:
                    self.add_error('password', e)

        if job_title == 'Other' and not job_title_other:
            self.add_error('job_title_other', 'Please specify your job title.')

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']
        user.set_password(self.cleaned_data['password'])
        # New accounts start inactive/unverified per specification
        user.is_active = False
        user.is_email_verified = False
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    email = forms.EmailField(
        label='Email Address',
        widget=forms.EmailInput(attrs={'class': 'form-input', 'autocomplete': 'email', 'placeholder': 'name@example.com'})
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'autocomplete': 'current-password'})
    )
    remember_me = forms.BooleanField(
        label='Remember me on this device',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'})
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email', '').strip().lower()
        password = cleaned_data.get('password')

        if email and password:
            user = authenticate(self.request, username=email, password=password)
            if user is None:
                # Check if account exists but unverified
                try:
                    existing_user = User.objects.get(email__iexact=email)
                    if not existing_user.is_email_verified:
                        raise ValidationError('Please verify your email address before logging in. Check your inbox for the activation link.')
                    if not existing_user.is_active:
                        raise ValidationError('This account has been disabled. Please contact support.')
                except User.DoesNotExist:
                    pass
                raise ValidationError('Invalid email address or password.')
            
            if not user.is_email_verified:
                raise ValidationError('Please verify your email address before logging in.')
            if not user.is_active:
                raise ValidationError('This account is disabled.')

            self.user_cache = user

        return cleaned_data

    def get_user(self):
        return self.user_cache


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'phone_number',
            'country',
            'job_title',
            'job_title_other',
            'sex',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input'}),
            'country': forms.Select(attrs={'class': 'form-select'}),
            'job_title': forms.Select(attrs={'class': 'form-select'}),
            'job_title_other': forms.TextInput(attrs={'class': 'form-input'}),
            'sex': forms.Select(attrs={'class': 'form-select'}),
        }
