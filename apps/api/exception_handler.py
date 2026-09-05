from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler

from apps.core.exceptions import BusinessError


def business_exception_handler(exc, context):
    if isinstance(exc, BusinessError):
        return Response({"detail": exc.message, **exc.details}, status=400)
    return drf_handler(exc, context)
