from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.register_view, name='register'),
    path('verify-email/<str:uidb64>/<str:token>/', views.verify_email_view, name='verify_email'),
    path('resend-verification/', views.resend_verification_view, name='resend_verification'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    
    # Student Verification
    path('student-verification/', views.student_verification_view, name='student_verification'),
    path('student-verification/resend/', views.resend_educational_email_view, name='resend_educational_email'),
    path('student-verification/verify-email/<str:uidb64>/<str:token>/', views.verify_educational_email_view, name='verify_educational_email'),
    path('student-verification/document/<int:verification_id>/', views.student_id_document_view, name='student_id_document'),

    # Password Reset
    path('password-reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
