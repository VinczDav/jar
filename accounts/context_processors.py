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
