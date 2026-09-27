import os
import uuid
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from rest_framework import status, views, permissions
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .serializers import (
    UserSerializer,
    SubscriptionPlanSerializer,
    SubscriptionSerializer,
    PDFProcessingJobSerializer,
    PaymentSerializer,
)
from subscriptions.models import SubscriptionPlan
from subscriptions.services import SubscriptionService
from pdf_processor.models import PDFProcessingJob
from pdf_processor.validators import validate_pdf_file, sanitize_filename
from pdf_processor.tasks import process_pdf_job_task
from payments.models import Payment
from notifications.services import EmailService
from accounts.tokens import email_verification_token

User = get_user_model()


class AuthRegisterAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password')
        first_name = request.data.get('first_name', '')
        last_name = request.data.get('last_name', '')
        country = request.data.get('country', 'Ethiopia')
        job_title = request.data.get('job_title', 'Developer')
        sex = request.data.get('sex', 'prefer_not_to_say')

        if not email or not password:
            return Response({'error': 'Email and password are required.'}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email__iexact=email).exists():
            return Response({'error': 'An account with this email already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            country=country,
            job_title=job_title,
            sex=sex,
            is_active=False,
            is_email_verified=False
        )

        EmailService.send_verification_email(user, request)
        return Response({
            'message': 'Account created successfully. Please check your email to verify your account.'
        }, status=status.HTTP_201_CREATED)


class AuthLoginAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password')

        user = authenticate(request, username=email, password=password)
        if not user:
            # Check unverified
            if User.objects.filter(email__iexact=email, is_email_verified=False).exists():
                return Response({'error': 'Please verify your email address before logging in.'}, status=status.HTTP_403_FORBIDDEN)
            return Response({'error': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_email_verified:
            return Response({'error': 'Please verify your email address.'}, status=status.HTTP_403_FORBIDDEN)

        login(request, user)
        return Response({'message': 'Logged in successfully.', 'user': UserSerializer(user).data})


class AuthLogoutAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({'message': 'Logged out successfully.'})


class ProfileAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SubscriptionPlansAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        plans = SubscriptionPlan.objects.filter(active=True).order_by('sort_order', 'price')
        serializer = SubscriptionPlanSerializer(plans, many=True)
        return Response(serializer.data)


class SubscriptionCurrentAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sub = SubscriptionService.get_active_subscription(request.user)
        trial_available = SubscriptionService.is_trial_available(request.user)
        if sub:
            return Response({
                'has_active_subscription': True,
                'trial_available': False,
                'subscription': SubscriptionSerializer(sub).data
            })
        return Response({
            'has_active_subscription': False,
            'trial_available': trial_available,
            'subscription': None
        })


class PDFProcessAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        uploaded_file = request.FILES.get('pdf_file')
        if not uploaded_file:
            return Response({'error': 'Missing pdf_file in upload.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        allowed, reason, is_trial, max_size_mb, max_pages = SubscriptionService.can_process_pdf(
            user,
            file_size_bytes=uploaded_file.size,
            page_count=1
        )
        if not allowed:
            return Response({'error': reason}, status=status.HTTP_403_FORBIDDEN)

        try:
            metadata = validate_pdf_file(uploaded_file, max_size_mb=max_size_mb, max_pages=max_pages)
        except ValidationError as exc:
            return Response({'error': exc.message if hasattr(exc, 'message') else str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Full check
        allowed_full, reason_full, _, _, _ = SubscriptionService.can_process_pdf(
            user,
            file_size_bytes=uploaded_file.size,
            page_count=metadata['page_count']
        )
        if not allowed_full:
            return Response({'error': reason_full}, status=status.HTTP_403_FORBIDDEN)

        clean_filename = sanitize_filename(uploaded_file.name)
        random_filename = f"{uuid.uuid4().hex}.pdf"
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        stored_path = os.path.join(upload_dir, random_filename)

        with open(stored_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        job = PDFProcessingJob.objects.create(
            user=user,
            original_filename=clean_filename,
            stored_filename=random_filename,
            page_count=metadata['page_count'],
            input_size=metadata['file_size'],
            status=PDFProcessingJob.STATUS_QUEUED
        )

        process_pdf_job_task.delay(str(job.id))
        return Response(PDFProcessingJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class PDFJobsAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        jobs = PDFProcessingJob.objects.filter(user=request.user).order_by('-created_at')
        serializer = PDFProcessingJobSerializer(jobs, many=True)
        return Response(serializer.data)


class PDFJobDetailAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, job_id):
        # Section 50: Object-level authorization
        try:
            job = PDFProcessingJob.objects.get(id=job_id, user=request.user)
        except PDFProcessingJob.DoesNotExist:
            return Response({'error': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(PDFProcessingJobSerializer(job).data)


class PDFJobDownloadAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, job_id):
        # Section 19 & 50: Strict ownership check
        try:
            job = PDFProcessingJob.objects.get(id=job_id, user=request.user)
        except PDFProcessingJob.DoesNotExist:
            return Response({'error': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not job.is_downloadable:
            return Response({'error': 'Document is not available for download.'}, status=status.HTTP_400_BAD_REQUEST)

        file_path = os.path.join(settings.MEDIA_ROOT, 'processed', job.processed_filename)
        if not os.path.exists(file_path):
            return Response({'error': 'File not found on server.'}, status=status.HTTP_404_NOT_FOUND)

        job.download_count += 1
        job.save(update_fields=['download_count'])

        base_name = os.path.splitext(job.original_filename)[0]
        download_filename = f"{base_name}_humatron_flattened.pdf"

        response = FileResponse(open(file_path, 'rb'), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{download_filename}"'
        return response


class PaymentsAPIView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        payments = Payment.objects.filter(user=request.user).order_by('-received_at')
        serializer = PaymentSerializer(payments, many=True)
        return Response(serializer.data)
