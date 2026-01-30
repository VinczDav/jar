import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from .models import Match, MatchAssignment, MatchApplication, Season, Competition, SavedColor, Team, Club, Venue
from .forms import MatchForm, MatchAssignmentForm, MatchResponseForm, MatchFilterForm
from audit.utils import log_action


def _notify_admins_about_decline(assignment, declining_user):
    """
    Send notification to all JT Admin / Koordinátor users when someone declines an assignment.
    Also sends email notifications.
    """
    from django.contrib.auth import get_user_model
    from documents.models import Notification
    from core.email_utils import send_templated_email

    User = get_user_model()
    # Reload match with all related objects for email template
    match = Match.objects.select_related(
        'venue', 'phase', 'phase__competition', 'home_team', 'away_team'
    ).get(pk=assignment.match_id)

    # Get all JT Admin / Koordinátor and Admin users (primary role OR secondary flag)
    admins = User.objects.filter(
        Q(role=User.Role.JT_ADMIN) | Q(role=User.Role.ADMIN) |
        Q(is_jt_admin_flag=True) | Q(is_admin_flag=True),
        is_active=True,
        is_deleted=False
    ).exclude(id=declining_user.id)  # Don't notify the user who declined

    if not admins.exists():
        return

    # Format notification message
    user_name = declining_user.get_full_name() or declining_user.username
    date_str = match.date.strftime('%Y.%m.%d') if match.date else 'Nincs dátum'
    time_str = match.time.strftime('%H:%M') if match.time else ''
    teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"

    title = f"{user_name} lemondta a kijelölést"
    message = f"{date_str} {time_str}\n{teams}"
    if assignment.decline_reason:
        message += f"\nIndok: {assignment.decline_reason}"

    # Get all assignments for this match for the email template
    all_assignments = match.assignments.select_related('user').order_by('role', 'created_at')

    # Send notification and email to all admins
    for admin in admins:
        # In-app notification
        Notification.objects.create(
            recipient=admin,
            title=title,
            message=message,
            notification_type=Notification.Type.WARNING,
            link="/matches/assignments/"
        )

        # Email notification
        if admin.email:
            send_templated_email(
                to_email=admin.email,
                subject=f'{user_name} lemondta a mérkőzést!',
                template_name='assignment_declined',
                context={
                    'declining_user': declining_user,
                    'match': match,
                    'assignment': assignment,
                    'all_assignments': all_assignments,
                }
            )


@login_required
def my_matches(request):
    """Show matches assigned to current user."""
    # Get tab parameter (upcoming or past)
    tab = request.GET.get('tab', 'upcoming')
    now = timezone.localtime(timezone.now())  # Convert to local time (Europe/Budapest)
    today = now.date()

    # Get filter parameters
    from datetime import timedelta
    season_id = request.GET.get('season', '')
    competition_id = request.GET.get('competition', '')
    team_id = request.GET.get('team', '')

    # Default date range: today to today + 14 days (for upcoming), or last 14 days (for past)
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Set default dates if not provided
    if not date_from and not date_to:
        if tab == 'upcoming':
            date_from = str(today)
            date_to = str(today + timedelta(days=14))
        elif tab == 'past':
            date_from = str(today - timedelta(days=14))
            date_to = str(today)

    # Get current/selected season
    current_season = Season.get_current()
    if season_id:
        try:
            selected_season = Season.objects.get(id=season_id)
        except Season.DoesNotExist:
            selected_season = current_season
    else:
        selected_season = current_season

    # Get user's assignments - exclude hidden matches, unpublished assignments, draft matches, and deleted matches
    assignments = MatchAssignment.objects.filter(
        user=request.user,
        match__is_hidden=False,  # Don't show hidden matches to referees
        match__is_assignment_published=True,  # Don't show unpublished assignments
        match__is_deleted=False  # Don't show soft-deleted matches
    ).exclude(
        match__status=Match.Status.DRAFT  # Don't show draft matches to referees
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition'
    )

    # Apply season filter
    if selected_season:
        assignments = assignments.filter(match__phase__competition__season=selected_season)

    # Apply other filters
    if competition_id:
        assignments = assignments.filter(match__phase__competition_id=competition_id)
    if date_from:
        assignments = assignments.filter(match__date__gte=date_from)
    if date_to:
        assignments = assignments.filter(match__date__lte=date_to)
    if team_id:
        assignments = assignments.filter(
            Q(match__home_team_id=team_id) | Q(match__away_team_id=team_id)
        )

    # Time-based filtering: match is "past" if start time + 1 minute has passed
    # Note: 'now' is already defined at function start as localtime
    current_time = now.time()
    one_min_ago = (now - timedelta(minutes=1)).time()

    # Pending: waiting for response (future matches only, always show on upcoming tab)
    if tab == 'upcoming':
        pending_assignments = assignments.filter(
            response_status=MatchAssignment.ResponseStatus.PENDING
        ).filter(
            Q(match__date__gt=today) |
            Q(match__date=today, match__time__isnull=True) |
            Q(match__date=today, match__time__gt=one_min_ago)
        ).order_by('match__date', 'match__time')
    else:
        pending_assignments = []

    if tab == 'past':
        # Past: matches where start time + 1 minute has passed
        display_assignments = assignments.filter(
            Q(match__date__lt=today) |
            Q(match__date=today, match__time__isnull=False, match__time__lte=one_min_ago)
        ).exclude(
            response_status=MatchAssignment.ResponseStatus.DECLINED
        ).order_by('-match__date', '-match__time')
    else:
        # Upcoming: accepted matches that haven't started yet
        display_assignments = assignments.filter(
            response_status=MatchAssignment.ResponseStatus.ACCEPTED
        ).filter(
            Q(match__date__gt=today) |
            Q(match__date=today, match__time__isnull=True) |
            Q(match__date=today, match__time__gt=one_min_ago)
        ).order_by('match__date', 'match__time')

    # Get seasons for filter (exclude soft-deleted)
    seasons = Season.objects.filter(is_deleted=False).order_by('-start_date')

    # Get competitions for filter (based on selected season, exclude soft-deleted)
    competitions = Competition.objects.filter(season=selected_season, is_deleted=False) if selected_season else Competition.objects.none()

    # Get teams for filter (exclude soft-deleted)
    teams = Team.objects.filter(is_deleted=False).order_by('name')

    # Get site settings and coordinators for cancellation check
    from accounts.models import SiteSettings, Coordinator
    site_settings = SiteSettings.get_settings()
    coordinators = Coordinator.objects.filter(is_active=True).select_related('user').order_by('order', 'user__last_name', 'user__first_name')

    # Pagination - 50 assignments per page
    from django.core.paginator import Paginator
    paginator = Paginator(display_assignments, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'pending_assignments': pending_assignments,
        'display_assignments': page_obj,
        'page_obj': page_obj,
        'current_tab': tab,
        'seasons': seasons,
        'selected_season': selected_season,
        'competitions': competitions,
        'selected_competition': competition_id,
        'date_from': date_from,
        'date_to': date_to,
        'teams': teams,
        'selected_team': team_id,
        'min_cancellation_hours': site_settings.min_cancellation_hours,
        'require_cancellation_reason': getattr(site_settings, 'require_cancellation_reason', True),
        'coordinators': coordinators,
    }
    return render(request, 'matches/my_matches.html', context)


