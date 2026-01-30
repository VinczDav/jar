from django.conf import settings
from documents.models import Notification


def unread_notifications(request):
    """
    Context processor to add unread notifications count to all templates.
    """
    if request.user.is_authenticated:
        count = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        return {'unread_notifications_count': count}
    return {'unread_notifications_count': 0}


def global_settings(request):
    """
    Context processor to add global settings to all templates.
    """
    return {
        'IS_TEST_SERVER': getattr(settings, 'TEST_SERVER', False),
        'DEBUG': settings.DEBUG,
    }


def application_settings(request):
    """
    Context processor to add match application settings to all templates.
    Determines if the "Jelentkezések" menu should be shown.
    """
    if not request.user.is_authenticated:
        return {'can_apply_for_matches': False}

    from .models import SiteSettings

    site_settings = SiteSettings.get_settings()
    user = request.user

    # Check if user can apply based on role and system settings
    can_apply = False

    # Referees can apply if referee applications are enabled
    if site_settings.application_referees_enabled and user.role == 'referee':
        can_apply = True

    # Inspectors can apply if inspector applications are enabled
    if site_settings.application_inspectors_enabled and user.role == 'inspector':
        can_apply = True

    # Tournament Directors can apply if TIG applications are enabled
    if site_settings.application_tournament_directors_enabled and user.role == 'tournament_director':
        can_apply = True

    # JT Admins and Admins can apply as any role if any application type is enabled
    if user.role in ['jt_admin', 'admin']:
        if (site_settings.application_referees_enabled or
            site_settings.application_inspectors_enabled or
            site_settings.application_tournament_directors_enabled):
            can_apply = True

    return {'can_apply_for_matches': can_apply}


def recent_logins(request):
    """
    Context processor to add last 5 logins for super admin sidebar.
    Only visible to super admin users.
    """
    if not request.user.is_authenticated:
        return {'recent_logins': []}

    # Only for super admin users
    if not getattr(request.user, 'is_super_admin', False):
        return {'recent_logins': []}

    from audit.models import AuditLog

    logins = AuditLog.objects.filter(
        action='login'
    ).select_related('user').order_by('-timestamp')[:5]

    return {'recent_logins': logins}


def match_badges(request):
    """
    Context processor to add match-related badge counts to navigation.
    - pending_matches_count: Matches where user is assigned but hasn't accepted (red)
    - all_my_matches_count: All future matches where user is assigned (for badge)
    - all_my_matches_accepted: True if all assigned matches are accepted (green indicator)
    - available_applications_count: Matches where user can apply (yellow)
    """
    if not request.user.is_authenticated:
        return {
            'pending_matches_count': 0,
            'all_my_matches_count': 0,
            'all_my_matches_accepted': True,
            'available_applications_count': 0,
        }

    from django.utils import timezone
    from django.db.models import Q
    from matches.models import Match, MatchAssignment

    user = request.user
    today = timezone.localdate()

    # Get user's future assignments (published, not cancelled, future date)
    future_assignments = MatchAssignment.objects.filter(
        user=user,
        match__is_deleted=False,
        match__is_assignment_published=True,
        match__date__gte=today
    ).exclude(
        match__status=Match.Status.CANCELLED
    ).exclude(
        response_status=MatchAssignment.ResponseStatus.DECLINED
    )

    # Count pending (not accepted) assignments
    pending_count = future_assignments.filter(
        response_status=MatchAssignment.ResponseStatus.PENDING
    ).count()

    # Count accepted assignments
    accepted_count = future_assignments.filter(
        response_status=MatchAssignment.ResponseStatus.ACCEPTED
    ).count()

    # Count all future assignments
    all_count = future_assignments.count()

    # Count available applications (matches where user can apply)
    available_apps_count = 0

    # Only calculate if user can apply
    from .models import SiteSettings
    site_settings = SiteSettings.get_settings()

    # Determine which role applications are enabled for this user
    can_apply_referee = site_settings.application_referees_enabled and user.role in ['referee', 'jt_admin', 'admin']
    can_apply_inspector = site_settings.application_inspectors_enabled and user.role in ['inspector', 'jt_admin', 'admin']
    can_apply_td = site_settings.application_tournament_directors_enabled and user.role in ['tournament_director', 'jt_admin', 'admin']

    if can_apply_referee or can_apply_inspector or can_apply_td:
        from matches.models import MatchApplication

        # Find matches with "szukseges" placeholder that has application_enabled=True
        # and user hasn't already applied
        already_applied_match_ids = MatchApplication.objects.filter(
            user=user,
            status__in=[MatchApplication.Status.PENDING, MatchApplication.Status.ACCEPTED]
        ).values_list('match_id', flat=True)

        # Find matches where user is already assigned (excluding declined)
        already_assigned_match_ids = MatchAssignment.objects.filter(
            user=user
        ).exclude(
            response_status=MatchAssignment.ResponseStatus.DECLINED
        ).values_list('match_id', flat=True)

        # Build query for available application positions
        # Site settings control who can apply (checked above via can_apply_*)
        # Per-position toggle (application_enabled) controls which positions are open
        app_query = Q()

        if can_apply_referee:
            app_query |= Q(
                role=MatchAssignment.Role.REFEREE,
                application_enabled=True,
                placeholder_type='szukseges'
            )

        if can_apply_inspector:
            app_query |= Q(
                role=MatchAssignment.Role.INSPECTOR,
                application_enabled=True,
                placeholder_type='szukseges'
            )

        if can_apply_td:
            app_query |= Q(
                role=MatchAssignment.Role.TOURNAMENT_DIRECTOR,
                application_enabled=True,
                placeholder_type='szukseges'
            )

        if app_query:
            # Count unique matches with open application positions
            available_apps_count = MatchAssignment.objects.filter(
                app_query,
                user__isnull=True,  # Only placeholder positions
                match__is_deleted=False,
                match__is_assignment_published=True,
                match__date__gte=today
            ).exclude(
                match__status=Match.Status.CANCELLED
            ).exclude(
                match_id__in=already_applied_match_ids
            ).exclude(
                match_id__in=already_assigned_match_ids
            ).values('match_id').distinct().count()

    return {
        'pending_matches_count': pending_count,
        'accepted_matches_count': accepted_count,
        'all_my_matches_count': all_count,
        'available_applications_count': available_apps_count,
    }
