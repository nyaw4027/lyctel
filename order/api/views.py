from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from order.models import Order


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_orders(request):
    orders = Order.objects.filter(user=request.user).order_by('-id')

    data = [
        {
            "id": o.id,
            "ref": o.order_ref,
            "status": o.status,
            "total": float(o.total_amount),
        }
        for o in orders
    ]

    return Response(data)