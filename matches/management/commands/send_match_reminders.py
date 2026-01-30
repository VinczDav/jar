"""
Management command to send email reminders for upcoming matches.

Sends reminders to:
- Users who accepted matches (if notify_match_reminder is enabled)
- Users who haven't accepted yet (if notify_match_reminder_pending is enabled)

The reminder is sent X hours before the match (configurable in NotificationSettings).

Usage:
    python manage.py send_match_reminders
    python manage.py send_match_reminders --dry-run

Should be run hourly via cron job, e.g.:
    0 * * * * cd /path/to/project && python manage.py send_match_reminders
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, datetime

from matches.models import Match, MatchAssignment
from accounts.models import NotificationSettings
from core.email_utils import send_templated_email
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send email reminders for upcoming matches'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be sent without actually sending',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.localtime(timezone.now())

        # Get notification settings
        notif_settings = NotificationSettings.get_settings()
        reminder_hours = getattr(notif_settings, 'match_reminder_hours', 24) or 24

        # Check if either reminder type is enabled
        notify_accepted = getattr(notif_settings, 'notify_match_reminder', True)
        notify_pending = getattr(notif_settings, 'notify_match_reminder_pending', True)

        if not notify_accepted and not notify_pending:
            self.stdout.write(self.style.WARNING('Both match reminder types are disabled. Nothing to send.'))
            return

        # Calculate the target datetime window
        # We want to find matches starting in approximately reminder_hours
        # We check for matches in a 1-hour window to avoid duplicates
        target_start = now + timedelta(hours=reminder_hours)
        target_end = target_start + timedelta(hours=1)

        self.stdout.write(f"Looking for matches between {target_start} and {target_end}")
        self.stdout.write(f"Reminder hours setting: {reminder_hours}")

        # Find published matches
        matches = Match.objects.filter(
            is_deleted=False,
            is_assignment_published=True,
            status__in=[Match.Status.SCHEDULED, Match.Status.CONFIRMED]
        ).select_related(
            'home_team', 'away_team', 'venue', 'phase', 'phase__competition'
        )

        # Filter by date and time
        matching_matches = []
        for match in matches:
            if not match.date:
                continue

            # Combine date and time
            match_time = match.time or datetime.min.time()
            match_datetime = timezone.make_aware(
                datetime.combine(match.date, match_time),
                timezone.get_current_timezone()
            )

            # Check if match is in our target window
            if target_start <= match_datetime < target_end:
                matching_matches.append((match, match_datetime))

        if not matching_matches:
            self.stdout.write('No matches found in the reminder window.')
            return

        self.stdout.write(f"Found {len(matching_matches)} matches to process")

        total_accepted_sent = 0
        total_pending_sent = 0

        for match, match_datetime in matching_matches:
            # Calculate days until match for display
            days_until = (match.date - now.date()).days

            # Get all assignments for this match
            all_assignments = match.assignments.select_related('user').order_by('role', 'created_at')

            # Process accepted assignments
            if notify_accepted:
                accepted_assignments = match.assignments.filter(
                    user__isnull=False,
                    response_status=MatchAssignment.ResponseStatus.ACCEPTED
                ).select_related('user')

                for assignment in accepted_assignments:
                    user = assignment.user
                    if not user.email:
                        continue

                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] Would send ACCEPTED reminder to {user.email}: "
                            f"{assignment.get_role_display()} - {match}"
                        )
                    else:
                        try:
                            send_templated_email(
                                to_email=user.email,
                                subject=f'Emlékeztető: Holnapi mérkőzésed - {match.date.strftime("%Y.%m.%d")}',
                                template_name='match_reminder',
                                context={
                                    'user': user,
                                    'match': match,
                                    'assignment': assignment,
                                    'days_until': days_until,
                                    'all_assignments': all_assignments,
                                }
                            )
                            total_accepted_sent += 1
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Sent ACCEPTED reminder to {user.email}: {assignment.get_role_display()}"
                                )
                            )
                        except Exception as e:
                            logger.error(f"Failed to send reminder to {user.email}: {e}")
                            self.stdout.write(
                                self.style.ERROR(f"Failed to send to {user.email}: {e}")
                            )

            # Process pending assignments
            if notify_pending:
                pending_assignments = match.assignments.filter(
                    user__isnull=False,
                    response_status=MatchAssignment.ResponseStatus.PENDING
                ).select_related('user')

                for assignment in pending_assignments:
                    user = assignment.user
                    if not user.email:
                        continue

                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] Would send PENDING reminder to {user.email}: "
                            f"{assignment.get_role_display()} - {match}"
                        )
                    else:
                        try:
                            send_templated_email(
                                to_email=user.email,
                                subject=f'FIGYELEM: El nem fogadott mérkőzésed van holnap!',
                                template_name='unaccepted_match_reminder',
                                context={
                                    'user': user,
                                    'match': match,
                                    'assignment': assignment,
                                    'days_until': days_until,
                                    'all_assignments': all_assignments,
                                }
                            )
                            total_pending_sent += 1
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Sent PENDING reminder to {user.email}: {assignment.get_role_display()}"
                                )
                            )
                        except Exception as e:
                            logger.error(f"Failed to send pending reminder to {user.email}: {e}")
                            self.stdout.write(
                                self.style.ERROR(f"Failed to send to {user.email}: {e}")
                            )

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run - no emails sent'))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully sent {total_accepted_sent} accepted reminders and '
                    f'{total_pending_sent} pending reminders'
                )
            )
