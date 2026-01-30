from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import MatchAssignment, Match
from documents.models import Notification


# Note: Assignment creation notifications are now handled directly in views.py
# (api_publish_match and api_update_match_assignments) to avoid duplicate notifications
# and ensure proper control over when notifications are sent.


# Note: Assignment deletion notifications are handled in views.py api_update_match_assignments
# to avoid duplicate notifications (previously this signal was also sending a notification)


@receiver(pre_delete, sender=Match)
def notify_match_deleted(sender, instance, **kwargs):
    """
    Send notification when a match is deleted/cancelled.
    Only if assignments are published.

    IMPORTANT: Must fetch and cache assignments immediately since CASCADE
    delete will remove them before this signal completes.
    """
    # Only send notification if assignments were published
    if not instance.is_assignment_published:
        return

    # CRITICAL: Fetch and convert to list immediately to avoid CASCADE delete issue
    # When a Match is deleted, Django deletes related MatchAssignments first,
    # so we must cache them before accessing instance.assignments later
    assigned_users = list(
        instance.assignments.filter(user__isnull=False)
        .select_related('user')
        .values_list('user', flat=True)
    )

    if not assigned_users:
        return

    # Format match details
    date_str = instance.date.strftime('%Y.%m.%d (%A)') if instance.date else 'Nincs dátum'
    time_str = instance.time.strftime('%H:%M') if instance.time else ''
    teams = f"{str(instance.home_team) if instance.home_team else 'TBD'} - {str(instance.away_team) if instance.away_team else 'TBD'}"
    venue = instance.venue.name if instance.venue else 'Nincs helyszín'

    message = f"{date_str} {time_str}\n{teams}\n{venue}"

    # Send notification to all assigned users
    from django.contrib.auth import get_user_model
    User = get_user_model()

    for user_id in assigned_users:
        user = User.objects.get(id=user_id)
        Notification.objects.create(
            recipient=user,
            title="Mérkőzés elmarad",
            message=message,
            notification_type=Notification.Type.WARNING,
            link="/matches/my/"
        )


# Store previous match state for change detection
_match_cache = {}

from django.db.models.signals import pre_save

@receiver(pre_save, sender=Match)
def cache_match_state(sender, instance, **kwargs):
    """Cache match state before save to detect changes."""
    if instance.pk:
        try:
            old_match = Match.objects.select_related('home_team', 'away_team', 'venue').get(pk=instance.pk)
            _match_cache[instance.pk] = {
                'date': old_match.date,
                'time': old_match.time,
                'venue_id': old_match.venue_id,
                'home_team_id': old_match.home_team_id,
                'away_team_id': old_match.away_team_id,
                'is_assignment_published': old_match.is_assignment_published,
                'status': old_match.status,
            }
        except Match.DoesNotExist:
            pass


