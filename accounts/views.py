import hashlib
import mimetypes
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordResetView as BasePasswordResetView,
    PasswordResetDoneView as BasePasswordResetDoneView,
    PasswordResetConfirmView as BasePasswordResetConfirmView,
    PasswordResetCompleteView as BasePasswordResetCompleteView,
)
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponseForbidden, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode
from django.utils.encoding import force_str

from .forms import RegistrationForm, LoginForm, ProfileForm, StudentVerificationForm
from .models import DeviceTrialSignal, StudentVerification, ApprovedEducationalDomain
from .tokens import email_verification_token, educational_email_token
from notifications.services import EmailService
from subscriptions.services import SubscriptionService
from pdf_processor.models import PDFProcessingJob

User = get_user_model()


def get_device_fingerprint(request):
    """
    Computes a privacy-conscious device identifier hash from client signals
    (User-Agent, Accept-Language, and client subnet).
    Used as an anti-abuse signal, NOT as an invasive tracking mechanism.
    """
    ua = request.META.get('HTTP_USER_AGENT', '')
    lang = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    raw_sig = f"{ua}|{lang}|{ip}"
    return hashlib.sha256(raw_sig.encode('utf-8')).hexdigest(), ip


def register_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            
            # Anti-abuse device tracking signal
            fingerprint, ip = get_device_fingerprint(request)
            user.device_fingerprint = fingerprint
            user.save(update_fields=['device_fingerprint'])
            
            DeviceTrialSignal.objects.create(
                fingerprint_hash=fingerprint,
                ip_address=ip,
                user=user,
                trials_count=0
            )

            # Send verification email
            EmailService.send_verification_email(user, request)
            
            return render(request, 'accounts/register_pending.html', {'email': user.email})
    else:
        form = RegistrationForm()

    return render(request, 'accounts/register.html', {'form': form})


