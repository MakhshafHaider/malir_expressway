import logging
import calendar
from datetime import timedelta, datetime
from django.utils import timezone
from django.db.models import Sum, Count, Q
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from utils.response import success_response, error_response
from utils.pagination import StandardPagination
from .models import Plaza, TollRate, TollTrip, TripStatus, PendingGateOpen
from .serializers import PlazaSerializer, TollRateSerializer, TollRateCreateSerializer, TollTripSerializer, TollLaneSerializer, PlazaCreateSerializer, LaneCreateSerializer
from .services import EntryService, ExitService, invalidate_rate_cache
from apps.users.permissions import IsAdmin, IsOperator

logger = logging.getLogger(__name__)


class VehicleEntryView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        tag_serial = request.data.get('tag_serial', '').strip()
        plaza_id = request.data.get('plaza_id')
        lane_id = request.data.get('lane_id')
        if not tag_serial or not plaza_id:
            return error_response("tag_serial and plaza_id are required")
        result = EntryService.process_entry(tag_serial, plaza_id, lane_id)
        if result['success']:
            PendingGateOpen.objects.create(plaza_id=plaza_id, lane_id=lane_id or None)
            return success_response(data=result, message="Entry recorded — gate open")
        extra = {k: v for k, v in result.items() if k not in ('success', 'reason')}
        return error_response(result.get('reason', 'Entry denied'), errors=extra or None, status_code=400)


class VehicleExitView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        tag_serial = request.data.get('tag_serial', '').strip()
        plaza_id = request.data.get('plaza_id')
        lane_id = request.data.get('lane_id')
        if not tag_serial or not plaza_id:
            return error_response("tag_serial and plaza_id are required")
        result = ExitService.process_exit(tag_serial, plaza_id, lane_id)
        if result['success']:
            PendingGateOpen.objects.create(plaza_id=plaza_id, lane_id=lane_id or None)
            return success_response(data=result, message="Exit recorded — gate open")
        extra = {k: v for k, v in result.items() if k not in ('success', 'reason')}
        return error_response(result.get('reason', 'Exit denied'), errors=extra or None, status_code=400)


class TripHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, vehicle_id):
        trips = TollTrip.objects.select_related(
            'entry_plaza', 'exit_plaza'
        ).filter(vehicle_id=vehicle_id).order_by('-entry_time')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(trips, request)
        return paginator.get_paginated_response(TollTripSerializer(page, many=True).data)


class PlazaListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plazas = Plaza.objects.prefetch_related('lanes').filter(is_active=True)
        return success_response(data=PlazaSerializer(plazas, many=True).data)


class TollRateListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rates = TollRate.objects.select_related('entry_plaza', 'exit_plaza').all()
        return success_response(data=TollRateSerializer(rates, many=True).data)


class AdminTripListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        trips = TollTrip.objects.select_related(
            'vehicle', 'entry_plaza', 'exit_plaza'
        ).all().order_by('-entry_time')
        status_filter = request.query_params.get('status')
        if status_filter:
            trips = trips.filter(status=status_filter)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(trips, request)
        return paginator.get_paginated_response(TollTripSerializer(page, many=True).data)


class AdminPlazaView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        plazas = Plaza.objects.prefetch_related('lanes').all().order_by('name')
        return success_response(data=PlazaSerializer(plazas, many=True).data)

    def post(self, request):
        serializer = PlazaCreateSerializer(data=request.data)
        if serializer.is_valid():
            plaza = serializer.save()
            return success_response(
                data=PlazaSerializer(plaza).data,
                message="Plaza created successfully",
                status_code=201,
            )
        return error_response("Invalid data", errors=serializer.errors)


