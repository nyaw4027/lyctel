from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from payment.models import Payment


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_payments(request):
    payments = Payment.objects.filter(user=request.user).order_by("-id")

    data = [
        {
            "id": p.id,
            "amount": float(p.amount),
            "method": p.method,
            "status": p.status,
            "created_at": p.created_at,
        }
        for p in payments
    ]

    return Response(data)