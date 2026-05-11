import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from utils.response import success_response, error_response
from .services import JazzCashService
from .serializers import InitiateTopupSerializer, TopupRequestSerializer
from .models import TopupRequest

logger = logging.getLogger(__name__)


class InitiateTopupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InitiateTopupSerializer(data=request.data)
        if serializer.is_valid():
            result = JazzCashService.initiate_topup(
                account_id=str(serializer.validated_data['account_id']),
                user_id=request.user.id,
                amount=serializer.validated_data['amount'],
            )
            if result['success']:
                return success_response(data=result, message="Topup initiated", status_code=201)
            return error_response(result['reason'])
        return error_response("Invalid data", errors=serializer.errors)


class JazzCashCallbackView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        txn_id = request.data.get('pp_TxnRefNo', '')
        response_code = request.data.get('pp_ResponseCode', '')
        # topup_id can come from POST body or query param (?topup_id=...)
        topup_id = request.data.get('topup_id', '') or request.query_params.get('topup_id', '')
        logger.info("JazzCash callback — txn: %s code: %s topup: %s", txn_id, response_code, topup_id)
        result = JazzCashService.handle_callback(txn_id, response_code, topup_id)
        if result['success']:
            return success_response(data=result, message="Payment recorded")
        return error_response(result['reason'], status_code=400)


class TopupHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        topups = TopupRequest.objects.filter(account_id=account_id).order_by('-requested_at')
        return success_response(data=TopupRequestSerializer(topups, many=True).data)
