"""
Management command to send email reminders for match feedback.

Sends reminders to users who haven't submitted feedback after their match:
- Day 1: First reminder
- Day 3: Second reminder
- Day 5: Third reminder
- Day 7: Fourth reminder
- Day 10: Final reminder

Usage:
    python manage.py send_feedback_reminders
    python manage.py send_feedback_reminders --dry-run

Should be run daily via cron job, e.g.:
    0 8 * * * cd /path/to/project && python manage.py send_feedback_reminders
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta

from matches.models import Match, MatchAssignment, MatchFeedback
from core.email_utils import send_templated_email
import logging

logger = logging.getLogger(__name__)

# Reminder schedule: days after match -> field name
REMINDER_SCHEDULE = {
    1: 'reminder_1_sent',
    3: 'reminder_3_sent',
    5: 'reminder_5_sent',
    7: 'reminder_7_sent',
    10: 'reminder_10_sent',
}


class Command(BaseCommand):
    help = 'Send email reminders for match feedback submissions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be sent without actually sending',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.localtime(timezone.now()).date()

        total_sent = 0

        for days_after, reminder_field in REMINDER_SCHEDULE.items():
            # Calculate the target match date for this reminder
            target_date = today - timedelta(days=days_after)

            self.stdout.write(f"\nProcessing {days_after}-day reminder (matches from {target_date})...")

            # Find completed matches on that date
            matches = Match.objects.filter(
                is_deleted=False,
                date=target_date,
                status__in=[Match.Status.SCHEDULED, Match.Status.CONFIRMED, Match.Status.COMPLETED]
            ).select_related(
                'home_team', 'away_team', 'venue', 'phase', 'phase__competition'
            )

            for match in matches:
                # Get assignments that need feedback reminders
                assignments = MatchAssignment.objects.filter(
                    match=match,
                    user__isnull=False,
                    response_status=MatchAssignment.ResponseStatus.ACCEPTED,
                    is_deleted=False,
                ).select_related('user')

                for assignment in assignments:
                    user = assignment.user
                    if not user.email:
                        continue

                    # Check if feedback already exists
                    if MatchFeedback.objects.filter(assignment=assignment).exists():
                        continue

                    # Check if this specific reminder was already sent
                    # We need to track this - for now we'll create a placeholder feedback
                    # or use a separate tracking mechanism

                    # Since we don't have feedback yet, we need another way to track
                    # Let's check if we should send based on assignment creation
                    # For simplicity, we'll use a flag approach - create feedback entry when sent

                    # Better approach: Track via a simple check
                    # Since we run daily, we only send for exact day matches

                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] Would send {days_after}-day reminder to {user.email}: "
                            f"{assignment.get_role_display()} - {match}"
                        )
                        total_sent += 1
                    else:
                        try:
                            send_templated_email(
                                to_email=user.email,
                                subject=f'Visszajelzés kérés: {match.date.strftime("%Y.%m.%d")} mérkőzésed',
                                template_name='feedback_reminder',
                                context={
                                    'user': user,
                                    'match': match,
                                    'assignment': assignment,
                                    'days_since': days_after,
                                }
                            )
                            total_sent += 1
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Sent {days_after}-day reminder to {user.email}: "
                                    f"{assignment.get_role_display()} - {match}"
                                )
                            )
                        except Exception as e:
                            logger.error(f"Failed to send feedback reminder to {user.email}: {e}")
                            self.stdout.write(
                                self.style.ERROR(f"Failed to send to {user.email}: {e}")
                            )

        if dry_run:
            self.stdout.write(self.style.WARNING(f'\nDry run - {total_sent} emails would be sent'))
        else:
            self.stdout.write(
                self.style.SUCCESS(f'\nSuccessfully sent {total_sent} feedback reminders')
            )
