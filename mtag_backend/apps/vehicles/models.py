import uuid
from django.db import models


class VehicleType(models.TextChoices):
    CAR = 'car', 'Car'
    MOTORCYCLE = 'motorcycle', 'Motorcycle'
    TRUCK = 'truck', 'Truck'
    BUS = 'bus', 'Bus'


class VehicleStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    INACTIVE = 'inactive', 'Inactive'
    SUSPENDED = 'suspended', 'Suspended'


class TagStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    EXPIRED = 'expired', 'Expired'
    SUSPENDED = 'suspended', 'Suspended'
    DEACTIVATED = 'deactivated', 'Deactivated'


class Vehicle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        'users.User', on_delete=models.PROTECT, related_name='vehicles'
    )
    plate_number = models.CharField(max_length=20, unique=True)
    vehicle_type = models.CharField(max_length=20, choices=VehicleType.choices)
    status = models.CharField(max_length=20, choices=VehicleStatus.choices, default=VehicleStatus.ACTIVE)
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vehicles'
        indexes = [models.Index(fields=['plate_number'])]

    def __str__(self):
        return self.plate_number


class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tag_serial = models.CharField(max_length=24, unique=True)
    epc = models.CharField(max_length=24, blank=True, default='')
    vehicle = models.OneToOneField(Vehicle, null=True, blank=True, on_delete=models.CASCADE, related_name='tag')
    issued_at = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateField()
    status = models.CharField(max_length=20, choices=TagStatus.choices, default=TagStatus.ACTIVE)
    last_scanned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'tags'
        indexes = [models.Index(fields=['tag_serial'])]

    def __str__(self):
        return self.tag_serial

    @property
    def is_valid(self):
        from django.utils import timezone
        return (
            self.vehicle_id is not None and
            self.status == TagStatus.ACTIVE and
            self.expiry_date >= timezone.now().date()
        )
