"""
Main URL configuration for Humatron (humatron.me).
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from . import views

urlpatterns = [
    # Core public pages
    path('', views.home_view, name='home'),
    path('about/', views.about_view, name='about'),
    path('robots.txt', views.robots_txt_view, name='robots_txt'),
    path('sitemap.xml', views.sitemap_xml_view, name='sitemap_xml'),

    # Administrative Panel (Section 38-44)
    path('admin/', admin.site.urls),

    # App routes
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('subscriptions/', include('subscriptions.urls', namespace='subscriptions')),
    path('payments/', include('payments.urls', namespace='payments')),
    path('pdf/', include('pdf_processor.urls', namespace='pdf_processor')),
    path('usage/', include('usage.urls', namespace='usage')),
    path('contact/', include('contact.urls', namespace='contact')),

    # REST APIs (Section 49)
    path('api/', include('api.urls', namespace='api')),

    # Convenient shortcuts matching specification navigation
    path('dashboard/', RedirectView.as_view(pattern_name='accounts:dashboard', permanent=False), name='dashboard_shortcut'),
]

# Error handlers
handler400 = 'config.views.error_400'
handler403 = 'config.views.error_403'
handler404 = 'config.views.error_404'
handler500 = 'config.views.error_500'

# In development, serve static
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
