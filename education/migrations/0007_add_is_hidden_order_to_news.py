from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('education', '0006_add_is_hidden_to_knowledgepost'),
    ]

    operations = [
        migrations.AddField(
            model_name='news',
            name='is_hidden',
            field=models.BooleanField(default=False, help_text='Elrejtett híreket csak tartalomkészítők látják', verbose_name='Elrejtett'),
        ),
        migrations.AddField(
            model_name='news',
            name='order',
            field=models.PositiveIntegerField(default=0, verbose_name='Sorrend'),
        ),
        migrations.AlterModelOptions(
            name='news',
            options={'ordering': ['-is_pinned', 'order', '-published_at', '-created_at'], 'verbose_name': 'Hír', 'verbose_name_plural': 'Hírek'},
        ),
    ]
