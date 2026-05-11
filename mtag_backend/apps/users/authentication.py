from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """Reads JWT from httpOnly 'access_token' cookie, falls back to Bearer header."""

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            raw_token = self.get_raw_token(header)
        else:
            cookie_val = request.COOKIES.get('access_token', '')
            raw_token = cookie_val.encode() if cookie_val else None

        if not raw_token:
            return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
