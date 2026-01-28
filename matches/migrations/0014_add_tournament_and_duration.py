# Generated migration for tournament support and match duration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0013_add_soft_delete'),
    ]

    operations = [
        # Add match_duration to Competition
        migrations.AddField(
            model_name='competition',
            name='match_duration',
            field=models.PositiveIntegerField(
                default=60,
                help_text='Egy mérkőzés átlagos időtartama percben',
                verbose_name='Meccs időtartam (perc)'
            ),
        ),
        # Add is_tournament to Match
        migrations.AddField(
            model_name='match',
            name='is_tournament',
            field=models.BooleanField(
                default=False,
                help_text='Ha be van jelölve, ez egy torna (több meccs, 1 rendező csapat)',
                verbose_name='Torna'
            ),
        ),
        # Add tournament_match_count to Match
        migrations.AddField(
            model_name='match',
            name='tournament_match_count',
            field=models.PositiveIntegerField(
                default=1,
                help_text='Tornánál: hány meccs van összesen',
                verbose_name='Meccsek száma'
            ),
        ),
    ]
