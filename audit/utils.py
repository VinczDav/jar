"""
Audit logging utility functions.

Használat:
    from audit.utils import log_action, AuditLog

    # Egyszerű log
    log_action(request, 'match', 'create', 'Új mérkőzés létrehozva', obj=match)

    # Log változásokkal
    log_action(request, 'match', 'update', 'Mérkőzés módosítva', obj=match, changes={
        'date': {'old': '2024-01-15', 'new': '2024-01-16'},
        'venue': {'old': 'Régi helyszín', 'new': 'Új helyszín'}
    })

    # Log extra adatokkal
    log_action(request, 'email', 'send', 'Email kiküldve', extra={
        'recipient': 'user@example.com',
        'subject': 'Mérkőzés emlékeztető'
    })
"""

from .models import AuditLog


def get_client_ip(request):
    """Kliens IP cím kinyerése a request-ből."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def log_action(request, category, action, description, obj=None, changes=None, extra=None):
    """
    Audit log bejegyzés létrehozása.

    Args:
        request: Django request objektum (vagy None scheduler esetén)
        category: AuditLog.Category érték (str)
        action: AuditLog.Action érték (str)
        description: Részletes leírás
        obj: Opcionális - az érintett objektum (Model instance)
        changes: Opcionális - változások dict {'field': {'old': x, 'new': y}}
        extra: Opcionális - extra adatok dict

    Returns:
        AuditLog: A létrehozott log bejegyzés
    """
    user = None
    ip_address = None
    user_agent = ''

    if request:
        if hasattr(request, 'user') and request.user.is_authenticated:
            user = request.user
        ip_address = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

    return AuditLog.objects.create(
        user=user,
        ip_address=ip_address,
        user_agent=user_agent,
        category=category,
        action=action,
        object_type=obj.__class__.__name__ if obj else '',
        object_id=obj.pk if obj and hasattr(obj, 'pk') else None,
        object_repr=str(obj)[:200] if obj else '',
        description=description,
        changes=changes,
        extra_data=extra,
    )


def log_system_action(category, action, description, obj=None, changes=None, extra=None):
    """
    Rendszer szintű log bejegyzés (request nélkül, pl. scheduler).

    Args:
        category: AuditLog.Category érték (str)
        action: AuditLog.Action érték (str)
        description: Részletes leírás
        obj: Opcionális - az érintett objektum
        changes: Opcionális - változások dict
        extra: Opcionális - extra adatok dict

    Returns:
        AuditLog: A létrehozott log bejegyzés
    """
    return AuditLog.objects.create(
        user=None,
        ip_address=None,
        user_agent='System/Scheduler',
        category=category,
        action=action,
        object_type=obj.__class__.__name__ if obj else '',
        object_id=obj.pk if obj and hasattr(obj, 'pk') else None,
        object_repr=str(obj)[:200] if obj else '',
        description=description,
        changes=changes,
        extra_data=extra,
    )


def get_model_changes(instance, fields=None):
    """
    Model változások összegyűjtése mentés előtt.

    Használat:
        # View-ban, update előtt:
        old_instance = Match.objects.get(pk=match.pk)
        changes = get_model_changes(old_instance, ['date', 'time', 'venue'])
        # ... update ...
        # changes dict-ben: {'date': {'old': ..., 'new': ...}, ...}

    Args:
        instance: Model instance (régi értékekkel)
        fields: Opcionális - figyelendő mezők listája

    Returns:
        dict: Callable, ami az új instance-szal meghívva visszaadja a változásokat
    """
    if fields is None:
        fields = [f.name for f in instance._meta.fields if f.name != 'id']

    old_values = {}
    for field in fields:
        value = getattr(instance, field, None)
        if hasattr(value, 'pk'):  # ForeignKey
            old_values[field] = {'value': value.pk, 'repr': str(value)}
        else:
            old_values[field] = {'value': value, 'repr': str(value) if value else None}

    def compare(new_instance):
        changes = {}
        for field in fields:
            new_value = getattr(new_instance, field, None)
            if hasattr(new_value, 'pk'):  # ForeignKey
                new_val = {'value': new_value.pk, 'repr': str(new_value)}
            else:
                new_val = {'value': new_value, 'repr': str(new_value) if new_value else None}

            old_val = old_values[field]
            if old_val['value'] != new_val['value']:
                changes[field] = {
                    'old': old_val['repr'],
                    'new': new_val['repr']
                }
        return changes if changes else None

    return compare
