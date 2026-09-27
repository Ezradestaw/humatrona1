from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    # Auth
    path('auth/register/', views.AuthRegisterAPIView.as_view(), name='auth_register'),
    path('auth/login/', views.AuthLoginAPIView.as_view(), name='auth_login'),
    path('auth/logout/', views.AuthLogoutAPIView.as_view(), name='auth_logout'),
    path('profile/', views.ProfileAPIView.as_view(), name='profile'),
    
    # Subscriptions
    path('subscription/', views.SubscriptionCurrentAPIView.as_view(), name='subscription_current'),
    path('subscription/plans/', views.SubscriptionPlansAPIView.as_view(), name='subscription_plans'),
    
    # PDF Processing
    path('pdf/process/', views.PDFProcessAPIView.as_view(), name='pdf_process'),
    path('pdf/jobs/', views.PDFJobsAPIView.as_view(), name='pdf_jobs'),
    path('pdf/jobs/<uuid:job_id>/', views.PDFJobDetailAPIView.as_view(), name='pdf_job_detail'),
    path('pdf/jobs/<uuid:job_id>/download/', views.PDFJobDownloadAPIView.as_view(), name='pdf_job_download'),
    
    # Payments
    path('payments/', views.PaymentsAPIView.as_view(), name='payments'),
]
