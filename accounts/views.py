from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.utils import timezone
from datetime import timedelta
from .models import User
from audit.utils import log_action, get_client_ip
from core.turnstile import verify_turnstile, get_turnstile_context
from core.email_utils import send_security_alert
from core.validators import validate_password_complexity
from documents.models import Notification


def home(request):
    """Home page - redirect based on authentication status."""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')
    return redirect('matches:public_matches')


def _notify_admins_failed_login(user, request):
    """Értesítés küldése adminoknak 10+ sikertelen bejelentkezés esetén."""
    admins = User.objects.filter(
        models.Q(role=User.Role.ADMIN) | models.Q(is_admin_flag=True),
        is_deleted=False
    )
    ip = get_client_ip(request)

    # Send in-app notifications
    for admin in admins:
        Notification.objects.create(
            recipient=admin,
            title='Figyelmeztetés: Többszörös sikertelen bejelentkezés',
            message=f'{user.get_full_name()} ({user.email}) felhasználónak {user.failed_login_count} sikertelen bejelentkezési kísérlete volt.\n\nUtolsó IP: {ip}',
            notification_type=Notification.Type.WARNING,
            link=f'/admin/users/{user.id}/edit/'
        )

    # Send email alert to admins
    send_security_alert(user, 'failed_logins', request=request)


def login_view(request):
    """Handle user login with Turnstile and audit logging."""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    error = None
    context = get_turnstile_context()

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        # Turnstile verification
        turnstile_token = request.POST.get('cf-turnstile-response', '')
        ip_address = get_client_ip(request)

        if not verify_turnstile(turnstile_token, ip_address):
            error = 'A bejelentkezés jelenleg nem lehetséges. Kérjük, próbáld újra.'
            log_action(request, 'auth', 'login_failed', f'Turnstile ellenőrzés sikertelen - {email}', extra={'email': email, 'reason': 'turnstile_failed', 'ip': ip_address})
            context['error'] = error
            return render(request, 'accounts/login.html', context)

        # First check if user exists and is not deleted/archived/disabled
        try:
            user_check = User.objects.get(email=email)
            # Deleted users: show generic error as if user doesn't exist
            if user_check.is_deleted:
                error = 'Hibás e-mail cím vagy jelszó.'
                log_action(request, 'auth', 'login_failed', f'Bejelentkezés törölve fiókkal - {email}', extra={'email': email, 'reason': 'deleted'})
                context['error'] = error
                return render(request, 'accounts/login.html', context)
            # Archived users (excluded/banned): show generic error as if user doesn't exist
            if user_check.is_archived:
                error = 'Hibás e-mail cím vagy jelszó.'
                log_action(request, 'auth', 'login_failed', f'Bejelentkezés kizárt fiókkal - {email}', extra={'email': email, 'reason': 'archived'})
                context['error'] = error
                return render(request, 'accounts/login.html', context)
            # Login disabled users
            if user_check.is_login_disabled:
                error = 'A bejelentkezés letiltva erre a fiókra.'
                log_action(request, 'auth', 'login_failed', f'Bejelentkezés tiltott fiókkal - {email}', extra={'email': email, 'reason': 'disabled'})
                context['error'] = error
                return render(request, 'accounts/login.html', context)
        except User.DoesNotExist:
            pass  # User doesn't exist, will fail auth below

        # Try to authenticate with email as username
        user = authenticate(request, username=email, password=password)

        if user is not None:
            # Sikeres bejelentkezés
            login(request, user)

            # Reset failed login counter
            if hasattr(user, 'failed_login_count') and user.failed_login_count > 0:
                user.failed_login_count = 0
                user.save(update_fields=['failed_login_count'])

            # Log successful login
            log_action(request, 'auth', 'login', f'Sikeres bejelentkezés - {user.get_full_name()}', obj=user)

            # Check if password change is required
            if user.must_change_password:
                return redirect('accounts:force_password_change')

            next_url = request.GET.get('next', 'accounts:dashboard')
            return redirect(next_url)
        else:
            # Sikertelen bejelentkezés
            error = 'Hibás e-mail cím vagy jelszó.'

            # Increment failed login counter if user exists
            try:
                user_check = User.objects.get(email=email)
                if hasattr(user_check, 'failed_login_count'):
                    user_check.failed_login_count = (user_check.failed_login_count or 0) + 1
                    user_check.last_failed_login = timezone.now()
                    user_check.save(update_fields=['failed_login_count', 'last_failed_login'])

                    # Notify admins after configured number of failed attempts
                    from .models import SiteSettings, NotificationSettings
                    site_settings = SiteSettings.get_settings()
                    notif_settings = NotificationSettings.get_settings()
                    max_attempts = site_settings.max_failed_login_attempts
                    if user_check.failed_login_count == max_attempts and notif_settings.notify_failed_logins:
                        _notify_admins_failed_login(user_check, request)

                log_action(request, 'auth', 'login_failed', f'Sikertelen bejelentkezés - {email} ({user_check.failed_login_count}. kísérlet)', obj=user_check, extra={'email': email, 'attempt': user_check.failed_login_count})
            except User.DoesNotExist:
                log_action(request, 'auth', 'login_failed', f'Sikertelen bejelentkezés - nem létező email: {email}', extra={'email': email, 'reason': 'user_not_found'})

    context['error'] = error
    return render(request, 'accounts/login.html', context)


