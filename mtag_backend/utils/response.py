from rest_framework.response import Response


def success_response(data=None, message="Success", status_code=200, meta=None):
    payload = {"success": True, "message": message, "data": data}
    if meta:
        payload["meta"] = meta
    return Response(payload, status=status_code)


def error_response(message="An error occurred", errors=None, status_code=400):
    payload = {"success": False, "message": message}
    if errors:
        payload["errors"] = errors
    return Response(payload, status=status_code)
