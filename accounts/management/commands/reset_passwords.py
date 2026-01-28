from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = 'Reset all user passwords to a default value'

    def add_arguments(self, parser):
        parser.add_argument(
            '--password',
            type=str,
            default='jelszo123',
            help='The password to set for all users (default: jelszo123)'
        )

    def handle(self, *args, **options):
        password = options['password']
        users = User.objects.all()

        for user in users:
            user.set_password(password)
            user.save()
            self.stdout.write(f'  {user.email} - OK')

        self.stdout.write(self.style.SUCCESS(
            f'\nSuccessfully reset passwords for {users.count()} users to "{password}"'
        ))
