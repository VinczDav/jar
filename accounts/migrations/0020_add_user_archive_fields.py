# Generated manually for Archive/Trash restructuring

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0019_add_tournament_director_flag'),
    ]

    operations = [
        # User archive fields
        migrations.AddField(
            model_name='user',
            name='is_archived',
            field=models.BooleanField(default=False, verbose_name='Archivált (kizárt)'),
        ),
        migrations.AddField(
            model_name='user',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Archiválás időpontja'),
        ),
    ]
