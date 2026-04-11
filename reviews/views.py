from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Avg, Count

from products.models import Product
from order.models import Order, OrderItem
from .models import Review


def can_review(user, product):
    """
    Customer can only review a product they have actually bought
    and whose order has been delivered.
    """
    return OrderItem.objects.filter(
        order__customer=user,
        order__status='delivered',
        product=product,
    ).exists()


@login_required
def submit_review(request, product_id):
    product = get_object_or_404(Product, pk=product_id, status='active')

    if not can_review(request.user, product):
        messages.error(request, 'You can only review products you have purchased and received.')
        return redirect('products:detail', slug=product.slug)

    if Review.objects.filter(product=product, customer=request.user).exists():
        messages.warning(request, 'You have already reviewed this product.')
        return redirect('products:detail', slug=product.slug)

    if request.method == 'POST':
        rating = int(request.POST.get('rating', 0))
        title  = request.POST.get('title', '').strip()
        body   = request.POST.get('body', '').strip()

        errors = {}
        if not 1 <= rating <= 5: errors['rating'] = 'Please select a rating between 1 and 5.'
        if not body:             errors['body']   = 'Please write a review.'

        if errors:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': errors})
            messages.error(request, 'Please fix the errors below.')
            return redirect('products:detail', slug=product.slug)

        Review.objects.create(
            product  = product,
            customer = request.user,
            rating   = rating,
            title    = title,
            body     = body,
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            stats = product.reviews.filter(is_visible=True).aggregate(
                avg=Avg('rating'), count=Count('id')
            )
            return JsonResponse({
                'success':      True,
                'message':      'Thank you for your review!',
                'avg_rating':   round(stats['avg'] or 0, 1),
                'review_count': stats['count'],
            })

        messages.success(request, 'Thank you for your review!')
    return redirect('products:detail', slug=product.slug)


@login_required
def delete_review(request, review_id):
    """Customer can delete their own review."""
    review = get_object_or_404(Review, pk=review_id, customer=request.user)
    product_slug = review.product.slug
    review.delete()
    messages.info(request, 'Your review has been removed.')
    return redirect('products:detail', slug=product_slug)