def logout_view(request):
    """Handle user logout with audit logging."""
    if request.user.is_authenticated:
        log_action(request, 'auth', 'logout', f'Kijelentkezés - {request.user.get_full_name()}', obj=request.user)
    logout(request)
    return redirect('accounts:login')


@login_required
def force_password_change(request):
    """Force password change for users who must change their password."""
    user = request.user

    # If user doesn't need to change password, redirect to dashboard
    if not user.must_change_password:
        return redirect('accounts:dashboard')

    error = None
    success = None

    if request.method == 'POST':
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        # Validate current password
        if not user.check_password(current_password):
            error = 'A jelenlegi jelszó hibás.'
        elif new_password != confirm_password:
            error = 'A két jelszó nem egyezik.'
        elif current_password == new_password:
            error = 'Az új jelszó nem lehet ugyanaz, mint a régi.'
        else:
            # Validate password complexity
            is_valid, complexity_error = validate_password_complexity(new_password)
            if not is_valid:
                error = complexity_error

        if not error:
            # Change password
            user.set_password(new_password)
            user.must_change_password = False
            user.save(update_fields=['password', 'must_change_password'])

            # Log the action
            log_action(request, 'auth', 'update', f'Jelszó megváltoztatva (első belépés) - {user.get_full_name()}', obj=user)

            # Re-login with new password
            login(request, user)

            return redirect('accounts:dashboard')

    return render(request, 'accounts/force_password_change.html', {
        'error': error,
    })


def password_reset_request(request):
    """Request password reset - sends email with reset link."""
    from core.rate_limiter import (
        check_rate_limit,
        PASSWORD_RESET_MAX_ATTEMPTS,
        PASSWORD_RESET_WINDOW,
        PASSWORD_RESET_IP_MAX_ATTEMPTS,
        PASSWORD_RESET_IP_WINDOW,
    )

    error = None
    success = None
    context = get_turnstile_context()

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        ip_address = get_client_ip(request)

        # Rate limit check - IP based (max 10 requests per IP per hour)
        ip_allowed, ip_remaining, ip_reset = check_rate_limit(
            f'password_reset_ip:{ip_address}',
            PASSWORD_RESET_IP_MAX_ATTEMPTS,
            PASSWORD_RESET_IP_WINDOW
        )

        if not ip_allowed:
            minutes_remaining = ip_reset // 60
            error = f'Túl sok kérés érkezett erről az IP címről. Próbáld újra {minutes_remaining} perc múlva.'
            log_action(request, 'auth', 'login_failed', f'Jelszó visszaállítás IP rate limit - {ip_address}', extra={'ip': ip_address, 'reason': 'ip_rate_limit'})
            context['error'] = error
            return render(request, 'accounts/password_reset_request.html', context)

        # Turnstile verification
        turnstile_token = request.POST.get('cf-turnstile-response', '')

        if not verify_turnstile(turnstile_token, ip_address):
            error = 'A kérés jelenleg nem lehetséges. Kérjük, próbáld újra.'
            context['error'] = error
            return render(request, 'accounts/password_reset_request.html', context)

        if not email:
            error = 'Kérlek add meg az e-mail címed.'
        else:
            # Rate limit check - Email based (max 3 requests per email per hour)
            email_allowed, email_remaining, email_reset = check_rate_limit(
                f'password_reset_email:{email}',
                PASSWORD_RESET_MAX_ATTEMPTS,
                PASSWORD_RESET_WINDOW
            )

            if not email_allowed:
                minutes_remaining = email_reset // 60
                # Don't reveal if rate limit is for this specific email
                success = 'Ha a megadott e-mail cím létezik a rendszerben, küldtünk egy jelszó visszaállító linket.'
                log_action(request, 'auth', 'login_failed', f'Jelszó visszaállítás email rate limit - {email}', extra={'email': email, 'ip': ip_address, 'reason': 'email_rate_limit'})
            else:
                try:
                    user = User.objects.get(email=email, is_deleted=False)

                    if user.is_login_disabled:
                        # Don't reveal account status - show generic message
                        success = 'Ha a megadott e-mail cím létezik a rendszerben, küldtünk egy jelszó visszaállító linket.'
                    else:
                        # Generate reset token using Django's built-in token generator
                        from django.contrib.auth.tokens import default_token_generator
                        from django.utils.http import urlsafe_base64_encode
                        from django.utils.encoding import force_bytes

                        uid = urlsafe_base64_encode(force_bytes(user.pk))
                        token = default_token_generator.make_token(user)

                        # Send email
                        from core.email_utils import send_templated_email
                        reset_url = f"{settings.SITE_URL}/password-reset/{uid}/{token}/"

                        send_templated_email(
                            to_email=user.email,
                            subject='Jelszó visszaállítás - JAR',
                            template_name='password_reset_link',
                            context={
                                'user': user,
                                'reset_url': reset_url,
                            }
                        )

                        log_action(request, 'auth', 'update', f'Jelszó visszaállítás kérve - {user.email}', obj=user, extra={'ip': ip_address})
                        success = 'Ha a megadott e-mail cím létezik a rendszerben, küldtünk egy jelszó visszaállító linket.'

                except User.DoesNotExist:
                    # Don't reveal if email exists or not - always show same message
                    success = 'Ha a megadott e-mail cím létezik a rendszerben, küldtünk egy jelszó visszaállító linket.'

    context['error'] = error
    context['success'] = success
    return render(request, 'accounts/password_reset_request.html', context)


