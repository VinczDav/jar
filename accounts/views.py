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

        # First check if user exists and is not deleted/disabled
        try:
            user_check = User.objects.get(email=email)
            if user_check.is_deleted:
                error = 'Ez a felhasználói fiók törölve lett.'
                log_action(request, 'auth', 'login_failed', f'Bejelentkezés törölve fiókkal - {email}', extra={'email': email, 'reason': 'deleted'})
                context['error'] = error
                return render(request, 'accounts/login.html', context)
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

                    # Notify admins after 10 failed attempts
                    if user_check.failed_login_count == 10:
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
    Redirect to Django Admin for users with admin module access.
    The user is already authenticated, so no re-login needed.
    """
    # Check if user has permission to access admin
    if not (request.user.is_superuser or request.user.is_admin_user):
        return HttpResponseForbidden('Nincs jogosultságod az adatbázis eléréséhez.')

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

    from matches.models import Match, MatchAssignment
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

    context = {
        'match_count': match_count,
        'assignment_count': assignment_count,
        'notification_count': notification_count,
        'site_settings': site_settings,
        'coordinators': coordinators,
        'jt_admin_users': jt_admin_users,
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

        site_settings.save()

        return JsonResponse({
            'success': True,
            'settings': {
                'min_cancellation_hours': site_settings.min_cancellation_hours,
            }
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)


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
        }

        # Only allow these fields (notified to admins)
        allowed_fields = ['email', 'phone', 'bank_account']

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

        # Send email notification to admins if there were changes
        if changes:
            # Get admin users with email
            admin_users = User.objects.filter(
                models.Q(role=User.Role.ADMIN) |
                models.Q(is_admin_flag=True) |
                models.Q(role=User.Role.JT_ADMIN) |
                models.Q(is_jt_admin_flag=True)
            ).exclude(email='').values_list('email', flat=True).distinct()

            if admin_users:
                changes_text = '\n'.join([
                    f"  - {c['field']}: {c['old']} → {c['new']}"
                    for c in changes
                ])

                subject = f'JAR - Profil módosítás: {user.get_full_name()}'
                message = f'''Kedves Adminisztrátor!

{user.get_full_name()} módosította a profilját.

Változások:
{changes_text}

Időpont: {timezone.localtime(timezone.now()).strftime('%Y.%m.%d %H:%M')}

JAR Rendszer'''

                try:
                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        list(admin_users),
                        fail_silently=True,
                    )
                except Exception:
                    pass  # Don't fail if email sending fails

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

    return JsonResponse({'success': True})
