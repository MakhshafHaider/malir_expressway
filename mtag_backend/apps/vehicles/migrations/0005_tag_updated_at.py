from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0004_tag_vehicle_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='tag',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