def verify_email_view(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user and email_verification_token.check_token(user, token):
        user.is_email_verified = True
        user.is_active = True
        user.save(update_fields=['is_email_verified', 'is_active'])
        messages.success(request, 'Your email has been verified successfully. You may now log in to Humatron.')
        return redirect('accounts:login')
    else:
        return render(request, 'accounts/verify_email_failed.html')


def resend_verification_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        if email:
            try:
                user = User.objects.get(email__iexact=email)
                if not user.is_email_verified:
                    EmailService.send_verification_email(user, request)
            except User.DoesNotExist:
                # Intentionally generic to prevent account enumeration
                pass
        messages.info(request, 'If an unverified account exists for this email, a new verification link has been sent.')
        return redirect('accounts:login')
    return render(request, 'accounts/resend_verification.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = LoginForm(request.POST, request=request)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            # Session expiry behavior based on 'remember_me'
            if form.cleaned_data.get('remember_me'):
                request.session.set_expiry(60 * 60 * 24 * 30)  # 30 days
            else:
                request.session.set_expiry(0)  # Browser close

            next_url = request.GET.get('next') or reverse('accounts:dashboard')
            return redirect(next_url)
    else:
        form = LoginForm()

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been signed out.')
    return redirect('accounts:login')


@login_required
def dashboard_view(request):
    user = request.user
    subscription = SubscriptionService.get_active_subscription(user)
    trial_available = SubscriptionService.is_trial_available(user)
    
    # Calculate usage metrics
    if subscription:
        used_count = subscription.used_count
        limit = subscription.pdf_limit
        remaining = max(0, limit - used_count)
        expires_at = subscription.end_date
        plan_name = subscription.plan.name
        status = subscription.status
    elif trial_available:
        used_count = 0
        limit = 1
        remaining = 1
        expires_at = None
        plan_name = "Free Trial"
        status = "Active Trial (1 Document)"
    else:
        used_count = 1 if user.trial_used else 0
        limit = 0
        remaining = 0
        expires_at = None
        plan_name = "No Active Subscription"
        status = "Expired / Limit Reached"

    # Recent processing jobs
    recent_jobs = PDFProcessingJob.objects.filter(user=user).order_by('-created_at')[:10]

    context = {
        'subscription': subscription,
        'trial_available': trial_available,
        'used_count': used_count,
        'limit': limit,
        'remaining': remaining,
        'expires_at': expires_at,
        'plan_name': plan_name,
        'status': status,
        'recent_jobs': recent_jobs,
    }
    return render(request, 'accounts/dashboard.html', context)


@login_required
def profile_view(request):
    user = request.user
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile information has been updated.')
            return redirect('accounts:profile')
    else:
        form = ProfileForm(instance=user)

    return render(request, 'accounts/profile.html', {'form': form})


# Password Reset Views with Humatron Templates
class CustomPasswordResetView(BasePasswordResetView):
    template_name = 'accounts/password_reset.html'
    email_template_name = 'email/password_reset/message.txt'
    html_email_template_name = 'email/password_reset/message.html'
    subject_template_name = 'email/password_reset/subject.txt'
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'Humatron Support <support@humatron.me>')
    success_url = reverse_lazy('accounts:password_reset_done')


class CustomPasswordResetDoneView(BasePasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'


class CustomPasswordResetConfirmView(BasePasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('accounts:password_reset_complete')


class CustomPasswordResetCompleteView(BasePasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'


@login_required
def student_verification_view(request):
    """
    Handles student discount verification requests:
    - Educational email
    - Educational institution
    - Student ID document (JPG/PNG/PDF max 10MB)
    - Expiration date
    """
    user = request.user
    verification, _ = StudentVerification.objects.get_or_create(user=user)

    if request.method == 'POST':
        form = StudentVerificationForm(request.POST, request.FILES, instance=verification)
        if form.is_valid():
            sv = form.save(commit=False)
            sv.user = user
            sv.educational_domain = sv.educational_email.split('@')[-1].lower()
            
            # Check if email changed or is not verified
            original_email = StudentVerification.objects.filter(pk=verification.pk).values_list('educational_email', flat=True).first() if verification.pk else None
            email_changed = original_email != sv.educational_email

            if email_changed or not sv.educational_email_verified:
                sv.educational_email_verified = False
                sv.status = StudentVerification.STATUS_PENDING
                sv.submitted_at = timezone.now()
                sv.rejection_reason = ''
                sv.save()
                
                # Send verification email
                EmailService.send_educational_verification_email(user, sv.educational_email, request=request)
                messages.success(
                    request,
                    f"Student verification submitted! A verification link has been sent to your educational email ({sv.educational_email}). "
                    "Please check your inbox and click the verification link to proceed."
                )
            else:
                # Email already verified, updating documents
                sv.status = StudentVerification.STATUS_UNDER_REVIEW
                sv.submitted_at = timezone.now()
                sv.rejection_reason = ''
                sv.save()
                messages.success(
                    request,
                    "Student ID document updated and submitted for administrator review."
                )
            return redirect('accounts:student_verification')
    else:
        form = StudentVerificationForm(instance=verification)

    context = {
        'form': form,
        'verification': verification,
        'is_verified': user.is_verified_student,
    }
    return render(request, 'accounts/student_verification.html', context)


@login_required
def resend_educational_email_view(request):
    """Resends the educational email verification link."""
    user = request.user
    verification = getattr(user, 'student_verification', None)
    if not verification or not verification.educational_email:
        messages.error(request, "No educational email found to verify.")
        return redirect('accounts:student_verification')

    if verification.educational_email_verified:
        messages.info(request, "Your educational email is already verified.")
        return redirect('accounts:student_verification')

    EmailService.send_educational_verification_email(user, verification.educational_email, request=request)
    messages.success(request, f"Verification link resent to {verification.educational_email}.")
    return redirect('accounts:student_verification')


@login_required
def verify_educational_email_view(request, uidb64, token):
    """
    Verifies educational email using cryptographic single-use token.
    """
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user and educational_email_token.check_token(user, token):
        verification = getattr(user, 'student_verification', None)
        if verification:
            verification.educational_email_verified = True
            if verification.student_id_file and verification.student_id_expiration_date:
                verification.status = StudentVerification.STATUS_UNDER_REVIEW
            else:
                verification.status = StudentVerification.STATUS_EMAIL_VERIFIED
            verification.save()
            messages.success(
                request,
                "Your educational email has been successfully verified! "
                "Your application is now under review by our administration team."
            )
        else:
            messages.success(request, "Educational email verified.")
        return redirect('accounts:student_verification')
    else:
        messages.error(request, "Invalid or expired educational verification link.")
        return redirect('accounts:student_verification')


@login_required
def student_id_document_view(request, verification_id):
    """
    Secure access to student ID document. Only the owner or staff can view it.
    Prevents public direct URL exposure.
    """
    verification = get_object_or_404(StudentVerification, pk=verification_id)
    if request.user != verification.user and not request.user.is_staff:
        return HttpResponseForbidden("You do not have permission to view this document.")

    if not verification.student_id_file or not verification.student_id_file.storage.exists(verification.student_id_file.name):
        raise Http404("Document file not found.")

    content_type, _ = mimetypes.guess_type(verification.student_id_file.name)
    content_type = content_type or 'application/octet-stream'
    return FileResponse(verification.student_id_file.open('rb'), content_type=content_type)

