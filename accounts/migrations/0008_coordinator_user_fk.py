# Generated migration for Coordinator model - switch from name/phone to user ForeignKey

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def clear_coordinators(apps, schema_editor):
    """Delete all existing coordinators since they can't be migrated automatically."""
    Coordinator = apps.get_model('accounts', 'Coordinator')
    Coordinator.objects.all().delete()


def noop(apps, schema_editor):
    """Reverse migration - nothing to do."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_add_coordinator_model'),
    ]

    operations = [
        # First, clear existing data
        migrations.RunPython(clear_coordinators, noop),

        # Remove old fields
        migrations.RemoveField(
            model_name='coordinator',
            name='name',
        ),
        migrations.RemoveField(
            model_name='coordinator',
            name='phone',
        ),

        # Add new user ForeignKey
        migrations.AddField(
            model_name='coordinator',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='coordinator_entries',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Felhasználó',
                default=1,  # Temporary default, data was cleared
            ),
            preserve_default=False,
        ),

        # Update ordering
        migrations.AlterModelOptions(
            name='coordinator',
            options={
                'ordering': ['order', 'user__last_name', 'user__first_name'],
                'verbose_name': 'Koordinátor',
                'verbose_name_plural': 'Koordinátorok'
            },
        ),
    ]
