# Generated migration for idempotency_key and source fields on Transaction

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_add_transfer_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='idempotency_key',
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name='transaction',
            name='source',
            field=models.CharField(
                blank=True,
                choices=[
                    ('online_exit', 'Online Exit'),
                    ('offline_exit_sync', 'Offline Exit (Synced)'),
                    ('topup_jazzcash', 'Top-up JazzCash'),
                    ('topup_cash', 'Top-up Cash'),
                    ('refund', 'Refund'),
                ],
                max_length=30,
                null=True,
            ),
        ),
    ]
