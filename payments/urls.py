from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('checkout/<slug:plan_code>/', views.checkout_view, name='checkout'),
    path('verify-telebirr/<slug:plan_code>/', views.verify_telebirr_view, name='verify_telebirr'),
    path('capture-paypal/<slug:plan_code>/', views.capture_paypal_view, name='capture_paypal'),
    path('history/', views.payment_history_view, name='history'),
    path('webhook/telebirr/', views.telebirr_webhook_view, name='telebirr_webhook'),
]