@login_required
def all_matches(request):
    """Show all matches with filters."""
    from datetime import timedelta

    # Get tab parameter (upcoming or past)
    tab = request.GET.get('tab', 'upcoming')
    now = timezone.localtime(timezone.now())
    today = now.date()

    # Set default dates if not provided (14 days range)
    form_data = request.GET.copy() if request.GET else {}
    if not request.GET.get('date_from') and not request.GET.get('date_to'):
        if tab == 'upcoming':
            form_data['date_from'] = str(today)
            form_data['date_to'] = str(today + timedelta(days=14))
        elif tab == 'past':
            form_data['date_from'] = str(today - timedelta(days=14))
            form_data['date_to'] = str(today)

    filter_form = MatchFilterForm(form_data or None)

    matches = Match.objects.select_related(
        'home_team', 'away_team', 'venue',
        'phase', 'phase__competition', 'phase__competition__season'
    ).prefetch_related('assignments', 'assignments__user').filter(is_deleted=False)

    # Hide hidden matches from non-admin users
    if not request.user.is_jt_admin:
        matches = matches.filter(is_hidden=False)

    # Apply filters
    if filter_form.is_valid():
        if filter_form.cleaned_data.get('season'):
            matches = matches.filter(phase__competition__season=filter_form.cleaned_data['season'])
        if filter_form.cleaned_data.get('competition'):
            matches = matches.filter(phase__competition=filter_form.cleaned_data['competition'])
        if filter_form.cleaned_data.get('date_from'):
            matches = matches.filter(date__gte=filter_form.cleaned_data['date_from'])
        if filter_form.cleaned_data.get('date_to'):
            matches = matches.filter(date__lte=filter_form.cleaned_data['date_to'])
        if filter_form.cleaned_data.get('team'):
            team = filter_form.cleaned_data['team']
            matches = matches.filter(Q(home_team=team) | Q(away_team=team))
    else:
        # Default: current season
        current_season = Season.get_current()
        if current_season:
            matches = matches.filter(phase__competition__season=current_season)

    # Filter by tab (upcoming or past)
    # A match is "past" if it has started (date+time+1min has passed)
    from django.db.models.functions import Coalesce, Cast
    from django.db.models import DateTimeField, Value
    from datetime import time as dt_time

    if tab == 'past':
        # Past: matches where datetime + 1 minute < now
        # We filter by: date < today OR (date == today AND time < current_time - 1 min)
        current_time = now.time()
        one_min_ago = (now - timedelta(minutes=1)).time()
        matches = matches.filter(
            Q(date__lt=today) |
            Q(date=today, time__isnull=False, time__lte=one_min_ago)
        )
    else:
        # Upcoming: matches where datetime + 1 minute >= now (hasn't started yet)
        current_time = now.time()
        one_min_ago = (now - timedelta(minutes=1)).time()
        matches = matches.filter(
            Q(date__gt=today) |
            Q(date=today, time__isnull=True) |
            Q(date=today, time__isnull=False, time__gt=one_min_ago) |
            Q(date__isnull=True)
        )

    # Sort with NULL dates at the end
    from django.db.models import Case, When, Value, IntegerField
    if tab == 'past':
        matches = matches.order_by('-date', '-time')  # Most recent first for past
    else:
        matches = matches.annotate(
            date_sort=Case(
                When(date__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            )
        ).order_by('date_sort', 'date', 'time')

    # Check if any non-default filter is applied
    has_filters = False
    if filter_form.is_valid():
        for field_name in ['season', 'competition', 'date_from', 'date_to', 'team']:
            if filter_form.cleaned_data.get(field_name):
                has_filters = True
                break

    # Pagination - 50 matches per page
    from django.core.paginator import Paginator
    paginator = Paginator(matches, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'matches': page_obj,
        'page_obj': page_obj,
        'filter_form': filter_form,
        'has_filters': has_filters,
        'current_tab': tab,
    }
    return render(request, 'matches/all_matches.html', context)


@login_required
def assignments(request):
    """JT Admin: Manage match assignments."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Team, Venue, CompetitionPhase, Competition
    from django.contrib.auth import get_user_model
    from referees.models import Unavailability
    from datetime import timedelta, datetime
    from django.core.paginator import Paginator
    User = get_user_model()

    # Get tab parameter (upcoming or past)
    tab = request.GET.get('tab', 'upcoming')
    now = timezone.localtime(timezone.now())
    today = now.date()
    one_min_ago = (now - timedelta(minutes=1)).time()

    # Get filter parameters
    filter_team = request.GET.get('team', '')
    filter_venue = request.GET.get('venue', '')
    filter_competition = request.GET.get('competition', '')
    filter_date_from = request.GET.get('date_from', '')
    filter_date_to = request.GET.get('date_to', '')

    # Set default dates if not provided
    # For upcoming: only set date_from to today (no date_to limit - show all future matches)
    # For past: set 14 days range
    if not filter_date_from and not filter_date_to:
        if tab == 'upcoming':
            filter_date_from = str(today)
            # No date_to for upcoming - show all future matches
        elif tab == 'past':
            filter_date_from = str(today - timedelta(days=14))
            filter_date_to = str(today)

    # Get matches that need assignments (draft or scheduled without confirmed referees)
    current_season = Season.get_current()

    matches = Match.objects.select_related(
        'home_team', 'away_team', 'venue',
        'phase', 'phase__competition'
    ).prefetch_related('assignments', 'assignments__user').filter(is_deleted=False)

    if current_season:
        matches = matches.filter(phase__competition__season=current_season)

    # Filter by status - show draft, scheduled, confirmed, and cancelled matches
    from django.db.models import Case, When, Value, IntegerField
    from django.db.models.functions import Coalesce

    matches = matches.filter(
        status__in=[Match.Status.DRAFT, Match.Status.CREATED, Match.Status.SCHEDULED, Match.Status.CONFIRMED, Match.Status.CANCELLED]
    )

    # Apply filters
    if filter_team:
        matches = matches.filter(Q(home_team_id=filter_team) | Q(away_team_id=filter_team))
    if filter_venue:
        matches = matches.filter(venue_id=filter_venue)
    if filter_competition:
        matches = matches.filter(phase__competition_id=filter_competition)
    if filter_date_from:
        try:
            date_from = datetime.strptime(filter_date_from, '%Y-%m-%d').date()
            matches = matches.filter(date__gte=date_from)
        except ValueError:
            pass
    if filter_date_to:
        try:
            date_to = datetime.strptime(filter_date_to, '%Y-%m-%d').date()
            matches = matches.filter(date__lte=date_to)
        except ValueError:
            pass

    # Filter by tab (upcoming or past)
    if tab == 'past':
        # Past: matches where start time + 1 minute has passed
        matches = matches.filter(
            Q(date__lt=today) |
            Q(date=today, time__isnull=False, time__lte=one_min_ago)
        ).order_by('-date', '-time')  # Most recent first for past
    else:
        # Upcoming: matches that haven't started yet (or no date)
        matches = matches.filter(
            Q(date__gt=today) |
            Q(date=today, time__isnull=True) |
            Q(date=today, time__isnull=False, time__gt=one_min_ago) |
            Q(date__isnull=True)
        ).annotate(
            # Sort NULL dates to the end
            date_sort=Case(
                When(date__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=IntegerField()
            )
        ).order_by('date_sort', 'date', 'time')

    # Pagination - 50 matches per page
    paginator = Paginator(matches, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Get options for sidebar selects - TBD teams first, then alphabetically (exclude deleted)
    teams = Team.objects.filter(is_active=True, is_deleted=False).order_by('-is_tbd', 'name')
    venues = Venue.objects.filter(is_active=True, is_deleted=False).order_by('city', 'name')
    phases = CompetitionPhase.objects.select_related('competition').filter(competition__is_deleted=False)
    competitions = Competition.objects.filter(is_deleted=False)
    if current_season:
        phases = phases.filter(competition__season=current_season)
        competitions = competitions.filter(season=current_season)
    referees = User.objects.filter(
        role__in=['referee', 'jt_admin', 'admin', 'inspector']
    ).order_by('last_name', 'first_name')

    # Get all unavailabilities for referees
    unavailabilities = Unavailability.objects.select_related('referee__user').all()
    # Build a dict: user_id -> list of {start, end} date strings
    referee_unavailabilities = {}
    for unavail in unavailabilities:
        user_id = unavail.referee.user_id
        if user_id not in referee_unavailabilities:
            referee_unavailabilities[user_id] = []
        referee_unavailabilities[user_id].append({
            'start': unavail.start_date.strftime('%Y-%m-%d'),
            'end': unavail.end_date.strftime('%Y-%m-%d'),
        })

    context = {
        'matches': page_obj,
        'page_obj': page_obj,
        'current_season': current_season,
        'current_tab': tab,
        'teams': teams,
        'venues': venues,
        'phases': phases,
        'competitions': competitions,
        'referees': referees,
        'referee_unavailabilities': referee_unavailabilities,
        # Filter values to preserve in form
        'filter_team': filter_team,
        'filter_venue': filter_venue,
        'filter_competition': filter_competition,
        'filter_date_from': filter_date_from,
        'filter_date_to': filter_date_to,
        # Super admin flag for no-notification option
        'is_super_admin': request.user.is_super_admin,
    }
    return render(request, 'matches/assignments.html', context)


@login_required
def create_match(request):
    """JT Admin: Create a new match."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    if request.method == 'POST':
        form = MatchForm(request.POST)
        if form.is_valid():
            match = form.save(commit=False)
            match.created_by = request.user
            match.status = Match.Status.DRAFT
            match.save()
            # Audit log
            log_action(request, 'match', 'create', f'Új mérkőzés létrehozva - {match}', obj=match)
            messages.success(request, 'Mérkőzés sikeresen létrehozva!')
            return redirect('matches:edit_match', match_id=match.id)
    else:
        form = MatchForm()

    context = {
        'form': form,
        'title': 'Új mérkőzés',
    }
    return render(request, 'matches/match_form.html', context)


@login_required
def edit_match(request, match_id):
    """JT Admin: Edit match and manage assignments."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    match = get_object_or_404(Match.objects.filter(is_deleted=False), id=match_id)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_match':
            form = MatchForm(request.POST, instance=match)
            if form.is_valid():
                form.save()
                # Audit log
                log_action(request, 'match', 'update', f'Mérkőzés adatai módosítva - {match}', obj=match)
                messages.success(request, 'Mérkőzés frissítve!')
                return redirect('matches:edit_match', match_id=match.id)
        elif action == 'update_assignments':
            assignment_form = MatchAssignmentForm(request.POST, match=match)
            if assignment_form.is_valid():
                assignment_form.save()
                # Audit log
                log_action(request, 'assignment', 'update', f'Kijelölések módosítva - {match}', obj=match)
                messages.success(request, 'Kijelölések frissítve!')
                return redirect('matches:edit_match', match_id=match.id)
        elif action == 'publish':
            # Publish match - change status to scheduled
            if match.assignments.exists():
                match.status = Match.Status.SCHEDULED
                match.save()
                # Audit log
                log_action(request, 'assignment', 'send', f'Mérkőzés kiírva - {match}', obj=match, extra={
                    'referees': [a.user.get_full_name() for a in match.assignments.all()]
                })
                messages.success(request, 'Mérkőzés kiírva! Értesítések elküldve a játékvezetőknek.')
            else:
                messages.error(request, 'Legalább egy játékvezetőt ki kell jelölni!')
            return redirect('matches:edit_match', match_id=match.id)
        elif action == 'delete':
            # Soft delete - mark as deleted but keep in database
            match.is_deleted = True
            match.deleted_at = timezone.now()
            match.save()
            # Audit log
            log_action(request, 'match', 'delete', f'Mérkőzés törölve - {match}', obj=match)
            messages.success(request, 'Mérkőzés törölve!')
            return redirect('matches:assignments')
    else:
        form = MatchForm(instance=match)

    assignment_form = MatchAssignmentForm(match=match)

    context = {
        'form': form,
        'assignment_form': assignment_form,
        'match': match,
        'title': 'Mérkőzés szerkesztése',
    }
    return render(request, 'matches/match_form.html', context)


@login_required
@require_POST
def respond_to_assignment(request, assignment_id):
    """Respond to a match assignment (accept/decline)."""
    from accounts.models import SiteSettings

    assignment = get_object_or_404(
        MatchAssignment,
        id=assignment_id,
        user=request.user
    )

    if assignment.response_status != MatchAssignment.ResponseStatus.PENDING:
        messages.error(request, 'Erre a kijelölésre már válaszoltál.')
        return redirect('matches:my_matches')

    site_settings = SiteSettings.get_settings()
    form = MatchResponseForm(request.POST, require_reason=site_settings.require_cancellation_reason)
    if form.is_valid():
        assignment.response_status = form.cleaned_data['response']
        assignment.response_date = timezone.now()
        if form.cleaned_data['response'] == 'declined':
            assignment.decline_reason = form.cleaned_data.get('decline_reason', '')
            # Set placeholder_type so the slot shows as "Hiányzik!" in admin panel
            assignment.placeholder_type = 'hianyzik'
        assignment.save()

        if form.cleaned_data['response'] == 'accepted':
            # Audit log
            log_action(request, 'assignment', 'accept', f'Kijelölés elfogadva - {assignment.match}', obj=assignment, extra={
                'match_id': assignment.match.id,
                'role': assignment.get_role_display()
            })
            messages.success(request, 'Kijelölés elfogadva!')
        else:
            # Audit log
            log_action(request, 'assignment', 'reject', f'Kijelölés elutasítva - {assignment.match}', obj=assignment, extra={
                'match_id': assignment.match.id,
                'role': assignment.get_role_display(),
                'reason': assignment.decline_reason
            })
            messages.info(request, 'Kijelölés elutasítva.')
            # Notify JT Admin / Koordinátor about the decline
            _notify_admins_about_decline(assignment, request.user)

        # Check if all referees confirmed
        match = assignment.match
        if match.is_all_confirmed and match.status == Match.Status.SCHEDULED:
            match.status = Match.Status.CONFIRMED
            match.save()
    else:
        # Form validation failed
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f'{error}')

    return redirect('matches:my_matches')


@login_required
@require_POST
def decline_accepted_assignment(request, assignment_id):
    """Decline an already accepted assignment."""
    from datetime import datetime, timedelta
    from accounts.models import SiteSettings

    assignment = get_object_or_404(
        MatchAssignment,
        id=assignment_id,
        user=request.user
    )

    if assignment.response_status != MatchAssignment.ResponseStatus.ACCEPTED:
        messages.error(request, 'Ez a kijelölés nem elfogadott státuszú.')
        return redirect('matches:my_matches')

    # Check if cancellation is within minimum time window
    match = assignment.match
    if match.date and match.time:
        site_settings = SiteSettings.get_settings()
        match_datetime = datetime.combine(match.date, match.time)
        if timezone.is_naive(match_datetime):
            match_datetime = timezone.make_aware(match_datetime)

        min_cancel_time = match_datetime - timedelta(hours=site_settings.min_cancellation_hours)
        now = timezone.now()

        if now >= min_cancel_time:
            # Within minimum cancellation window - cannot cancel online
            hours = site_settings.min_cancellation_hours
            days = hours // 24
            coordinator_name = site_settings.coordinator_name
            coordinator_phone = site_settings.coordinator_phone

            if coordinator_phone:
                error_msg = (
                    f'A mérkőzés {days} napon ({hours} órán) belül van, ezért online nem mondható le. '
                    f'Kérjük vedd fel a kapcsolatot közvetlenül a koordinátorral: '
                    f'{coordinator_name} ({coordinator_phone})'
                )
            else:
                error_msg = (
                    f'A mérkőzés {days} napon ({hours} órán) belül van, ezért online nem mondható le. '
                    f'Kérjük vedd fel a kapcsolatot közvetlenül a koordinátorral: {coordinator_name}'
                )

            messages.error(request, error_msg)
            return redirect('matches:my_matches')

    decline_reason = request.POST.get('decline_reason', '').strip()

    # Check if reason is required based on site settings
    if not hasattr(site_settings, 'require_cancellation_reason'):
        # For backwards compatibility - if setting doesn't exist yet
        require_reason = True
    else:
        require_reason = site_settings.require_cancellation_reason

    if require_reason and not decline_reason:
        messages.error(request, 'Kérlek add meg a lemondás okát.')
        return redirect('matches:my_matches')

    assignment.response_status = MatchAssignment.ResponseStatus.DECLINED
    assignment.response_date = timezone.now()
    assignment.decline_reason = decline_reason if decline_reason else 'Nem megadott'
    # Set placeholder_type so the slot shows as "Hiányzik!" in admin panel
    assignment.placeholder_type = 'hianyzik'
    assignment.save()

    # Audit log
    log_action(request, 'assignment', 'cancel', f'Elfogadott kijelölés lemondva - {assignment.match}', obj=assignment, extra={
        'match_id': assignment.match.id,
        'role': assignment.get_role_display(),
        'reason': decline_reason
    })

    messages.info(request, 'A kijelölést lemondtad.')

    # Notify JT Admin / Koordinátor about the decline
    _notify_admins_about_decline(assignment, request.user)

    # Update match status back to scheduled if it was confirmed
    match = assignment.match
    if match.status == Match.Status.CONFIRMED:
        match.status = Match.Status.SCHEDULED
        match.save()

    return redirect('matches:my_matches')


@login_required
def match_detail(request, match_id):
    """View match details."""
    match = get_object_or_404(
        Match.objects.filter(is_deleted=False).select_related(
            'home_team', 'away_team', 'venue',
            'phase', 'phase__competition', 'phase__competition__season',
            'created_by'
        ).prefetch_related('assignments', 'assignments__user'),
        id=match_id
    )

    # Check if user is assigned to this match
    user_assignment = None
    if request.user.is_authenticated:
        user_assignment = match.assignments.filter(user=request.user).first()

    context = {
        'match': match,
        'user_assignment': user_assignment,
        'can_edit': request.user.is_jt_admin,
    }
    return render(request, 'matches/match_detail.html', context)


@login_required
def get_competitions(request):
    """AJAX endpoint to get competitions for a season."""
    season_id = request.GET.get('season_id')
    if season_id:
        competitions = Competition.objects.filter(season_id=season_id, is_deleted=False).values('id', 'short_name', 'name')
        return JsonResponse(list(competitions), safe=False)
    return JsonResponse([], safe=False)


def public_matches(request):
    """Public page showing upcoming matches for the next 2 weeks."""
    from datetime import timedelta
    from itertools import groupby

    today = timezone.localtime(timezone.now()).date()  # Use local time for date
    two_weeks_later = today + timedelta(days=14)

    matches = Match.objects.filter(
        date__gte=today,
        date__lte=two_weeks_later,
        is_hidden=False,
        is_deleted=False
    ).exclude(
        status=Match.Status.CANCELLED
    ).select_related(
        'home_team', 'away_team', 'venue',
        'phase', 'phase__competition'
    ).prefetch_related(
        'assignments', 'assignments__user'
    ).order_by('date', 'time')

    # Group matches by date
    matches_by_date = []
    for date, group in groupby(matches, key=lambda m: m.date):
        matches_by_date.append({
            'date': date,
            'matches': list(group)
        })

    context = {
        'matches_by_date': matches_by_date,
        'today': today,
    }
    return render(request, 'matches/public_matches.html', context)


@login_required
def match_data(request):
    """Admin: Manage match-related data (teams, venues, competitions, etc.)."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Team, Venue, Season, Competition, CompetitionPhase

    context = {
        'seasons': Season.objects.filter(is_deleted=False).order_by('-start_date'),
        'competitions': Competition.objects.filter(is_deleted=False).select_related('season').order_by('-season__start_date', 'name'),
        'teams': Team.objects.filter(is_deleted=False).order_by('name'),
        'venues': Venue.objects.filter(is_deleted=False).order_by('city', 'name'),
    }
    return render(request, 'matches/match_data.html', context)


@login_required
def add_team(request):
    """Admin: Add a new team."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Team

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        short_name = request.POST.get('short_name', '').strip()
        city = request.POST.get('city', '').strip()

        if name:
            team = Team.objects.create(name=name, short_name=short_name, city=city)
            log_action(request, 'system', 'create', f'Csapat létrehozva: {name}', obj=team)
            messages.success(request, f'Csapat létrehozva: {name}')

    return redirect('matches:match_data')


@login_required
def delete_team(request, team_id):
    """Admin: Delete a team."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Team

    if request.method == 'POST':
        team = get_object_or_404(Team, id=team_id)
        name = team.name
        log_action(request, 'system', 'delete', f'Csapat törölve: {name}', extra={'team_id': team_id})
        team.delete()
        messages.success(request, f'Csapat törölve: {name}')

    return redirect('matches:match_data')


@login_required
def add_venue(request):
    """Admin: Add a new venue."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Venue

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        city = request.POST.get('city', '').strip()
        address = request.POST.get('address', '').strip()

        if name:
            venue = Venue.objects.create(name=name, city=city, address=address)
            log_action(request, 'system', 'create', f'Helyszín létrehozva: {name}', obj=venue)
            messages.success(request, f'Helyszín létrehozva: {name}')

    return redirect('matches:match_data')


@login_required
def delete_venue(request, venue_id):
    """Admin: Delete a venue."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Venue

    if request.method == 'POST':
        venue = get_object_or_404(Venue, id=venue_id)
        name = venue.name
        log_action(request, 'system', 'delete', f'Helyszín törölve: {name}', extra={'venue_id': venue_id})
        venue.delete()
        messages.success(request, f'Helyszín törölve: {name}')

    return redirect('matches:competitions_list')


@login_required
def add_season(request):
    """Admin: Add a new season."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Season

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        is_active = request.POST.get('is_active') == 'on'

        if name and start_date and end_date:
            Season.objects.create(
                name=name,
                start_date=start_date,
                end_date=end_date,
                is_active=is_active
            )
            messages.success(request, f'Szezon létrehozva: {name}')

    return redirect('matches:competitions_list')


@login_required
def add_competition(request):
    """Admin: Add a new competition."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Competition, Season

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        short_name = request.POST.get('short_name', '').strip()
        season_id = request.POST.get('season')
        color = request.POST.get('color', '#6366f1').strip()

        if name and season_id:
            season = get_object_or_404(Season, id=season_id)
            Competition.objects.create(name=name, short_name=short_name, season=season, color=color)
            messages.success(request, f'Bajnokság létrehozva: {name}')

    return redirect('matches:competitions_list')


@login_required
def add_phase(request):
    """Admin: Add a new competition phase."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Competition, CompetitionPhase

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        competition_id = request.POST.get('competition')
        payment_amount = request.POST.get('payment_amount', '0')
        payment_type = request.POST.get('payment_type', 'per_person')

        # Parse payment amount
        try:
            payment_amount = int(payment_amount)
        except (ValueError, TypeError):
            payment_amount = 0

        if name and competition_id:
            competition = get_object_or_404(Competition, id=competition_id)
            CompetitionPhase.objects.create(
                name=name,
                competition=competition,
                payment_amount=payment_amount,
                payment_type=payment_type
            )
            messages.success(request, f'Szakasz létrehozva: {name}')

    return redirect('matches:competitions_list')


@login_required
def edit_competition(request, competition_id):
    """Admin: Edit a competition."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Competition, Season

    competition = get_object_or_404(Competition, id=competition_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        short_name = request.POST.get('short_name', '').strip()
        season_id = request.POST.get('season')
        color = request.POST.get('color', competition.color).strip()
        match_duration = request.POST.get('match_duration', '60')

        if name and season_id:
            competition.name = name
            competition.short_name = short_name
            competition.season = get_object_or_404(Season, id=season_id)
            competition.color = color
            try:
                competition.match_duration = int(match_duration) if match_duration else 60
            except ValueError:
                competition.match_duration = 60

            # Application defaults
            competition.referee_application_default = request.POST.get('referee_application_default') == 'on'
            competition.inspector_application_default = request.POST.get('inspector_application_default') == 'on'
            competition.tournament_director_application_default = request.POST.get('tournament_director_application_default') == 'on'

            competition.save()
            messages.success(request, f'Bajnokság frissítve: {name}')

        return redirect('matches:competitions_list')

    seasons = Season.objects.filter(is_deleted=False).order_by('-start_date')
    return render(request, 'matches/competition_edit.html', {
        'competition': competition,
        'seasons': seasons,
    })


@login_required
@require_POST
def delete_competition(request, competition_id):
    """Admin: Soft delete a competition."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from django.utils import timezone

    competition = get_object_or_404(Competition, id=competition_id)
    name = competition.short_name or competition.name

    # Soft delete
    competition.is_deleted = True
    competition.deleted_at = timezone.now()
    competition.save()

    messages.success(request, f'Bajnokság törölve: {name}')

    return redirect('matches:competitions_list')


@login_required
@require_POST
def delete_phase(request, phase_id):
    """Admin: Delete a competition phase."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import CompetitionPhase

    phase = get_object_or_404(CompetitionPhase, id=phase_id)
    name = phase.name
    phase.delete()
    messages.success(request, f'Szakasz törölve: {name}')

    return redirect('matches:competitions_list')


@login_required
def api_get_phases(request, competition_id):
    """API: Get phases for a competition."""
    from .models import Competition, CompetitionPhase

    competition = get_object_or_404(Competition, id=competition_id)
    phases = CompetitionPhase.objects.filter(competition=competition)

    phases_data = []
    for phase in phases:
        phases_data.append({
            'id': phase.id,
            'name': phase.name,
            'payment_amount': phase.payment_amount,
            'payment_type': phase.payment_type,
            'referee_payment': phase.referee_payment,
            'referee_payment_type': phase.referee_payment_type,
            'reserve_payment': phase.reserve_payment,
            'reserve_payment_type': phase.reserve_payment_type,
            'inspector_payment': phase.inspector_payment,
            'inspector_payment_type': phase.inspector_payment_type,
            'tournament_director_payment': phase.tournament_director_payment,
            'tournament_director_payment_type': phase.tournament_director_payment_type,
            'referee_count': phase.referee_count,
            'reserve_count': phase.reserve_count,
            'inspector_count': phase.inspector_count,
            'tournament_director_count': phase.tournament_director_count,
            'requires_mfsz_declaration': phase.requires_mfsz_declaration,
            'referee_application_enabled': phase.referee_application_enabled,
            'inspector_application_enabled': phase.inspector_application_enabled,
            'tournament_director_application_enabled': phase.tournament_director_application_enabled,
        })

    return JsonResponse({'phases': phases_data})


@login_required
def api_get_teams_by_competition(request, competition_id):
    """API: Get teams enrolled in a competition."""
    from .models import Competition, Team

    competition = get_object_or_404(Competition, id=competition_id)
    teams = Team.objects.filter(
        competitions=competition,
        is_active=True,
        is_deleted=False
    ).order_by('-is_tbd', 'club__name', 'suffix')

    teams_data = []
    for team in teams:
        teams_data.append({
            'id': team.id,
            'name': str(team),
            'display_name': team.display_name,
            'is_tbd': team.is_tbd,
        })

    return JsonResponse({'teams': teams_data})


@login_required
def api_get_phase_competition(request, phase_id):
    """API: Get competition ID for a phase."""
    from .models import CompetitionPhase

    phase = get_object_or_404(CompetitionPhase, id=phase_id)
    return JsonResponse({
        'phase_id': phase.id,
        'competition_id': phase.competition_id,
        'competition_name': str(phase.competition)
    })


@login_required
@require_POST
def api_add_phase(request, competition_id):
    """API: Add a phase to a competition."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from .models import Competition, CompetitionPhase

    try:
        data = json.loads(request.body)
        competition = get_object_or_404(Competition, id=competition_id)

        # Use competition defaults for application settings
        phase = CompetitionPhase.objects.create(
            competition=competition,
            name=data.get('name', 'Új szakasz'),
            payment_amount=int(data.get('payment_amount', 0)),
            payment_type=data.get('payment_type', 'per_person'),
            referee_count=int(data.get('referee_count', 2)),
            reserve_count=int(data.get('reserve_count', 0)),
            inspector_count=int(data.get('inspector_count', 0)),
            referee_application_enabled=competition.referee_application_default,
            inspector_application_enabled=competition.inspector_application_default,
            tournament_director_application_enabled=competition.tournament_director_application_default,
        )

        return JsonResponse({
            'id': phase.id,
            'name': phase.name,
            'payment_amount': phase.payment_amount,
            'payment_type': phase.payment_type,
            'referee_payment': phase.referee_payment,
            'inspector_payment': phase.inspector_payment,
            'tournament_director_payment': phase.tournament_director_payment,
            'referee_count': phase.referee_count,
            'reserve_count': phase.reserve_count,
            'inspector_count': phase.inspector_count,
            'tournament_director_count': phase.tournament_director_count,
            'requires_mfsz_declaration': phase.requires_mfsz_declaration,
            'referee_application_enabled': phase.referee_application_enabled,
            'inspector_application_enabled': phase.inspector_application_enabled,
            'tournament_director_application_enabled': phase.tournament_director_application_enabled,
        })
    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_POST
def api_update_phase(request, phase_id):
    """API: Update a phase."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from .models import CompetitionPhase

    try:
        data = json.loads(request.body)
        phase = get_object_or_404(CompetitionPhase, id=phase_id)

        if 'name' in data:
            phase.name = data['name']
        if 'payment_amount' in data:
            phase.payment_amount = int(data['payment_amount'])
        if 'payment_type' in data:
            phase.payment_type = data['payment_type']
        if 'referee_payment' in data:
            phase.referee_payment = int(data['referee_payment'])
        if 'referee_payment_type' in data:
            phase.referee_payment_type = data['referee_payment_type']
        if 'reserve_payment' in data:
            phase.reserve_payment = int(data['reserve_payment'])
        if 'reserve_payment_type' in data:
            phase.reserve_payment_type = data['reserve_payment_type']
        if 'inspector_payment' in data:
            phase.inspector_payment = int(data['inspector_payment'])
        if 'inspector_payment_type' in data:
            phase.inspector_payment_type = data['inspector_payment_type']
        if 'tournament_director_payment' in data:
            phase.tournament_director_payment = int(data['tournament_director_payment'])
        if 'tournament_director_payment_type' in data:
            phase.tournament_director_payment_type = data['tournament_director_payment_type']
        if 'referee_count' in data:
            phase.referee_count = int(data['referee_count'])
        if 'reserve_count' in data:
            phase.reserve_count = int(data['reserve_count'])
        if 'inspector_count' in data:
            phase.inspector_count = int(data['inspector_count'])
        if 'tournament_director_count' in data:
            phase.tournament_director_count = int(data['tournament_director_count'])
        if 'requires_mfsz_declaration' in data:
            phase.requires_mfsz_declaration = bool(data['requires_mfsz_declaration'])
        if 'referee_application_enabled' in data:
            phase.referee_application_enabled = bool(data['referee_application_enabled'])
        if 'inspector_application_enabled' in data:
            phase.inspector_application_enabled = bool(data['inspector_application_enabled'])
        if 'tournament_director_application_enabled' in data:
            phase.tournament_director_application_enabled = bool(data['tournament_director_application_enabled'])

        phase.save()

        return JsonResponse({
            'id': phase.id,
            'name': phase.name,
            'payment_amount': phase.payment_amount,
            'payment_type': phase.payment_type,
            'referee_payment': phase.referee_payment,
            'referee_payment_type': phase.referee_payment_type,
            'reserve_payment': phase.reserve_payment,
            'reserve_payment_type': phase.reserve_payment_type,
            'inspector_payment': phase.inspector_payment,
            'inspector_payment_type': phase.inspector_payment_type,
            'tournament_director_payment': phase.tournament_director_payment,
            'tournament_director_payment_type': phase.tournament_director_payment_type,
            'referee_count': phase.referee_count,
            'reserve_count': phase.reserve_count,
            'inspector_count': phase.inspector_count,
            'tournament_director_count': phase.tournament_director_count,
            'requires_mfsz_declaration': phase.requires_mfsz_declaration,
            'referee_application_enabled': phase.referee_application_enabled,
            'inspector_application_enabled': phase.inspector_application_enabled,
            'tournament_director_application_enabled': phase.tournament_director_application_enabled,
        })
    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_POST
def api_delete_phase(request, phase_id):
    """API: Delete a phase."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from .models import CompetitionPhase

    phase = get_object_or_404(CompetitionPhase, id=phase_id)
    phase.delete()

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_reorder_competition(request, competition_id):
    """API: Move competition up or down in order."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    try:
        data = json.loads(request.body)
        direction = data.get('direction')  # 'up' or 'down'
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    competition = get_object_or_404(Competition, id=competition_id, is_deleted=False)

    # Get all competitions in the same season, ordered
    competitions = list(Competition.objects.filter(
        season=competition.season,
        is_deleted=False
    ).order_by('order', 'name'))

    current_index = next((i for i, c in enumerate(competitions) if c.id == competition_id), None)
    if current_index is None:
        return JsonResponse({'error': 'Competition not found.'}, status=404)

    if direction == 'up' and current_index > 0:
        # Swap with previous
        other = competitions[current_index - 1]
        competition.order, other.order = other.order, competition.order
        # Ensure they're different
        if competition.order == other.order:
            competition.order = current_index - 1
            other.order = current_index
        competition.save()
        other.save()
    elif direction == 'down' and current_index < len(competitions) - 1:
        # Swap with next
        other = competitions[current_index + 1]
        competition.order, other.order = other.order, competition.order
        # Ensure they're different
        if competition.order == other.order:
            competition.order = current_index + 1
            other.order = current_index
        competition.save()
        other.save()

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_create_competition(request):
    """API: Create a new competition."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    name = data.get('name', '').strip()
    short_name = data.get('short_name', '').strip()
    season_id = data.get('season_id')
    color = data.get('color', '#6366f1')
    match_duration = data.get('match_duration', 60)

    if not name or not season_id:
        return JsonResponse({'error': 'Név és szezon megadása kötelező.'}, status=400)

    season = get_object_or_404(Season, id=season_id)

    # Get max order for this season
    max_order = Competition.objects.filter(season=season, is_deleted=False).aggregate(
        max_order=Max('order')
    )['max_order'] or 0

    competition = Competition.objects.create(
        name=name,
        short_name=short_name,
        season=season,
        color=color,
        match_duration=match_duration,
        order=max_order + 1
    )

    return JsonResponse({
        'success': True,
        'id': competition.id,
        'name': competition.name,
        'short_name': competition.short_name,
        'color': competition.color,
        'season_id': competition.season_id,
        'match_duration': competition.match_duration,
        'order': competition.order,
    })


# ==================== MATCH API ====================

@login_required
def api_get_match(request, match_id):
    """API: Get match details for sidebar editing."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    match = get_object_or_404(
        Match.objects.select_related(
            'home_team', 'away_team', 'venue',
            'phase', 'phase__competition'
        ).prefetch_related('assignments', 'assignments__user').filter(is_deleted=False),
        id=match_id
    )

    # Get assignments - order: referee, reserve, inspector, tournament_director
    referees = []
    reserves = []
    inspectors = []
    tournament_directors = []

    for assignment in match.assignments.all():
        assignment_data = {
            'id': assignment.id,
            'user_id': assignment.user_id if assignment.user else None,
            'user_name': assignment.user.get_full_name() or assignment.user.username if assignment.user else None,
            'placeholder_type': assignment.placeholder_type or None,
            'response_status': assignment.response_status,
            'decline_reason': assignment.decline_reason or '',
            'application_enabled': assignment.application_enabled,
        }
        if assignment.role == MatchAssignment.Role.REFEREE:
            referees.append(assignment_data)
        elif assignment.role == MatchAssignment.Role.RESERVE:
            reserves.append(assignment_data)
        elif assignment.role == MatchAssignment.Role.INSPECTOR:
            inspectors.append(assignment_data)
        elif assignment.role == MatchAssignment.Role.TOURNAMENT_DIRECTOR:
            tournament_directors.append(assignment_data)

    # Get site-level application settings
    from accounts.models import SiteSettings
    site_settings = SiteSettings.get_settings()

    # Get phase settings for pre-populating slots
    # Application toggles are controlled by site-level settings only
    # Per-position toggle (application_enabled field) controls individual positions
    phase_settings = {
        'referee_count': match.phase.referee_count if match.phase else 2,
        'reserve_count': match.phase.reserve_count if match.phase else 0,
        'inspector_count': match.phase.inspector_count if match.phase else 0,
        'tournament_director_count': match.phase.tournament_director_count if match.phase else 0,
        # Application settings: only site-level settings control toggle clickability
        # Per-position toggle controls which specific positions are open for applications
        'referee_application_enabled': site_settings.application_referees_enabled,
        'inspector_application_enabled': site_settings.application_inspectors_enabled,
        'tournament_director_application_enabled': site_settings.application_tournament_directors_enabled,
    }

    # Get applicants for this match, categorized by role
    applications = MatchApplication.objects.filter(
        match=match,
        status=MatchApplication.Status.PENDING
    ).values('user_id', 'role')

    applicants_by_role = {
        'referee': [],
        'inspector': [],
        'tournament_director': [],
    }
    for app in applications:
        role = app['role']
        if role in applicants_by_role:
            applicants_by_role[role].append(app['user_id'])

    # Also provide flat list for backwards compatibility
    applicants = list(set(app['user_id'] for app in applications))

    return JsonResponse({
        'id': match.id,
        'date': match.date.isoformat() if match.date else None,
        'time': match.time.strftime('%H:%M') if match.time else None,
        'venue_id': match.venue_id,
        'venue_name': str(match.venue) if match.venue else None,
        'court': match.court,
        'home_team_id': match.home_team_id,
        'home_team_name': str(match.home_team) if match.home_team else None,
        'home_team_is_tbd': match.home_team.is_tbd if match.home_team else False,
        'away_team_id': match.away_team_id,
        'away_team_name': str(match.away_team) if match.away_team else None,
        'away_team_is_tbd': match.away_team.is_tbd if match.away_team else False,
        'phase_id': match.phase_id,
        'phase_name': str(match.phase) if match.phase else None,
        'competition_color': match.phase.competition.color if match.phase else '#6366f1',
        'phase_settings': phase_settings,
        'status': match.status,
        'notes': match.notes,
        'is_hidden': match.is_hidden,
        'is_assignment_published': match.is_assignment_published,
        'is_tournament': match.is_tournament,
        'tournament_match_count': match.tournament_match_count,
        'tournament_court_count': match.tournament_court_count,
        'mfsz_declaration_override': match.mfsz_declaration_override,
        'referees': referees,
        'reserves': reserves,
        'inspectors': inspectors,
        'tournament_directors': tournament_directors,
        'applicants': applicants,
        'applicants_by_role': applicants_by_role,
    })


@login_required
@require_POST
def api_update_match(request, match_id):
    """API: Update match details."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from .models import Team, Venue, CompetitionPhase

    match = get_object_or_404(Match.objects.filter(is_deleted=False), id=match_id)

    try:
        from datetime import datetime
        data = json.loads(request.body)

        # Track changes for logging
        changes = {}
        old_values = {
            'date': str(match.date) if match.date else None,
            'time': str(match.time) if match.time else None,
            'venue': match.venue.name if match.venue else None,
            'home_team': str(match.home_team) if match.home_team else None,
            'away_team': str(match.away_team) if match.away_team else None,
            'court': match.court,
            'notes': match.notes,
            'is_tournament': match.is_tournament,
            'tournament_match_count': match.tournament_match_count,
            'tournament_court_count': match.tournament_court_count,
            'mfsz_declaration_override': match.mfsz_declaration_override,
        }

        # Update basic fields - convert strings to proper types
        if 'date' in data:
            date_str = data['date']
            if date_str:
                match.date = datetime.strptime(date_str, '%Y-%m-%d').date()
            else:
                match.date = None

        if 'time' in data:
            time_str = data['time']
            if time_str:
                match.time = datetime.strptime(time_str, '%H:%M').time()
            else:
                match.time = None

        if 'court' in data:
            match.court = data['court'] or ''
        if 'notes' in data:
            match.notes = data['notes'] or ''

        # Update foreign keys - handle empty strings and None
        if 'venue_id' in data:
            venue_id = data['venue_id']
            match.venue = Venue.objects.get(id=int(venue_id)) if venue_id and venue_id != '' else None
        if 'home_team_id' in data:
            team_id = data['home_team_id']
            match.home_team = Team.objects.get(id=int(team_id)) if team_id and team_id != '' else None
        if 'away_team_id' in data:
            team_id = data['away_team_id']
            match.away_team = Team.objects.get(id=int(team_id)) if team_id and team_id != '' else None
        if 'phase_id' in data:
            phase_id = data['phase_id']
            match.phase = CompetitionPhase.objects.get(id=int(phase_id)) if phase_id and phase_id != '' else None

        # Tournament fields
        if 'is_tournament' in data:
            match.is_tournament = bool(data['is_tournament'])
            # If switching to tournament, clear away_team
            if match.is_tournament:
                match.away_team = None

        if 'tournament_match_count' in data:
            try:
                count = int(data['tournament_match_count']) if data['tournament_match_count'] else 1
                match.tournament_match_count = max(1, count)
            except (ValueError, TypeError):
                match.tournament_match_count = 1

        if 'tournament_court_count' in data:
            try:
                count = int(data['tournament_court_count']) if data['tournament_court_count'] else 1
                match.tournament_court_count = max(1, count)
            except (ValueError, TypeError):
                match.tournament_court_count = 1

        # MFSZ declaration override
        if 'mfsz_declaration_override' in data:
            value = data['mfsz_declaration_override']
            if value is None or value == '' or value == 'null':
                match.mfsz_declaration_override = None
            elif value == True or value == 'true':
                match.mfsz_declaration_override = True
            elif value == False or value == 'false':
                match.mfsz_declaration_override = False

        match.save()

        # Build changes dict for logging
        new_values = {
            'date': str(match.date) if match.date else None,
            'time': str(match.time) if match.time else None,
            'venue': match.venue.name if match.venue else None,
            'home_team': str(match.home_team) if match.home_team else None,
            'away_team': str(match.away_team) if match.away_team else None,
            'court': match.court,
            'notes': match.notes,
            'is_tournament': match.is_tournament,
            'tournament_match_count': match.tournament_match_count,
            'tournament_court_count': match.tournament_court_count,
            'mfsz_declaration_override': match.mfsz_declaration_override,
        }

        for key in old_values:
            if old_values[key] != new_values[key]:
                changes[key] = {'from': old_values[key], 'to': new_values[key]}

        # Audit log
        if changes:
            changed_fields = ", ".join(changes.keys())
            log_action(
                request,
                'match',
                'update',
                f"Mérkőzés adatai módosítva: {changed_fields}",
                obj=match,
                changes=changes
            )

        # Send email notifications if requested and match is published
        send_email = data.get('send_email', False)
        if send_email and changes and match.is_assignment_published and match.status in [Match.Status.SCHEDULED, Match.Status.CONFIRMED]:
            from core.email_utils import send_match_assignment_notification
            import logging
            logger = logging.getLogger(__name__)

            # Refresh match with related objects
            match = Match.objects.select_related('home_team', 'away_team', 'venue', 'phase', 'phase__competition').get(id=match_id)

            # Get all current assignments
            assignments = MatchAssignment.objects.filter(match=match).select_related('user')

            # Log what changes happened
            changed_keys = list(changes.keys())
            logger.info(f"[MATCH UPDATE EMAIL] Match {match_id} changed: {changed_keys}")

            for assignment in assignments:
                if assignment.user and assignment.user.email:
                    logger.info(f"[MATCH UPDATE EMAIL] Sending modified notification to {assignment.user.email}")
                    try:
                        result = send_match_assignment_notification(assignment, notify_type='modified', changes=changed_keys)
                        logger.info(f"[MATCH UPDATE EMAIL] Email result: {result}")
                    except Exception as e:
                        logger.error(f"[MATCH UPDATE EMAIL] Email error for {assignment.user.email}: {e}")

        return JsonResponse({'success': True})
    except Exception as e:
        import traceback
        traceback.print_exc()  # Print full traceback to console for debugging
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_POST
def api_update_match_assignments(request, match_id):
    """API: Update match assignments."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    match = get_object_or_404(Match.objects.filter(is_deleted=False), id=match_id)

    # Valid placeholder types
    PLACEHOLDER_TYPES = ['hianyzik', 'szukseges', 'nincs']

    try:
        data = json.loads(request.body)

        # Track existing assigned users for notification logic
        # Use original_assigned_user_ids from frontend if provided (captures state when sidebar opened)
        # This is important because auto-save may have created assignments before user clicks save
        original_from_request = data.get('original_assigned_user_ids', None)
        if original_from_request is not None:
            existing_assigned_user_ids = set(int(uid) for uid in original_from_request if uid)
        else:
            # Fallback: query database (used by auto-save, but auto-save skips notifications anyway)
            existing_assigned_user_ids = set(
                match.assignments.filter(user__isnull=False)
                .exclude(response_status=MatchAssignment.ResponseStatus.DECLINED)
                .values_list('user_id', flat=True)
            )

        # Check if frontend reported match details changed (venue, time, teams)
        has_match_details_changed = data.get('has_match_details_changed', False)

        # Track newly assigned users during this update
        newly_assigned_user_ids = set()

        # Capture original assignment state for change detection (including placeholders)
        # This is used to detect if ANY assignment configuration changed, not just user changes
        original_assignment_snapshot = set()
        for a in match.assignments.all():
            if a.user_id:
                original_assignment_snapshot.add(f"user_{a.user_id}_{a.role}")
            elif a.placeholder_type:
                original_assignment_snapshot.add(f"placeholder_{a.placeholder_type}_{a.role}_{a.id}")

        # Keep track of ALL existing assignments by status
        declined_assignments = {
            (a.user_id, a.role): a
            for a in match.assignments.filter(response_status=MatchAssignment.ResponseStatus.DECLINED)
            if a.user_id
        }

        accepted_assignments = {
            (a.user_id, a.role): a
            for a in match.assignments.filter(response_status=MatchAssignment.ResponseStatus.ACCEPTED)
            if a.user_id
        }

        pending_assignments = {
            (a.user_id, a.role): a
            for a in match.assignments.filter(response_status=MatchAssignment.ResponseStatus.PENDING)
            if a.user_id
        }

        # Keep track of placeholder assignments as lists by role (to handle multiple of same type)
        placeholder_assignments_by_role = {}
        for a in match.assignments.filter(user__isnull=True):
            if a.placeholder_type:
                if a.role not in placeholder_assignments_by_role:
                    placeholder_assignments_by_role[a.role] = []
                placeholder_assignments_by_role[a.role].append(a)

        # Track which assignments we're keeping/updating
        kept_declined = set()
        kept_accepted = set()
        kept_pending = set()
        kept_placeholder_ids = set()

        # Helper to process assignment
        def process_assignment(item, role, order):
            # Support both old format (simple value) and new format (object with value and application_enabled)
            if isinstance(item, dict):
                value = item.get('value', '')
                application_enabled = item.get('application_enabled', False)
                pre_accepted = item.get('pre_accepted', False)
            else:
                value = item
                application_enabled = False
                pre_accepted = False

            if not value:
                return

            # Check if it's a placeholder type
            if value in PLACEHOLDER_TYPES:
                # Check if there's a declined assignment for this role
                declined_for_role = [
                    (k, a) for k, a in declined_assignments.items()
                    if k[1] == role and k not in kept_declined
                ]
                if declined_for_role and value == 'hianyzik':
                    # Keep the first declined assignment and update its placeholder_type
                    key, assignment = declined_for_role[0]
                    assignment.placeholder_type = value
                    assignment.save()
                    kept_declined.add(key)
                else:
                    # Check if there's an existing placeholder of this type we can reuse
                    existing_placeholders = placeholder_assignments_by_role.get(role, [])
                    reusable = None
                    for p in existing_placeholders:
                        if p.id not in kept_placeholder_ids and p.placeholder_type == value:
                            reusable = p
                            break

                    if reusable:
                        # Reuse existing placeholder, update application_enabled if needed
                        kept_placeholder_ids.add(reusable.id)
                        if reusable.application_enabled != application_enabled:
                            reusable.application_enabled = application_enabled
                            reusable.save(update_fields=['application_enabled'])
                    else:
                        # Create new placeholder
                        MatchAssignment.objects.create(
                            match=match,
                            user=None,
                            placeholder_type=value,
                            role=role,
                            application_enabled=application_enabled if value == 'szukseges' else False
                        )
            else:
                # It's a user ID
                try:
                    user_id = int(value)
                    key = (user_id, role)

                    # Check if this user was declined - if so, reset their status
                    if key in declined_assignments and key not in kept_declined:
                        # Re-assign the same user who declined - reset to pending
                        assignment = declined_assignments[key]
                        assignment.response_status = MatchAssignment.ResponseStatus.PENDING
                        assignment.placeholder_type = ''
                        assignment.response_date = None
                        assignment.decline_reason = ''
                        assignment.save()
                        kept_declined.add(key)
                        # Track as newly assigned (they declined before, so treat as new)
                        newly_assigned_user_ids.add(user_id)
                    # Check if this user already accepted - preserve their status
                    elif key in accepted_assignments and key not in kept_accepted:
                        # Keep the accepted assignment as is
                        kept_accepted.add(key)
                    # Check if this user already has a pending assignment - keep it
                    elif key in pending_assignments and key not in kept_pending:
                        # Assignment already exists with same user and role - keep it
                        kept_pending.add(key)
                        # If pre-accepted, update status to ACCEPTED
                        if pre_accepted:
                            assignment = pending_assignments[key]
                            assignment.response_status = MatchAssignment.ResponseStatus.ACCEPTED
                            assignment.response_date = timezone.now()
                            assignment.save()
                        # Track as newly assigned if they weren't in the original state
                        # (This handles the case where auto-save created the assignment)
                        if user_id not in existing_assigned_user_ids:
                            newly_assigned_user_ids.add(user_id)
                    else:
                        # Create new assignment
                        new_assignment = MatchAssignment.objects.create(
                            match=match,
                            user_id=user_id,
                            placeholder_type='',
                            role=role
                        )
                        # If pre-accepted, set response_status to ACCEPTED
                        if pre_accepted:
                            new_assignment.response_status = MatchAssignment.ResponseStatus.ACCEPTED
                            new_assignment.response_date = timezone.now()
                            new_assignment.save()
                        # Track as newly assigned (if not previously assigned)
                        if user_id not in existing_assigned_user_ids:
                            newly_assigned_user_ids.add(user_id)
                except (ValueError, TypeError):
                    pass  # Invalid value, skip

        # Process referees
        for idx, value in enumerate(data.get('referees', [])):
            process_assignment(value, MatchAssignment.Role.REFEREE, idx)

        # Process inspectors
        for idx, value in enumerate(data.get('inspectors', [])):
            process_assignment(value, MatchAssignment.Role.INSPECTOR, idx)

        # Process reserves
        for idx, value in enumerate(data.get('reserves', [])):
            process_assignment(value, MatchAssignment.Role.RESERVE, idx)

        # Process tournament directors
        for idx, value in enumerate(data.get('tournament_directors', [])):
            process_assignment(value, MatchAssignment.Role.TOURNAMENT_DIRECTOR, idx)

        # For declined assignments that weren't kept: clear placeholder_type instead of deleting
        # This preserves the assignment record so the X icon persists in dropdown
        for key, assignment in declined_assignments.items():
            if key not in kept_declined:
                if assignment.placeholder_type:
                    assignment.placeholder_type = ''
                    assignment.save()

        for key, assignment in accepted_assignments.items():
            if key not in kept_accepted:
                assignment.delete()

        for key, assignment in pending_assignments.items():
            if key not in kept_pending:
                assignment.delete()

        # Delete unused placeholder assignments
        for role, placeholders in placeholder_assignments_by_role.items():
            for assignment in placeholders:
                if assignment.id not in kept_placeholder_ids:
                    assignment.delete()

        # Refresh match from database to get latest assignment data (avoids ORM cache issues)
        match = Match.objects.get(pk=match_id)

        # Capture new assignment state and compare to detect ANY configuration change
        new_assignment_snapshot = set()
        for a in match.assignments.all():
            if a.user_id:
                new_assignment_snapshot.add(f"user_{a.user_id}_{a.role}")
            elif a.placeholder_type:
                new_assignment_snapshot.add(f"placeholder_{a.placeholder_type}_{a.role}_{a.id}")

        # Detect if assignment configuration changed (including placeholder additions/removals)
        has_assignment_config_changed = original_assignment_snapshot != new_assignment_snapshot

        # Update match status based on confirmation state
        if match.status == Match.Status.SCHEDULED and match.is_all_confirmed:
            # Upgrade to confirmed when all are accepted
            match.status = Match.Status.CONFIRMED
            match.save()
        elif match.status == Match.Status.CONFIRMED and not match.is_all_confirmed:
            # Downgrade back to scheduled if new pending assignment was added
            match.status = Match.Status.SCHEDULED
            match.save()

        # Send notifications when saving a published match
        # skip_notifications: Used by auto-save to avoid duplicate notifications
        # no_notification: Super admin option to skip ALL notifications (internal + email)
        # Internal notifications: Sent when explicitly saving (not auto-save)
        # Email notifications: Only when send_email=True
        skip_notifications = data.get('skip_notifications', False)
        no_notification = data.get('no_notification', False)
        send_email = data.get('send_email', False)

        # If no_notification is True, skip all notifications entirely
        if no_notification:
            skip_notifications = True
            send_email = False

        # Initialize removed_user_ids for logging (calculated below if notifications are sent)
        removed_user_ids = set()

        # DEBUG: Log notification conditions
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[NOTIF DEBUG] skip_notifications={skip_notifications}, is_published={match.is_assignment_published}, status={match.status}")
        logger.info(f"[NOTIF DEBUG] send_email={send_email}, has_match_details_changed={has_match_details_changed}")
        logger.info(f"[NOTIF DEBUG] existing_assigned_user_ids={existing_assigned_user_ids}")
        logger.info(f"[NOTIF DEBUG] newly_assigned_user_ids={newly_assigned_user_ids}")

        if not skip_notifications and match.is_assignment_published and match.status in [Match.Status.SCHEDULED, Match.Status.CONFIRMED]:
            from documents.models import Notification
            from core.email_utils import send_match_assignment_notification

            # Refresh match with related objects
            match = Match.objects.select_related('home_team', 'away_team', 'venue', 'phase__competition').get(pk=match_id)

            # Get current assigned user IDs (non-declined, non-placeholder)
            current_assigned_user_ids = set(
                a.user_id
                for a in match.assignments.filter(user__isnull=False)
                .exclude(response_status=MatchAssignment.ResponseStatus.DECLINED)
                if not a.placeholder_type
            )

            # Calculate changes based on original state from frontend
            # existing_assigned_user_ids = who was assigned when sidebar opened
            # current_assigned_user_ids = who is assigned now after save
            removed_user_ids = existing_assigned_user_ids - current_assigned_user_ids
            # Note: newly_assigned_user_ids is already tracked during processing

            # DEBUG: Log the calculated changes
            logger.info(f"[NOTIF DEBUG] current_assigned_user_ids={current_assigned_user_ids}")
            logger.info(f"[NOTIF DEBUG] removed_user_ids={removed_user_ids}")

            # Determine if any personnel change happened
            has_personnel_changed = bool(newly_assigned_user_ids) or bool(removed_user_ids)

            # Substantive change = match details changed OR personnel changed OR assignment configuration changed
            # has_assignment_config_changed includes adding/removing placeholder slots
            has_substantive_change = has_match_details_changed or has_personnel_changed or has_assignment_config_changed
            logger.info(f"[NOTIF DEBUG] has_personnel_changed={has_personnel_changed}, has_assignment_config_changed={has_assignment_config_changed}, has_substantive_change={has_substantive_change}")

            # Build notification message for internal notifications
            date_str = match.date.strftime('%Y.%m.%d (%A)') if match.date else 'Nincs dátum'
            time_str = match.time.strftime('%H:%M') if match.time else ''
            teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"
            venue = match.venue.name if match.venue else 'Nincs helyszín'
            message = f"{date_str} {time_str}\n{teams}\n{venue}"
            match_link = f"/matches/{match.id}/"

            def send_notification(user, title, notif_type, assignment=None, email_notify_type=None):
                """Helper to send internal notification and optionally HTML email"""
                logger.info(f"[EMAIL DEBUG] send_notification called: user={user.email}, send_email={send_email}, assignment={assignment}, email_notify_type={email_notify_type}")
                Notification.objects.create(
                    recipient=user,
                    title=title,
                    message=message,
                    notification_type=notif_type,
                    link=match_link
                )
                # Send HTML templated email if enabled and assignment provided
                if send_email and user.email and assignment and email_notify_type:
                    logger.info(f"[EMAIL DEBUG] Sending HTML email to {user.email}, type={email_notify_type}")
                    try:
                        result = send_match_assignment_notification(
                            assignment,
                            notify_type=email_notify_type,
                            new_user_ids=newly_assigned_user_ids if email_notify_type == 'modified' else None
                        )
                        logger.info(f"[EMAIL DEBUG] Email send result: {result}")
                    except Exception as e:
                        logger.error(f"[EMAIL DEBUG] Email send FAILED: {e}", exc_info=True)
                else:
                    logger.info(f"[EMAIL DEBUG] Skipping email: send_email={send_email}, user.email={user.email}, assignment={assignment is not None}, email_notify_type={email_notify_type}")

            # 1. Send "Töröltek a kiírásból" to removed users
            logger.info(f"[EMAIL DEBUG] Removed user IDs: {removed_user_ids}")
            if removed_user_ids:
                # Get the removed assignments (they might have been deleted or user changed)
                # We need to create temporary assignment objects for email context
                removed_users = User.objects.filter(id__in=removed_user_ids)
                for user in removed_users:
                    logger.info(f"[EMAIL DEBUG] Processing removed user: {user.email}")
                    # Create internal notification
                    Notification.objects.create(
                        recipient=user,
                        title="Töröltek a kiírásból",
                        message=message,
                        notification_type=Notification.Type.WARNING,
                        link=match_link
                    )
                    # For removed users, we need to create a temporary assignment-like object for email
                    if send_email and user.email:
                        logger.info(f"[EMAIL DEBUG] Sending 'removed' email to {user.email}")
                        try:
                            # Create a temporary assignment for the email template
                            temp_assignment = MatchAssignment(
                                match=match,
                                user=user,
                                role=MatchAssignment.Role.REFEREE  # Default role for removed notification
                            )
                            result = send_match_assignment_notification(temp_assignment, notify_type='removed')
                            logger.info(f"[EMAIL DEBUG] Removed email result: {result}")
                        except Exception as e:
                            logger.error(f"[EMAIL DEBUG] Removed email FAILED: {e}", exc_info=True)

            # 2. Send notifications to current assignees
            assignments = match.assignments.filter(
                user__isnull=False
            ).exclude(
                response_status=MatchAssignment.ResponseStatus.DECLINED
            ).select_related('user')

            for assignment in assignments:
                logger.info(f"[NOTIF DEBUG] Processing assignment: user_id={assignment.user_id}, in_newly={assignment.user_id in newly_assigned_user_ids}, in_existing={assignment.user_id in existing_assigned_user_ids}")
                if assignment.user_id in newly_assigned_user_ids:
                    # New assignment: ALWAYS send notification
                    logger.info(f"[NOTIF DEBUG] -> Sending NEW notification to {assignment.user.email}")
                    send_notification(assignment.user, "Új mérkőzésre lettél kiírva", Notification.Type.MATCH, assignment, 'new')
                elif has_substantive_change and assignment.user_id in existing_assigned_user_ids:
                    # Existing user and something changed: send "changed" notification
                    logger.info(f"[NOTIF DEBUG] -> Sending MODIFIED notification to {assignment.user.email}")
                    send_notification(assignment.user, "Megváltozott a kiírás", Notification.Type.WARNING, assignment, 'modified')
                else:
                    logger.info(f"[NOTIF DEBUG] -> No notification for user_id={assignment.user_id} (has_substantive_change={has_substantive_change})")

        # Audit log - track ALL changes with full details
        # Get current assignment info for logging
        current_assignments = match.assignments.filter(user__isnull=False).select_related('user')
        assigned_users_info = []
        email_list = []
        for a in current_assignments:
            user_info = f"{a.user.get_full_name()} ({a.get_role_display()})"
            assigned_users_info.append(user_info)
            if a.user.email:
                email_list.append(a.user.email)

        # Build log message based on action type
        if no_notification:
            # Super admin saved without any notifications
            log_description = f"Mérkőzés játékvezetői módosítva (értesítés nélkül - super admin)"
        elif skip_notifications:
            # Auto-save (no notifications sent)
            log_description = f"Mérkőzés játékvezetői módosítva (auto-mentés)"
        elif not match.is_assignment_published:
            # Draft save - match not published yet
            log_description = f"Mérkőzés játékvezetői módosítva - piszkozatként elmentve"
        elif send_email and email_list:
            # Published match with email
            emails_str = " + ".join(email_list)
            log_description = f"Mérkőzés játékvezetői publikálva ÉS email küldve -> {emails_str}"
        elif match.is_assignment_published:
            # Published match without email
            log_description = f"Mérkőzés játékvezetői publikálva (email nélkül)"
        else:
            log_description = f"Mérkőzés játékvezetői módosítva"

        # Log details
        log_extra = {
            'match_id': match.id,
            'match_date': str(match.date) if match.date else None,
            'match_time': str(match.time) if match.time else None,
            'is_published': match.is_assignment_published,
            'send_email': send_email,
            'skip_notifications': skip_notifications,
            'assigned_users': assigned_users_info,
            'emails_sent_to': email_list if send_email else [],
            'newly_assigned_user_ids': list(newly_assigned_user_ids),
            'removed_user_ids': list(removed_user_ids),
        }

        log_action(
            request,
            'assignment',
            'update',
            log_description,
            obj=match,
            extra=log_extra
        )

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_POST
def api_publish_match(request, match_id):
    """API: Publish match (change status to scheduled)."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    match = get_object_or_404(
        Match.objects.filter(is_deleted=False).select_related('home_team', 'away_team', 'venue'),
        id=match_id
    )

    if not match.assignments.exists():
        return JsonResponse({'error': 'Legalább egy játékvezetőt ki kell jelölni!'}, status=400)

    # Check if we should send emails and/or skip all notifications
    try:
        data = json.loads(request.body)
        send_email = data.get('send_email', False)
        no_notification = data.get('no_notification', False)
    except (json.JSONDecodeError, ValueError):
        send_email = False
        no_notification = False

    match.status = Match.Status.SCHEDULED
    match.is_assignment_published = True  # Automatikusan láthatóvá teszi a kiírást
    match.save()

    # If no_notification is True (super admin), skip ALL notifications
    # Otherwise: Always send internal notifications to ALL assigned users when publishing
    # Email notifications only when send_email=True
    from documents.models import Notification
    from core.email_utils import send_match_assignment_notification

    # Refresh match with related objects for email template
    match = Match.objects.select_related('home_team', 'away_team', 'venue', 'phase__competition').get(pk=match_id)
    assignments = match.assignments.filter(user__isnull=False).select_related('user')

    if assignments.exists() and not no_notification:
        date_str = match.date.strftime('%Y.%m.%d (%A)') if match.date else 'Nincs dátum'
        time_str = match.time.strftime('%H:%M') if match.time else ''
        teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"
        venue = match.venue.name if match.venue else 'Nincs helyszín'
        message = f"{date_str} {time_str}\n{teams}\n{venue}"
        title = "Új mérkőzésre lettél kiírva"

        match_link = f"/matches/{match.id}/"
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[PUBLISH EMAIL DEBUG] send_email={send_email}, no_notification={no_notification}, assignments count={assignments.count()}")

        for assignment in assignments:
            logger.info(f"[PUBLISH EMAIL DEBUG] Processing assignment: user={assignment.user.email}")
            # Always create internal notification
            Notification.objects.create(
                recipient=assignment.user,
                title=title,
                message=message,
                notification_type=Notification.Type.MATCH,
                link=match_link
            )

            # Send HTML templated email if send_email=True and user has email
            if send_email and assignment.user.email:
                logger.info(f"[PUBLISH EMAIL DEBUG] Sending email to {assignment.user.email}")
                try:
                    result = send_match_assignment_notification(assignment, notify_type='new')
                    logger.info(f"[PUBLISH EMAIL DEBUG] Email result: {result}")
                except Exception as e:
                    logger.error(f"[PUBLISH EMAIL DEBUG] Email FAILED: {e}", exc_info=True)
            else:
                logger.info(f"[PUBLISH EMAIL DEBUG] Skipping email: send_email={send_email}, user.email={assignment.user.email}")

    # Audit log - track publish action with full details
    assigned_users_info = []
    email_list = []
    for a in assignments:
        user_info = f"{a.user.get_full_name()} ({a.get_role_display()})"
        assigned_users_info.append(user_info)
        if a.user.email:
            email_list.append(a.user.email)

    if no_notification:
        log_description = f"Mérkőzés publikálva (értesítés nélkül - super admin)"
    elif send_email and email_list:
        emails_str = " + ".join(email_list)
        log_description = f"Mérkőzés publikálva ÉS email küldve -> {emails_str}"
    else:
        log_description = f"Mérkőzés publikálva (email nélkül)"

    log_action(
        request,
        'assignment',
        'publish',
        log_description,
        obj=match,
        extra={
            'match_id': match.id,
            'match_date': str(match.date) if match.date else None,
            'match_time': str(match.time) if match.time else None,
            'send_email': send_email,
            'no_notification': no_notification,
            'assigned_users': assigned_users_info,
            'emails_sent_to': email_list if (send_email and not no_notification) else [],
        }
    )

    return JsonResponse({'success': True, 'status': match.status})


@login_required
@require_POST
def api_delete_match(request, match_id):
    """API: Soft delete a match (hide but keep in database)."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    match = get_object_or_404(Match.objects.filter(is_deleted=False), id=match_id)

    # Store match info for logging before soft delete
    match_repr = str(match)

    # Soft delete - mark as deleted but keep in database
    match.is_deleted = True
    match.deleted_at = timezone.now()
    match.save()

    # Audit log
    log_action(
        request,
        'match',
        'delete',
        f"Mérkőzés törölve (soft delete): {match_repr}",
        obj=match,
        extra={
            'match_id': match.id,
            'match_date': str(match.date) if match.date else None,
        }
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_accept_assignment(request, assignment_id):
    """API: Accept assignment on behalf of referee (coordinator only)."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    assignment = get_object_or_404(MatchAssignment, id=assignment_id)
    old_status = assignment.response_status
    assignment.response_status = MatchAssignment.ResponseStatus.ACCEPTED
    assignment.response_date = timezone.now()
    assignment.save()

    # Check if all referees confirmed
    match = assignment.match
    if match.is_all_confirmed and match.status == Match.Status.SCHEDULED:
        match.status = Match.Status.CONFIRMED
        match.save()

    # Audit log
    referee_name = assignment.user.get_full_name() if assignment.user else 'Ismeretlen'
    log_action(
        request,
        'assignment',
        'accept',
        f"Kiírás elfogadva (koordinátor által): {referee_name} - {match}",
        obj=match,
        extra={
            'assignment_id': assignment.id,
            'referee_id': assignment.user_id,
            'referee_name': referee_name,
            'old_status': old_status,
            'new_status': assignment.response_status,
            'accepted_by_coordinator': True
        }
    )

    return JsonResponse({
        'success': True,
        'response_status': assignment.response_status,
        'match_status': match.status
    })


@login_required
@require_POST
def api_reset_assignment(request, assignment_id):
    """API: Reset assignment status back to pending (coordinator only)."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    assignment = get_object_or_404(MatchAssignment, id=assignment_id)
    old_status = assignment.response_status
    assignment.response_status = MatchAssignment.ResponseStatus.PENDING
    assignment.response_date = None
    assignment.decline_reason = ''
    assignment.save()

    # Update match status back to scheduled if it was confirmed
    match = assignment.match
    if match.status == Match.Status.CONFIRMED:
        match.status = Match.Status.SCHEDULED
        match.save()

    # Audit log
    referee_name = assignment.user.get_full_name() if assignment.user else 'Ismeretlen'
    log_action(
        request,
        'assignment',
        'update',
        f"Kiírás visszaállítva függőre (koordinátor által): {referee_name} - {match}",
        obj=match,
        extra={
            'assignment_id': assignment.id,
            'referee_id': assignment.user_id,
            'referee_name': referee_name,
            'old_status': old_status,
            'new_status': assignment.response_status,
            'reset_by_coordinator': True
        }
    )

    return JsonResponse({
        'success': True,
        'response_status': assignment.response_status,
        'match_status': match.status
    })


@login_required
def api_get_referees(request):
    """API: Get list of available referees (only users who are referees by role or flag)."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Get optional match_id for application info
    match_id = request.GET.get('match_id')

    # Only return users who are referees (by role or by flag)
    # Exclude deleted users and hidden users
    users = User.objects.filter(
        Q(role=User.Role.REFEREE) | Q(is_referee_flag=True),
        is_deleted=False,
        is_hidden_from_colleagues=False
    ).order_by('last_name', 'first_name')

    # Get applications for this match if match_id is provided
    applied_user_ids = set()
    if match_id:
        applied_user_ids = set(
            MatchApplication.objects.filter(
                match_id=match_id,
                status=MatchApplication.Status.PENDING
            ).values_list('user_id', flat=True)
        )

    return JsonResponse({
        'referees': [
            {
                'id': user.id,
                'name': user.get_full_name() or user.username,
                'has_applied': user.id in applied_user_ids,
            }
            for user in users
        ]
    })


@login_required
def api_get_users_by_position(request):
    """API: Get list of available users by position type."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    position = request.GET.get('position', 'referee')
    match_id = request.GET.get('match_id')

    # Build query based on position type
    if position == 'referee':
        users = User.objects.filter(
            Q(role=User.Role.REFEREE) | Q(is_referee_flag=True),
            is_deleted=False,
            is_hidden_from_colleagues=False
        )
    elif position == 'inspector':
        users = User.objects.filter(
            Q(role=User.Role.INSPECTOR) | Q(is_inspector_flag=True),
            is_deleted=False,
            is_hidden_from_colleagues=False
        )
    elif position == 'tournament_director':
        users = User.objects.filter(
            Q(role=User.Role.TOURNAMENT_DIRECTOR) | Q(is_tournament_director_flag=True),
            is_deleted=False,
            is_hidden_from_colleagues=False
        )
    else:
        return JsonResponse({'users': []})

    users = users.order_by('last_name', 'first_name')

    # Get applications for this match if match_id is provided
    applied_user_ids = set()
    if match_id:
        applied_user_ids = set(
            MatchApplication.objects.filter(
                match_id=match_id,
                status=MatchApplication.Status.PENDING,
                role=position
            ).values_list('user_id', flat=True)
        )

    return JsonResponse({
        'users': [
            {
                'id': user.id,
                'name': user.get_full_name() or user.username,
                'has_applied': user.id in applied_user_ids,
            }
            for user in users
        ]
    })


# ==================== CLUBS & TEAMS ====================

@login_required
def clubs_list(request):
    """Admin: List all clubs with their teams."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from django.db.models import Prefetch, Min

    show_inactive = request.GET.get('show_inactive') == '1'

    # Order competitions by their order field
    competitions_qs = Competition.objects.filter(is_deleted=False).order_by('order', 'name')

    # Teams ordered by their first competition's order, then by name
    # Filter out deleted and archived teams
    teams_qs = Team.objects.filter(is_deleted=False, is_archived=False).prefetch_related(
        Prefetch('competitions', queryset=competitions_qs)
    ).annotate(
        first_comp_order=Min('competitions__order')
    ).order_by('first_comp_order', 'custom_name')

    # Filter out deleted and archived clubs
    clubs = Club.objects.filter(is_deleted=False, is_archived=False).prefetch_related(
        Prefetch('teams', queryset=teams_qs)
    ).order_by('name')

    if not show_inactive:
        clubs = clubs.filter(is_active=True)

    context = {
        'clubs': clubs,
        'show_inactive': show_inactive,
        'total_clubs': Club.objects.filter(is_deleted=False, is_archived=False).count(),
        'active_clubs': Club.objects.filter(is_deleted=False, is_archived=False, is_active=True).count(),
        'total_teams': Team.objects.filter(is_deleted=False, is_archived=False).count(),
        'active_teams': Team.objects.filter(is_deleted=False, is_archived=False, is_active=True).count(),
    }
    return render(request, 'matches/clubs_list.html', context)


@login_required
def club_edit(request, club_id=None):
    """Admin: Create or edit a club."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import ClubContact

    club = None
    if club_id:
        club = get_object_or_404(Club, id=club_id, is_deleted=False)

    if request.method == 'POST':
        # Basic fields
        name = request.POST.get('name', '').strip()
        short_name = request.POST.get('short_name', '').strip()

        # Address fields
        country = request.POST.get('country', '').strip()
        city = request.POST.get('city', '').strip()
        postal_code = request.POST.get('postal_code', '').strip()
        address = request.POST.get('address', '').strip()

        # Representative fields
        representative_name = request.POST.get('representative_name', '').strip()
        representative_phone = request.POST.get('representative_phone', '').strip()
        representative_email = request.POST.get('representative_email', '').strip()

        # Contact fields
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        website = request.POST.get('website', '').strip()
        facebook = request.POST.get('facebook', '').strip()

        if name:
            if club:
                club.name = name
                club.short_name = short_name
                # is_active is managed via archive page, not here
                club.country = country
                club.city = city
                club.postal_code = postal_code
                club.address = address
                club.representative_name = representative_name
                club.representative_phone = representative_phone
                club.representative_email = representative_email
                club.email = email
                club.phone = phone
                club.website = website
                club.facebook = facebook
                if 'logo' in request.FILES:
                    club.logo = request.FILES['logo']
                club.save()

                # Handle additional contacts
                # Delete removed contacts
                deleted_contacts = request.POST.get('deleted_contacts', '')
                if deleted_contacts:
                    for contact_id in deleted_contacts.split(','):
                        if contact_id:
                            ClubContact.objects.filter(id=contact_id, club=club).delete()

                # Update existing contacts
                existing_contacts = request.POST.get('existing_contacts', '')
                if existing_contacts:
                    for contact_id in existing_contacts.split(','):
                        if contact_id:
                            try:
                                contact = ClubContact.objects.get(id=contact_id, club=club)
                                contact.contact_type = request.POST.get(f'contact_type_{contact_id}', 'email')
                                contact.label = request.POST.get(f'contact_label_{contact_id}', '').strip()
                                contact.value = request.POST.get(f'contact_value_{contact_id}', '').strip()
                                if contact.value:
                                    contact.save()
                            except ClubContact.DoesNotExist:
                                pass

                # Create new contacts
                new_contacts = request.POST.get('new_contacts', '')
                if new_contacts:
                    for new_id in new_contacts.split(','):
                        if new_id:
                            contact_type = request.POST.get(f'contact_type_{new_id}', 'email')
                            label = request.POST.get(f'contact_label_{new_id}', '').strip()
                            value = request.POST.get(f'contact_value_{new_id}', '').strip()
                            if value:
                                ClubContact.objects.create(
                                    club=club,
                                    contact_type=contact_type,
                                    label=label,
                                    value=value
                                )

                messages.success(request, f'Klub frissítve: {name}')
            else:
                club = Club.objects.create(
                    name=name,
                    short_name=short_name,
                    is_active=True,  # New clubs are always active
                    country=country,
                    city=city,
                    postal_code=postal_code,
                    address=address,
                    representative_name=representative_name,
                    representative_phone=representative_phone,
                    representative_email=representative_email,
                    email=email,
                    phone=phone,
                    website=website,
                    facebook=facebook,
                    logo=request.FILES.get('logo')
                )
                messages.success(request, f'Klub létrehozva: {name}')
            return redirect('matches:club_edit', club_id=club.id)

    # Get non-deleted teams for the club
    teams = club.teams.filter(is_deleted=False) if club else []

    context = {
        'club': club,
        'teams': teams,
    }
    return render(request, 'matches/club_edit.html', context)


@login_required
def club_toggle_active(request, club_id):
    """Admin: Toggle club active status."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Club

    if request.method == 'POST':
        club = get_object_or_404(Club, id=club_id)
        club.is_active = not club.is_active
        club.save()
        status = 'aktiválva' if club.is_active else 'deaktiválva'
        messages.success(request, f'Klub {status}: {club.name}')

    return redirect('matches:clubs_list')


@login_required
def club_delete(request, club_id):
    """Admin: Soft delete a club and all its teams."""
    if not request.user.is_admin_user:
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)
        return HttpResponseForbidden('Nincs jogosultságod.')

    if request.method == 'POST':
        club = get_object_or_404(Club, id=club_id)
        club_name = club.name

        # Use the model's soft_delete method with cascade
        club.soft_delete(cascade=True)

        # Audit log
        log_action(request, 'match', 'soft_delete', f'Klub törölve: {club_name}', obj=club)

        # Return JSON for AJAX calls
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'success': True, 'message': f'Klub törölve: {club_name}'})

        messages.success(request, f'Klub törölve: {club_name}')

    return redirect('matches:clubs_list')


@login_required
def api_archive_club(request, club_id):
    """API: Archive a club and all its teams."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    club = get_object_or_404(Club, id=club_id)
    club_name = club.name

    # Use the model's archive method with cascade
    club.archive(cascade=True)

    # Audit log
    log_action(request, 'match', 'archive', f'Klub archiválva: {club_name}', obj=club)

    return JsonResponse({'success': True, 'message': f'Klub archiválva: {club_name}'})


@login_required
def team_edit(request, club_id, team_id=None):
    """Admin: Create or edit a team within a club."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    club = get_object_or_404(Club, id=club_id, is_deleted=False)
    team = None
    if team_id:
        team = get_object_or_404(Team, id=team_id, club=club, is_deleted=False)

    if request.method == 'POST':
        custom_name = request.POST.get('custom_name', '').strip()
        short_name = request.POST.get('short_name', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        # Manager fields
        manager_name = request.POST.get('manager_name', '').strip()
        manager_phone = request.POST.get('manager_phone', '').strip()
        manager_email = request.POST.get('manager_email', '').strip()

        # Competition IDs
        competition_ids = request.POST.getlist('competitions')

        if not custom_name:
            messages.error(request, 'A csapat neve kötelező!')
            return redirect('matches:team_edit', club_id=club.id, team_id=team.id if team else None)

        if team:
            team.custom_name = custom_name
            team.short_name = short_name
            team.is_active = is_active
            team.manager_name = manager_name
            team.manager_phone = manager_phone
            team.manager_email = manager_email
            if 'logo' in request.FILES:
                team.logo = request.FILES['logo']
            team.save()

            # Update competitions
            team.competitions.set(competition_ids)

            messages.success(request, f'Csapat frissítve: {team}')
        else:
            team = Team.objects.create(
                club=club,
                custom_name=custom_name,
                short_name=short_name,
                is_active=is_active,
                manager_name=manager_name,
                manager_phone=manager_phone,
                manager_email=manager_email,
                logo=request.FILES.get('logo')
            )

            # Set competitions
            team.competitions.set(competition_ids)

            messages.success(request, f'Csapat létrehozva: {team}')
        return redirect('matches:team_edit', club_id=club.id, team_id=team.id)

    # Get competitions grouped by season
    from collections import OrderedDict
    seasons = Season.objects.filter(is_deleted=False).order_by('-is_active', '-start_date')
    competitions_by_season = OrderedDict()
    for season in seasons:
        comps = Competition.objects.filter(season=season, is_deleted=False).order_by('order', 'name')
        if comps.exists():
            competitions_by_season[season] = comps

    # Get current team's competition IDs
    team_competition_ids = []
    if team:
        team_competition_ids = list(team.competitions.values_list('id', flat=True))

    context = {
        'club': club,
        'team': team,
        'competitions_by_season': competitions_by_season,
        'team_competition_ids': team_competition_ids,
    }
    return render(request, 'matches/team_edit.html', context)


@login_required
def team_toggle_active(request, team_id):
    """Admin: Toggle team active status."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Team

    if request.method == 'POST':
        team = get_object_or_404(Team, id=team_id)
        team.is_active = not team.is_active
        team.save()
        status = 'aktiválva' if team.is_active else 'deaktiválva'
        messages.success(request, f'Csapat {status}: {team}')

    return redirect('matches:clubs_list')


@login_required
def team_delete(request, team_id):
    """Admin: Soft delete a team."""
    if not request.user.is_admin_user:
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)
        return HttpResponseForbidden('Nincs jogosultságod.')

    if request.method == 'POST':
        team = get_object_or_404(Team, id=team_id)
        club_id = team.club_id
        team_name = str(team)

        # Use the model's soft_delete method
        team.soft_delete()

        # Audit log
        log_action(request, 'match', 'soft_delete', f'Csapat törölve: {team_name}', obj=team)

        # Return JSON for AJAX calls
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'success': True, 'message': f'Csapat törölve: {team_name}'})

        messages.success(request, f'Csapat törölve: {team_name}')
        return redirect('matches:club_edit', club_id=club_id)

    return redirect('matches:clubs_list')


