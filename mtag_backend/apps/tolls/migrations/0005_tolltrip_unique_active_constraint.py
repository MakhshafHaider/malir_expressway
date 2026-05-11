# Generated migration adding UniqueConstraint for one active trip per vehicle

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tolls', '0004_add_pending_gate_open'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='tolltrip',
            constraint=models.UniqueConstraint(
                condition=models.Q(status='active'),
                fields=['vehicle'],
                name='unique_active_trip_per_vehicle',
            ),
        ),
    ]
