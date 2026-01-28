from django.contrib.auth.decorators import login_required
from django.db.models import Q, Avg
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.utils import timezone
from accounts.models import User
from matches.models import Match, MatchAssignment, Season, Competition
from .models import Referee, Unavailability, InspectorReport, RefereeEvaluation
import json


@login_required
def feedbacks(request):
    """Show inspector feedbacks for current user."""
    from datetime import timedelta
    user = request.user
    today = timezone.localtime(timezone.now()).date()

    # Get filter parameters
    season_id = request.GET.get('season', '')
    competition_id = request.GET.get('competition', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    inspector_id = request.GET.get('inspector', '')

    # Set default dates if not provided (past 7 days for past feedbacks)
    if not date_from and not date_to:
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

    # Get evaluations where user is the referee (from submitted reports)
    evaluations = RefereeEvaluation.objects.filter(
        referee=user,
        report__status=InspectorReport.Status.SUBMITTED
    ).select_related(
        'report', 'report__match', 'report__inspector',
        'report__match__home_team', 'report__match__away_team',
        'report__match__venue', 'report__match__phase',
        'report__match__phase__competition'
    )

    # Apply season filter
    if selected_season:
        evaluations = evaluations.filter(report__match__phase__competition__season=selected_season)

    # Apply other filters
    if competition_id:
        evaluations = evaluations.filter(report__match__phase__competition_id=competition_id)
    if date_from:
        evaluations = evaluations.filter(report__match__date__gte=date_from)
    if date_to:
        evaluations = evaluations.filter(report__match__date__lte=date_to)
    if inspector_id:
        evaluations = evaluations.filter(report__inspector_id=inspector_id)

    # Build feedbacks data
    feedbacks_data = []
    for evaluation in evaluations.order_by('-report__match__date', '-report__match__time'):
        feedbacks_data.append({
            'match': evaluation.report.match,
            'inspector': evaluation.report.inspector,
            'evaluation': evaluation,
        })

    # Get seasons for filter
    seasons = Season.objects.all().order_by('-start_date')

    # Get competitions for filter
    competitions = Competition.objects.filter(season=selected_season) if selected_season else Competition.objects.none()

    # Get inspectors for filter (users who have submitted evaluations for this user)
    inspector_user_ids = RefereeEvaluation.objects.filter(
        referee=user,
        report__status=InspectorReport.Status.SUBMITTED
    ).values_list('report__inspector_id', flat=True).distinct()
    inspectors = User.objects.filter(id__in=inspector_user_ids).order_by('last_name', 'first_name')

    context = {
        'feedbacks': feedbacks_data,
        'seasons': seasons,
        'selected_season': selected_season,
        'competitions': competitions,
        'selected_competition': competition_id,
        'date_from': date_from,
        'date_to': date_to,
        'inspectors': inspectors,
        'selected_inspector': inspector_id,
    }

    return render(request, 'referees/feedbacks.html', context)


@login_required
def unavailability(request):
    """Manage unavailability periods."""
    user = request.user

    # Get or create referee profile
    try:
        referee = user.referee_profile
    except Referee.DoesNotExist:
        referee = Referee.objects.create(user=user)

    # Get user's unavailabilities
    unavailabilities = Unavailability.objects.filter(referee=referee).order_by('-start_date')

    # Get current month/year for calendar
    today = timezone.localtime(timezone.now()).date()  # Use local time for date
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))

    context = {
        'unavailabilities': unavailabilities,
        'current_year': year,
        'current_month': month,
    }

    return render(request, 'referees/unavailability.html', context)


@login_required
@require_POST
def add_unavailability(request):
    """Add a new unavailability period."""
    user = request.user

    try:
        referee = user.referee_profile
    except Referee.DoesNotExist:
        referee = Referee.objects.create(user=user)

    try:
        data = json.loads(request.body)
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        reason = data.get('reason', '')

        if not start_date or not end_date:
            return JsonResponse({'error': 'Hiányzó dátumok'}, status=400)

        Unavailability.objects.create(
            referee=referee,
            start_date=start_date,
            end_date=end_date,
            reason=reason
        )

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_POST
def delete_unavailability(request, unavailability_id):
    """Delete an unavailability period."""
    user = request.user

    try:
        referee = user.referee_profile
    except Referee.DoesNotExist:
        return JsonResponse({'error': 'Nincs jogosultságod'}, status=403)

    unavailability = get_object_or_404(Unavailability, id=unavailability_id, referee=referee)
    unavailability.delete()

    return JsonResponse({'success': True})


@login_required
def colleagues(request):
    """Show colleague list with contact info."""
    # Base filter: active, not hidden, not deleted
    base_filter = Q(is_active=True, is_hidden_from_colleagues=False, is_deleted=False)

    # Get JT Admins (primary role OR jt_admin flag)
    jt_admins = User.objects.filter(
        base_filter & (Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True))
    ).order_by('last_name', 'first_name')

    # Get Referees: primary role is REFEREE, OR has is_referee_flag
    # Exclude those already shown as JT Admins
    referees = User.objects.filter(
        base_filter & (Q(role=User.Role.REFEREE) | Q(is_referee_flag=True))
    ).exclude(
        Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True)
    ).order_by('last_name', 'first_name')

    # Get list of users who are inspectors
    inspector_ids = set(User.objects.filter(
        base_filter & (Q(role=User.Role.INSPECTOR) | Q(is_inspector_flag=True))
    ).values_list('id', flat=True))

    context = {
        'jt_admins': jt_admins,
        'referees': referees,
        'inspector_ids': inspector_ids,
    }
    return render(request, 'referees/colleagues.html', context)


