"""
food/ratings.py — Food item ratings after delivery (item 9)

SETUP in food/models.py — add:

    class FoodReview(models.Model):
        STARS = [(i, f'{i} star') for i in range(1, 6)]
        food_order = models.ForeignKey('FoodOrder', on_delete=models.CASCADE,
                                        related_name='reviews')
        food_item  = models.ForeignKey('FoodItem', on_delete=models.CASCADE,
                                        related_name='reviews', null=True)
        customer   = models.ForeignKey(settings.AUTH_USER_MODEL,
                                        on_delete=models.CASCADE)
        rating     = models.PositiveSmallIntegerField(choices=STARS)
        comment    = models.TextField(blank=True)
        created_at = models.DateTimeField(auto_now_add=True)
        class Meta:
            unique_together = [('food_order', 'food_item', 'customer')]

Add to food/urls.py:
    path('rate/<str:order_ref>/', views.rate_food_order, name='rate_order'),

Trigger: in food/views.py restaurant_update_order() when status='delivered',
    fire sms_food_delivered() which includes the rating link:
    "Rate: lynctel.app/food/rate/FOOD-001/"
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.contrib import messages


@login_required
def rate_food_order(request, order_ref):
    """GET/POST /food/rate/<order_ref>/ — star rating for each item in the order."""
    from food.models import FoodOrder
    order = get_object_or_404(FoodOrder, order_ref=order_ref, customer=request.user)

    if request.method == 'POST':
        _save_ratings(request, order)
        messages.success(request, 'Thank you for your rating! 🌟')
        return redirect('food:order_history')

    return render(request, 'food/rate_order.html', {
        'order':      order,
        'cart_count': 0,
    })


def _save_ratings(request, order):
    try:
        from food.models import FoodReview, FoodOrderItem
        for item in order.items.select_related('food').all():
            rating_key = f'rating_{item.pk}'
            comment_key = f'comment_{item.pk}'
            rating = int(request.POST.get(rating_key, 0))
            if 1 <= rating <= 5:
                FoodReview.objects.update_or_create(
                    food_order=order,
                    food_item=item.food,
                    customer=request.user,
                    defaults={
                        'rating':  rating,
                        'comment': request.POST.get(comment_key, '').strip(),
                    },
                )
    except Exception:
        pass