from django.urls import path
from . import views

app_name = 'documents'

urlpatterns = [
    path('', views.document_list, name='list'),
    path('upload/', views.document_upload, name='upload'),
    path('<int:document_id>/new-version/', views.document_new_version, name='new_version'),
    path('api/<int:document_id>/delete/', views.api_document_delete, name='api_document_delete'),
]
