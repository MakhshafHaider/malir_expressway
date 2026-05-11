import logging
from rest_framework.views import exception_handler
from rest_framework.exceptions import ValidationError, AuthenticationFailed, NotAuthenticated
from utils.response import error_response

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        if isinstance(exc, ValidationError):
            return error_response(
                message="Validation failed",
                errors=response.data,
                status_code=response.status_code
            )
        if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
            return error_response(
                message="Authentication required",
                status_code=response.status_code
            )
        return error_response(
            message=str(response.data.get('detail', 'Request failed')),
            status_code=response.status_code
        )

    logger.exception("Unhandled exception in view: %s", exc)
    return error_response(message="Internal server error", status_code=500)
