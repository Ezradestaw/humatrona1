from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('checkout/<slug:plan_code>/', views.checkout_view, name='checkout'),
    path('verify-telebirr/<slug:plan_code>/', views.verify_telebirr_view, name='verify_telebirr'),
    path('history/', views.payment_history_view, name='history'),
    path('webhook/telebirr/', views.telebirr_webhook_view, name='telebirr_webhook'),
    
    # Binance Manual Payment Endpoints
    path('binance/manual/<slug:plan_code>/', views.binance_manual_checkout_view, name='binance_manual_checkout'),
    path('binance/status/<int:payment_id>/', views.binance_manual_status_view, name='binance_manual_status'),
    
    # Binance Pay Endpoints (Official v3/v2 integration)
    path('binance/initiate/<slug:plan_code>/', views.initiate_binance_pay_view, name='initiate_binance'),
    path('binance/return/', views.binance_return_view, name='binance_return'),
    path('binance/cancel/', views.binance_cancel_view, name='binance_cancel'),
    path('binance/status/<str:merchant_trade_no>/', views.binance_order_status_api, name='binance_status'),
    path('binance/simulate-checkout/<str:merchant_trade_no>/', views.binance_simulate_checkout_view, name='binance_simulate_checkout'),
    path('webhook/binance/', views.binance_webhook_view, name='binance_webhook'),
]
