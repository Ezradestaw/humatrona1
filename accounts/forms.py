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


class StudentVerificationForm(forms.ModelForm):
    """
    Form for student verification requests.
    Validates educational domain, expiration date, and uploaded student ID document.
    """
    class Meta:
        from accounts.models import StudentVerification
        model = StudentVerification
        fields = [
            'educational_email',
            'educational_institution',
            'student_id_expiration_date',
            'student_id_file',
        ]
        widgets = {
            'educational_email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'student@university.edu or student@aau.edu.et'
            }),
            'educational_institution': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'University / College Name'
            }),
            'student_id_expiration_date': forms.DateInput(attrs={
                'class': 'form-input',
                'type': 'date'
            }),
            'student_id_file': forms.FileInput(attrs={
                'class': 'form-input',
                'accept': '.jpg,.jpeg,.png,.pdf'
            }),
        }

    def clean_educational_email(self):
        email = self.cleaned_data.get('educational_email', '').strip().lower()
        if not email:
            raise ValidationError('Educational email address is required.')
        
        from accounts.models import ApprovedEducationalDomain
        if not ApprovedEducationalDomain.is_domain_approved(email):
            raise ValidationError(
                'This educational email domain is not currently in the approved educational list. '
                'Please use an authorized university/college email (.edu, .edu.et, etc.) or contact support.'
            )
        return email

    def clean_student_id_expiration_date(self):
        exp_date = self.cleaned_data.get('student_id_expiration_date')
        if not exp_date:
            raise ValidationError('Student ID expiration date is required.')
        
        from django.utils import timezone
        if exp_date < timezone.now().date():
            raise ValidationError(
                'The student ID expiration date must be today or in the future. '
                'Expired student IDs cannot be accepted for a student discount.'
            )
        return exp_date

    def clean_student_id_file(self):
        uploaded_file = self.cleaned_data.get('student_id_file')
        if not uploaded_file:
            raise ValidationError('Student ID document is required.')

        # Max 10MB
        max_size = 10 * 1024 * 1024
        if uploaded_file.size > max_size:
            raise ValidationError('Student ID document must not exceed 10 MB.')

        # Extension check
        import os
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.pdf']
        if ext not in allowed_extensions:
            raise ValidationError('Only JPG, JPEG, PNG, or PDF files are accepted for student verification.')

        # Mime type check if available
        content_type = getattr(uploaded_file, 'content_type', '')
        allowed_types = ['image/jpeg', 'image/png', 'application/pdf', 'application/x-pdf', 'image/pjpeg']
        if content_type and content_type not in allowed_types:
            raise ValidationError('Invalid file type. Please upload a valid JPG, PNG, or PDF file.')

        return uploaded_file

