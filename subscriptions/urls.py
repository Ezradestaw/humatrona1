from django.urls import path
from . import views

app_name = 'subscriptions'

urlpatterns = [
    path('', views.plans_view, name='plans'),
    path('manage/', views.my_subscription_view, name='my_subscription'),
    path('cancel/<int:subscription_id>/', views.cancel_subscription_view, name='cancel_subscription'),
]
