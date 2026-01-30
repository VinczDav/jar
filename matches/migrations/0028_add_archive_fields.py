# Generated manually for Archive/Trash restructuring

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0027_phase_payment_types'),
    ]

    operations = [
        # Season archive fields
        migrations.AddField(
            model_name='season',
            name='is_archived',
            field=models.BooleanField(default=False, verbose_name='Archivált'),
        ),
        migrations.AddField(
            model_name='season',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archiválás időpontja'),
        ),

        # Competition archive fields
        migrations.AddField(
            model_name='competition',
            name='is_archived',
            field=models.BooleanField(default=False, verbose_name='Archivált'),
        ),
        migrations.AddField(
            model_name='competition',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archiválás időpontja'),
        ),

        # CompetitionPhase archive fields (also add soft delete fields)
        migrations.AddField(
            model_name='competitionphase',
            name='is_archived',
            field=models.BooleanField(default=False, verbose_name='Archivált'),
        ),
        migrations.AddField(
            model_name='competitionphase',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archiválás időpontja'),
        ),
        migrations.AddField(
            model_name='competitionphase',
            name='is_deleted',
            field=models.BooleanField(default=False, verbose_name='Törölve'),
        ),
        migrations.AddField(
            model_name='competitionphase',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Törlés időpontja'),
        ),

        # Match archive fields
        migrations.AddField(
            model_name='match',
            name='is_archived',
            field=models.BooleanField(default=False, verbose_name='Archivált'),
        ),
        migrations.AddField(
            model_name='match',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archiválás időpontja'),
        ),

        # Club archive fields
        migrations.AddField(
            model_name='club',
            name='is_archived',
            field=models.BooleanField(default=False, verbose_name='Archivált'),
        ),
        migrations.AddField(
            model_name='club',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archiválás időpontja'),
        ),

        # Team archive fields
        migrations.AddField(
            model_name='team',
            name='is_archived',
            field=models.BooleanField(default=False, verbose_name='Archivált'),
        ),
        migrations.AddField(
            model_name='team',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archiválás időpontja'),
        ),

        # Venue archive fields
        migrations.AddField(
            model_name='venue',
            name='is_archived',
            field=models.BooleanField(default=False, verbose_name='Archivált'),
        ),
        migrations.AddField(
            model_name='venue',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archiválás időpontja'),
        ),
    ]