@login_required
def api_archive_team(request, team_id):
    """API: Archive a team."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    team = get_object_or_404(Team, id=team_id)
    team_name = str(team)

    # Use the model's archive method
    team.archive()

    # Audit log
    log_action(request, 'match', 'archive', f'Csapat archiválva: {team_name}', obj=team)

    return JsonResponse({'success': True, 'message': f'Csapat archiválva: {team_name}'})


@login_required
def team_add_alternative(request, team_id):
    """Admin: Add alternative name to team."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Team, TeamAlternativeName, Competition

    if request.method == 'POST':
        team = get_object_or_404(Team, id=team_id)
        name = request.POST.get('name', '').strip()
        competition_id = request.POST.get('competition')

        if name:
            competition = None
            if competition_id:
                competition = Competition.objects.filter(id=competition_id).first()

            TeamAlternativeName.objects.create(
                team=team,
                name=name,
                competition=competition
            )
            messages.success(request, f'Alternatív név hozzáadva: {name}')

    return redirect('matches:team_edit', club_id=team.club_id, team_id=team_id)


@login_required
def team_delete_alternative(request, alt_id):
    """Admin: Delete alternative name."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import TeamAlternativeName

    if request.method == 'POST':
        alt = get_object_or_404(TeamAlternativeName, id=alt_id)
        team = alt.team
        alt.delete()
        messages.success(request, 'Alternatív név törölve.')
        return redirect('matches:team_edit', club_id=team.club_id, team_id=team.id)

    return redirect('matches:clubs_list')


# ==================== VENUES ====================

@login_required
def venues_list(request):
    """Admin: List all venues."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    show_inactive = request.GET.get('show_inactive') == '1'
    # Filter out deleted and archived venues (archived are in Archive page)
    venues = Venue.objects.filter(is_deleted=False, is_archived=False).order_by('city', 'name')

    if not show_inactive:
        venues = venues.filter(is_active=True)

    context = {
        'venues': venues,
        'show_inactive': show_inactive,
        'total_count': Venue.objects.filter(is_deleted=False, is_archived=False).count(),
        'active_count': Venue.objects.filter(is_deleted=False, is_archived=False, is_active=True).count(),
    }
    return render(request, 'matches/venues_list.html', context)


