from rest_framework import serializers
from order.models import Order


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = [
            "id",
            "order_ref",
            "status",
            "total_amount",
            "delivery_address",
            "delivery_city",
            "created_at",
        ]