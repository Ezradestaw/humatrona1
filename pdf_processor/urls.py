from django.urls import path
from . import views

app_name = 'pdf_processor'

urlpatterns = [
    path('upload/', views.upload_view, name='upload'),
    path('history/', views.job_list_view, name='history'),
    path('jobs/<uuid:job_id>/', views.job_detail_view, name='job_detail'),
    path('jobs/<uuid:job_id>/download/', views.download_view, name='download'),
    path('jobs/<uuid:job_id>/delete/', views.job_delete_view, name='delete'),
]
