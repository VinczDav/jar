# Generated manually for referee -> user migration and model updates

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('matches', '0001_initial'),
    ]

    operations = [
        # Remove the old unique_together constraint
        migrations.AlterUniqueTogether(
            name='matchassignment',
            unique_together=set(),
        ),
        # Remove the old referee field
        migrations.RemoveField(
            model_name='matchassignment',
            name='referee',
        ),
        # Add the new user field
        migrations.AddField(
            model_name='matchassignment',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='match_assignments',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Játékvezető',
                default=1,
            ),
            preserve_default=False,
        ),
        # Add new unique_together with user
        migrations.AlterUniqueTogether(
            name='matchassignment',
            unique_together={('match', 'user')},
        ),
        # Update Match model - add created_by
        migrations.AddField(
            model_name='match',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_matches',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Létrehozta',
            ),
        ),
        # Update Match status field with new choices including DRAFT
        migrations.AlterField(
            model_name='match',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Piszkozat'),
                    ('scheduled', 'Kiírva'),
                    ('confirmed', 'Visszaigazolva'),
                    ('completed', 'Lejátszva'),
                    ('cancelled', 'Törölve'),
                ],
                default='draft',
                max_length=20,
                verbose_name='Státusz',
            ),
        ),
        # Update Match ordering
        migrations.AlterModelOptions(
            name='match',
            options={
                'ordering': ['-date', '-time'],
                'verbose_name': 'Mérkőzés',
                'verbose_name_plural': 'Mérkőzések',
            },
        ),
        # Update MatchAssignment ordering
        migrations.AlterModelOptions(
            name='matchassignment',
            options={
                'ordering': ['role', 'user__last_name'],
                'verbose_name': 'Kijelölés',
                'verbose_name_plural': 'Kijelölések',
            },
        ),
        # Remove external_id from Match
        migrations.RemoveField(
            model_name='match',
            name='external_id',
        ),
    ]
