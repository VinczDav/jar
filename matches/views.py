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

from .models import Match, MatchAssignment, Season, Competition, SavedColor, Team
from .forms import MatchForm, MatchAssignmentForm, MatchResponseForm, MatchFilterForm
from audit.utils import log_action


def _notify_admins_about_decline(assignment, declining_user):
    """
    Send notification to all JT Admin / Koordinátor users when someone declines an assignment.
    """
    from django.contrib.auth import get_user_model
    from documents.models import Notification

    User = get_user_model()
    match = assignment.match

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
    teams = f"{match.home_team.name if match.home_team else 'TBD'} - {match.away_team.name if match.away_team else 'TBD'}"

    title = f"{user_name} lemondta a kijelölést"
    message = f"{date_str} {time_str}\n{teams}"
    if assignment.decline_reason:
        message += f"\nIndok: {assignment.decline_reason}"

    # Send notification to all admins
    for admin in admins:
        Notification.objects.create(
            recipient=admin,
            title=title,
            message=message,
            notification_type=Notification.Type.WARNING,
            link="/matches/assignments/"
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

    # Default date range: today to today + 7 days (for upcoming), or last 7 days (for past)
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Set default dates if not provided
    if not date_from and not date_to:
        if tab == 'upcoming':
            date_from = str(today)
            date_to = str(today + timedelta(days=7))
        elif tab == 'past':
            date_from = str(today - timedelta(days=7))
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

    # Get seasons for filter
    seasons = Season.objects.all().order_by('-start_date')

    # Get competitions for filter (based on selected season)
    competitions = Competition.objects.filter(season=selected_season) if selected_season else Competition.objects.none()

    # Get teams for filter
    teams = Team.objects.all().order_by('name')

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

    # Set default dates if not provided
    form_data = request.GET.copy() if request.GET else {}
    if not request.GET.get('date_from') and not request.GET.get('date_to'):
        if tab == 'upcoming':
            form_data['date_from'] = str(today)
            form_data['date_to'] = str(today + timedelta(days=7))
        elif tab == 'past':
            form_data['date_from'] = str(today - timedelta(days=7))
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
    if not filter_date_from and not filter_date_to:
        if tab == 'upcoming':
            filter_date_from = str(today)
            filter_date_to = str(today + timedelta(days=7))
        elif tab == 'past':
            filter_date_from = str(today - timedelta(days=7))
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

    # Get options for sidebar selects - TBD teams first, then alphabetically
    teams = Team.objects.filter(is_active=True).order_by('-is_tbd', 'name')
    venues = Venue.objects.filter(is_active=True).order_by('city', 'name')
    phases = CompetitionPhase.objects.select_related('competition')
    competitions = Competition.objects.all()
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
    assignment = get_object_or_404(
        MatchAssignment,
        id=assignment_id,
        user=request.user
    )

    if assignment.response_status != MatchAssignment.ResponseStatus.PENDING:
        messages.error(request, 'Erre a kijelölésre már válaszoltál.')
        return redirect('matches:my_matches')

    form = MatchResponseForm(request.POST)
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
    if not decline_reason:
        messages.error(request, 'Kérlek add meg a lemondás okát.')
        return redirect('matches:my_matches')

    assignment.response_status = MatchAssignment.ResponseStatus.DECLINED
    assignment.response_date = timezone.now()
    assignment.decline_reason = decline_reason
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
        competitions = Competition.objects.filter(season_id=season_id).values('id', 'short_name', 'name')
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
        'seasons': Season.objects.all().order_by('-start_date'),
        'competitions': Competition.objects.select_related('season').order_by('-season__start_date', 'name'),
        'teams': Team.objects.all().order_by('name'),
        'venues': Venue.objects.all().order_by('city', 'name'),
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
            competition.save()
            messages.success(request, f'Bajnokság frissítve: {name}')

        return redirect('matches:competitions_list')

    seasons = Season.objects.all().order_by('-start_date')
    return render(request, 'matches/competition_edit.html', {
        'competition': competition,
        'seasons': seasons,
    })


@login_required
@require_POST
def delete_competition(request, competition_id):
    """Admin: Delete a competition."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Competition

    competition = get_object_or_404(Competition, id=competition_id)
    name = competition.short_name or competition.name
    competition.delete()
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
            'referee_count': phase.referee_count,
            'reserve_count': phase.reserve_count,
            'inspector_count': phase.inspector_count,
            'requires_mfsz_declaration': phase.requires_mfsz_declaration,
        })

    return JsonResponse({'phases': phases_data})


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

        phase = CompetitionPhase.objects.create(
            competition=competition,
            name=data.get('name', 'Új szakasz'),
            payment_amount=int(data.get('payment_amount', 0)),
            payment_type=data.get('payment_type', 'per_person'),
            referee_count=int(data.get('referee_count', 2)),
            reserve_count=int(data.get('reserve_count', 0)),
            inspector_count=int(data.get('inspector_count', 0)),
        )

        return JsonResponse({
            'id': phase.id,
            'name': phase.name,
            'payment_amount': phase.payment_amount,
            'payment_type': phase.payment_type,
            'referee_count': phase.referee_count,
            'reserve_count': phase.reserve_count,
            'inspector_count': phase.inspector_count,
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
        if 'referee_count' in data:
            phase.referee_count = int(data['referee_count'])
        if 'reserve_count' in data:
            phase.reserve_count = int(data['reserve_count'])
        if 'inspector_count' in data:
            phase.inspector_count = int(data['inspector_count'])
        if 'requires_mfsz_declaration' in data:
            phase.requires_mfsz_declaration = bool(data['requires_mfsz_declaration'])

        phase.save()

        return JsonResponse({
            'id': phase.id,
            'name': phase.name,
            'payment_amount': phase.payment_amount,
            'payment_type': phase.payment_type,
            'referee_count': phase.referee_count,
            'reserve_count': phase.reserve_count,
            'inspector_count': phase.inspector_count,
            'requires_mfsz_declaration': phase.requires_mfsz_declaration,
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
        }
        if assignment.role == MatchAssignment.Role.REFEREE:
            referees.append(assignment_data)
        elif assignment.role == MatchAssignment.Role.RESERVE:
            reserves.append(assignment_data)
        elif assignment.role == MatchAssignment.Role.INSPECTOR:
            inspectors.append(assignment_data)
        elif assignment.role == MatchAssignment.Role.TOURNAMENT_DIRECTOR:
            tournament_directors.append(assignment_data)

    # Get phase settings for pre-populating slots
    phase_settings = {
        'referee_count': match.phase.referee_count if match.phase else 2,
        'reserve_count': match.phase.reserve_count if match.phase else 0,
        'inspector_count': match.phase.inspector_count if match.phase else 0,
    }

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
            'home_team': match.home_team.name if match.home_team else None,
            'away_team': match.away_team.name if match.away_team else None,
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
            'home_team': match.home_team.name if match.home_team else None,
            'away_team': match.away_team.name if match.away_team else None,
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
        def process_assignment(value, role, order):
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
                        # Reuse existing placeholder
                        kept_placeholder_ids.add(reusable.id)
                    else:
                        # Create new placeholder
                        MatchAssignment.objects.create(
                            match=match,
                            user=None,
                            placeholder_type=value,
                            role=role
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
                        # Track as newly assigned if they weren't in the original state
                        # (This handles the case where auto-save created the assignment)
                        if user_id not in existing_assigned_user_ids:
                            newly_assigned_user_ids.add(user_id)
                    else:
                        # Create new assignment
                        MatchAssignment.objects.create(
                            match=match,
                            user_id=user_id,
                            placeholder_type='',
                            role=role
                        )
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
        # Internal notifications: Sent when explicitly saving (not auto-save)
        # Email notifications: Only when send_email=True
        skip_notifications = data.get('skip_notifications', False)
        send_email = data.get('send_email', False)

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

            # Substantive change = match details changed OR personnel changed
            has_substantive_change = has_match_details_changed or has_personnel_changed
            logger.info(f"[NOTIF DEBUG] has_personnel_changed={has_personnel_changed}, has_substantive_change={has_substantive_change}")

            # Build notification message for internal notifications
            date_str = match.date.strftime('%Y.%m.%d (%A)') if match.date else 'Nincs dátum'
            time_str = match.time.strftime('%H:%M') if match.time else ''
            teams = f"{match.home_team.name if match.home_team else 'TBD'} - {match.away_team.name if match.away_team else 'TBD'}"
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
        skip_notifications = data.get('skip_notifications', False)
        send_email = data.get('send_email', False)

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
        if skip_notifications:
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

    # Check if we should send emails
    try:
        data = json.loads(request.body)
        send_email = data.get('send_email', False)
    except (json.JSONDecodeError, ValueError):
        send_email = False

    match.status = Match.Status.SCHEDULED
    match.is_assignment_published = True  # Automatikusan láthatóvá teszi a kiírást
    match.save()

    # Always send internal notifications to ALL assigned users when publishing
    # Email notifications only when send_email=True
    from documents.models import Notification
    from core.email_utils import send_match_assignment_notification

    # Refresh match with related objects for email template
    match = Match.objects.select_related('home_team', 'away_team', 'venue', 'phase__competition').get(pk=match_id)
    assignments = match.assignments.filter(user__isnull=False).select_related('user')

    if assignments.exists():
        date_str = match.date.strftime('%Y.%m.%d (%A)') if match.date else 'Nincs dátum'
        time_str = match.time.strftime('%H:%M') if match.time else ''
        teams = f"{match.home_team.name if match.home_team else 'TBD'} - {match.away_team.name if match.away_team else 'TBD'}"
        venue = match.venue.name if match.venue else 'Nincs helyszín'
        message = f"{date_str} {time_str}\n{teams}\n{venue}"
        title = "Új mérkőzésre lettél kiírva"

        match_link = f"/matches/{match.id}/"
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[PUBLISH EMAIL DEBUG] send_email={send_email}, assignments count={assignments.count()}")

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

    if send_email and email_list:
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
            'assigned_users': assigned_users_info,
            'emails_sent_to': email_list if send_email else [],
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

    # Only return users who are referees (by role or by flag)
    # Exclude deleted users and hidden users
    users = User.objects.filter(
        Q(role=User.Role.REFEREE) | Q(is_referee_flag=True),
        is_deleted=False,
        is_hidden_from_colleagues=False
    ).order_by('last_name', 'first_name')

    return JsonResponse({
        'referees': [
            {
                'id': user.id,
                'name': user.get_full_name() or user.username,
            }
            for user in users
        ]
    })


# ==================== TEAMS ====================

@login_required
def teams_list(request):
    """Admin: List all teams."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Team

    show_inactive = request.GET.get('show_inactive') == '1'
    teams = Team.objects.prefetch_related('alternative_names').order_by('name')

    if not show_inactive:
        teams = teams.filter(is_active=True)

    context = {
        'teams': teams,
        'show_inactive': show_inactive,
        'total_count': Team.objects.count(),
        'active_count': Team.objects.filter(is_active=True).count(),
    }
    return render(request, 'matches/teams_list.html', context)


@login_required
def team_edit(request, team_id=None):
    """Admin: Create or edit a team."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Team, TeamAlternativeName, Competition

    team = None
    if team_id:
        team = get_object_or_404(Team, id=team_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        short_name = request.POST.get('short_name', '').strip()
        city = request.POST.get('city', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if name:
            if team:
                team.name = name
                team.short_name = short_name
                team.city = city
                team.is_active = is_active
                if 'logo' in request.FILES:
                    team.logo = request.FILES['logo']
                team.save()
                messages.success(request, f'Csapat frissítve: {name}')
            else:
                team = Team.objects.create(
                    name=name,
                    short_name=short_name,
                    city=city,
                    is_active=is_active,
                    logo=request.FILES.get('logo')
                )
                messages.success(request, f'Csapat létrehozva: {name}')
            return redirect('matches:team_edit', team_id=team.id)

    context = {
        'team': team,
        'competitions': Competition.objects.select_related('season').order_by('-season__start_date', 'name'),
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
        messages.success(request, f'Csapat {status}: {team.name}')

    return redirect('matches:teams_list')


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

    return redirect('matches:team_edit', team_id=team_id)


@login_required
def team_delete_alternative(request, alt_id):
    """Admin: Delete alternative name."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import TeamAlternativeName

    if request.method == 'POST':
        alt = get_object_or_404(TeamAlternativeName, id=alt_id)
        team_id = alt.team_id
        alt.delete()
        messages.success(request, 'Alternatív név törölve.')
        return redirect('matches:team_edit', team_id=team_id)

    return redirect('matches:teams_list')


# ==================== VENUES ====================

@login_required
def venues_list(request):
    """Admin: List all venues."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Venue

    show_inactive = request.GET.get('show_inactive') == '1'
    venues = Venue.objects.order_by('city', 'name')

    if not show_inactive:
        venues = venues.filter(is_active=True)

    context = {
        'venues': venues,
        'show_inactive': show_inactive,
        'total_count': Venue.objects.count(),
        'active_count': Venue.objects.filter(is_active=True).count(),
    }
    return render(request, 'matches/venues_list.html', context)


@login_required
def venue_edit(request, venue_id=None):
    """Admin: Create or edit a venue."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Venue

    venue = None
    if venue_id:
        venue = get_object_or_404(Venue, id=venue_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        city = request.POST.get('city', '').strip()
        address = request.POST.get('address', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if name and city:
            if venue:
                venue.name = name
                venue.city = city
                venue.address = address
                venue.is_active = is_active
                venue.save()
                messages.success(request, f'Helyszín frissítve: {name}')
            else:
                venue = Venue.objects.create(
                    name=name,
                    city=city,
                    address=address,
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


# ==================== COMPETITIONS ====================

@login_required
def competitions_list(request):
    """Admin: List all competitions and seasons."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import Season, Competition

    context = {
        'seasons': Season.objects.all().order_by('-start_date'),
        'competitions': Competition.objects.select_related('season').prefetch_related('phases').order_by('-season__start_date', 'name'),
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
            teams = f"{match.home_team.name if match.home_team else 'TBD'} - {match.away_team.name if match.away_team else 'TBD'}"
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
def deleted_items(request):
    """Show soft-deleted items for permanent deletion."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Get all soft-deleted matches
    deleted_matches = Match.objects.filter(is_deleted=True).select_related(
        'home_team', 'away_team', 'venue', 'phase', 'phase__competition'
    ).order_by('-deleted_at')

    # Get all soft-deleted users
    deleted_users = User.objects.filter(is_deleted=True).order_by('-deleted_at')

    context = {
        'deleted_matches': deleted_matches,
        'deleted_users': deleted_users,
    }

    return render(request, 'matches/deleted_items.html', context)


@login_required
@require_POST
def api_permanently_delete_match(request, match_id):
    """API: Permanently delete a soft-deleted match."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

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
    """API: Restore a soft-deleted match."""
    if not request.user.is_jt_admin:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

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

    # Get query params
    search = request.GET.get('search', '').strip()
    show_deleted = request.GET.get('show_deleted') == '1'

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

    # Apply search filter
    if search:
        users = users.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )

    # Count for the filtered view
    if request.user.is_admin_user:
        total_count = User.objects.filter(is_deleted=False).count()
        deleted_count = User.objects.filter(is_deleted=True).count()
    else:
        # JT Admin sees referee and JT Admin counts
        user_filter = (Q(role=User.Role.REFEREE) | Q(is_referee_flag=True) |
                       Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True))
        total_count = User.objects.filter(user_filter, is_deleted=False).count()
        deleted_count = User.objects.filter(user_filter, is_deleted=True).count()

    context = {
        'users': users,
        'search': search,
        'show_deleted': show_deleted,
        'total_count': total_count,
        'deleted_count': deleted_count,
        'is_admin_view': request.user.is_admin_user,
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

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Ez az e-mail cím már foglalt!')
            return render(request, 'matches/user_edit.html', {'user_obj': None})

        # Generate password if not provided
        generated_password = password if password else get_random_string(12)

        # Create user
        user = User.objects.create_user(
            username=email,  # Use email as username
            email=email,
            password=generated_password,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
        )

        # Save additional fields
        _save_user_fields(request, user)

        # Send welcome email if checkbox is checked
        send_welcome = request.POST.get('send_password_email') == 'on'
        email_sent = False
        if send_welcome and email:
            try:
                from core.email_utils import send_welcome_email
                if send_welcome_email(user, generated_password):
                    email_sent = True
                    messages.success(request, f'Felhasználó létrehozva és üdvözlő email elküldve: {user.get_full_name() or email}')
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

        # Email update (check uniqueness)
        new_email = request.POST.get('email', '').strip()
        if new_email and new_email != user_obj.email:
            if User.objects.filter(email=new_email).exclude(id=user_obj.id).exists():
                messages.error(request, 'Ez az e-mail cím már foglalt!')
            else:
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

    return JsonResponse({
        'success': True,
        'is_hidden': user.is_hidden_from_colleagues
    })


@login_required
@require_POST
def api_user_restore(request, user_id):
    """API: Restore a soft-deleted user (Admin only)."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Csak adminisztrátor állíthat vissza törölt felhasználót.'}, status=403)

    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User.objects.filter(is_deleted=True), id=user_id)

    # Restore user - also re-enable login and unhide
    user.is_deleted = False
    user.deleted_at = None
    user.is_hidden_from_colleagues = False
    user.is_login_disabled = False
    user.save()

    # Audit log - user restored
    from audit.utils import log_action
    log_action(
        request,
        'user',
        'update',
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
def api_user_permanently_delete(request, user_id):
    """API: Permanently delete a soft-deleted user."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

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
