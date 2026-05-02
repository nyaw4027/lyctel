from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rider.models import Delivery


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def active_deliveries(request):
    deliveries = Delivery.objects.filter(
        rider=request.user,
        status__in=["assigned", "picked_up", "en_route"]
    ).order_by("-id")

    data = [
        {
            "id": d.id,
            "order_ref": d.order.order_ref,
            "status": d.status,
            "address": d.order.delivery_address,
            "city": d.order.delivery_city,
            "commission": float(d.rider_commission),
        }
        for d in deliveries
    ]

    return Response(data)