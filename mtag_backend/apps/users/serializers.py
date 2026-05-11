from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, required=False)

    class Meta:
        model = User
        fields = ['full_name', 'phone', 'cnic', 'password']

    def create(self, validated_data):
        if 'password' not in validated_data:
            import secrets, string
            alphabet = string.ascii_letters + string.digits + '!@#'
            validated_data['password'] = ''.join(secrets.choice(alphabet) for _ in range(12))
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs['phone'], password=attrs['password'])
        if not user:
            raise serializers.ValidationError("Invalid phone number or password.")
        if user.status == 'blocked':
            raise serializers.ValidationError("Account is blocked. Contact support.")
        user.last_login_at = timezone.now()
        user.save(update_fields=['last_login_at'])
        refresh = RefreshToken.for_user(user)
        return {
            'user_id': user.id,
            'uuid': str(user.uuid),
            'full_name': user.full_name,
            'phone': user.phone,
            'role': user.user_role,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }


class UserDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'uuid', 'full_name', 'phone', 'cnic', 'user_role', 'status', 'created_at']
        read_only_fields = ['id', 'uuid', 'created_at']


class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'uuid', 'full_name', 'phone', 'user_role', 'status', 'created_at']