@login_required
def venue_edit(request, venue_id=None):
    """Admin: Create or edit a venue."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    venue = None
    if venue_id:
        venue = get_object_or_404(Venue, id=venue_id, is_deleted=False)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        city = request.POST.get('city', '').strip()
        postal_code = request.POST.get('postal_code', '').strip()
        address = request.POST.get('address', '').strip()
        google_maps_url = request.POST.get('google_maps_url', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if name and city:
            if venue:
                venue.name = name
                venue.city = city
                venue.postal_code = postal_code
                venue.address = address
                venue.google_maps_url = google_maps_url
                venue.is_active = is_active
                venue.save()
                messages.success(request, f'Helyszín frissítve: {name}')
            else:
                venue = Venue.objects.create(
                    name=name,
                    city=city,
                    postal_code=postal_code,
                    address=address,
                    google_maps_url=google_maps_url,
                    is_active=is_active
                )
                messages.success(request, f'Helyszín létrehozva: {name}')
            return redirect('matches:venues_list')

    context = {
        'venue': venue,
    }
    return render(request, 'matches/venue_edit.html', context)


@login_required
def venue_toggle_active(request, venue_id):
    """Admin: Toggle venue active status."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Venue

    if request.method == 'POST':
        venue = get_object_or_404(Venue, id=venue_id)
        venue.is_active = not venue.is_active
        venue.save()
        status = 'aktiválva' if venue.is_active else 'deaktiválva'
        messages.success(request, f'Helyszín {status}: {venue.name}')

    return redirect('matches:venues_list')


