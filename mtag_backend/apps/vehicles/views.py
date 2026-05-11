import csv
import io
import logging
from datetime import date
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser
from utils.response import success_response, error_response
from .models import Vehicle, Tag, TagStatus
from .serializers import VehicleSerializer, VehicleCreateSerializer, TagSerializer, TagReissueSerializer, normalize_plate
from apps.users.permissions import IsOperator, IsAdmin

logger = logging.getLogger(__name__)


class VehicleListCreateView(APIView):
    permission_classes = [IsOperator]

    def get(self, request):
        vehicles = Vehicle.objects.select_related('tag', 'owner').all().order_by('-registered_at')
        plate = request.query_params.get('plate')
        if plate:
            vehicles = vehicles.filter(plate_number__icontains=normalize_plate(plate))
        return success_response(data=VehicleSerializer(vehicles, many=True).data)

    def post(self, request):
        serializer = VehicleCreateSerializer(data=request.data)
        if serializer.is_valid():
            vehicle = serializer.save()
            logger.info("Vehicle registered: %s", vehicle.plate_number)
            return success_response(
                data=VehicleSerializer(vehicle).data,
                message="Vehicle registered successfully",
                status_code=201
            )
        return error_response("Registration failed", errors=serializer.errors)


class VehicleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            vehicle = Vehicle.objects.select_related('tag', 'owner').get(pk=pk)
            return success_response(data=VehicleSerializer(vehicle).data)
        except Vehicle.DoesNotExist:
            return error_response("Vehicle not found", status_code=404)

    def patch(self, request, pk):
        try:
            vehicle = Vehicle.objects.get(pk=pk)
            serializer = VehicleSerializer(vehicle, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return success_response(data=serializer.data, message="Vehicle updated")
            return error_response("Update failed", errors=serializer.errors)
        except Vehicle.DoesNotExist:
            return error_response("Vehicle not found", status_code=404)


class VehicleByPlateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, plate_number):
        try:
            vehicle = Vehicle.objects.select_related('tag', 'owner').get(
                plate_number=normalize_plate(plate_number)
            )
            return success_response(data=VehicleSerializer(vehicle).data)
        except Vehicle.DoesNotExist:
            return error_response("Vehicle not found", status_code=404)


class TagReissueView(APIView):
    permission_classes = [IsOperator]

    def post(self, request, vehicle_id):
        try:
            vehicle = Vehicle.objects.get(pk=vehicle_id)
        except Vehicle.DoesNotExist:
            return error_response("Vehicle not found", status_code=404)

        serializer = TagReissueSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response("Invalid data", errors=serializer.errors)

        from datetime import date
        new_serial = serializer.validated_data['tag_serial']

        # Deactivate the vehicle's current tag
        old_tag = Tag.objects.filter(vehicle=vehicle).first()
        if old_tag:
            old_tag.vehicle = None
            old_tag.status = TagStatus.DEACTIVATED
            old_tag.save()

        # Assign the unassigned inventory tag to this vehicle
        new_tag = Tag.objects.get(tag_serial=new_serial, vehicle__isnull=True)
        new_tag.vehicle = vehicle
        new_tag.expiry_date = date(2099, 12, 31)
        new_tag.status = TagStatus.ACTIVE
        new_tag.save()

        logger.info("Tag reissued for vehicle %s — old deactivated, new serial %s", vehicle.plate_number, new_serial)
        return success_response(
            data=TagSerializer(new_tag).data,
            message="Tag reissued successfully",
            status_code=201,
        )


class AvailableTagsView(APIView):
    permission_classes = [IsOperator]

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        qs = Tag.objects.filter(
            vehicle__isnull=True,
            status=TagStatus.ACTIVE,
        ).order_by('tag_serial')
        if search:
            qs = qs.filter(tag_serial__icontains=search)
        tags = qs.values('id', 'tag_serial', 'epc')[:20]
        return success_response(data=list(tags))


class TagCreateView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        tag_serial = request.data.get('tag_serial', '').strip()
        epc = request.data.get('epc', '').strip()
        if not tag_serial:
            return error_response("tag_serial is required")
        if Tag.objects.filter(tag_serial=tag_serial).exists():
            return error_response("A tag with this serial already exists", status_code=409)
        tag = Tag.objects.create(
            tag_serial=tag_serial,
            epc=epc,
            vehicle=None,
            expiry_date=date(2099, 12, 31),
            status=TagStatus.ACTIVE,
        )
        logger.info("Single tag added: %s", tag_serial)
        return success_response(
            data={'id': str(tag.id), 'tag_serial': tag.tag_serial, 'epc': tag.epc},
            message="Tag added to inventory",
            status_code=201,
        )


class VehicleSuspendView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        try:
            vehicle = Vehicle.objects.select_related('tag').get(pk=pk)
        except Vehicle.DoesNotExist:
            return error_response("Vehicle not found", status_code=404)

        from .models import VehicleStatus
        action = request.data.get('action')
        if action == 'suspend':
            vehicle.status = VehicleStatus.SUSPENDED
            vehicle.save(update_fields=['status'])
            tag = getattr(vehicle, 'tag', None)
            if tag:
                tag.status = TagStatus.SUSPENDED
                tag.save(update_fields=['status'])
        elif action == 'activate':
            vehicle.status = VehicleStatus.ACTIVE
            vehicle.save(update_fields=['status'])
            tag = getattr(vehicle, 'tag', None)
            if tag:
                tag.status = TagStatus.ACTIVE
                tag.save(update_fields=['status'])
        else:
            return error_response("action must be 'suspend' or 'activate'")

        logger.info("Vehicle %s — action: %s", vehicle.plate_number, action)
        return success_response(data=VehicleSerializer(vehicle).data, message=f"Vehicle {action}d successfully")


class TagInventoryUploadView(APIView):
    permission_classes = [IsAdmin]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return error_response("No file uploaded.", status_code=400)
        if not file.name.lower().endswith('.csv'):
            return error_response("File must be a CSV.", status_code=400)

        try:
            content = file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            return error_response("File encoding not supported. Use UTF-8.", status_code=400)

        reader = csv.DictReader(io.StringIO(content))
        existing = set(Tag.objects.values_list('tag_serial', flat=True))
        to_create, added, skipped, row_errors = [], [], [], []

        for i, row in enumerate(reader, start=2):
            serial = (row.get('TID') or '').strip()
            epc = (row.get('EPC') or '').strip()
            if not serial:
                row_errors.append(f"Row {i}: missing TID")
                continue
            if serial in existing:
                skipped.append(serial)
                continue
            existing.add(serial)
            to_create.append(Tag(
                tag_serial=serial,
                epc=epc,
                vehicle=None,
                expiry_date=date(2099, 12, 31),
                status=TagStatus.ACTIVE,
            ))
            added.append(serial)

        Tag.objects.bulk_create(to_create)
        logger.info("Tag CSV upload: %d added, %d skipped", len(added), len(skipped))

        return success_response(
            data={
                'added': len(added),
                'skipped': len(skipped),
                'errors': row_errors,
                'skipped_serials': skipped,
            },
            message=f"{len(added)} tag(s) added, {len(skipped)} already existed.",
            status_code=201,
        )
