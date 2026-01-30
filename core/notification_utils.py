"""
Notification utilities with settings integration.
"""
from documents.models import Notification


def is_notification_enabled(category):
    """
    Check if a notification category is enabled in NotificationSettings.

    Categories:
    - match_assignment: New match assignment
    - match_reminder: Match reminder
    - match_cancellation: Match cancellation (admin)
    - match_modification: Match modification
    - efo: EFO notifications
    - travel_expense: Travel expense notifications
    - news: News notifications
    - mandatory_news: Mandatory news
    - report: Report notifications
    - medical_expiry: Medical expiry reminder
    - failed_logins: Failed login attempts (admin)
    """
    from accounts.models import NotificationSettings

    settings = NotificationSettings.get_settings()

    field_name = f'notify_{category}'
    return getattr(settings, field_name, True)


def create_notification(recipient, title, message, notification_type=Notification.Type.INFO,
                       link='', category=None):
    """
    Create a notification if the category is enabled.

    Args:
        recipient: User to receive the notification
        title: Notification title
        message: Notification message
        notification_type: Type of notification (info, warning, success, error, match)
        link: Optional link
        category: Notification category to check settings (optional)

    Returns:
        Notification object if created, None if category is disabled
    """
    # If category is specified, check if it's enabled
    if category and not is_notification_enabled(category):
        return None

    return Notification.objects.create(
        recipient=recipient,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link
    )


def create_notifications_bulk(recipients, title, message, notification_type=Notification.Type.INFO,
                             link='', category=None):
    """
    Create notifications for multiple recipients if category is enabled.

    Args:
        recipients: Queryset or list of users to receive the notification
        title: Notification title
        message: Notification message
        notification_type: Type of notification
        link: Optional link
        category: Notification category to check settings (optional)

    Returns:
        List of created notifications, empty list if category is disabled
    """
    # If category is specified, check if it's enabled
    if category and not is_notification_enabled(category):
        return []

    notifications = [
        Notification(
            recipient=recipient,
            title=title,
            message=message,
            notification_type=notification_type,
            link=link
        )
        for recipient in recipients
    ]

    return Notification.objects.bulk_create(notifications)