@login_required
def api_archive_venue(request, venue_id):
    """API: Archive a venue."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    venue = get_object_or_404(Venue, id=venue_id)
    venue_name = venue.name

    # Use the model's archive method
    venue.archive()

    # Audit log
    log_action(request, 'match', 'archive', f'Helyszín archiválva: {venue_name}', obj=venue)

    return JsonResponse({'success': True, 'message': f'Helyszín archiválva: {venue_name}'})


@login_required
def api_delete_venue(request, venue_id):
    """API: Soft delete a venue."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    venue = get_object_or_404(Venue, id=venue_id)
    venue_name = venue.name

    # Use the model's soft_delete method
    venue.soft_delete()

    # Audit log
    log_action(request, 'match', 'soft_delete', f'Helyszín törölve: {venue_name}', obj=venue)

    return JsonResponse({'success': True, 'message': f'Helyszín törölve: {venue_name}'})


# ==================== COMPETITIONS ====================

@login_required
def competitions_list(request):
    """Admin: List all competitions and seasons."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    context = {
        'seasons': Season.objects.filter(is_deleted=False).order_by('-start_date'),
        'competitions': Competition.objects.filter(is_deleted=False).select_related('season').prefetch_related('phases').order_by('-season__start_date', 'name'),
    }
    return render(request, 'matches/competitions_list.html', context)


@login_required
@require_POST
def update_competition_color(request, competition_id):
    """Admin: Update competition color."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Competition

    competition = get_object_or_404(Competition, id=competition_id)
    color = request.POST.get('color', '#6366f1').strip()

    # Validate hex color format
    if color and len(color) == 7 and color.startswith('#'):
        competition.color = color
        competition.save()
        messages.success(request, f'Szín módosítva: {competition.short_name}')

    return redirect('matches:competitions_list')


# ==================== SAVED COLORS API ====================

@login_required
def list_colors(request):
    """API: List all saved colors."""
    colors = SavedColor.objects.all().values('id', 'name', 'color', 'order')
    return JsonResponse(list(colors), safe=False)


@login_required
@require_POST
def save_color(request):
    """API: Save a new color."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        color = data.get('color', '').strip()

        if not name or not color:
            return JsonResponse({'error': 'Név és szín megadása kötelező.'}, status=400)

        # Validate hex color format
        if not (len(color) == 7 and color.startswith('#')):
            return JsonResponse({'error': 'Érvénytelen színkód.'}, status=400)

        # Get next order number
        max_order = SavedColor.objects.aggregate(Max('order'))['order__max'] or 0

        saved_color = SavedColor.objects.create(
            name=name,
            color=color,
            order=max_order + 1
        )

        return JsonResponse({
            'id': saved_color.id,
            'name': saved_color.name,
            'color': saved_color.color,
            'order': saved_color.order
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Érvénytelen JSON.'}, status=400)


@login_required
@require_POST
def delete_color(request):
    """API: Delete a saved color."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    try:
        data = json.loads(request.body)
        color_id = data.get('id')

        if not color_id:
            return JsonResponse({'error': 'Szín ID megadása kötelező.'}, status=400)

        saved_color = get_object_or_404(SavedColor, id=color_id)
        saved_color.delete()

        return JsonResponse({'success': True})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Érvénytelen JSON.'}, status=400)


# ==================== MATCH VISIBILITY API ====================

@login_required
@require_POST
def api_toggle_match_hidden(request, match_id):
    """API: Toggle match hidden status."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    match = get_object_or_404(Match.objects.filter(is_deleted=False), id=match_id)
    was_hidden = match.is_hidden
    match.is_hidden = not match.is_hidden
    match.save()

    # Audit log
    action_desc = "Mérkőzés elrejtve" if match.is_hidden else "Mérkőzés láthatóvá téve"
    log_action(
        request,
        'match',
        'update',
        action_desc,
        obj=match,
        changes={'is_hidden': {'from': was_hidden, 'to': match.is_hidden}}
    )

    return JsonResponse({
        'success': True,
        'is_hidden': match.is_hidden
    })


@login_required
@require_POST
def api_toggle_assignment_published(request, match_id):
    """API: Toggle assignment publication status."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    match = get_object_or_404(Match.objects.filter(is_deleted=False), id=match_id)
    was_published = match.is_assignment_published
    match.is_assignment_published = not match.is_assignment_published

    # If unpublishing and status is scheduled, revert to draft
    if not match.is_assignment_published and match.status == Match.Status.SCHEDULED:
        match.status = Match.Status.DRAFT

    match.save()

    # Send notifications when publishing assignment (only if match is scheduled/confirmed)
    if not was_published and match.is_assignment_published and match.status in [Match.Status.SCHEDULED, Match.Status.CONFIRMED]:
        from documents.models import Notification

        # Get all assignments for this match
        assignments = match.assignments.filter(user__isnull=False)

        # Create notifications for each assigned user
        for assignment in assignments:
            # Format match details
            date_str = match.date.strftime('%Y.%m.%d (%A)') if match.date else 'Nincs dátum'
            time_str = match.time.strftime('%H:%M') if match.time else ''
            teams = f"{str(match.home_team) if match.home_team else 'TBD'} - {str(match.away_team) if match.away_team else 'TBD'}"
            venue = match.venue.name if match.venue else 'Nincs helyszín'

            message = f"{date_str} {time_str}\n{teams}\n{venue}"

            Notification.objects.create(
                recipient=assignment.user,
                title="Új mérkőzésre lettél kiírva",
                message=message,
                notification_type=Notification.Type.MATCH,
                link=f"/matches/{match.id}/"
            )

    # Audit log
    if match.is_assignment_published:
        log_description = "Mérkőzés kiírás publikálva (láthatóvá téve)"
    else:
        log_description = "Mérkőzés kiírás elrejtve (visszavonva piszkozatba)"

    log_action(
        request,
        'assignment',
        'update',
        log_description,
        obj=match,
        changes={
            'is_assignment_published': {'from': was_published, 'to': match.is_assignment_published},
            'status': {'from': Match.Status.SCHEDULED if not was_published else match.status, 'to': match.status}
        }
    )

    return JsonResponse({
        'success': True,
        'is_assignment_published': match.is_assignment_published,
        'status': match.status
    })


