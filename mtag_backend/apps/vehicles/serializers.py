import re
from datetime import date
from rest_framework import serializers
from .models import Vehicle, Tag


def normalize_plate(value: str) -> str:
    return re.sub(r'[\s\-]', '', value).upper()


class TagSerializer(serializers.ModelSerializer):
    is_valid = serializers.ReadOnlyField()

    class Meta:
        model = Tag
        fields = ['id', 'tag_serial', 'issued_at', 'expiry_date', 'status', 'last_scanned_at', 'is_valid']
        read_only_fields = ['id', 'issued_at', 'last_scanned_at']


class VehicleSerializer(serializers.ModelSerializer):
    tag = TagSerializer(read_only=True)
    owner_phone = serializers.CharField(source='owner.phone', read_only=True)
    owner_name = serializers.CharField(source='owner.full_name', read_only=True)

    class Meta:
        model = Vehicle
        fields = ['id', 'plate_number', 'vehicle_type', 'status', 'registered_at', 'owner_phone', 'owner_name', 'tag']
        read_only_fields = ['id', 'registered_at']


class VehicleCreateSerializer(serializers.ModelSerializer):
    tag_serial = serializers.CharField(write_only=True)
    owner_id = serializers.IntegerField(write_only=True)
    initial_balance = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        required=False, default=0,
        min_value=0,
    )

    class Meta:
        model = Vehicle
        fields = ['plate_number', 'vehicle_type', 'owner_id', 'tag_serial', 'initial_balance']

    def validate_plate_number(self, value):
        normalized = normalize_plate(value)
        if not re.match(r'^[A-Z0-9]{3,10}$', normalized):
            raise serializers.ValidationError(
                "Plate number must be 3–10 letters/digits only (e.g. LHR1234)."
            )
        return normalized

    def validate_owner_id(self, value):
        from apps.users.models import User
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("User not found for given owner_id.")
        return value

    def validate_tag_serial(self, value):
        if not Tag.objects.filter(tag_serial=value, vehicle__isnull=True).exists():
            if Tag.objects.filter(tag_serial=value).exists():
                raise serializers.ValidationError("This tag is already assigned to another vehicle.")
            raise serializers.ValidationError("Tag not found in inventory.")
        return value

    def create(self, validated_data):
        from django.db import transaction
        from apps.accounts.models import Account
        from .models import TagStatus
        tag_serial = validated_data.pop('tag_serial')
        initial_balance = validated_data.pop('initial_balance', 0)
        with transaction.atomic():
            vehicle = Vehicle.objects.create(**validated_data)
            tag = Tag.objects.get(tag_serial=tag_serial, vehicle__isnull=True)
            tag.vehicle = vehicle
            tag.expiry_date = date(2099, 12, 31)
            tag.status = TagStatus.ACTIVE
            tag.save()
            Account.objects.create(
                vehicle=vehicle,
                user_id=validated_data['owner_id'],
                balance=initial_balance,
            )
        return vehicle


class TagReissueSerializer(serializers.Serializer):
    tag_serial = serializers.CharField(max_length=24)

    def validate_tag_serial(self, value):
        if not Tag.objects.filter(tag_serial=value, vehicle__isnull=True).exists():
            if Tag.objects.filter(tag_serial=value).exists():
                raise serializers.ValidationError("This tag is already assigned to a vehicle.")
            raise serializers.ValidationError("Tag not found in inventory.")
        return value
