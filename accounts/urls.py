from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('database/', views.database_redirect, name='database'),
    path('users/', views.users_list, name='users'),
    path('settings/', views.admin_settings, name='admin_settings'),

    # Notification API endpoints
    path('api/notifications/', views.api_get_notifications, name='api_notifications'),
    path('api/notifications/<int:notification_id>/read/', views.api_mark_notification_read, name='api_notification_read'),
    path('api/notifications/mark-all-read/', views.api_mark_all_notifications_read, name='api_notifications_mark_all_read'),

    # Admin settings API endpoints
    path('api/settings/delete-all-matches/', views.api_delete_all_matches, name='api_delete_all_matches'),
    path('api/settings/delete-all-notifications/', views.api_delete_all_notifications, name='api_delete_all_notifications'),
    path('api/settings/save/', views.api_save_site_settings, name='api_save_site_settings'),

    # Coordinator API endpoints
    path('api/coordinators/add/', views.api_add_coordinator, name='api_add_coordinator'),
    path('api/coordinators/<int:coordinator_id>/delete/', views.api_delete_coordinator, name='api_delete_coordinator'),
    path('api/coordinators/<int:coordinator_id>/toggle/', views.api_toggle_coordinator, name='api_toggle_coordinator'),

    # Profile API endpoints
    path('api/profile/update/', views.api_profile_update, name='api_profile_update'),
    path('api/profile/picture/upload/', views.api_profile_picture_upload, name='api_profile_picture_upload'),
    path('api/profile/picture/delete/', views.api_profile_picture_delete, name='api_profile_picture_delete'),
]
