import logging
from decimal import Decimal, InvalidOperation
from django.db import transaction as db_transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from utils.response import success_response, error_response
from utils.pagination import StandardPagination
from .models import Account, Transaction, TransactionType, TransactionStatus
from .serializers import AccountSerializer, TransactionSerializer, TransferSerializer
from .services import TransferService
from apps.users.permissions import IsAdmin, IsOperator

logger = logging.getLogger(__name__)


class AccountDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, vehicle_id):
        try:
            account = Account.objects.select_related('vehicle').get(vehicle_id=vehicle_id)
            return success_response(data=AccountSerializer(account).data)
        except Account.DoesNotExist:
            return error_response("Account not found", status_code=404)


class TransactionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        try:
            account = Account.objects.get(id=account_id)
        except Account.DoesNotExist:
            return error_response("Account not found", status_code=404)

        txns = account.transactions.all()
        txn_type = request.query_params.get('type')
        if txn_type:
            txns = txns.filter(transaction_type=txn_type)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(txns, request)
        return paginator.get_paginated_response(TransactionSerializer(page, many=True).data)


class AdminAccountListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        accounts = Account.objects.select_related('vehicle', 'user').all()
        return success_response(data=AccountSerializer(accounts, many=True).data)


class TransferView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TransferSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Invalid data", errors=serializer.errors)

        d = serializer.validated_data
        result = TransferService.execute(
            user=request.user,
            source_vehicle_id=str(d['source_vehicle_id']),
            target_vehicle_id=str(d['target_vehicle_id']),
            cnic=d['cnic'],
            phone=d['phone'],
            name=d['name'],
        )

        if not result['success']:
            return error_response(
                result['reason'],
                status_code=result.get('status_code', 400)
            )
        return success_response(data=result, message="Balance transferred successfully")


class OperatorTopupView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        tag_serial = request.data.get('tag_serial', '').strip()
        amount_raw = request.data.get('amount')
        if not tag_serial or amount_raw is None:
            return error_response("tag_serial and amount are required")
        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal('0.01'))
            if amount <= 0:
                return error_response("Amount must be greater than zero")
        except (InvalidOperation, ValueError):
            return error_response("Invalid amount")

        from apps.vehicles.models import Tag
        try:
            tag = Tag.objects.select_related('vehicle').get(tag_serial=tag_serial)
        except Tag.DoesNotExist:
            return error_response("Tag not found", status_code=404)

        with db_transaction.atomic():
            account = Account.objects.select_for_update().get(vehicle=tag.vehicle)
            balance_before = account.balance
            account.balance += amount
            account.save(update_fields=['balance', 'balance_updated_at'])
            Transaction.objects.create(
                account=account,
                tag_serial=tag_serial,
                transaction_type=TransactionType.TOPUP,
                amount=amount,
                balance_before=balance_before,
                balance_after=account.balance,
                status=TransactionStatus.SUCCESS,
            )

        logger.info("Operator topup — tag: %s amount: %s new_balance: %s", tag_serial, amount, account.balance)
        return success_response(data={
            'plate_number': tag.vehicle.plate_number,
            'amount_added': str(amount),
            'new_balance': str(account.balance),
        }, message="Balance topped up successfully")


class PlateTopupView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        import re
        plate_raw = request.data.get('plate_number', '').strip()
        amount_raw = request.data.get('amount')
        if not plate_raw or amount_raw is None:
            return error_response("plate_number and amount are required")

        plate = re.sub(r'[\s\-]', '', plate_raw).upper()

        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal('0.01'))
            if amount <= 0:
                return error_response("Amount must be greater than zero")
        except (InvalidOperation, ValueError):
            return error_response("Invalid amount")

        from apps.vehicles.models import Vehicle
        try:
            vehicle = Vehicle.objects.get(plate_number=plate)
        except Vehicle.DoesNotExist:
            return error_response("Vehicle not found", status_code=404)

        if not Account.objects.filter(vehicle=vehicle).exists():
            return error_response("No account found for this vehicle", status_code=404)

        with db_transaction.atomic():
            account = Account.objects.select_for_update().get(vehicle=vehicle)
            balance_before = account.balance
            account.balance += amount
            account.save(update_fields=['balance', 'balance_updated_at'])
            tag_serial = getattr(getattr(vehicle, 'tag', None), 'tag_serial', '')
            Transaction.objects.create(
                account=account,
                tag_serial=tag_serial,
                transaction_type=TransactionType.TOPUP,
                amount=amount,
                balance_before=balance_before,
                balance_after=account.balance,
                status=TransactionStatus.SUCCESS,
            )

        logger.info("Plate topup — plate: %s amount: %s new_balance: %s", plate, amount, account.balance)
        return success_response(data={
            'plate_number': vehicle.plate_number,
            'vehicle_type': vehicle.vehicle_type,
            'amount_added': str(amount),
            'balance_before': str(balance_before),
            'new_balance': str(account.balance),
        }, message="Balance updated successfully")
