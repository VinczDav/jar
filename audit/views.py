from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from .models import AuditLog


@login_required
def log_list(request):
    """Audit log lista oldal - csak adminoknak."""
    if not request.user.is_admin_user:
        return HttpResponseForbidden('Nincs jogosultságod.')

    logs = AuditLog.objects.select_related('user').all()

    # Szűrők
    category = request.GET.get('category', '')
    action = request.GET.get('action', '')
    user_id = request.GET.get('user', '')
    search = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    if category:
        logs = logs.filter(category=category)
    if action:
        logs = logs.filter(action=action)
    if user_id:
        logs = logs.filter(user_id=user_id)
    if search:
        logs = logs.filter(
            Q(description__icontains=search) |
            Q(object_repr__icontains=search) |
            Q(ip_address__icontains=search) |
            Q(user__email__icontains=search) |
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search)
        )
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    # Pagination
    paginator = Paginator(logs, 50)
    page = request.GET.get('page', 1)
    page_obj = paginator.get_page(page)

    # Statisztikák
    today = timezone.localtime().date()
    week_ago = today - timedelta(days=7)

    stats = {
        'total': AuditLog.objects.count(),
        'today': AuditLog.objects.filter(timestamp__date=today).count(),
        'week': AuditLog.objects.filter(timestamp__date__gte=week_ago).count(),
        'failed_logins_today': AuditLog.objects.filter(
            action='login_failed',
            timestamp__date=today
        ).count(),
    }

    # Felhasználók a szűrőhöz
    from accounts.models import User
    users = User.objects.filter(is_deleted=False).order_by('last_name', 'first_name')

    # Super admin can see full details
    is_super_admin = getattr(request.user, 'is_super_admin', False)

    # For regular admin, filter out the soft_delete/hard_delete distinction in the filter dropdown
    # They see both as "Törlés" anyway
    if is_super_admin:
        action_choices = AuditLog.Action.choices
    else:
        # Regular admin sees simplified actions (soft_delete shows as "Törlés", hard_delete hidden)
        action_choices = [
            (value, label) for value, label in AuditLog.Action.choices
            if value != 'hard_delete'  # Hide hard_delete option from regular admin
        ]

    context = {
        'page_obj': page_obj,
        'logs': page_obj,
        'stats': stats,
        'categories': AuditLog.Category.choices,
        'actions': action_choices,
        'users': users,
        'filters': {
            'category': category,
            'action': action,
            'user': user_id,
            'search': search,
            'date_from': date_from,
            'date_to': date_to,
        },
        'is_super_admin': is_super_admin,
    }

    return render(request, 'audit/log_list.html', context)


@login_required
def log_detail_api(request, log_id):
    """Log részletek API - AJAX híváshoz."""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Nincs jogosultságod.'}, status=403)

    try:
        log = AuditLog.objects.select_related('user').get(pk=log_id)
    except AuditLog.DoesNotExist:
        return JsonResponse({'error': 'Nem található.'}, status=404)

    # Check if user is super admin for full details
    is_super_admin = getattr(request.user, 'is_super_admin', False)

    # Determine action display - super admin sees "Soft törlés" for soft_delete
    if is_super_admin and log.action == 'soft_delete':
        action_display = 'Soft törlés'
    else:
        action_display = log.get_action_display()

    # Basic data for all admins
    data = {
        'id': log.id,
        'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        'user': log.user.get_full_name() if log.user else 'Rendszer',
        'category': log.get_category_display(),
        'action': action_display,
        'description': log.description,
        'object_type': log.object_type,
        'object_id': log.object_id,
        'object_repr': log.object_repr,
        'is_super_admin': is_super_admin,
    }

    # Super admin gets full details
    if is_super_admin:
        data.update({
            'user_email': log.user.email if log.user else None,
            'ip_address': log.ip_address,
            'user_agent': log.user_agent,
            'changes': log.changes,
            'extra_data': log.extra_data,
        })

    return JsonResponse(data)
