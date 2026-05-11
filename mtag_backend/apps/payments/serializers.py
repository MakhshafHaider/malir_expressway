from rest_framework import serializers
from .models import TopupRequest


class TopupRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = TopupRequest
        fields = ['id', 'amount', 'status', 'jazzcash_txn_id', 'requested_at', 'completed_at']
        read_only_fields = ['id', 'amount', 'status', 'jazzcash_txn_id', 'requested_at', 'completed_at']


class InitiateTopupSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=100)
