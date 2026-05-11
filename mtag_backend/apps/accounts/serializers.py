from rest_framework import serializers
from .models import Account, Transaction
from apps.vehicles.models import Vehicle


class AccountSerializer(serializers.ModelSerializer):
    plate_number = serializers.CharField(source='vehicle.plate_number', read_only=True)
    vehicle_type = serializers.CharField(source='vehicle.vehicle_type', read_only=True)

    class Meta:
        model = Account
        fields = ['id', 'plate_number', 'vehicle_type', 'balance', 'balance_updated_at', 'created_at']
        read_only_fields = ['id', 'plate_number', 'vehicle_type', 'balance', 'balance_updated_at', 'created_at']


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_type', 'amount',
            'balance_before', 'balance_after',
            'status', 'tag_serial', 'reference_id', 'processed_at'
        ]
        read_only_fields = [
            'id', 'transaction_type', 'amount', 'balance_before',
            'balance_after', 'status', 'tag_serial', 'reference_id', 'processed_at'
        ]


class TransferSerializer(serializers.Serializer):
    source_vehicle_id = serializers.UUIDField()
    target_vehicle_id = serializers.UUIDField()
    cnic = serializers.CharField(max_length=20)
    phone = serializers.CharField(max_length=20)
    name = serializers.CharField(max_length=100)

    def validate(self, data):
        if data['source_vehicle_id'] == data['target_vehicle_id']:
            raise serializers.ValidationError("Source and target vehicle must be different.")
        return data