def password_reset_confirm(request, uidb64, token):
    """Confirm password reset with token."""
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_decode

    error = None
    success = None
    valid_link = False

    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
        valid_link = default_token_generator.check_token(user, token)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
        valid_link = False

    if not valid_link:
        return render(request, 'accounts/password_reset_confirm.html', {
            'valid_link': False,
            'error': 'Ez a link érvénytelen vagy már lejárt. Kérj új jelszó visszaállító linket.',
        })

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if new_password != confirm_password:
            error = 'A két jelszó nem egyezik.'
        else:
            # Validate password complexity
            is_valid, complexity_error = validate_password_complexity(new_password)
            if not is_valid:
                error = complexity_error

        if not error:
            # Change password
            user.set_password(new_password)
            user.must_change_password = False
            user.save(update_fields=['password', 'must_change_password'])

            log_action(request, 'auth', 'update', f'Jelszó visszaállítva linkkel - {user.get_full_name()}', obj=user)

            success = 'A jelszavad sikeresen megváltozott! Most már bejelentkezhetsz.'

            return render(request, 'accounts/password_reset_confirm.html', {
                'valid_link': True,
                'success': success,
                'password_changed': True,
            })

    return render(request, 'accounts/password_reset_confirm.html', {
        'valid_link': True,
        'error': error,
    })


def initial_password_setup(request, uidb64, token):
    """
    Initial password setup for new users.
    Uses 24-hour token instead of 15-minute password reset token.
    """
    from django.utils.http import urlsafe_base64_decode
    from core.validators import initial_password_token_generator

    error = None
    success = None
    valid_link = False

    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)
        valid_link = initial_password_token_generator.check_token(user, token)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
        valid_link = False

    if not valid_link:
        return render(request, 'accounts/password_reset_confirm.html', {
            'valid_link': False,
            'error': 'Ez a link érvénytelen vagy már lejárt. Kérd az adminisztrátortól, hogy küldjön új meghívót.',
            'is_initial_setup': True,
        })

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if new_password != confirm_password:
            error = 'A két jelszó nem egyezik.'
        else:
            # Validate password complexity
            is_valid, complexity_error = validate_password_complexity(new_password)
            if not is_valid:
                error = complexity_error

        if not error:
            # Set password and clear the must_change_password flag
            user.set_password(new_password)
            user.must_change_password = False
            user.save(update_fields=['password', 'must_change_password'])

            log_action(request, 'auth', 'update', f'Jelszó beállítva (új felhasználó) - {user.get_full_name()}', obj=user)

            success = 'A jelszavad sikeresen beállítva! Most már bejelentkezhetsz.'

            return render(request, 'accounts/password_reset_confirm.html', {
                'valid_link': True,
                'success': success,
                'password_changed': True,
                'is_initial_setup': True,
            })

    return render(request, 'accounts/password_reset_confirm.html', {
        'valid_link': True,
        'error': error,
        'is_initial_setup': True,
    })