@login_required
def profiles(request):
    """JT Admin: Manage referee profiles."""
    if not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    # Show users who are:
    # - Referees (by role OR by flag)
    # - JT Admins (by role OR by flag)
    users = User.objects.filter(
        Q(role=User.Role.REFEREE) | Q(is_referee_flag=True) |
        Q(role=User.Role.JT_ADMIN) | Q(is_jt_admin_flag=True),
        is_deleted=False
    ).order_by('last_name', 'first_name')

    context = {
        'users': users,
    }
    return render(request, 'referees/profiles.html', context)


@login_required
def reports(request):
    """Inspector: View reports."""
    if not request.user.is_inspector:
        return HttpResponseForbidden('Nincs jogosultságod.')

    # Get all reports created by this inspector
    reports = InspectorReport.objects.filter(
        inspector=request.user
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition'
    ).prefetch_related('evaluations', 'evaluations__referee').order_by('-created_at')

    context = {
        'reports': reports,
    }
    return render(request, 'referees/reports.html', context)


@login_required
def view_report(request, report_id):
    """View a single inspector report."""
    report = get_object_or_404(InspectorReport, id=report_id)

    # Check permission: inspector can view their own, referee can view if they're evaluated
    is_owner = report.inspector == request.user
    is_evaluated = report.evaluations.filter(referee=request.user).exists()

    if not is_owner and not is_evaluated and not request.user.is_jt_admin:
        return HttpResponseForbidden('Nincs jogosultságod.')

    context = {
        'report': report,
        'evaluations': report.evaluations.all().select_related('referee'),
        'is_owner': is_owner,
    }
    return render(request, 'referees/view_report.html', context)


@login_required
def create_report(request):
    """Inspector: Create new report."""
    if not request.user.is_inspector:
        return HttpResponseForbidden('Nincs jogosultságod.')

    today = timezone.localtime(timezone.now()).date()

    # Get matches where the user was assigned as an inspector
    # Exclude matches that already have a report from this inspector
    existing_report_match_ids = InspectorReport.objects.filter(
        inspector=request.user
    ).values_list('match_id', flat=True)

    inspector_assignments = MatchAssignment.objects.filter(
        user=request.user,
        role=MatchAssignment.Role.INSPECTOR,
        match__date__lt=today  # Only past matches
    ).exclude(
        match__status=Match.Status.CANCELLED
    ).exclude(
        match_id__in=existing_report_match_ids
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition'
    ).order_by('-match__date', '-match__time')

    # Build match data with referees
    available_matches = []
    for assignment in inspector_assignments:
        match = assignment.match
        referees = match.assignments.filter(
            role__in=[MatchAssignment.Role.REFEREE, MatchAssignment.Role.RESERVE],
            user__isnull=False
        ).exclude(
            response_status=MatchAssignment.ResponseStatus.DECLINED
        ).select_related('user')

        available_matches.append({
            'match': match,
            'referees': [a.user for a in referees],
        })

    if request.method == 'POST':
        match_id = request.POST.get('match_id')
        general_notes = request.POST.get('notes', '')

        if not match_id:
            return JsonResponse({'error': 'Nincs mérkőzés kiválasztva'}, status=400)

        # Verify the match is in available_matches
        match = None
        referees = []
        for item in available_matches:
            if str(item['match'].id) == str(match_id):
                match = item['match']
                referees = item['referees']
                break

        if not match:
            return JsonResponse({'error': 'Érvénytelen mérkőzés'}, status=400)

        # Create the report
        report = InspectorReport.objects.create(
            match=match,
            inspector=request.user,
            status=InspectorReport.Status.SUBMITTED,
            general_notes=general_notes
        )

        # Create evaluations for each referee
        for referee in referees:
            rules = request.POST.get(f'referee_{referee.id}_rules', 3)
            positioning = request.POST.get(f'referee_{referee.id}_positioning', 3)
            communication = request.POST.get(f'referee_{referee.id}_communication', 3)
            fitness = request.POST.get(f'referee_{referee.id}_fitness', 3)
            overall = request.POST.get(f'referee_{referee.id}_overall', 3)
            notes = request.POST.get(f'referee_{referee.id}_notes', '')

            # Convert to int with default
            try:
                rules = int(rules) if rules else 3
                positioning = int(positioning) if positioning else 3
                communication = int(communication) if communication else 3
                fitness = int(fitness) if fitness else 3
                overall = int(overall) if overall else 3
            except ValueError:
                rules = positioning = communication = fitness = overall = 3

            # Clamp values to 1-5
            rules = max(1, min(5, rules))
            positioning = max(1, min(5, positioning))
            communication = max(1, min(5, communication))
            fitness = max(1, min(5, fitness))
            overall = max(1, min(5, overall))

            RefereeEvaluation.objects.create(
                report=report,
                referee=referee,
                rules_knowledge=rules,
                positioning=positioning,
                communication=communication,
                fitness=fitness,
                overall_rating=overall,
                notes=notes
            )

        # Send notification to each evaluated referee
        from documents.models import Notification

        date_str = match.date.strftime('%Y.%m.%d') if match.date else ''
        teams = f"{match.home_team.name if match.home_team else 'TBD'} - {match.away_team.name if match.away_team else 'TBD'}"
        inspector_name = request.user.get_full_name()

        for referee in referees:
            Notification.objects.create(
                recipient=referee,
                title="Új ellenőri jelentést kaptál",
                message=f"{date_str}\n{teams}\n\nEllenőr: {inspector_name}",
                notification_type=Notification.Type.INFO,
                link="/referees/feedbacks/"
            )

        return redirect('referees:view_report', report_id=report.id)

    context = {
        'available_matches': available_matches,
    }
    return render(request, 'referees/create_report.html', context)
