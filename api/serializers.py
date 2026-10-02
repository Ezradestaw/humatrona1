from rest_framework import serializers
from django.contrib.auth import get_user_model
from subscriptions.models import SubscriptionPlan, Subscription
from pdf_processor.models import PDFProcessingJob
from payments.models import Payment

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name',
            'phone_number', 'country', 'job_title', 'job_title_other',
            'sex', 'is_email_verified', 'trial_used', 'date_joined'
        ]
        read_only_fields = ['id', 'email', 'is_email_verified', 'trial_used', 'date_joined']


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    pdf_limit = serializers.IntegerField(read_only=True)
    max_file_size_mb = serializers.IntegerField(read_only=True)
    max_pages_per_pdf = serializers.IntegerField(read_only=True)

    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'code', 'slug', 'description', 'price',
            'currency', 'billing_period', 'usage_limit', 'max_file_size',
            'processing_priority', 'features',
            'price_etb', 'duration_days',
            'pdf_limit', 'max_file_size_mb', 'max_pages_per_pdf'
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    remaining_quota = serializers.IntegerField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'id', 'plan', 'status', 'start_date', 'end_date',
            'pdf_limit', 'used_count', 'remaining_quota', 'payment_method'
        ]


class PDFProcessingJobSerializer(serializers.ModelSerializer):
    is_downloadable = serializers.BooleanField(read_only=True)
    input_size_formatted = serializers.CharField(read_only=True)
    output_size_formatted = serializers.CharField(read_only=True)

    class Meta:
        model = PDFProcessingJob
        fields = [
            'id', 'original_filename', 'status', 'page_count',
            'input_size', 'output_size', 'input_size_formatted',
            'output_size_formatted', 'is_downloadable', 'download_count',
            'created_at', 'completed_at', 'error_message'
        ]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            'id', 'provider', 'transaction_id', 'amount',
            'currency', 'status', 'received_at', 'verified_at'
        ]
        read_only_fields = fields