@login_required
def dashboard(request):
    """Main dashboard after login."""
    from matches.models import Match, MatchAssignment
    from education.models import News
    from datetime import timedelta
    from django.db.models import Q, Count

    # Time-based filtering: match is "upcoming" if start time + 1 minute hasn't passed yet
    now = timezone.localtime(timezone.now())  # Convert to local time (Europe/Budapest)
    today = now.date()
    one_min_ago = (now - timedelta(minutes=1)).time()

    # Get upcoming matches where user is assigned (exclude draft, deleted, and declined)
    upcoming_assignments = MatchAssignment.objects.filter(
        user=request.user,
        match__is_assignment_published=True,
        match__is_deleted=False  # Exclude soft-deleted matches
    ).exclude(
        match__status=Match.Status.DRAFT
    ).exclude(
        response_status=MatchAssignment.ResponseStatus.DECLINED  # User declined - don't show
    ).filter(
        # Upcoming: start time + 1 minute hasn't passed yet
        Q(match__date__gt=today) |
        Q(match__date=today, match__time__isnull=True) |
        Q(match__date=today, match__time__gt=one_min_ago)
    ).select_related(
        'match', 'match__home_team', 'match__away_team',
        'match__venue', 'match__phase', 'match__phase__competition'
    ).order_by('match__date', 'match__time')[:10]

    upcoming_matches = [a.match for a in upcoming_assignments]

    # Get news based on user permissions
    if request.user.has_content_module:
        # Content creators see all news (including their own unpublished/hidden)
        news_list = News.objects.filter(
            Q(is_published=True) |
            Q(scheduled_at__isnull=False, scheduled_at__lte=now) |
            Q(created_by=request.user)
        ).distinct().order_by('-is_pinned', 'order', '-published_at', '-created_at')[:20]
    else:
        # Regular users see only published and not hidden news
        news_list = News.objects.filter(
            Q(is_published=True) |
            Q(scheduled_at__isnull=False, scheduled_at__lte=now)
        ).filter(
            is_hidden=False
        ).distinct().order_by('-is_pinned', 'order', '-published_at', '-created_at')[:10]

    context = {
        'upcoming_matches': upcoming_matches,
        'upcoming_assignments': upcoming_assignments,
        'news_list': news_list,
        'now': now,
    }

    # Admin statistics
    if request.user.is_admin_user or request.user.is_jt_admin:
        from billing.models import TravelCost

        # Date ranges
        this_month_start = today.replace(day=1)
        next_7_days = today + timedelta(days=7)

        # Total active users
        total_users = User.objects.filter(is_active=True, is_deleted=False).count()

        # Active referees (is_referee or is_referee_flag)
        active_referees = User.objects.filter(
            is_active=True, is_deleted=False
        ).filter(
            Q(role=User.Role.REFEREE) | Q(is_referee_flag=True)
        ).distinct().count()

        # Upcoming matches (next 7 days, published)
        upcoming_matches_count = Match.objects.filter(
            is_deleted=False,
            is_assignment_published=True,
            date__gte=today,
            date__lte=next_7_days
        ).count()

        # Unaccepted assignments (pending response status for upcoming matches)
        unaccepted_assignments = MatchAssignment.objects.filter(
            match__is_deleted=False,
            match__is_assignment_published=True,
            match__date__gte=today,
            response_status=MatchAssignment.ResponseStatus.PENDING
        ).count()

        # Travel costs awaiting approval
        pending_travel_costs = TravelCost.objects.filter(
            status='submitted'
        ).count()

        # Matches without assigned referees (next 7 days)
        matches_without_referees = Match.objects.filter(
            is_deleted=False,
            date__gte=today,
            date__lte=next_7_days
        ).annotate(
            referee_count=Count('assignments', filter=Q(assignments__user__isnull=False))
        ).filter(referee_count=0).count()

        context['admin_stats'] = {
            'total_users': total_users,
            'active_referees': active_referees,
            'upcoming_matches': upcoming_matches_count,
            'unaccepted_assignments': unaccepted_assignments,
            'pending_travel_costs': pending_travel_costs,
            'matches_without_referees': matches_without_referees,
        }

    # Server statistics (Admin only, not JT Admin)
    if request.user.is_admin_user:
        try:
            import psutil
            import platform

            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()

            # Memory
            memory = psutil.virtual_memory()
            memory_total_gb = round(memory.total / (1024 ** 3), 1)
            memory_used_gb = round(memory.used / (1024 ** 3), 1)
            memory_percent = memory.percent

            # Disk
            disk = psutil.disk_usage('/')
            disk_total_gb = round(disk.total / (1024 ** 3), 1)
            disk_used_gb = round(disk.used / (1024 ** 3), 1)
            disk_percent = disk.percent

            # System info
            system_info = {
                'os': platform.system(),
                'os_version': platform.release(),
                'python_version': platform.python_version(),
                'hostname': platform.node(),
            }

            context['server_stats'] = {
                'cpu_percent': cpu_percent,
                'cpu_count': cpu_count,
                'memory_total_gb': memory_total_gb,
                'memory_used_gb': memory_used_gb,
                'memory_percent': memory_percent,
                'disk_total_gb': disk_total_gb,
                'disk_used_gb': disk_used_gb,
                'disk_percent': disk_percent,
                'system_info': system_info,
            }
        except ImportError:
            # psutil not installed
            context['server_stats'] = None

    return render(request, 'accounts/dashboard.html', context)