@login_required
@require_POST
def api_toggle_match_cancelled(request, match_id):
    """API: Toggle match cancelled status."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    match = get_object_or_404(Match.objects.filter(is_deleted=False), id=match_id)

    if match.status == Match.Status.CANCELLED:
        # Restore to draft - make visible again for editing
        match.status = Match.Status.DRAFT
        match.is_hidden = False  # Make match visible again (szem ikon)
        # Note: is_assignment_published stays False until manually published
        is_cancelled = False
    else:
        # Mark as cancelled
        # The post_save signal will send notifications and delete assignments
        # Hide both match and assignments from public view
        match.status = Match.Status.CANCELLED
        match.time = None
        match.is_assignment_published = False  # Hide assignments (emberke ikon)
        match.is_hidden = True  # Hide match itself (szem ikon)
        is_cancelled = True

    match.save()

    # Audit log
    if is_cancelled:
        log_description = "Mérkőzés lemondva (cancelled)"
    else:
        log_description = "Mérkőzés visszaállítva (cancelled -> draft)"

    log_action(
        request,
        'match',
        'cancel' if is_cancelled else 'update',
        log_description,
        obj=match,
        extra={
            'match_id': match.id,
            'is_cancelled': is_cancelled,
            'new_status': match.status
        }
    )

    return JsonResponse({
        'success': True,
        'is_cancelled': is_cancelled,
        'status': match.status
    })


@login_required
@require_POST
def api_create_match(request):
    """API: Create a new match."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    try:
        data = json.loads(request.body)

        # Required fields
        date_str = data.get('date')
        time_str = data.get('time')

        if not date_str or not time_str:
            return JsonResponse({'error': 'Dátum és időpont megadása kötelező.'}, status=400)

        # Parse date and time
        from datetime import datetime
        match_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        match_time = datetime.strptime(time_str, '%H:%M').time()

        # Tournament fields
        is_tournament = data.get('is_tournament', False)
        tournament_match_count = data.get('tournament_match_count', 1)
        tournament_court_count = data.get('tournament_court_count', 1)
        try:
            tournament_match_count = int(tournament_match_count) if tournament_match_count else 1
            if tournament_match_count < 1:
                tournament_match_count = 1
        except (ValueError, TypeError):
            tournament_match_count = 1
        try:
            tournament_court_count = int(tournament_court_count) if tournament_court_count else 1
            if tournament_court_count < 1:
                tournament_court_count = 1
        except (ValueError, TypeError):
            tournament_court_count = 1

        # Create match
        match = Match.objects.create(
            date=match_date,
            time=match_time,
            home_team_id=data.get('home_team') or None,
            away_team_id=data.get('away_team') or None if not is_tournament else None,
            venue_id=data.get('venue') or None,
            court=data.get('court', ''),
            phase_id=data.get('phase') or None,
            notes=data.get('notes', ''),
            status=Match.Status.DRAFT,
            created_by=request.user,
            is_tournament=is_tournament,
            tournament_match_count=tournament_match_count if is_tournament else 1,
            tournament_court_count=tournament_court_count if is_tournament else 1
        )

        # Audit log
        event_type = 'Torna' if is_tournament else 'Mérkőzés'
        log_action(request, 'match', 'create', f'{event_type} létrehozva (API) - {match}', obj=match)

        return JsonResponse({
            'success': True,
            'match_id': match.id
        })
    except ValueError as e:
        return JsonResponse({'error': f'Érvénytelen dátum vagy idő formátum: {e}'}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Érvénytelen JSON.'}, status=400)


@login_required
def archive(request):
    """Show archived items (is_archived=True).
    Regular Admin: can view only (read-only)
    Super Admin: can edit, restore, and delete
    """
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from django.contrib.auth import get_user_model
    from .models import Club, Team, Venue, Competition, Season, CompetitionPhase
    User = get_user_model()

    is_super_admin = getattr(request.user, 'is_super_admin', False)
    active_tab = request.GET.get('tab', 'seasons')

    # Get archived (is_archived=True, not deleted) items
    archived_seasons = Season.objects.filter(is_archived=True, is_deleted=False).order_by('-archived_at')
    archived_competitions = Competition.objects.filter(is_archived=True, is_deleted=False).select_related('season').order_by('-archived_at')
    archived_matches = Match.objects.filter(is_archived=True, is_deleted=False).select_related(
        'home_team', 'away_team', 'venue', 'phase', 'phase__competition'
    ).order_by('-archived_at')
    archived_venues = Venue.objects.filter(is_archived=True, is_deleted=False).order_by('-archived_at')
    archived_clubs = Club.objects.filter(is_archived=True, is_deleted=False).order_by('-archived_at')
    archived_teams = Team.objects.filter(is_archived=True, is_deleted=False).select_related('club').order_by('-archived_at')
    archived_users = User.objects.filter(is_archived=True, is_deleted=False).order_by('-archived_at')

    # Count items
    counts = {
        'archived_seasons': archived_seasons.count(),
        'archived_competitions': archived_competitions.count(),
        'archived_matches': archived_matches.count(),
        'archived_venues': archived_venues.count(),
        'archived_clubs': archived_clubs.count(),
        'archived_teams': archived_teams.count(),
        'archived_users': archived_users.count(),
    }

    context = {
        'is_super_admin': is_super_admin,
        'active_tab': active_tab,
        'counts': counts,
        # Archived items
        'archived_seasons': archived_seasons,
        'archived_competitions': archived_competitions,
        'archived_matches': archived_matches,
        'archived_venues': archived_venues,
        'archived_clubs': archived_clubs,
        'archived_teams': archived_teams,
        'archived_users': archived_users,
    }

    return render(request, 'matches/archive.html', context)


@login_required
def trash_view(request):
    """Show soft-deleted items (Kuka). Super Admin only.
    Super Admin can restore or permanently delete items.
    """
    if not getattr(request.user, 'is_super_admin', False):
        return HttpResponseForbidden('Nincs jogosultságod ehhez az oldalhoz.')

    from django.contrib.auth import get_user_model
    from .models import Club, Team, Venue, Competition, Season, CompetitionPhase
    User = get_user_model()

    active_tab = request.GET.get('tab', 'matches')

    # Get all soft-deleted items
    deleted_seasons = Season.objects.filter(is_deleted=True).order_by('-deleted_at')
    deleted_competitions = Competition.objects.filter(is_deleted=True).select_related('season').order_by('-deleted_at')
    deleted_matches = Match.objects.filter(is_deleted=True).select_related(
        'home_team', 'away_team', 'venue', 'phase', 'phase__competition'
    ).order_by('-deleted_at')
    deleted_venues = Venue.objects.filter(is_deleted=True).order_by('-deleted_at')
    deleted_clubs = Club.objects.filter(is_deleted=True).order_by('-deleted_at')
    deleted_teams = Team.objects.filter(is_deleted=True).select_related('club').order_by('-deleted_at')
    deleted_users = User.objects.filter(is_deleted=True).order_by('-deleted_at')

    # Count items
    counts = {
        'deleted_seasons': deleted_seasons.count(),
        'deleted_competitions': deleted_competitions.count(),
        'deleted_matches': deleted_matches.count(),
        'deleted_venues': deleted_venues.count(),
        'deleted_clubs': deleted_clubs.count(),
        'deleted_teams': deleted_teams.count(),
        'deleted_users': deleted_users.count(),
        'total': (
            deleted_seasons.count() + deleted_competitions.count() + deleted_matches.count() +
            deleted_venues.count() + deleted_clubs.count() + deleted_teams.count() + deleted_users.count()
        ),
    }

    context = {
        'active_tab': active_tab,
        'counts': counts,
        'deleted_seasons': deleted_seasons,
        'deleted_competitions': deleted_competitions,
        'deleted_matches': deleted_matches,
        'deleted_venues': deleted_venues,
        'deleted_clubs': deleted_clubs,
        'deleted_teams': deleted_teams,
        'deleted_users': deleted_users,
    }

    return render(request, 'matches/trash.html', context)


@login_required
def deleted_items(request):
    """Show soft-deleted items for permanent deletion. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return HttpResponseForbidden('Nincs jogosultságod ehhez az oldalhoz.')

    from django.contrib.auth import get_user_model
    from datetime import datetime
    from .models import Club, Team, Venue, Competition, Season
    User = get_user_model()

    # Get filter params
    search_query = request.GET.get('q', '').strip()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    item_type = request.GET.get('type', 'all')

    # Parse dates
    date_from_obj = None
    date_to_obj = None
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            pass

    # Get all soft-deleted items
    deleted_matches = Match.objects.filter(is_deleted=True).select_related(
        'home_team', 'away_team', 'venue', 'phase', 'phase__competition'
    ).order_by('-deleted_at')

    deleted_users = User.objects.filter(is_deleted=True).order_by('-deleted_at')

    deleted_clubs = Club.objects.filter(is_deleted=True).order_by('-deleted_at')

    deleted_teams = Team.objects.filter(is_deleted=True).select_related('club').order_by('-deleted_at')

    deleted_venues = Venue.objects.filter(is_deleted=True).order_by('-deleted_at')

    deleted_competitions = Competition.objects.filter(is_deleted=True).select_related('season').order_by('-deleted_at')

    deleted_seasons = Season.objects.filter(is_deleted=True).order_by('-deleted_at')

    # Apply date filters
    if date_from_obj:
        deleted_matches = deleted_matches.filter(deleted_at__gte=date_from_obj)
        deleted_users = deleted_users.filter(deleted_at__gte=date_from_obj)
        deleted_clubs = deleted_clubs.filter(deleted_at__gte=date_from_obj)
        deleted_teams = deleted_teams.filter(deleted_at__gte=date_from_obj)
        deleted_venues = deleted_venues.filter(deleted_at__gte=date_from_obj)
        deleted_competitions = deleted_competitions.filter(deleted_at__gte=date_from_obj)
        deleted_seasons = deleted_seasons.filter(deleted_at__gte=date_from_obj)

    if date_to_obj:
        deleted_matches = deleted_matches.filter(deleted_at__lte=date_to_obj)
        deleted_users = deleted_users.filter(deleted_at__lte=date_to_obj)
        deleted_clubs = deleted_clubs.filter(deleted_at__lte=date_to_obj)
        deleted_teams = deleted_teams.filter(deleted_at__lte=date_to_obj)
        deleted_venues = deleted_venues.filter(deleted_at__lte=date_to_obj)
        deleted_competitions = deleted_competitions.filter(deleted_at__lte=date_to_obj)
        deleted_seasons = deleted_seasons.filter(deleted_at__lte=date_to_obj)

    # Apply search filter
    if search_query:
        from django.db.models import Q
        deleted_matches = deleted_matches.filter(
            Q(home_team__name__icontains=search_query) |
            Q(away_team__name__icontains=search_query) |
            Q(venue__name__icontains=search_query) |
            Q(phase__competition__name__icontains=search_query)
        )
        deleted_users = deleted_users.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(username__icontains=search_query)
        )
        deleted_clubs = deleted_clubs.filter(
            Q(name__icontains=search_query) |
            Q(short_name__icontains=search_query) |
            Q(city__icontains=search_query)
        )
        deleted_teams = deleted_teams.filter(
            Q(custom_name__icontains=search_query) |
            Q(short_name__icontains=search_query) |
            Q(club__name__icontains=search_query) |
            Q(suffix__icontains=search_query)
        )
        deleted_venues = deleted_venues.filter(
            Q(name__icontains=search_query) |
            Q(city__icontains=search_query) |
            Q(address__icontains=search_query)
        )
        deleted_competitions = deleted_competitions.filter(
            Q(name__icontains=search_query) |
            Q(short_name__icontains=search_query) |
            Q(season__name__icontains=search_query)
        )
        deleted_seasons = deleted_seasons.filter(
            Q(name__icontains=search_query)
        )

    # Apply type filter
    if item_type != 'all':
        if item_type != 'match':
            deleted_matches = Match.objects.none()
        if item_type != 'user':
            deleted_users = User.objects.none()
        if item_type != 'club':
            deleted_clubs = Club.objects.none()
        if item_type != 'team':
            deleted_teams = Team.objects.none()
        if item_type != 'venue':
            deleted_venues = Venue.objects.none()
        if item_type != 'competition':
            deleted_competitions = Competition.objects.none()
        if item_type != 'season':
            deleted_seasons = Season.objects.none()

    # Counts for stats
    counts = {
        'matches': deleted_matches.count(),
        'users': deleted_users.count(),
        'clubs': deleted_clubs.count(),
        'teams': deleted_teams.count(),
        'venues': deleted_venues.count(),
        'competitions': deleted_competitions.count(),
        'seasons': deleted_seasons.count(),
    }
    counts['total'] = sum(counts.values())

    context = {
        'deleted_matches': deleted_matches,
        'deleted_users': deleted_users,
        'deleted_clubs': deleted_clubs,
        'deleted_teams': deleted_teams,
        'deleted_venues': deleted_venues,
        'deleted_competitions': deleted_competitions,
        'deleted_seasons': deleted_seasons,
        'item_type': item_type,
        'counts': counts,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
    }

    return render(request, 'matches/deleted_items.html', context)


@login_required
@require_POST
def api_permanently_delete_match(request, match_id):
    """API: Permanently delete a soft-deleted match. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a végleges törléshez.'}, status=403)

    match = get_object_or_404(Match.objects.filter(is_deleted=True), id=match_id)

    # Store match info for logging before delete
    match_repr = str(match)
    match_date = str(match.date) if match.date else None

    # Permanently delete the match and all related assignments
    match.delete()

    # Audit log
    log_action(
        request,
        'match',
        'delete',
        f"Mérkőzés véglegesen törölve: {match_repr}",
        extra={
            'match_id': match_id,
            'match_date': match_date,
            'permanent': True
        }
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_restore_match(request, match_id):
    """API: Restore a soft-deleted match. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a visszaállításhoz.'}, status=403)

    match = get_object_or_404(Match.objects.filter(is_deleted=True), id=match_id)

    # Restore the match
    match.is_deleted = False
    match.deleted_at = None
    match.save()

    # Audit log
    log_action(
        request,
        'match',
        'update',
        f"Mérkőzés visszaállítva a törölt elemek közül: {match}",
        obj=match,
        extra={
            'match_id': match.id,
            'restored': True
        }
    )

    return JsonResponse({'success': True})


# ==================== USER MANAGEMENT ====================

@login_required
def users_list(request):
    """JT Admin/Admin: List users (JT Admins only see referees, Admins see all)."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from django.contrib.auth import get_user_model
    User = get_user_model()

    is_super_admin = getattr(request.user, 'is_super_admin', False)

    # Get query params
    search = request.GET.get('search', '').strip()
    role_filter = request.GET.get('role', '').strip()
    # Only super admin can view deleted users
    show_deleted = is_super_admin and request.GET.get('show_deleted') == '1'

    # Base query
    users = User.objects.all().order_by('last_name', 'first_name')

    # JT Admins (who are not also Admin) only see referees and JT Admins
    # Admins see all users
    if not request.user.is_admin_user:
        # Only show users who are referees or JT Admins (by role or by flag)
        users = users.filter(
            Q(role=User.Role.REFEREE) | Q(is_referee_flag=True) |
            Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True)
        )

    if not show_deleted:
        users = users.filter(is_deleted=False)

    # Archived users only appear in Archive page, not here
    users = users.filter(is_archived=False)

    # Apply role filter (by role OR by flag - show everyone who has that permission)
    if role_filter:
        role_filters = {
            'referee': Q(role=User.Role.REFEREE) | Q(is_referee_flag=True),
            'jt_admin': Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True),
            'vb': Q(role=User.Role.VB) | Q(is_vb_flag=True),
            'inspector': Q(role=User.Role.INSPECTOR) | Q(is_inspector_flag=True),
            'accountant': Q(role=User.Role.ACCOUNTANT) | Q(is_accountant_flag=True),
            'admin': Q(role=User.Role.ADMIN) | Q(is_admin_flag=True),
            'tournament_director': Q(role=User.Role.TOURNAMENT_DIRECTOR) | Q(is_tournament_director_flag=True),
        }
        if role_filter in role_filters:
            users = users.filter(role_filters[role_filter])

    # Apply search filter
    if search:
        users = users.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )

    # Count for the filtered view (deleted count only for super admin)
    if request.user.is_admin_user:
        total_count = User.objects.filter(is_deleted=False).count()
        deleted_count = User.objects.filter(is_deleted=True).count() if is_super_admin else 0
    else:
        # JT Admin sees referee and JT Admin counts
        user_filter = (Q(role=User.Role.REFEREE) | Q(is_referee_flag=True) |
                       Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True))
        total_count = User.objects.filter(user_filter, is_deleted=False).count()
        deleted_count = User.objects.filter(user_filter, is_deleted=True).count() if is_super_admin else 0

    # Available roles for filter dropdown
    role_choices = [
        ('', 'Összes szerepkör'),
        ('referee', 'Játékvezető'),
        ('jt_admin', 'JT Admin'),
        ('vb', 'VB tag'),
        ('inspector', 'Ellenőr'),
        ('accountant', 'Könyvelő'),
        ('admin', 'Adminisztrátor'),
        ('tournament_director', 'Tornaigazgató'),
    ]

    context = {
        'users': users,
        'search': search,
        'role_filter': role_filter,
        'role_choices': role_choices,
        'show_deleted': show_deleted,
        'total_count': total_count,
        'deleted_count': deleted_count,
        'is_admin_view': request.user.is_admin_user,
        'is_super_admin': is_super_admin,
    }
    return render(request, 'matches/users_list.html', context)


@login_required
def user_create(request):
    """JT Admin/Admin: Create a new user."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from django.contrib.auth import get_user_model
    User = get_user_model()

    if request.method == 'POST':
        # Basic info
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '').strip()

        if not email:
            messages.error(request, 'E-mail cím megadása kötelező!')
            return render(request, 'matches/user_edit.html', {'user_obj': None})

        # Check for existing non-deleted users with this email
        if User.objects.filter(email=email, is_deleted=False).exists():
            messages.error(request, 'Ez az e-mail cím már foglalt!')
            return render(request, 'matches/user_edit.html', {'user_obj': None})

        # If a deleted user exists with this email, modify their email/username to allow reuse
        deleted_user_with_email = User.objects.filter(email=email, is_deleted=True).first()
        if deleted_user_with_email:
            # Append timestamp to the deleted user's email and username to free up the address
            import time
            suffix = f"_deleted_{int(time.time())}"
            deleted_user_with_email.email = f"{deleted_user_with_email.email}{suffix}"
            deleted_user_with_email.username = f"{deleted_user_with_email.username}{suffix}"
            deleted_user_with_email.save(update_fields=['email', 'username'])

        # Check if we're sending welcome email with setup link
        send_welcome = request.POST.get('send_password_email') == 'on'

        # Create user
        user = User.objects.create_user(
            username=email,  # Use email as username
            email=email,
            password=password if password else None,  # None if sending setup link
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )

        # If sending welcome email without manual password, set unusable password
        if send_welcome and not password:
            user.set_unusable_password()
            user.save(update_fields=['password'])

        # Save additional fields
        _save_user_fields(request, user)

        # Send welcome email if checkbox is checked
        email_sent = False
        if send_welcome and email:
            try:
                from core.email_utils import send_welcome_email
                if send_welcome_email(user):
                    email_sent = True
                    messages.success(request, f'Felhasználó létrehozva és meghívó email elküldve: {user.get_full_name() or email}')
                else:
                    messages.warning(request, f'Felhasználó létrehozva, de az email küldés sikertelen: {user.get_full_name() or email}')
            except Exception as e:
                logger.error(f"Failed to send welcome email to {email}: {e}")
                messages.warning(request, f'Felhasználó létrehozva, de az email küldés sikertelen: {user.get_full_name() or email}')
        else:
            messages.success(request, f'Felhasználó létrehozva: {user.get_full_name() or email}')

        # Audit log - user created
        from audit.utils import log_action
        log_action(
            request,
            'user',
            'create',
            f'Új felhasználó létrehozva: {user.get_full_name()} ({user.email})',
            obj=user,
            extra={
                'email': user.email,
                'role': user.role,
                'welcome_email_sent': email_sent,
            }
        )

        return redirect('matches:user_edit', user_id=user.id)

    context = {
        'user_obj': None,
    }
    return render(request, 'matches/user_edit.html', context)


@login_required
def user_edit(request, user_id):
    """JT Admin/Admin: Edit a user profile."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user_obj = get_object_or_404(User, id=user_id)

    # JT Admin (non-Admin) can only edit referees
    # JT Admin (non-Admin) can only edit referees and other JT Admins
    if not request.user.is_admin_user:
        is_referee_or_jt = (user_obj.role == User.Role.REFEREE or user_obj.is_referee_flag or
                           user_obj.role == User.Role.JT_ADMIN or user_obj.is_jt_admin_flag)
        if not is_referee_or_jt:
            return HttpResponseForbidden('Csak játékvezetői és JT Admin profilokat szerkeszthetsz.')

    if request.method == 'POST':
        # Track changes for audit log
        old_email = user_obj.email
        old_role = user_obj.role
        password_changed = False
        password_email_sent = False

        # Basic info
        user_obj.first_name = request.POST.get('first_name', '').strip()
        user_obj.last_name = request.POST.get('last_name', '').strip()
        user_obj.phone = request.POST.get('phone', '').strip()

        # Email update (check uniqueness - exclude soft-deleted users)
        new_email = request.POST.get('email', '').strip()
        if new_email and new_email != user_obj.email:
            if User.objects.filter(email=new_email, is_deleted=False).exclude(id=user_obj.id).exists():
                messages.error(request, 'Ez az e-mail cím már foglalt!')
            else:
                # If a deleted user exists with this email, modify their email/username to allow reuse
                deleted_user_with_email = User.objects.filter(email=new_email, is_deleted=True).first()
                if deleted_user_with_email:
                    import time
                    suffix = f"_deleted_{int(time.time())}"
                    deleted_user_with_email.email = f"{deleted_user_with_email.email}{suffix}"
                    deleted_user_with_email.username = f"{deleted_user_with_email.username}{suffix}"
                    deleted_user_with_email.save(update_fields=['email', 'username'])
                user_obj.email = new_email
                user_obj.username = new_email

        # Password change (only if provided)
        new_password = request.POST.get('password', '').strip()
        if new_password:
            user_obj.set_password(new_password)
            password_changed = True
            messages.info(request, 'Jelszó megváltoztatva!')

        # Send new password via email
        send_password_email = request.POST.get('send_password_email') == 'on'
        if send_password_email:
            import string
            import random
            # Generate random password
            chars = string.ascii_letters + string.digits
            generated_password = ''.join(random.choice(chars) for _ in range(12))
            user_obj.set_password(generated_password)
            password_changed = True

            # Send email with new password
            try:
                from core.email_utils import send_password_reset_email
                if send_password_reset_email(user_obj, generated_password):
                    password_email_sent = True
                    messages.success(request, f'Új jelszó elküldve a következő címre: {user_obj.email}')
                else:
                    messages.warning(request, f'Jelszó beállítva, de az email küldés sikertelen')
            except Exception as e:
                messages.warning(request, f'Jelszó beállítva, de az email küldés sikertelen: {str(e)}')

        # Profile picture
        if 'profile_picture' in request.FILES:
            user_obj.profile_picture = request.FILES['profile_picture']
        elif request.POST.get('remove_profile_picture') == '1':
            user_obj.profile_picture = None

        # Save additional fields
        _save_user_fields(request, user_obj)

        user_obj.save()

        # Audit log - user updated
        from audit.utils import log_action
        changes = {}
        if old_email != user_obj.email:
            changes['email'] = {'old': old_email, 'new': user_obj.email}
        if old_role != user_obj.role:
            changes['role'] = {'old': old_role, 'new': user_obj.role}

        log_action(
            request,
            'user',
            'update',
            f'Felhasználó módosítva: {user_obj.get_full_name()} ({user_obj.email})',
            obj=user_obj,
            changes=changes if changes else None,
            extra={
                'password_changed': password_changed,
                'password_email_sent': password_email_sent,
            }
        )

        messages.success(request, 'Profil frissítve!')
        return redirect('matches:user_edit', user_id=user_obj.id)

    from datetime import date
    context = {
        'user_obj': user_obj,
        'today': date.today(),
    }
    return render(request, 'matches/user_edit.html', context)


