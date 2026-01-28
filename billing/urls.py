from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    path('match-counts/', views.match_counts, name='match_counts'),
    path('tig/', views.tig, name='tig'),
    path('tig-admin/', views.tig_admin, name='tig_admin'),
    path('tig-vb/', views.tig_vb, name='tig_vb'),
    path('travel-costs/', views.travel_costs, name='travel_costs'),
    path('travel-costs-admin/', views.travel_costs_admin, name='travel_costs_admin'),
    path('efo/', views.efo, name='efo'),
    path('ekho/', views.ekho, name='ekho'),
    path('referee-data/', views.referee_data, name='referee_data'),
    # API endpoints
    path('api/tig-update/', views.api_tig_update, name='api_tig_update'),
    path('api/travel-cost/upload/', views.api_travel_cost_upload, name='api_travel_cost_upload'),
    path('api/travel-cost/<int:travel_cost_id>/approve/', views.api_travel_cost_approve, name='api_travel_cost_approve'),
    path('api/travel-cost/<int:travel_cost_id>/reject/', views.api_travel_cost_reject, name='api_travel_cost_reject'),
    path('api/travel-cost/<int:travel_cost_id>/return/', views.api_travel_cost_return, name='api_travel_cost_return'),
    path('api/travel-cost/<int:travel_cost_id>/preview/', views.api_travel_cost_preview, name='api_travel_cost_preview'),
    path('api/travel-cost/<int:travel_cost_id>/delete/', views.api_travel_cost_delete, name='api_travel_cost_delete'),
    path('api/travel-cost/<int:travel_cost_id>/reupload/', views.api_travel_cost_reupload, name='api_travel_cost_reupload'),
    path('api/travel-cost/<int:travel_cost_id>/decline/', views.api_travel_cost_decline, name='api_travel_cost_decline'),
    path('api/travel-cost/<int:travel_cost_id>/edit/', views.api_travel_cost_edit, name='api_travel_cost_edit'),
    path('api/declaration/<int:declaration_id>/declare/', views.api_declaration_declare, name='api_declaration_declare'),
    path('api/declaration/<int:declaration_id>/undeclare/', views.api_declaration_undeclare, name='api_declaration_undeclare'),
    path('api/declaration/<int:declaration_id>/delete/', views.api_declaration_delete, name='api_declaration_delete'),
    path('api/declaration/<int:declaration_id>/hide/', views.api_declaration_hide, name='api_declaration_hide'),
    path('api/declaration/<int:declaration_id>/unhide/', views.api_declaration_unhide, name='api_declaration_unhide'),
]
