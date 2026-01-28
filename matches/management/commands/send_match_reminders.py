"""
Management command to send reminders for pending match assignments.

Sends notifications to referees who have pending assignments for matches
that are coming up in 5, 3, 2, or 1 day(s).

Usage:
    python manage.py send_match_reminders

Should be run daily via cron job, e.g.:
    0 8 * * * cd /path/to/project && python manage.py send_match_reminders
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from matches.models import Match, MatchAssignment
from documents.models import Notification


class Command(BaseCommand):
    help = 'Send reminders for pending match assignments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be sent without actually sending',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.localtime(timezone.now()).date()

        # Reminder days: 5, 3, 2, 1 days before match
        reminder_days = [5, 3, 2, 1]

        total_sent = 0

        for days in reminder_days:
            target_date = today + timedelta(days=days)

            # Find published matches on this date
            matches = Match.objects.filter(
                date=target_date,
                is_deleted=False,
                is_assignment_published=True,
                status__in=[Match.Status.SCHEDULED, Match.Status.CONFIRMED]
            ).select_related('home_team', 'away_team', 'venue')

            for match in matches:
                # Find pending assignments for this match
                pending_assignments = MatchAssignment.objects.filter(
                    match=match,
                    user__isnull=False,
                    response_status=MatchAssignment.ResponseStatus.PENDING
                ).select_related('user')

                for assignment in pending_assignments:
                    user = assignment.user

                    # Build notification message
                    date_str = match.date.strftime('%Y.%m.%d (%A)') if match.date else ''
                    time_str = match.time.strftime('%H:%M') if match.time else ''
                    teams = f"{match.home_team.name if match.home_team else 'TBD'} - {match.away_team.name if match.away_team else 'TBD'}"
                    venue = match.venue.name if match.venue else 'Nincs helyszín'

                    # Day text in Hungarian
                    if days == 1:
                        day_text = "HOLNAP"
                    else:
                        day_text = f"{days} nap múlva"

                    message = f"{day_text}!\n\n{date_str} {time_str}\n{teams}\n{venue}"

                    if dry_run:
                        self.stdout.write(
                            f"Would send to {user.email}: {assignment.get_role_display()} - {teams} ({days} day(s))"
                        )
                    else:
                        match_link = f"/matches/{match.id}/"
                        # Check if we already sent a reminder today for this match
                        existing = Notification.objects.filter(
                            recipient=user,
                            title="El nem fogadott mérkőzésed van",
                            created_at__date=today,
                            link=match_link
                        ).exists()

                        if not existing:
                            Notification.objects.create(
                                recipient=user,
                                title="El nem fogadott mérkőzésed van",
                                message=message,
                                notification_type=Notification.Type.WARNING,
                                link=match_link
                            )
                            total_sent += 1
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Sent reminder to {user.email}: {assignment.get_role_display()} - {teams}"
                                )
                            )

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run - no notifications sent'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Successfully sent {total_sent} reminders'))