def _save_user_fields(request, user):
    """Helper to save all user fields from request."""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Address
    user.country = request.POST.get('country', 'Magyarország').strip()
    user.postal_code = request.POST.get('postal_code', '').strip()
    user.city = request.POST.get('city', '').strip()
    user.address = request.POST.get('address', '').strip()

    # Birth info
    user.mother_maiden_name = request.POST.get('mother_maiden_name', '').strip()
    birth_date = request.POST.get('birth_date', '').strip()
    if birth_date:
        from datetime import datetime
        try:
            user.birth_date = datetime.strptime(birth_date, '%Y-%m-%d').date()
        except ValueError:
            pass
    else:
        user.birth_date = None
    user.birth_place = request.POST.get('birth_place', '').strip()

    # Vehicle info
    user.vehicle_owner = request.POST.get('vehicle_owner', '').strip()
    user.vehicle_authorization = request.POST.get('vehicle_authorization') == 'on'
    user.vehicle_make = request.POST.get('vehicle_make', '').strip()
    user.vehicle_model = request.POST.get('vehicle_model', '').strip()
    vehicle_year = request.POST.get('vehicle_year', '').strip()
    if vehicle_year:
        try:
            user.vehicle_year = int(vehicle_year)
        except ValueError:
            pass
    else:
        user.vehicle_year = None
    vehicle_engine_cc = request.POST.get('vehicle_engine_cc', '').strip()
    if vehicle_engine_cc:
        try:
            user.vehicle_engine_cc = int(vehicle_engine_cc)
        except ValueError:
            pass
    else:
        user.vehicle_engine_cc = None
    user.vehicle_license_plate = request.POST.get('vehicle_license_plate', '').strip()
    user.vehicle_engine_type = request.POST.get('vehicle_engine_type', '').strip()
    user.vehicle_reimbursement_enabled = request.POST.get('vehicle_reimbursement_enabled') == 'on'

    # Contract info
    user.taj_number = request.POST.get('taj_number', '').strip()

    # Billing info
    user.billing_type = request.POST.get('billing_type', User.BillingType.NINCS)
    user.tax_id = request.POST.get('tax_id', '').strip()
    user.bank_account = request.POST.get('bank_account', '').strip()

    # Medical certificate
    medical_valid_until = request.POST.get('medical_valid_until', '').strip()
    if medical_valid_until:
        from datetime import datetime
        try:
            user.medical_valid_until = datetime.strptime(medical_valid_until, '%Y-%m-%d').date()
        except ValueError:
            pass
    else:
        user.medical_valid_until = None

    # Admin flags - full control for Admins
    if request.user.is_admin_user:
        new_role = request.POST.get('role', User.Role.REFEREE)
        new_admin_flag = request.POST.get('is_admin_flag') == 'on'

        # Super Admin restriction: only super admins can grant admin rights
        is_super = getattr(request.user, 'is_super_admin', False)

        if not is_super:
            # Non-super admins cannot set role to ADMIN or give admin flag
            if new_role == User.Role.ADMIN:
                new_role = user.role if user.pk else User.Role.REFEREE  # Keep existing or default
            # Cannot grant admin flag (but can keep it if already has it)
            if new_admin_flag and not user.is_admin_flag:
                new_admin_flag = False
            # Cannot revoke admin flag from existing admins (only super admin can)
            if user.is_admin_flag:
                new_admin_flag = True

        # Self-lockout protection: don't allow removing own admin access
        is_editing_self = (user.id == request.user.id)
        if is_editing_self:
            # Keep admin access if currently admin
            would_lose_admin = (new_role != User.Role.ADMIN and not new_admin_flag)
            if would_lose_admin:
                # Force keep admin access
                new_admin_flag = True

        user.role = new_role
        # Role flags for multiple roles
        user.is_referee_flag = request.POST.get('is_referee_flag') == 'on'
        user.is_jt_admin_flag = request.POST.get('is_jt_admin_flag') == 'on'
        user.is_vb_flag = request.POST.get('is_vb_flag') == 'on'
        user.is_inspector_flag = request.POST.get('is_inspector_flag') == 'on'
        user.is_accountant_flag = request.POST.get('is_accountant_flag') == 'on'
        user.is_admin_flag = new_admin_flag
        # Other flags
        user.has_content_module = request.POST.get('has_content_module') == 'on'
        user.is_hidden_from_colleagues = request.POST.get('is_hidden_from_colleagues') == 'on'
        user.is_login_disabled = request.POST.get('is_login_disabled') == 'on'

    # JT Admin (non-Admin) - limited control: only inspector flag, hidden, login disabled
    elif request.user.is_jt_admin:
        # JT Admin can create new referees, but cannot change role of existing JT Admins
        is_jt_admin_user = user.role == User.Role.JT_ADMIN or user.is_jt_admin_flag
        if not is_jt_admin_user:
            # For referees (new or existing): set role to REFEREE
            user.role = User.Role.REFEREE
            user.is_referee_flag = True
        # JT Admin can toggle inspector flag for anyone they can edit
        user.is_inspector_flag = request.POST.get('is_inspector_flag') == 'on'
        # JT Admin can hide users and disable login
        user.is_hidden_from_colleagues = request.POST.get('is_hidden_from_colleagues') == 'on'
        user.is_login_disabled = request.POST.get('is_login_disabled') == 'on'

    user.save()


@login_required
@require_POST
def api_user_delete(request, user_id):
    """API: Soft delete a user."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User.objects.filter(is_deleted=False), id=user_id)

    # Don't allow deleting yourself
    if user.id == request.user.id:
        return JsonResponse({'error': 'Nem törölheted saját magadat!'}, status=400)

    # JT Admin (non-Admin) can only delete referees and other JT Admins
    if not request.user.is_admin_user:
        is_referee_or_jt = (user.role == User.Role.REFEREE or user.is_referee_flag or
                           user.role == User.Role.JT_ADMIN or user.is_jt_admin_flag)
        if not is_referee_or_jt:
            return JsonResponse({'error': 'Csak játékvezetőket és JT Adminokat törölhetsz.'}, status=403)

    # Save user info before soft delete for audit log
    user_name = user.get_full_name()
    user_email = user.email

    # Soft delete
    user.is_deleted = True
    user.deleted_at = timezone.now()

    # JT Admin deletion needs admin approval - until then, hide and disable login
    if not request.user.is_admin_user:
        user.is_hidden_from_colleagues = True
        user.is_login_disabled = True

    user.save()

    # Audit log - user soft deleted
    from audit.utils import log_action
    log_action(
        request,
        'user',
        'delete',
        f'Felhasználó törölve (soft delete): {user_name} ({user_email})',
        obj=user,
        extra={
            'soft_delete': True,
            'user_email': user_email,
            'user_role': user.role,
        }
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_user_toggle_login(request, user_id):
    """API: Toggle user login disabled status."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User, id=user_id)

    # Don't allow disabling yourself
    if user.id == request.user.id:
        return JsonResponse({'error': 'Nem tilthatod le saját magadat!'}, status=400)

    # JT Admins (non-Admin) can only toggle login for referees and JT Admins
    if not request.user.is_admin_user:
        is_referee_or_jt = (user.role == User.Role.REFEREE or user.is_referee_flag or
                           user.role == User.Role.JT_ADMIN or user.is_jt_admin_flag)
        if not is_referee_or_jt:
            return JsonResponse({'error': 'Csak játékvezetők és JT Adminok bejelentkezését módosíthatod.'}, status=403)

    user.is_login_disabled = not user.is_login_disabled
    user.save()

    return JsonResponse({
        'success': True,
        'is_login_disabled': user.is_login_disabled
    })


@login_required
@require_POST
def api_user_toggle_visibility(request, user_id):
    """API: Toggle user visibility (hidden from colleagues)."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User, id=user_id)

    # Don't allow hiding yourself
    if user.id == request.user.id:
        return JsonResponse({'error': 'Nem rejtheted el saját magadat!'}, status=400)

    # JT Admins (non-Admin) can only toggle visibility for referees and JT Admins
    if not request.user.is_admin_user:
        is_referee_or_jt = (user.role == User.Role.REFEREE or user.is_referee_flag or
                           user.role == User.Role.JT_ADMIN or user.is_jt_admin_flag)
        if not is_referee_or_jt:
            return JsonResponse({'error': 'Csak játékvezetők és JT Adminok láthatóságát módosíthatod.'}, status=403)

    user.is_hidden_from_colleagues = not user.is_hidden_from_colleagues
    user.save()

    # Audit log
    action = 'hide_user' if user.is_hidden_from_colleagues else 'update'
    log_action(request, 'user', action, f'Felhasználó {"elrejtve" if user.is_hidden_from_colleagues else "megjelenítve"}: {user.get_full_name()}', obj=user)

    return JsonResponse({
        'success': True,
        'is_hidden': user.is_hidden_from_colleagues
    })


@login_required
@require_POST
def api_user_exclude(request, user_id):
    """API: Exclude (archive) a user - they cannot login anymore."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User, id=user_id, is_deleted=False)

    # Don't allow excluding yourself
    if user.id == request.user.id:
        return JsonResponse({'error': 'Nem zárhatod ki saját magadat!'}, status=400)

    # Don't allow excluding super admins
    if getattr(user, 'is_super_admin', False):
        return JsonResponse({'error': 'Ez a felhasználó nem zárható ki.'}, status=400)

    # Use the model's exclude_user method
    user.exclude_user()

    # Audit log
    log_action(request, 'user', 'exclude_user', f'Felhasználó kizárva: {user.get_full_name()}', obj=user)

    return JsonResponse({'success': True, 'message': f'Felhasználó kizárva: {user.get_full_name()}'})


@login_required
@require_POST
def api_user_restore(request, user_id):
    """API: Restore a soft-deleted or archived user. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a visszaállításhoz.'}, status=403)

    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()

    # Find user that is either deleted OR archived
    user = get_object_or_404(User.objects.filter(Q(is_deleted=True) | Q(is_archived=True)), id=user_id)

    # Restore user - clear all states
    user.restore()

    # Audit log - user restored
    log_action(
        request,
        'user',
        'restore',
        f'Felhasználó visszaállítva: {user.get_full_name()} ({user.email})',
        obj=user,
        extra={
            'restored': True,
            'user_email': user.email,
        }
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_user_toggle_archive(request, user_id):
    """API: Toggle archive status of a user."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User, id=user_id, is_deleted=False)

    # Don't allow archiving yourself
    if user.id == request.user.id:
        return JsonResponse({'error': 'Nem archiválhatod saját magadat!'}, status=400)

    # Don't allow archiving super admins (unless you are super admin)
    if getattr(user, 'is_super_admin', False) and not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Ez a felhasználó nem archiválható.'}, status=400)

    if user.is_archived:
        # Unarchive - only super admin can do this
        if not getattr(request.user, 'is_super_admin', False):
            return JsonResponse({'error': 'Nincs jogosultságod az archiválás visszavonásához.'}, status=403)
        user.is_archived = False
        user.archived_at = None
        user.save(update_fields=['is_archived', 'archived_at'])
        log_action(request, 'user', 'restore', f'Felhasználó archiválás megszüntetve: {user.get_full_name()}', obj=user)
        return JsonResponse({'success': True, 'archived': False})
    else:
        # Archive
        from django.utils import timezone
        user.is_archived = True
        user.archived_at = timezone.now()
        user.save(update_fields=['is_archived', 'archived_at'])
        log_action(request, 'user', 'archive', f'Felhasználó archiválva: {user.get_full_name()}', obj=user)
        return JsonResponse({'success': True, 'archived': True})


