import logging
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings as django_settings
from utils.response import success_response, error_response
from .serializers import RegisterSerializer, LoginSerializer, UserDetailSerializer, UserListSerializer
from .models import User
from .permissions import IsAdmin

logger = logging.getLogger(__name__)


class LoginRateThrottle(AnonRateThrottle):
    scope = 'login'


def _set_auth_cookies(response, access: str, refresh: str) -> None:
    is_secure = not django_settings.DEBUG
    jwt_settings = django_settings.SIMPLE_JWT
    access_max_age = int(jwt_settings['ACCESS_TOKEN_LIFETIME'].total_seconds())
    refresh_max_age = int(jwt_settings['REFRESH_TOKEN_LIFETIME'].total_seconds())
    response.set_cookie('access_token', access, max_age=access_max_age,
                        httponly=True, samesite='Lax', secure=is_secure, path='/')
    response.set_cookie('refresh_token', refresh, max_age=refresh_max_age,
                        httponly=True, samesite='Lax', secure=is_secure, path='/')


def _clear_auth_cookies(response) -> None:
    response.delete_cookie('access_token', path='/')
    response.delete_cookie('refresh_token', path='/')


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            logger.info("New user registered: %s", user.phone)
            return success_response(
                data=UserDetailSerializer(user).data,
                message="Registration successful",
                status_code=201
            )
        return error_response("Registration failed", errors=serializer.errors)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            access = data.pop('access')
            refresh = data.pop('refresh')
            response = success_response(data=data, message="Login successful")
            _set_auth_cookies(response, access, refresh)
            return response
        return error_response("Login failed", errors=serializer.errors, status_code=401)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token_str = request.COOKIES.get('refresh_token') or request.data.get('refresh', '')
        if refresh_token_str:
            try:
                token = RefreshToken(refresh_token_str)
                token.blacklist()
            except Exception:
                pass
        response = success_response(message="Logged out successfully")
        _clear_auth_cookies(response)
        return response


class TokenRefreshCookieView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from rest_framework_simplejwt.serializers import TokenRefreshSerializer
        refresh_token_str = request.COOKIES.get('refresh_token')
        if not refresh_token_str:
            return error_response("No refresh token", status_code=401)
        try:
            serializer = TokenRefreshSerializer(data={'refresh': refresh_token_str})
            serializer.is_valid(raise_exception=True)
            access = serializer.validated_data['access']
            new_refresh = serializer.validated_data.get('refresh', refresh_token_str)
            response = success_response(data={'detail': 'Token refreshed'})
            _set_auth_cookies(response, access, new_refresh)
            return response
        except Exception:
            response = error_response("Session expired. Please log in again.", status_code=401)
            _clear_auth_cookies(response)
            return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return success_response(data=UserDetailSerializer(request.user).data)

    def patch(self, request):
        serializer = UserDetailSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return success_response(data=serializer.data, message="Profile updated")
        return error_response("Update failed", errors=serializer.errors)


class AdminUserListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        users = User.objects.all().order_by('-id')
        serializer = UserListSerializer(users, many=True)
        return success_response(data=serializer.data)


class AdminUserDetailView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
            return success_response(data=UserDetailSerializer(user).data)
        except User.DoesNotExist:
            return error_response("User not found", status_code=404)

    def patch(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
            serializer = UserDetailSerializer(user, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return success_response(data=serializer.data, message="User updated")
            return error_response("Update failed", errors=serializer.errors)
        except User.DoesNotExist:
            return error_response("User not found", status_code=404)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')

        if not old_password or not new_password:
            return error_response("old_password and new_password are required")
        if not request.user.check_password(old_password):
            return error_response("Current password is incorrect", status_code=400)
        if len(new_password) < 8:
            return error_response("New password must be at least 8 characters")

        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])
        logger.info("Password changed for user %s", request.user.phone)
        return success_response(message="Password changed successfully")
