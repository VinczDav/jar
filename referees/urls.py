from django.urls import path
from . import views

app_name = 'referees'

urlpatterns = [
    path('feedbacks/', views.feedbacks, name='feedbacks'),
    path('unavailability/', views.unavailability, name='unavailability'),
    path('unavailability/add/', views.add_unavailability, name='add_unavailability'),
    path('unavailability/<int:unavailability_id>/delete/', views.delete_unavailability, name='delete_unavailability'),
    path('colleagues/', views.colleagues, name='colleagues'),
    path('profiles/', views.profiles, name='profiles'),
    path('reports/', views.reports, name='reports'),
    path('reports/create/', views.create_report, name='create_report'),
    path('reports/<int:report_id>/', views.view_report, name='view_report'),
]