@login_required
def database_redirect(request):
    """
    Redirect to Django Admin for super admins only.
    The user is already authenticated, so no re-login needed.
    """
    # Check if user has permission to access admin - only super admins
    is_super = getattr(request.user, 'is_super_admin', False)
    if not (request.user.is_superuser or is_super):
        return HttpResponseForbidden('Csak Super Admin férhet hozzá az adatbázis kezeléshez.')

    # Check if admin is enabled
    if not settings.ADMIN_ENABLED:
        return HttpResponseForbidden('Az adatbázis kezelés jelenleg nem elérhető.')

    # Redirect to the secret admin URL
    return redirect(f'/{settings.ADMIN_URL_PATH}')


@login_required
def users_list(request):
    """User management for admins."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    users = User.objects.all().order_by('last_name', 'first_name')
    return render(request, 'accounts/users.html', {'users': users})


@login_required
def api_get_notifications(request):
    """API: Get user notifications."""
    from documents.models import Notification
    from django.http import JsonResponse
    from datetime import timedelta

    # Get all notifications from the last 30 days
    thirty_days_ago = timezone.now() - timedelta(days=30)

    notifications = Notification.objects.filter(
        recipient=request.user,
        created_at__gte=thirty_days_ago
    ).order_by('-created_at')

    # Get total count before slicing
    total_count = notifications.count()

    # Limit parameter for initial view (default 3)
    limit = request.GET.get('limit', '3')
    if limit != 'all':
        notifications = notifications[:int(limit)]

    data = []
    for notif in notifications:
        data.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'type': notif.notification_type,
            'is_read': notif.is_read,
            'link': notif.link,
            'created_at': timezone.localtime(notif.created_at).strftime('%Y.%m.%d %H:%M')
        })

    return JsonResponse({'notifications': data, 'total_count': total_count})


@login_required
def api_mark_notification_read(request, notification_id):
    """API: Mark notification as read."""
    from documents.models import Notification
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        notification = Notification.objects.get(
            id=notification_id,
            recipient=request.user
        )
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()

        return JsonResponse({'success': True})
    except Notification.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)


@login_required
def api_mark_all_notifications_read(request):
    """API: Mark all notifications as read."""
    from documents.models import Notification
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    Notification.objects.filter(
        recipient=request.user,
        is_read=False
    ).update(
        is_read=True,
        read_at=timezone.now()
    )

    return JsonResponse({'success': True})


@login_required
def admin_settings(request):
    """Admin settings page - dangerous operations. Admin only."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from matches.models import Match, MatchAssignment, CompetitionPhase
    from documents.models import Notification
    from .models import SiteSettings, Coordinator

    # Get or create site settings
    site_settings = SiteSettings.get_settings()

    # Get all coordinators (with user data prefetched)
    coordinators = list(Coordinator.objects.select_related('user').all())

    # Get JT Admin users who are not yet coordinators
    # Use the already fetched coordinators to avoid duplicate query
    existing_coordinator_user_ids = [c.user_id for c in coordinators]
    jt_admin_users = User.objects.filter(
        models.Q(role=User.Role.JT_ADMIN) |
        models.Q(is_jt_admin_flag=True) |
        models.Q(role=User.Role.ADMIN) |
        models.Q(is_admin_flag=True)
    ).exclude(
        id__in=existing_coordinator_user_ids
    ).order_by('last_name', 'first_name')

    # Get counts
    match_count = Match.objects.count()
    assignment_count = MatchAssignment.objects.count()
    notification_count = Notification.objects.count()

    # Count phases with applications enabled
    application_phase_count = CompetitionPhase.objects.filter(
        models.Q(referee_application_enabled=True) |
        models.Q(inspector_application_enabled=True) |
        models.Q(tournament_director_application_enabled=True)
    ).count()

    context = {
        'match_count': match_count,
        'assignment_count': assignment_count,
        'notification_count': notification_count,
        'site_settings': site_settings,
        'coordinators': coordinators,
        'jt_admin_users': jt_admin_users,
        'application_phase_count': application_phase_count,
    }

    return render(request, 'accounts/admin_settings.html', context)