@receiver(post_save, sender=Match)
def notify_match_changed(sender, instance, created, **kwargs):
    """
    Send notification when match details change (date, time, venue, teams),
    when match is published for the first time, or when match is cancelled.
    Only for published assignments on scheduled/confirmed matches.
    """
    # Skip if this is a new match
    if created:
        return

    # Check if we have cached previous state
    if instance.pk not in _match_cache:
        return

    old_state = _match_cache[instance.pk]
    del _match_cache[instance.pk]

    # Check if match was just cancelled (status changed to CANCELLED)
    was_just_cancelled = (old_state['status'] != Match.Status.CANCELLED and
                         instance.status == Match.Status.CANCELLED and
                         old_state['is_assignment_published'])

    if was_just_cancelled:
        # Get all assigned users BEFORE we delete them
        assigned_users = list(
            instance.assignments.filter(user__isnull=False)
            .select_related('user')
        )

        if assigned_users:
            # Format match details
            date_str = instance.date.strftime('%Y.%m.%d (%A)') if instance.date else 'Nincs dátum'
            time_str = instance.time.strftime('%H:%M') if instance.time else ''
            teams = f"{str(instance.home_team) if instance.home_team else 'TBD'} - {str(instance.away_team) if instance.away_team else 'TBD'}"
            venue = instance.venue.name if instance.venue else 'Nincs helyszín'

            message = f"{date_str} {time_str}\n{teams}\n{venue}"

            # Send notification to all assigned users
            for assignment in assigned_users:
                Notification.objects.create(
                    recipient=assignment.user,
                    title="Mérkőzés elmarad",
                    message=message,
                    notification_type=Notification.Type.WARNING,
                    link=f"/matches/{instance.id}/"
                )

            # Delete all assignments (reset to fresh match)
            instance.assignments.all().delete()

            # Unpublish assignments
            instance.is_assignment_published = False
            # Use update to avoid triggering signals again
            Match.objects.filter(pk=instance.pk).update(is_assignment_published=False)

        return

    # Note: "first publish" notifications are now handled in api_publish_match directly
    # This signal only handles changes to already-published matches

    # Only check for changes on scheduled/confirmed matches with published assignments
    if instance.status not in [Match.Status.SCHEDULED, Match.Status.CONFIRMED]:
        return

    if not instance.is_assignment_published:
        return

    # Compare fields to detect changes in match details
    changed = False
    if (old_state['date'] != instance.date or
        old_state['time'] != instance.time or
        old_state['venue_id'] != instance.venue_id or
        old_state['home_team_id'] != instance.home_team_id or
        old_state['away_team_id'] != instance.away_team_id):
        changed = True

    if not changed:
        return

    # Get all assigned users
    assignments = instance.assignments.filter(user__isnull=False)

    if not assignments.exists():
        return

    # Format match details
    date_str = instance.date.strftime('%Y.%m.%d (%A)') if instance.date else 'Nincs dátum'
    time_str = instance.time.strftime('%H:%M') if instance.time else ''
    teams = f"{str(instance.home_team) if instance.home_team else 'TBD'} - {str(instance.away_team) if instance.away_team else 'TBD'}"
    venue = instance.venue.name if instance.venue else 'Nincs helyszín'

    message = f"{date_str} {time_str}\n{teams}\n{venue}"

    # Send notification to all assigned users
    for assignment in assignments:
        Notification.objects.create(
            recipient=assignment.user,
            title="Megváltozott a kiírás",
            message=message,
            notification_type=Notification.Type.WARNING,
            link=f"/matches/{instance.id}/"
        )

    # Check for unavailability conflicts if date changed
    if old_state['date'] != instance.date and instance.date:
        from referees.models import Unavailability

        for assignment in assignments:
            user = assignment.user
            # Check if user has a referee profile with unavailability on this date
            try:
                referee = user.referee_profile
                conflicting_unavailability = Unavailability.objects.filter(
                    referee=referee,
                    start_date__lte=instance.date,
                    end_date__gte=instance.date
                ).first()

                if conflicting_unavailability:
                    # Send notification to the user about conflict
                    unavail_reason = conflicting_unavailability.reason or 'Nem megadott'
                    Notification.objects.create(
                        recipient=user,
                        title="Szabadság ütközés!",
                        message=f"Az áthelyezett mérkőzés ütközik a szabadságoddal!\n\n{date_str} {time_str}\n{teams}\n\nSzabadság: {conflicting_unavailability.start_date.strftime('%Y.%m.%d')} - {conflicting_unavailability.end_date.strftime('%Y.%m.%d')}\nIndok: {unavail_reason}",
                        notification_type=Notification.Type.ERROR,
                        link=f"/matches/{instance.id}/"
                    )

                    # Also notify coordinators/JT admins about the conflict
                    from accounts.models import User as UserModel
                    from django.db.models import Q
                    coordinators = UserModel.objects.filter(
                        Q(role=UserModel.Role.JT_ADMIN) | Q(is_jt_admin_flag=True),
                        is_deleted=False
                    )
                    for coordinator in coordinators:
                        Notification.objects.create(
                            recipient=coordinator,
                            title="Szabadság ütközés mérkőzés áthelyezéskor",
                            message=f"{user.get_full_name()} szabadsága ütközik az áthelyezett mérkőzéssel!\n\n{date_str} {time_str}\n{teams}\n\nSzabadság: {conflicting_unavailability.start_date.strftime('%Y.%m.%d')} - {conflicting_unavailability.end_date.strftime('%Y.%m.%d')}",
                            notification_type=Notification.Type.WARNING,
                            link=f"/matches/{instance.id}/edit/"
                        )
            except Exception:
                pass  # No referee profile
