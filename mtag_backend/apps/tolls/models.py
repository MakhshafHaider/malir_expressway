import uuid
from django.db import models
from apps.vehicles.models import VehicleType


class Plaza(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'plazas'

    def __str__(self):
        return f"{self.name} ({self.code})"


class TollLane(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plaza = models.ForeignKey(Plaza, on_delete=models.CASCADE, related_name='lanes')
    lane_number = models.IntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'toll_lanes'
        unique_together = ('plaza', 'lane_number')

    def __str__(self):
        return f"{self.plaza.code} — Lane {self.lane_number}"


class TollRate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry_plaza = models.ForeignKey(Plaza, on_delete=models.CASCADE, related_name='entry_rates')
    exit_plaza = models.ForeignKey(Plaza, on_delete=models.CASCADE, related_name='exit_rates')
    vehicle_type = models.CharField(max_length=20, choices=VehicleType.choices)
    rate = models.DecimalField(max_digits=8, decimal_places=2)
    peak_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.0)
    effective_from = models.DateField()

    class Meta:
        db_table = 'toll_rates'
        ordering = ['-effective_from']
        unique_together = ('entry_plaza', 'exit_plaza', 'vehicle_type', 'effective_from')

    def __str__(self):
        return f"{self.entry_plaza.code}→{self.exit_plaza.code} — {self.vehicle_type} Rs.{self.rate}"


class TripStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'


class TollTrip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vehicle = models.ForeignKey('vehicles.Vehicle', on_delete=models.PROTECT, related_name='trips')
    tag = models.ForeignKey('vehicles.Tag', on_delete=models.PROTECT, related_name='trips')
    account = models.ForeignKey('accounts.Account', on_delete=models.PROTECT, related_name='trips')
    entry_plaza = models.ForeignKey(Plaza, on_delete=models.PROTECT, related_name='entry_trips')
    entry_lane = models.ForeignKey(
        TollLane, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='entry_trips'
    )
    entry_time = models.DateTimeField(auto_now_add=True)
    exit_plaza = models.ForeignKey(
        Plaza, null=True, blank=True,
        on_delete=models.PROTECT, related_name='exit_trips'
    )
    exit_lane = models.ForeignKey(
        TollLane, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='exit_trips'
    )
    exit_time = models.DateTimeField(null=True, blank=True)
    charge_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=TripStatus.choices, default=TripStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'toll_trips'
        indexes = [
            models.Index(fields=['vehicle', 'status']),
            models.Index(fields=['entry_time']),
            models.Index(fields=['updated_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['vehicle'],
                condition=models.Q(status='active'),
                name='unique_active_trip_per_vehicle'
            )
        ]

    def __str__(self):
        return f"{self.vehicle.plate_number} — {self.status}"


class SyncLog(models.Model):
    """Tracks last successful sync timestamp per table per direction."""
    table_name   = models.CharField(max_length=60, unique=True)
    last_pull_at = models.DateTimeField(null=True, blank=True)
    last_push_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sync_log'

    def __str__(self):
        return self.table_name


class PendingGateOpen(models.Model):
    """Created by the HTTP API when entry/exit succeeds via portal.
    run_gate.py polls this table and opens the barrier when it finds a record for its plaza."""
    plaza = models.ForeignKey(Plaza, on_delete=models.CASCADE, related_name='pending_opens')
    lane = models.ForeignKey(TollLane, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'pending_gate_opens'