@login_required
def api_delete_all_matches(request):
    """API: Soft delete all matches (hide but keep in database). Admin only."""
    from django.http import JsonResponse
    from django.utils import timezone
    from matches.models import Match

    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    # Soft delete - mark all as deleted but keep in database
    count = Match.objects.filter(is_deleted=False).count()
    Match.objects.filter(is_deleted=False).update(
        is_deleted=True,
        deleted_at=timezone.now()
    )

    return JsonResponse({'success': True, 'deleted': count})


@login_required
def api_delete_all_notifications(request):
    """API: Delete all notifications. Admin only."""
    from django.http import JsonResponse
    from documents.models import Notification

    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    count = Notification.objects.count()
    Notification.objects.all().delete()

    return JsonResponse({'success': True, 'deleted': count})


@login_required
def api_save_site_settings(request):
    """API: Save site settings. Admin only."""
    from django.http import JsonResponse
    from .models import SiteSettings
    import json

    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)

        site_settings = SiteSettings.get_settings()

        # Update fields
        if 'min_cancellation_hours' in data:
            hours = int(data['min_cancellation_hours'])
            if hours < 0:
                return JsonResponse({'error': 'Az óraszám nem lehet negatív.'}, status=400)
            site_settings.min_cancellation_hours = hours

        if 'require_cancellation_reason' in data:
            site_settings.require_cancellation_reason = bool(data['require_cancellation_reason'])

        # Security settings
        if 'max_failed_login_attempts' in data:
            attempts = int(data['max_failed_login_attempts'])
            if attempts < 1:
                return JsonResponse({'error': 'A próbálkozások száma minimum 1 kell legyen.'}, status=400)
            site_settings.max_failed_login_attempts = attempts

        if 'session_timeout_hours' in data:
            hours = int(data['session_timeout_hours'])
            if hours < 1:
                return JsonResponse({'error': 'A session időtartam minimum 1 óra kell legyen.'}, status=400)
            site_settings.session_timeout_hours = hours

        # Application settings
        if 'application_referees_enabled' in data:
            site_settings.application_referees_enabled = bool(data['application_referees_enabled'])
        if 'application_inspectors_enabled' in data:
            site_settings.application_inspectors_enabled = bool(data['application_inspectors_enabled'])
        if 'application_tournament_directors_enabled' in data:
            site_settings.application_tournament_directors_enabled = bool(data['application_tournament_directors_enabled'])

        # Super Admin only settings - check permission
        is_super = getattr(request.user, 'is_super_admin', False)
        if request.user.is_superuser or is_super:
            if 'email_enabled' in data:
                site_settings.email_enabled = bool(data['email_enabled'])
            if 'admin_notification_emails' in data:
                site_settings.admin_notification_emails = data['admin_notification_emails'].strip()
            if 'notify_server_issues' in data:
                site_settings.notify_server_issues = bool(data['notify_server_issues'])
            if 'notify_security_alerts' in data:
                site_settings.notify_security_alerts = bool(data['notify_security_alerts'])
            if 'notify_unusual_login_countries' in data:
                site_settings.notify_unusual_login_countries = bool(data['notify_unusual_login_countries'])

        site_settings.save()

        return JsonResponse({
            'success': True,
            'settings': {
                'min_cancellation_hours': site_settings.min_cancellation_hours,
                'require_cancellation_reason': site_settings.require_cancellation_reason,
                'max_failed_login_attempts': site_settings.max_failed_login_attempts,
                'session_timeout_hours': site_settings.session_timeout_hours,
                'application_referees_enabled': site_settings.application_referees_enabled,
                'application_inspectors_enabled': site_settings.application_inspectors_enabled,
                'application_tournament_directors_enabled': site_settings.application_tournament_directors_enabled,
                'email_enabled': site_settings.email_enabled,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
def notification_settings(request):
    """Notification settings page - configure which notifications are enabled. Admin only."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    from .models import NotificationSettings

    # Get or create notification settings
    notif_settings = NotificationSettings.get_settings()

    context = {
        'notif_settings': notif_settings,
    }

    return render(request, 'accounts/notification_settings.html', context)


@login_required
def api_save_notification_settings(request):
    """API: Save notification settings. Admin only."""
    from django.http import JsonResponse
    from .models import NotificationSettings
    import json

    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)

        notif_settings = NotificationSettings.get_settings()

        # Update all notification toggles
        toggle_fields = [
            'notify_match_assignment',
            'notify_match_reminder',
            'notify_match_reminder_pending',
            'notify_match_cancellation',
            'notify_match_modification',
            'notify_efo',
            'notify_travel_expense',
            'notify_news',
            'notify_mandatory_news',
            'notify_report',
            'notify_medical_expiry',
            'notify_failed_logins',
        ]

        for field in toggle_fields:
            if field in data:
                setattr(notif_settings, field, bool(data[field]))

        # Update numeric timing fields
        if 'match_reminder_hours' in data:
            notif_settings.match_reminder_hours = max(1, min(168, int(data['match_reminder_hours'])))
        if 'match_reminder_days' in data:
            notif_settings.match_reminder_days = max(1, min(14, int(data['match_reminder_days'])))
        if 'medical_expiry_reminder_days' in data:
            notif_settings.medical_expiry_reminder_days = max(1, min(90, int(data['medical_expiry_reminder_days'])))

        notif_settings.save()

        # Log the action
        from audit.utils import log_action
        log_action(
            request, 'system', 'update',
            'Értesítés beállítások módosítva',
            obj=notif_settings
        )

        return JsonResponse({
            'success': True,
            'message': 'Beállítások mentve.'
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@login_required
def api_add_coordinator(request):
    """API: Add a new coordinator from JT Admin users. Admin only."""
    from django.http import JsonResponse
    from .models import Coordinator
    import json

    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)

        user_id = data.get('user_id')

        if not user_id:
            return JsonResponse({'error': 'A felhasználó kiválasztása kötelező.'}, status=400)

        # Check if user exists and has JT Admin role
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'error': 'A felhasználó nem található.'}, status=404)

        if not user.is_jt_admin:
            return JsonResponse({'error': 'A felhasználónak JT Admin jogosultsága kell legyen.'}, status=400)

        # Check if already a coordinator (OneToOneField - use hasattr for efficiency)
        if hasattr(user, 'coordinator_entry'):
            return JsonResponse({'error': 'Ez a felhasználó már koordinátor.'}, status=400)

        # Get max order
        max_order = Coordinator.objects.aggregate(models.Max('order'))['order__max'] or 0

        coordinator = Coordinator.objects.create(
            user=user,
            order=max_order + 1
        )

        return JsonResponse({
            'success': True,
            'coordinator': {
                'id': coordinator.id,
                'user_id': user.id,
                'name': coordinator.name,
                'phone': coordinator.phone,
                'is_active': coordinator.is_active,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@login_required
def api_delete_coordinator(request, coordinator_id):
    """API: Delete a coordinator. Admin only."""
    from django.http import JsonResponse
    from .models import Coordinator

    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        coordinator = Coordinator.objects.get(id=coordinator_id)
        coordinator.delete()
        return JsonResponse({'success': True})
    except Coordinator.DoesNotExist:
        return JsonResponse({'error': 'Koordinátor nem található.'}, status=404)


@login_required
def api_toggle_coordinator(request, coordinator_id):
    """API: Toggle coordinator active status. Admin only."""
    from django.http import JsonResponse
    from .models import Coordinator

    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        coordinator = Coordinator.objects.get(id=coordinator_id)
        coordinator.is_active = not coordinator.is_active
        coordinator.save()
        return JsonResponse({
            'success': True,
            'is_active': coordinator.is_active
        })
    except Coordinator.DoesNotExist:
        return JsonResponse({'error': 'Koordinátor nem található.'}, status=404)


@login_required
def profile(request):
    """User profile page."""
    today = timezone.localtime(timezone.now()).date()
    return render(request, 'accounts/profile.html', {'today': today})


@login_required
def api_profile_update(request):
    """API: Update user profile (only email, phone, bank_account)."""
    from django.http import JsonResponse
    from django.core.mail import send_mail
    from django.conf import settings
    import json

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
        user = request.user

        # Track changes
        changes = []
        field_labels = {
            'email': 'E-mail cím',
            'phone': 'Telefonszám',
            'bank_account': 'Bankszámlaszám',
            'facebook_link': 'Facebook/Messenger link',
        }

        # Only allow these fields (notified to admins)
        allowed_fields = ['email', 'phone', 'bank_account', 'facebook_link']

        for field in allowed_fields:
            if field in data:
                old_value = getattr(user, field, '') or ''
                new_value = data[field] or ''

                if old_value != new_value:
                    changes.append({
                        'field': field_labels.get(field, field),
                        'old': old_value or '(üres)',
                        'new': new_value or '(üres)',
                    })
                    setattr(user, field, new_value)

        # Handle medical_valid_until separately (no admin notification needed)
        if 'medical_valid_until' in data:
            from datetime import datetime
            medical_value = data['medical_valid_until']
            if medical_value:
                try:
                    user.medical_valid_until = datetime.strptime(medical_value, '%Y-%m-%d').date()
                except ValueError:
                    pass  # Ignore invalid date
            else:
                user.medical_valid_until = None

        # If email changed, also update username (since email is used as username)
        if 'email' in data and data['email']:
            user.username = data['email']

        user.save()

        # Log profile update
        if changes:
            log_action(request, 'user', 'update', f'Profil módosítva - {user.get_full_name()}', obj=user, changes={
                c['field']: {'old': c['old'], 'new': c['new']} for c in changes
            })

        return JsonResponse({'success': True, 'changes': len(changes)})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_profile_picture_upload(request):
    """API: Upload profile picture."""
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    if 'profile_picture' not in request.FILES:
        return JsonResponse({'error': 'Nincs kép feltöltve.'}, status=400)

    user = request.user
    picture = request.FILES['profile_picture']

    # Validate file type
    allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    if picture.content_type not in allowed_types:
        return JsonResponse({'error': 'Csak JPEG, PNG, GIF vagy WebP formátum engedélyezett.'}, status=400)

    # Validate file size (max 5MB)
    if picture.size > 5 * 1024 * 1024:
        return JsonResponse({'error': 'A kép mérete maximum 5MB lehet.'}, status=400)

    # Delete old picture if exists
    if user.profile_picture:
        user.profile_picture.delete(save=False)

    user.profile_picture = picture
    user.save()

    log_action(request, 'user', 'upload', f'Profilkép feltöltve - {user.get_full_name()}', obj=user)

    return JsonResponse({
        'success': True,
        'url': user.profile_picture.url
    })


@login_required
def api_profile_picture_delete(request):
    """API: Delete profile picture."""
    from django.http import JsonResponse

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    user = request.user

    if user.profile_picture:
        user.profile_picture.delete(save=False)
        user.profile_picture = None
        user.save()
        log_action(request, 'user', 'delete', f'Profilkép törölve - {user.get_full_name()}', obj=user)

    return JsonResponse({'success': True})


@login_required
def api_send_test_email(request):
    """API: Send test email. Super Admin only."""
    from django.http import JsonResponse
    from django.core.mail import send_mail
    import json

    # Super Admin only
    is_super = getattr(request.user, 'is_super_admin', False)
    if not (request.user.is_superuser or is_super):
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
        recipient = data.get('email', '').strip()

        if not recipient:
            return JsonResponse({'error': 'Kérlek add meg a címzett e-mail címét.'}, status=400)

        # Validate email format
        import re
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', recipient):
            return JsonResponse({'error': 'Érvénytelen e-mail cím formátum.'}, status=400)

        # Check if email is enabled globally
        from .models import SiteSettings
        site_settings = SiteSettings.get_settings()
        if not site_settings.email_enabled:
            return JsonResponse({
                'error': 'Az e-mail küldés jelenleg ki van kapcsolva a beállításokban.'
            }, status=400)

        # Send test email
        subject = 'JAR - Teszt e-mail'
        message = f'''Kedves Felhasználó!

Ez egy teszt e-mail a JAR (Játékvezetői Adminisztrációs Rendszer) rendszerből.

Ha megkaptad ezt az üzenetet, az e-mail küldés megfelelően működik!

Küldés időpontja: {timezone.localtime(timezone.now()).strftime('%Y.%m.%d %H:%M:%S')}
Küldő: {request.user.get_full_name()}

---
JAR Rendszer
'''

        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )

        log_action(
            request, 'system', 'create',
            f'Teszt e-mail küldve: {recipient}',
            extra={'recipient': recipient}
        )

        return JsonResponse({
            'success': True,
            'message': f'Teszt e-mail sikeresen elküldve: {recipient}'
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Hiba történt: {str(e)}'}, status=500)
