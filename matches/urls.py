from django.urls import path
from . import views

app_name = 'matches'

urlpatterns = [
    path('', views.public_matches, name='public_matches'),
    path('my/', views.my_matches, name='my_matches'),
    path('applications/', views.match_applications, name='match_applications'),
    path('all/', views.all_matches, name='all_matches'),
    path('assignments/', views.assignments, name='assignments'),
    path('create/', views.create_match, name='create_match'),
    path('<int:match_id>/', views.match_detail, name='match_detail'),
    path('<int:match_id>/edit/', views.edit_match, name='edit_match'),
    path('assignment/<int:assignment_id>/respond/', views.respond_to_assignment, name='respond_to_assignment'),
    path('assignment/<int:assignment_id>/decline/', views.decline_accepted_assignment, name='decline_accepted_assignment'),
    path('api/competitions/', views.get_competitions, name='get_competitions'),

    # Admin: Clubs
    path('admin/clubs/', views.clubs_list, name='clubs_list'),
    path('admin/clubs/new/', views.club_edit, name='club_new'),
    path('admin/clubs/<int:club_id>/', views.club_edit, name='club_edit'),
    path('admin/clubs/<int:club_id>/toggle/', views.club_toggle_active, name='club_toggle_active'),
    path('admin/clubs/<int:club_id>/delete/', views.club_delete, name='club_delete'),
    path('api/club/<int:club_id>/archive/', views.api_archive_club, name='api_archive_club'),

    # Admin: Teams (within clubs)
    path('admin/clubs/<int:club_id>/teams/new/', views.team_edit, name='team_new'),
    path('admin/clubs/<int:club_id>/teams/<int:team_id>/', views.team_edit, name='team_edit'),
    path('admin/teams/<int:team_id>/toggle/', views.team_toggle_active, name='team_toggle_active'),
    path('admin/teams/<int:team_id>/delete/', views.team_delete, name='team_delete'),
    path('admin/teams/<int:team_id>/alternative/add/', views.team_add_alternative, name='team_add_alternative'),
    path('admin/teams/alternative/<int:alt_id>/delete/', views.team_delete_alternative, name='team_delete_alternative'),
    path('api/team/<int:team_id>/archive/', views.api_archive_team, name='api_archive_team'),

    # Legacy redirect: teams -> clubs
    path('admin/teams/', views.clubs_list, name='teams_list'),

    # Admin: Venues
    path('admin/venues/', views.venues_list, name='venues_list'),
    path('admin/venues/new/', views.venue_edit, name='venue_new'),
    path('admin/venues/<int:venue_id>/', views.venue_edit, name='venue_edit'),
    path('admin/venues/<int:venue_id>/toggle/', views.venue_toggle_active, name='venue_toggle_active'),
    path('api/venue/<int:venue_id>/archive/', views.api_archive_venue, name='api_archive_venue'),
    path('api/venue/<int:venue_id>/delete/', views.api_delete_venue, name='api_delete_venue'),

    # Admin: Competitions & Seasons
    path('admin/competitions/', views.competitions_list, name='competitions_list'),
    path('admin/season/add/', views.add_season, name='add_season'),
    path('admin/competition/add/', views.add_competition, name='add_competition'),
    path('admin/competition/<int:competition_id>/', views.edit_competition, name='edit_competition'),
    path('admin/competition/<int:competition_id>/color/', views.update_competition_color, name='update_competition_color'),
    path('admin/competition/<int:competition_id>/delete/', views.delete_competition, name='delete_competition'),
    path('admin/phase/add/', views.add_phase, name='add_phase'),
    path('admin/phase/<int:phase_id>/delete/', views.delete_phase, name='delete_phase'),

    # API: Phases
    path('api/competition/<int:competition_id>/phases/', views.api_get_phases, name='api_get_phases'),
    path('api/competition/<int:competition_id>/teams/', views.api_get_teams_by_competition, name='api_get_teams_by_competition'),
    path('api/phase/<int:phase_id>/competition/', views.api_get_phase_competition, name='api_get_phase_competition'),
    path('api/competition/<int:competition_id>/phase/add/', views.api_add_phase, name='api_add_phase'),
    path('api/phase/<int:phase_id>/update/', views.api_update_phase, name='api_update_phase'),
    path('api/phase/<int:phase_id>/delete/', views.api_delete_phase, name='api_delete_phase'),

    # API: Competition management
    path('api/competition/create/', views.api_create_competition, name='api_create_competition'),
    path('api/competition/<int:competition_id>/reorder/', views.api_reorder_competition, name='api_reorder_competition'),

    # API: Match management
    path('api/match/create/', views.api_create_match, name='api_create_match'),
    path('api/match/<int:match_id>/', views.api_get_match, name='api_get_match'),
    path('api/match/<int:match_id>/update/', views.api_update_match, name='api_update_match'),
    path('api/match/<int:match_id>/assignments/', views.api_update_match_assignments, name='api_update_match_assignments'),
    path('api/match/<int:match_id>/publish/', views.api_publish_match, name='api_publish_match'),
    path('api/match/<int:match_id>/delete/', views.api_delete_match, name='api_delete_match'),
    path('api/match/<int:match_id>/toggle-hidden/', views.api_toggle_match_hidden, name='api_toggle_match_hidden'),
    path('api/match/<int:match_id>/toggle-assignment-published/', views.api_toggle_assignment_published, name='api_toggle_assignment_published'),
    path('api/match/<int:match_id>/toggle-cancelled/', views.api_toggle_match_cancelled, name='api_toggle_match_cancelled'),
    path('api/referees/', views.api_get_referees, name='api_get_referees'),
    path('api/users-by-position/', views.api_get_users_by_position, name='api_get_users_by_position'),
    path('api/assignment/<int:assignment_id>/accept/', views.api_accept_assignment, name='api_accept_assignment'),
    path('api/assignment/<int:assignment_id>/reset/', views.api_reset_assignment, name='api_reset_assignment'),

    # API: Match Applications
    path('api/match/<int:match_id>/apply/', views.api_apply_for_match, name='api_apply_for_match'),
    path('api/application/<int:application_id>/withdraw/', views.api_withdraw_application, name='api_withdraw_application'),

    # API: Saved Colors
    path('api/colors/', views.list_colors, name='list_colors'),
    path('api/colors/save/', views.save_color, name='save_color'),
    path('api/colors/delete/', views.delete_color, name='delete_color'),

    # Admin: Archive and deleted items management
    path('admin/archive/', views.archive, name='archive'),
    path('admin/trash/', views.trash_view, name='trash'),
    path('admin/deleted/', views.deleted_items, name='deleted_items'),  # Legacy redirect to trash
    path('api/match/<int:match_id>/permanently-delete/', views.api_permanently_delete_match, name='api_permanently_delete_match'),
    path('api/match/<int:match_id>/restore/', views.api_restore_match, name='api_restore_match'),
    path('api/club/<int:club_id>/restore/', views.api_restore_club, name='api_restore_club'),
    path('api/club/<int:club_id>/permanently-delete/', views.api_permanently_delete_club, name='api_permanently_delete_club'),
    path('api/team/<int:team_id>/restore/', views.api_restore_team, name='api_restore_team'),
    path('api/team/<int:team_id>/permanently-delete/', views.api_permanently_delete_team, name='api_permanently_delete_team'),
    path('api/venue/<int:venue_id>/restore/', views.api_restore_venue, name='api_restore_venue'),
    path('api/venue/<int:venue_id>/permanently-delete/', views.api_permanently_delete_venue, name='api_permanently_delete_venue'),
    path('api/competition/<int:competition_id>/restore/', views.api_restore_competition, name='api_restore_competition'),
    path('api/competition/<int:competition_id>/permanently-delete/', views.api_permanently_delete_competition, name='api_permanently_delete_competition'),
    path('api/season/<int:season_id>/restore/', views.api_restore_season, name='api_restore_season'),
    path('api/season/<int:season_id>/permanently-delete/', views.api_permanently_delete_season, name='api_permanently_delete_season'),
    path('api/season/<int:season_id>/activate/', views.api_activate_season, name='api_activate_season'),

    # Admin: User management
    path('admin/users/', views.users_list, name='users_list'),
    path('admin/users/create/', views.user_create, name='user_create'),
    path('admin/users/<int:user_id>/edit/', views.user_edit, name='user_edit'),
    path('api/user/<int:user_id>/delete/', views.api_user_delete, name='api_user_delete'),
    path('api/user/<int:user_id>/toggle-login/', views.api_user_toggle_login, name='api_user_toggle_login'),
    path('api/user/<int:user_id>/toggle-visibility/', views.api_user_toggle_visibility, name='api_user_toggle_visibility'),
    path('api/user/<int:user_id>/toggle-archive/', views.api_user_toggle_archive, name='api_user_toggle_archive'),
    path('api/user/<int:user_id>/exclude/', views.api_user_exclude, name='api_user_exclude'),
    path('api/user/<int:user_id>/restore/', views.api_user_restore, name='api_user_restore'),
    path('api/user/<int:user_id>/permanently-delete/', views.api_user_permanently_delete, name='api_user_permanently_delete'),

    # Match Feedback (user-facing)
    path('feedback/', views.match_feedback_list, name='match_feedback_list'),
    path('feedback/<int:assignment_id>/', views.match_feedback_submit, name='match_feedback_submit'),
    path('api/feedback/<int:assignment_id>/submit/', views.api_submit_feedback, name='api_submit_feedback'),

    # Match Feedback (admin)
    path('admin/feedbacks/', views.admin_feedback_list, name='admin_feedback_list'),
    path('api/feedback/<int:feedback_id>/details/', views.api_feedback_details, name='api_feedback_details'),
]
