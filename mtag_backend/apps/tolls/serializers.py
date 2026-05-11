from rest_framework import serializers
from .models import Plaza, TollLane, TollRate, TollTrip


class TollLaneSerializer(serializers.ModelSerializer):
    class Meta:
        model = TollLane
        fields = ['id', 'lane_number', 'is_active']


class PlazaSerializer(serializers.ModelSerializer):
    lanes = TollLaneSerializer(many=True, read_only=True)

    class Meta:
        model = Plaza
        fields = ['id', 'name', 'code', 'latitude', 'longitude', 'is_active', 'lanes']


class PlazaCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plaza
        fields = ['name', 'code', 'latitude', 'longitude', 'is_active']


class LaneCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TollLane
        fields = ['lane_number', 'is_active']


class TollRateSerializer(serializers.ModelSerializer):
    entry_plaza_name = serializers.CharField(source='entry_plaza.name', read_only=True)
    exit_plaza_name = serializers.CharField(source='exit_plaza.name', read_only=True)

    class Meta:
        model = TollRate
        fields = [
            'id', 'entry_plaza', 'entry_plaza_name',
            'exit_plaza', 'exit_plaza_name',
            'vehicle_type', 'rate', 'effective_from'
        ]


class TollRateCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TollRate
        fields = ['entry_plaza', 'exit_plaza', 'vehicle_type', 'rate', 'effective_from']

    def validate(self, data):
        if data.get('entry_plaza') == data.get('exit_plaza'):
            raise serializers.ValidationError("Entry and exit plaza cannot be the same.")
        return data


class TollTripSerializer(serializers.ModelSerializer):
    entry_plaza_name = serializers.CharField(source='entry_plaza.name', read_only=True)
    exit_plaza_name = serializers.CharField(source='exit_plaza.name', read_only=True, allow_null=True)
    plate_number = serializers.CharField(source='vehicle.plate_number', read_only=True)
    duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model = TollTrip
        fields = [
            'id', 'plate_number', 'entry_plaza_name', 'exit_plaza_name',
            'entry_time', 'exit_time', 'charge_amount',
            'balance_before', 'balance_after', 'status', 'duration_minutes'
        ]

    def get_duration_minutes(self, obj):
        if obj.exit_time and obj.entry_time:
            delta = obj.exit_time - obj.entry_time
            return round(delta.total_seconds() / 60, 1)
        return None