class AdminPlazaDetailView(APIView):
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        try:
            plaza = Plaza.objects.prefetch_related('lanes').get(pk=pk)
        except Plaza.DoesNotExist:
            return error_response("Plaza not found", status_code=404)
        serializer = PlazaCreateSerializer(plaza, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            plaza.refresh_from_db()
            return success_response(data=PlazaSerializer(plaza).data, message="Plaza updated")
        return error_response("Invalid data", errors=serializer.errors)

    def delete(self, request, pk):
        try:
            plaza = Plaza.objects.get(pk=pk)
        except Plaza.DoesNotExist:
            return error_response("Plaza not found", status_code=404)
        try:
            plaza.delete()
        except Exception:
            return error_response("Cannot delete plaza with existing trips. Deactivate it instead.", status_code=409)
        return success_response(message="Plaza deleted")


class AdminLaneView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, plaza_id):
        try:
            plaza = Plaza.objects.get(pk=plaza_id)
        except Plaza.DoesNotExist:
            return error_response("Plaza not found", status_code=404)
        serializer = LaneCreateSerializer(data=request.data)
        if serializer.is_valid():
            try:
                from django.db import IntegrityError
                lane = serializer.save(plaza=plaza)
            except IntegrityError:
                return error_response(
                    f"Lane {serializer.validated_data['lane_number']} already exists for this plaza.",
                    status_code=400,
                )
            return success_response(
                data=TollLaneSerializer(lane).data,
                message="Lane added successfully",
                status_code=201,
            )
        return error_response("Invalid data", errors=serializer.errors)


class AdminTollRateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        rates = TollRate.objects.select_related('entry_plaza', 'exit_plaza').all().order_by(
            'entry_plaza__name', 'exit_plaza__name', 'vehicle_type'
        )
        return success_response(data=TollRateSerializer(rates, many=True).data)

    def post(self, request):
        serializer = TollRateCreateSerializer(data=request.data)
        if serializer.is_valid():
            rate = serializer.save()
            invalidate_rate_cache()
            return success_response(
                data=TollRateSerializer(rate).data,
                message="Toll rate created successfully",
                status_code=201,
            )
        return error_response("Invalid data", errors=serializer.errors)


class AdminRateDetailView(APIView):
    permission_classes = [IsAdmin]

    def delete(self, request, pk):
        try:
            rate = TollRate.objects.get(pk=pk)
        except TollRate.DoesNotExist:
            return error_response("Toll rate not found", status_code=404)
        rate.delete()
        return success_response(message="Toll rate deleted")

    def patch(self, request, pk):
        try:
            rate = TollRate.objects.select_related('entry_plaza', 'exit_plaza').get(pk=pk)
        except TollRate.DoesNotExist:
            return error_response("Toll rate not found", status_code=404)
        serializer = TollRateCreateSerializer(rate, data=request.data, partial=True)
        if serializer.is_valid():
            rate = serializer.save()
            invalidate_rate_cache()
            return success_response(data=TollRateSerializer(rate).data, message="Rate updated")
        return error_response("Invalid data", errors=serializer.errors)


class AdminStatsView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        from apps.vehicles.models import Vehicle
        from apps.accounts.models import Account

        now = timezone.now()
        today = now.date()

        # Last 6 months
        monthly = []
        for i in range(5, -1, -1):
            year = now.year
            month = now.month - i
            while month <= 0:
                month += 12
                year -= 1
            _, last_day = calendar.monthrange(year, month)
            month_start = timezone.make_aware(datetime(year, month, 1))
            month_end = timezone.make_aware(datetime(year, month, last_day, 23, 59, 59))
            agg = TollTrip.objects.filter(
                status=TripStatus.COMPLETED,
                exit_time__gte=month_start,
                exit_time__lte=month_end,
            ).aggregate(revenue=Sum('charge_amount'), count=Count('id'))
            monthly.append({
                'month': month_start.strftime('%b'),
                'toll': float(agg['revenue'] or 0),
                'transactions': agg['count'] or 0,
            })

        # Last 7 days
        daily = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            day_start = timezone.make_aware(datetime(day.year, day.month, day.day))
            day_end = day_start + timedelta(days=1)
            agg = TollTrip.objects.filter(
                status=TripStatus.COMPLETED,
                exit_time__gte=day_start,
                exit_time__lt=day_end,
            ).aggregate(revenue=Sum('charge_amount'), count=Count('id'))
            daily.append({
                'day': day.strftime('%a'),
                'amount': float(agg['revenue'] or 0),
                'count': agg['count'] or 0,
            })

        # Vehicle type breakdown
        total_vehicles = Vehicle.objects.count()
        vehicle_type_counts = Vehicle.objects.values('vehicle_type').annotate(count=Count('id'))
        vehicle_type_data = [
            {
                'name': row['vehicle_type'].capitalize(),
                'value': round(row['count'] / total_vehicles * 100) if total_vehicles else 0,
                'count': row['count'],
            }
            for row in vehicle_type_counts
        ]

        # Plaza stats
        plaza_stats = [
            {
                'name': plaza.name,
                'revenue': float(
                    TollTrip.objects.filter(status=TripStatus.COMPLETED, exit_plaza=plaza)
                    .aggregate(rev=Sum('charge_amount'))['rev'] or 0
                ),
                'trips': TollTrip.objects.filter(status=TripStatus.COMPLETED, exit_plaza=plaza).count(),
                'is_active': plaza.is_active,
            }
            for plaza in Plaza.objects.all()
        ]

        # Summary totals
        total_balance = Account.objects.aggregate(total=Sum('balance'))['total'] or 0
        agg = TollTrip.objects.aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status=TripStatus.COMPLETED)),
            active=Count('id', filter=Q(status=TripStatus.ACTIVE)),
            revenue=Sum('charge_amount', filter=Q(status=TripStatus.COMPLETED)),
        )

        return success_response(data={
            'monthly': monthly,
            'daily': daily,
            'vehicle_type_breakdown': vehicle_type_data,
            'plaza_stats': plaza_stats,
            'total_vehicles': total_vehicles,
            'total_balance': float(total_balance),
            'active_plazas': Plaza.objects.filter(is_active=True).count(),
            'total_trips': agg['total'] or 0,
            'completed_trips': agg['completed'] or 0,
            'active_trips': agg['active'] or 0,
            'total_revenue': float(agg['revenue'] or 0),
        })


