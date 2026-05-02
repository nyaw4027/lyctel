from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from products.models import Product


@api_view(["GET"])
@permission_classes([AllowAny])
def product_list(request):
    products = Product.objects.all()

    data = [
        {
            "id": p.id,
            "name": p.name,
            "price": float(p.price),
            "image": p.image.url if p.image else None,
        }
        for p in products
    ]

    return Response(data)