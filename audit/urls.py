from django.urls import path
from . import views

app_name = 'audit'

urlpatterns = [
    path('', views.log_list, name='log_list'),
    path('api/<int:log_id>/', views.log_detail_api, name='log_detail_api'),
]