@login_required
@require_POST
def api_user_permanently_delete(request, user_id):
    """API: Permanently delete a soft-deleted user. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a végleges törléshez.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User.objects.filter(is_deleted=True), id=user_id)

    # Don't allow deleting yourself
    if user.id == request.user.id:
        return JsonResponse({'error': 'Nem törölheted saját magadat!'}, status=400)

    # Save user info before permanent delete for audit log
    user_name = user.get_full_name()
    user_email = user.email
    user_role = user.role
    user_pk = user.pk

    # Permanently delete
    user.delete()

    # Audit log - user permanently deleted
    from audit.utils import log_action
    log_action(
        request,
        'user',
        'delete',
        f'Felhasználó véglegesen törölve: {user_name} ({user_email})',
        obj=None,  # User is already deleted
        extra={
            'permanent_delete': True,
            'deleted_user_id': user_pk,
            'user_email': user_email,
            'user_name': user_name,
            'user_role': user_role,
        }
    )

    return JsonResponse({'success': True})


# =============================================================================
# API: Restore/Delete endpoints for all entity types
# =============================================================================

@login_required
@require_POST
def api_restore_club(request, club_id):
    """API: Restore a soft-deleted club. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a visszaállításhoz.'}, status=403)

    club = get_object_or_404(Club.objects.filter(is_deleted=True), id=club_id)
    club.is_deleted = False
    club.deleted_at = None
    club.save()

    log_action(
        request, 'match', 'update',
        f'Klub visszaállítva: {club.name}',
        obj=club, extra={'restored': True}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_permanently_delete_club(request, club_id):
    """API: Permanently delete a soft-deleted club. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a végleges törléshez.'}, status=403)

    club = get_object_or_404(Club.objects.filter(is_deleted=True), id=club_id)
    club_name = club.name
    club_pk = club.pk
    club.delete()

    log_action(
        request, 'match', 'delete',
        f'Klub véglegesen törölve: {club_name}',
        extra={'permanent_delete': True, 'club_id': club_pk, 'club_name': club_name}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_restore_team(request, team_id):
    """API: Restore a soft-deleted team. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a visszaállításhoz.'}, status=403)

    team = get_object_or_404(Team.objects.filter(is_deleted=True), id=team_id)
    team.is_deleted = False
    team.deleted_at = None
    team.save()

    log_action(
        request, 'match', 'update',
        f'Csapat visszaállítva: {team}',
        obj=team, extra={'restored': True}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_permanently_delete_team(request, team_id):
    """API: Permanently delete a soft-deleted team. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a végleges törléshez.'}, status=403)

    team = get_object_or_404(Team.objects.filter(is_deleted=True), id=team_id)
    team_name = str(team)
    team_pk = team.pk
    team.delete()

    log_action(
        request, 'match', 'delete',
        f'Csapat véglegesen törölve: {team_name}',
        extra={'permanent_delete': True, 'team_id': team_pk, 'team_name': team_name}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_restore_venue(request, venue_id):
    """API: Restore a soft-deleted venue. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a visszaállításhoz.'}, status=403)

    venue = get_object_or_404(Venue.objects.filter(is_deleted=True), id=venue_id)
    venue.is_deleted = False
    venue.deleted_at = None
    venue.save()

    log_action(
        request, 'match', 'update',
        f'Helyszín visszaállítva: {venue.name}',
        obj=venue, extra={'restored': True}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_permanently_delete_venue(request, venue_id):
    """API: Permanently delete a soft-deleted venue. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a végleges törléshez.'}, status=403)

    venue = get_object_or_404(Venue.objects.filter(is_deleted=True), id=venue_id)
    venue_name = venue.name
    venue_pk = venue.pk
    venue.delete()

    log_action(
        request, 'match', 'delete',
        f'Helyszín véglegesen törölve: {venue_name}',
        extra={'permanent_delete': True, 'venue_id': venue_pk, 'venue_name': venue_name}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_restore_competition(request, competition_id):
    """API: Restore a soft-deleted competition. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a visszaállításhoz.'}, status=403)

    competition = get_object_or_404(Competition.objects.filter(is_deleted=True), id=competition_id)
    competition.is_deleted = False
    competition.deleted_at = None
    competition.save()

    log_action(
        request, 'match', 'update',
        f'Bajnokság visszaállítva: {competition.name}',
        obj=competition, extra={'restored': True}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_permanently_delete_competition(request, competition_id):
    """API: Permanently delete a soft-deleted competition. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a végleges törléshez.'}, status=403)

    competition = get_object_or_404(Competition.objects.filter(is_deleted=True), id=competition_id)
    competition_name = competition.name
    competition_pk = competition.pk
    competition.delete()

    log_action(
        request, 'match', 'delete',
        f'Bajnokság véglegesen törölve: {competition_name}',
        extra={'permanent_delete': True, 'competition_id': competition_pk, 'competition_name': competition_name}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_restore_season(request, season_id):
    """API: Restore a soft-deleted season. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a visszaállításhoz.'}, status=403)

    season = get_object_or_404(Season.objects.filter(is_deleted=True), id=season_id)
    season.is_deleted = False
    season.deleted_at = None
    season.save()

    log_action(
        request, 'match', 'update',
        f'Szezon visszaállítva: {season.name}',
        obj=season, extra={'restored': True}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_permanently_delete_season(request, season_id):
    """API: Permanently delete a soft-deleted season. Super Admin only."""
    if not getattr(request.user, 'is_super_admin', False):
        return JsonResponse({'error': 'Nincs jogosultságod a végleges törléshez.'}, status=403)

    season = get_object_or_404(Season.objects.filter(is_deleted=True), id=season_id)
    season_name = season.name
    season_pk = season.pk
    season.delete()

    log_action(
        request, 'match', 'delete',
        f'Szezon véglegesen törölve: {season_name}',
        extra={'permanent_delete': True, 'season_id': season_pk, 'season_name': season_name}
    )

    return JsonResponse({'success': True})


@login_required
@require_POST
def api_activate_season(request, season_id):
    """API: Activate an archived (inactive) season. Admin only."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    season = get_object_or_404(Season.objects.filter(is_deleted=False), id=season_id)
    season.is_active = True
    season.save()

    log_action(
        request, 'match', 'update',
        f'Szezon aktiválva: {season.name}',
        obj=season, extra={'activated': True}
    )

    return JsonResponse({'success': True})


@login_required
def match_applications(request):
    """Match applications page - available matches and current applications."""
    from accounts.models import SiteSettings
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Q

    site_settings = SiteSettings.get_settings()
    user = request.user
    today = timezone.localdate()

    # Get filter parameters
    season_id = request.GET.get('season', '')
    competition_id = request.GET.get('competition', '')
    team_id = request.GET.get('team', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Default date range: today to today + 14 days
    if not date_from and not date_to:
        date_from = str(today)
        date_to = str(today + timedelta(days=14))

    # Determine which roles the user can apply for
    # Only users with the specific permission can apply for that role
    can_apply_as_referee = (
        site_settings.application_referees_enabled and
        user.is_referee  # Játékvezető permission - can apply as referee AND reserve
    )
    can_apply_as_inspector = (
        site_settings.application_inspectors_enabled and
        user.is_inspector  # Ellenőr permission only
    )
    can_apply_as_tournament_director = (
        site_settings.application_tournament_directors_enabled and
        user.is_tournament_director  # Tornaigazgató permission only
    )

    # Get current/selected season
    current_season = Season.get_current()
    if season_id:
        try:
            selected_season = Season.objects.get(id=season_id, is_deleted=False)
        except Season.DoesNotExist:
            selected_season = current_season
    else:
        selected_season = current_season

    # Get user's current applications (pending only)
    my_applications = MatchApplication.objects.filter(
        user=user,
        status=MatchApplication.Status.PENDING
    ).select_related(
        'match', 'match__phase', 'match__phase__competition',
        'match__venue', 'match__home_team', 'match__away_team'
    ).order_by('match__date', 'match__time')

    # Get IDs of matches user has already applied to
    applied_match_ids = set(my_applications.values_list('match_id', flat=True))

    # Get IDs of matches user is already assigned to (excluding declined assignments)
    assigned_match_ids = set(
        MatchAssignment.objects.filter(user=user).exclude(
            response_status=MatchAssignment.ResponseStatus.DECLINED
        ).values_list('match_id', flat=True)
    )

    # Build available matches query
    available_matches = Match.objects.filter(
        is_deleted=False,
        status__in=[Match.Status.CREATED, Match.Status.SCHEDULED, Match.Status.CONFIRMED],
        date__gte=today,  # Future matches only
    ).exclude(
        id__in=applied_match_ids  # Exclude already applied
    ).exclude(
        id__in=assigned_match_ids  # Exclude already assigned
    ).select_related(
        'phase', 'phase__competition', 'venue', 'home_team', 'away_team',
        'home_team__club', 'away_team__club'
    ).order_by('date', 'time')

    # Apply season filter
    if selected_season:
        available_matches = available_matches.filter(phase__competition__season=selected_season)

    # Apply other filters
    if competition_id:
        available_matches = available_matches.filter(phase__competition_id=competition_id)
    if date_from:
        available_matches = available_matches.filter(date__gte=date_from)
    if date_to:
        available_matches = available_matches.filter(date__lte=date_to)
    if team_id:
        available_matches = available_matches.filter(
            Q(home_team_id=team_id) | Q(away_team_id=team_id)
        )

    # Filter based on matches that have open positions with application_enabled=True
    # Get match IDs with open positions for roles user can apply for
    open_position_filter = Q()

    if can_apply_as_referee:
        open_position_filter |= Q(
            role=MatchAssignment.Role.REFEREE,
            application_enabled=True,
            placeholder_type='szukseges',
            user__isnull=True
        )
    if can_apply_as_inspector:
        open_position_filter |= Q(
            role=MatchAssignment.Role.INSPECTOR,
            application_enabled=True,
            placeholder_type='szukseges',
            user__isnull=True
        )
    if can_apply_as_tournament_director:
        open_position_filter |= Q(
            role=MatchAssignment.Role.TOURNAMENT_DIRECTOR,
            application_enabled=True,
            placeholder_type='szukseges',
            user__isnull=True
        )

    if open_position_filter:
        # Get match IDs that have at least one open position for applicable roles
        match_ids_with_open_positions = MatchAssignment.objects.filter(
            open_position_filter
        ).values_list('match_id', flat=True).distinct()
        available_matches = available_matches.filter(id__in=match_ids_with_open_positions)
    else:
        available_matches = Match.objects.none()

    # Get seasons for filter (exclude soft-deleted)
    seasons = Season.objects.filter(is_deleted=False).order_by('-start_date')

    # Get competitions for filter (based on selected season, exclude soft-deleted)
    competitions = Competition.objects.filter(
        season=selected_season, is_deleted=False
    ).order_by('order', 'name') if selected_season else Competition.objects.none()

    # Get teams for filter (exclude soft-deleted)
    teams = Team.objects.filter(is_deleted=False, is_active=True).order_by('club__name', 'suffix')

    context = {
        'available_matches': available_matches,
        'my_applications': my_applications,
        'can_apply_as_referee': can_apply_as_referee,
        'can_apply_as_inspector': can_apply_as_inspector,
        'can_apply_as_tournament_director': can_apply_as_tournament_director,
        'site_settings': site_settings,
        'seasons': seasons,
        'selected_season': selected_season,
        'competitions': competitions,
        'selected_competition': competition_id,
        'date_from': date_from,
        'date_to': date_to,
        'teams': teams,
        'selected_team': team_id,
    }

    return render(request, 'matches/applications.html', context)


@login_required
def api_apply_for_match(request, match_id):
    """API: Apply for a match."""
    from accounts.models import SiteSettings

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        import json
        data = json.loads(request.body)
        role = data.get('role')

        if not role or role not in ['referee', 'inspector', 'tournament_director']:
            return JsonResponse({'error': 'Érvénytelen szerepkör.'}, status=400)

        match = Match.objects.select_related('phase').get(pk=match_id, is_deleted=False)
        site_settings = SiteSettings.get_settings()
        user = request.user

        # Check user permission for the specific role
        if role == 'referee' and not user.is_referee:
            return JsonResponse({'error': 'Nincs játékvezető jogosultságod.'}, status=403)
        if role == 'inspector' and not user.is_inspector:
            return JsonResponse({'error': 'Nincs ellenőr jogosultságod.'}, status=403)
        if role == 'tournament_director' and not user.is_tournament_director:
            return JsonResponse({'error': 'Nincs tornaigazgató jogosultságod.'}, status=403)

        # Check global settings
        if role == 'referee' and not site_settings.application_referees_enabled:
            return JsonResponse({'error': 'Játékvezető jelentkezés nincs engedélyezve.'}, status=400)
        if role == 'inspector' and not site_settings.application_inspectors_enabled:
            return JsonResponse({'error': 'Ellenőr jelentkezés nincs engedélyezve.'}, status=400)
        if role == 'tournament_director' and not site_settings.application_tournament_directors_enabled:
            return JsonResponse({'error': 'Tornaigazgató jelentkezés nincs engedélyezve.'}, status=400)

        # Check if there's an open position with application_enabled for this role
        role_to_assignment_role = {
            'referee': MatchAssignment.Role.REFEREE,
            'inspector': MatchAssignment.Role.INSPECTOR,
            'tournament_director': MatchAssignment.Role.TOURNAMENT_DIRECTOR
        }
        open_position = MatchAssignment.objects.filter(
            match=match,
            role=role_to_assignment_role[role],
            application_enabled=True,
            placeholder_type='szukseges',
            user__isnull=True
        ).exists()
        if not open_position:
            return JsonResponse({'error': 'Nincs nyitott pozíció erre a szerepre ezen a meccsen.'}, status=400)

        # Check if already applied
        existing = MatchApplication.objects.filter(
            user=user, match=match, role=role
        ).first()

        if existing:
            if existing.status == MatchApplication.Status.PENDING:
                return JsonResponse({'error': 'Már jelentkeztél erre a meccsre.'}, status=400)
            elif existing.status == MatchApplication.Status.WITHDRAWN:
                # Reactivate withdrawn application
                existing.status = MatchApplication.Status.PENDING
                existing.save()
                return JsonResponse({'success': True, 'application_id': existing.id})

        # Check if already assigned to this match (excluding declined assignments)
        existing_assignment = MatchAssignment.objects.filter(
            user=user, match=match
        ).exclude(
            response_status=MatchAssignment.ResponseStatus.DECLINED
        ).exists()
        if existing_assignment:
            return JsonResponse({'error': 'Már ki vagy írva erre a meccsre.'}, status=400)

        # Create application
        application = MatchApplication.objects.create(
            user=user,
            match=match,
            role=role,
            status=MatchApplication.Status.PENDING
        )

        # Audit log
        from audit.utils import log_action
        role_display = dict(MatchApplication.Role.choices).get(role, role)
        log_action(
            request, 'match', 'create',
            f'Jelentkezés mérkőzésre: {match} ({role_display})',
            obj=application
        )

        return JsonResponse({'success': True, 'application_id': application.id})

    except Match.DoesNotExist:
        return JsonResponse({'error': 'Mérkőzés nem található.'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@login_required
def api_withdraw_application(request, application_id):
    """API: Withdraw a match application."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        application = MatchApplication.objects.select_related('match').get(
            pk=application_id,
            user=request.user,
            status=MatchApplication.Status.PENDING
        )

        application.status = MatchApplication.Status.WITHDRAWN
        application.save()

        # Audit log
        from audit.utils import log_action
        role_display = dict(MatchApplication.Role.choices).get(application.role, application.role)
        log_action(
            request, 'match', 'cancel',
            f'Jelentkezés visszavonva: {application.match} ({role_display})',
            obj=application
        )

        return JsonResponse({'success': True})

    except MatchApplication.DoesNotExist:
        return JsonResponse({'error': 'Jelentkezés nem található.'}, status=404)


# =============================================================================
# MATCH FEEDBACK VIEWS
# =============================================================================

@login_required
def match_feedback_list(request):
    """User-facing: List of matches that need feedback."""
    from django.db.models import Q
    from datetime import timedelta

    user = request.user
    today = timezone.localdate()

    # Get user's past accepted assignments that haven't submitted feedback yet
    # Only include matches from the past (match date < today)
    assignments_needing_feedback = MatchAssignment.objects.filter(
        user=user,
        response_status=MatchAssignment.ResponseStatus.ACCEPTED,
        match__is_deleted=False,
        match__date__lt=today
    ).exclude(
        match__status=Match.Status.CANCELLED
    ).exclude(
        feedback__isnull=False  # Exclude assignments that already have feedback
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition'
    ).order_by('-match__date', '-match__time')[:50]

    # Get assignments with feedback (for history view)
    assignments_with_feedback = MatchAssignment.objects.filter(
        user=user,
        response_status=MatchAssignment.ResponseStatus.ACCEPTED,
        feedback__isnull=False
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition',
        'feedback'
    ).order_by('-match__date', '-match__time')[:20]

    context = {
        'assignments_needing_feedback': assignments_needing_feedback,
        'assignments_with_feedback': assignments_with_feedback,
    }
    return render(request, 'matches/match_feedback_list.html', context)


@login_required
def match_feedback_submit(request, assignment_id):
    """User-facing: Submit feedback for a specific match assignment."""
    from .models import MatchFeedback, RedCardReport, RedCardWitness

    assignment = get_object_or_404(
        MatchAssignment.objects.select_related(
            'match', 'match__home_team', 'match__away_team',
            'match__venue', 'match__phase', 'match__phase__competition'
        ),
        id=assignment_id,
        user=request.user,
        response_status=MatchAssignment.ResponseStatus.ACCEPTED
    )

    # Check if feedback already exists
    existing_feedback = getattr(assignment, 'feedback', None)
    if existing_feedback:
        return redirect('matches:match_feedback_list')

    context = {
        'assignment': assignment,
        'violation_codes': RedCardReport.ViolationCode.choices,
        'offender_functions': RedCardReport.OffenderFunction.choices,
    }
    return render(request, 'matches/match_feedback_submit.html', context)


@login_required
def api_submit_feedback(request, assignment_id):
    """API: Submit match feedback."""
    from .models import MatchFeedback, RedCardReport, RedCardWitness
    import json

    if request.method != 'POST':
        return JsonResponse({'error': 'Csak POST kérés engedélyezett.'}, status=405)

    assignment = get_object_or_404(
        MatchAssignment,
        id=assignment_id,
        user=request.user,
        response_status=MatchAssignment.ResponseStatus.ACCEPTED
    )

    # Check if feedback already exists
    if hasattr(assignment, 'feedback'):
        return JsonResponse({'error': 'Már beküldted a visszajelzést ehhez a mérkőzéshez.'}, status=400)

    try:
        data = json.loads(request.body)
        feedback_type = data.get('feedback_type')
        notes = data.get('notes', '')
        red_cards = data.get('red_cards', [])

        if feedback_type not in ['ok', 'red_card', 'issue']:
            return JsonResponse({'error': 'Érvénytelen visszajelzés típus.'}, status=400)

        # Create feedback
        feedback = MatchFeedback.objects.create(
            assignment=assignment,
            feedback_type=feedback_type,
            notes=notes
        )

        # Create red card reports if any
        if feedback_type == 'red_card' and red_cards:
            for rc_data in red_cards:
                red_card = RedCardReport.objects.create(
                    feedback=feedback,
                    incident_time=rc_data.get('incident_time', '00:00'),
                    violation_code=rc_data.get('violation_code', '10'),
                    offender_name=rc_data.get('offender_name', ''),
                    offender_jersey_number=rc_data.get('offender_jersey_number', ''),
                    offender_function=rc_data.get('offender_function', 'player'),
                    offender_function_other=rc_data.get('offender_function_other', ''),
                    incident_description=rc_data.get('incident_description', '')
                )

                # Create witnesses
                witnesses = rc_data.get('witnesses', [])
                for witness_data in witnesses:
                    if witness_data.get('name') and witness_data.get('phone'):
                        RedCardWitness.objects.create(
                            red_card_report=red_card,
                            name=witness_data['name'],
                            phone=witness_data['phone']
                        )

        # Send notification to JT Admins if red card or issue
        if feedback_type in ['red_card', 'issue']:
            _notify_admins_about_feedback(feedback)

        # Log the action
        from audit.utils import log_action
        log_action(
            request, 'match', 'feedback',
            f'Mérkőzés visszajelzés: {assignment.match} ({feedback.get_feedback_type_display()})',
            obj=feedback
        )

        return JsonResponse({'success': True, 'feedback_id': feedback.id})

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Érvénytelen JSON adat.'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def _notify_admins_about_feedback(feedback):
    """Send notification to JT Admins about a match feedback with red card or issue."""
    from django.contrib.auth import get_user_model
    from documents.models import Notification
    from core.email_utils import send_templated_email

    User = get_user_model()
    jt_admins = User.objects.filter(
        role__in=['jt_admin', 'admin'],
        is_deleted=False,
        is_active=True
    )

    match = feedback.assignment.match
    feedback_type_display = feedback.get_feedback_type_display()
    red_cards = feedback.red_cards.all() if feedback.feedback_type == 'red_card' else None

    # Determine email subject based on feedback type
    if feedback.feedback_type == 'red_card':
        subject = f'Végleges kiállítás: {match}'
    elif feedback.feedback_type == 'issue':
        subject = f'Probléma jelentés: {match}'
    else:
        subject = f'Mérkőzés visszajelzés: {match}'

    for admin in jt_admins:
        # Create in-app notification
        Notification.objects.create(
            recipient=admin,
            notification_type='feedback',
            title=f'Új mérkőzés visszajelzés: {feedback_type_display}',
            message=f'{feedback.assignment.user.get_full_name()} visszajelzést küldött a(z) {match} mérkőzésről.',
            link=f'/matches/admin/feedbacks/?match={match.id}'
        )

        # Send email if enabled
        if getattr(admin, 'email_feedback_alerts', True):
            try:
                send_templated_email(
                    to_email=admin.email,
                    subject=subject,
                    template_name='match_feedback_notification',
                    context={
                        'admin': admin,
                        'feedback': feedback,
                        'match': match,
                        'red_cards': red_cards,
                    }
                )
            except Exception:
                pass  # Don't fail if email fails


@login_required
def admin_feedback_list(request):
    """Admin-facing: List all match feedbacks."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import MatchFeedback

    # Get filter values
    feedback_type = request.GET.get('type', '')
    match_id = request.GET.get('match', '')
    user_id = request.GET.get('user', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Base query
    feedbacks = MatchFeedback.objects.select_related(
        'assignment', 'assignment__user',
        'assignment__match', 'assignment__match__home_team',
        'assignment__match__away_team', 'assignment__match__venue',
        'assignment__match__phase', 'assignment__match__phase__competition'
    ).prefetch_related('red_cards').order_by('-submitted_at')

    # Apply filters
    if feedback_type:
        feedbacks = feedbacks.filter(feedback_type=feedback_type)
    if match_id:
        feedbacks = feedbacks.filter(assignment__match_id=match_id)
    if user_id:
        feedbacks = feedbacks.filter(assignment__user_id=user_id)
    if date_from:
        feedbacks = feedbacks.filter(assignment__match__date__gte=date_from)
    if date_to:
        feedbacks = feedbacks.filter(assignment__match__date__lte=date_to)

    # Get all users for filter dropdown
    from django.contrib.auth import get_user_model
    User = get_user_model()
    all_users = User.objects.filter(is_deleted=False).order_by('last_name', 'first_name')

    context = {
        'feedbacks': feedbacks[:100],
        'all_users': all_users,
        'selected_type': feedback_type,
        'selected_match': match_id,
        'selected_user': user_id,
        'date_from': date_from,
        'date_to': date_to,
        'feedback_types': MatchFeedback.FeedbackType.choices,
    }
    return render(request, 'matches/admin_feedback_list.html', context)


@login_required
def api_feedback_details(request, feedback_id):
    """API: Get feedback details including red card reports."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    from .models import MatchFeedback

    feedback = get_object_or_404(
        MatchFeedback.objects.select_related(
            'assignment', 'assignment__user',
            'assignment__match', 'assignment__match__home_team',
            'assignment__match__away_team'
        ).prefetch_related('red_cards__witnesses'),
        id=feedback_id
    )

    red_cards_data = []
    for rc in feedback.red_cards.all():
        witnesses = [{'name': w.name, 'phone': w.phone} for w in rc.witnesses.all()]
        red_cards_data.append({
            'incident_time': rc.incident_time,
            'violation_code': rc.violation_code,
            'violation_code_display': rc.get_violation_code_display(),
            'offender_name': rc.offender_name,
            'offender_jersey_number': rc.offender_jersey_number,
            'offender_function': rc.offender_function,
            'offender_function_display': rc.get_offender_function_display(),
            'offender_function_other': rc.offender_function_other,
            'incident_description': rc.incident_description,
            'witnesses': witnesses,
        })

    data = {
        'id': feedback.id,
        'feedback_type': feedback.feedback_type,
        'feedback_type_display': feedback.get_feedback_type_display(),
        'notes': feedback.notes,
        'submitted_at': feedback.submitted_at.strftime('%Y.%m.%d %H:%M'),
        'user_name': feedback.assignment.user.get_full_name(),
        'match': str(feedback.assignment.match),
        'match_date': feedback.assignment.match.date.strftime('%Y.%m.%d'),
        'red_cards': red_cards_data,
    }
    return JsonResponse(data)