class AdminTripCloseView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, trip_id):
        try:
            trip = TollTrip.objects.select_related('vehicle', 'entry_plaza', 'exit_plaza').get(
                pk=trip_id, status=TripStatus.ACTIVE
            )
        except TollTrip.DoesNotExist:
            return error_response("Active trip not found", status_code=404)

        trip.status = TripStatus.FAILED
        trip.exit_time = timezone.now()
        trip.save(update_fields=['status', 'exit_time'])

        logger.info("Admin force-closed trip %s for vehicle %s", trip.id, trip.vehicle.plate_number)
        return success_response(data=TollTripSerializer(trip).data, message="Trip closed successfully")


class AdminTripRefundView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, trip_id):
        from django.db import transaction as db_transaction
        from apps.accounts.models import Account, Transaction, TransactionType, TransactionStatus, TransactionSource

        try:
            trip = TollTrip.objects.select_related('vehicle', 'account').get(
                pk=trip_id, status=TripStatus.COMPLETED
            )
        except TollTrip.DoesNotExist:
            return error_response("Completed trip not found", status_code=404)

        if not trip.charge_amount or trip.charge_amount <= 0:
            return error_response("No charge to refund for this trip", status_code=400)

        if Transaction.objects.filter(toll_trip=trip, transaction_type=TransactionType.REFUND).exists():
            return error_response("This trip has already been refunded", status_code=400)

        with db_transaction.atomic():
            account = Account.objects.select_for_update().get(pk=trip.account.pk)
            balance_before = account.balance
            account.balance += trip.charge_amount
            account.save(update_fields=['balance', 'balance_updated_at'])
            Transaction.objects.create(
                account=account,
                toll_trip=trip,
                transaction_type=TransactionType.REFUND,
                amount=trip.charge_amount,
                balance_before=balance_before,
                balance_after=account.balance,
                status=TransactionStatus.SUCCESS,
                source=TransactionSource.REFUND,
            )

        logger.info("Admin refunded trip %s for %s — PKR %s", trip.id, trip.vehicle.plate_number, trip.charge_amount)
        return success_response(data={
            'trip_id': str(trip.id),
            'plate_number': trip.vehicle.plate_number,
            'refunded_amount': str(trip.charge_amount),
            'new_balance': str(account.balance),
        }, message="Refund processed successfully")


class AdminGateEventListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        qs = PendingGateOpen.objects.select_related('plaza', 'lane').order_by('-created_at')
        pending_only = request.query_params.get('pending') == '1'
        if pending_only:
            qs = qs.filter(executed_at__isnull=True)
        events = qs[:100]
        data = [
            {
                'id': e.id,
                'plaza': e.plaza.name,
                'lane': e.lane.lane_number if e.lane else None,
                'created_at': e.created_at.isoformat(),
                'executed_at': e.executed_at.isoformat() if e.executed_at else None,
                'status': 'executed' if e.executed_at else 'pending',
            }
            for e in events
        ]
        return success_response(data=data)
