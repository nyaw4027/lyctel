from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import FraudFlag
from .services import release_vendor_payout


@staff_member_required
def flagged_orders(request):
    flags = (
        FraudFlag.objects.filter(resolved=False)
        .select_related('order', 'order__customer')
        .order_by('-severity', '-created_at')
    )
    return render(request, 'fraud/flagged_orders.html', {'flags': flags})


@staff_member_required
@require_POST
def resolve_flag(request, pk):
    flag = get_object_or_404(FraudFlag, pk=pk)
    # 'clear'   -> false positive, eligible for payout release
    # 'confirm' -> real fraud, payout stays held permanently
    resolution = request.POST.get('resolution', 'clear')

    flag.resolved           = True
    flag.is_confirmed_fraud = (resolution == 'confirm')
    flag.resolved_by        = request.user
    flag.resolved_at        = timezone.now()
    flag.resolution_note    = request.POST.get('note', '').strip()
    flag.save()

    order = flag.order

    if resolution == 'confirm':
        messages.warning(request, f'{order.order_ref} marked as confirmed fraud. Payout stays held.')
        return redirect('fraud:flagged_orders')

    # 'clear' path — only release if NOTHING else is blocking this order:
    #   1. no other unresolved flags on it, AND
    #   2. it never had a flag confirmed as real fraud (even an old,
    #      already-resolved one — that's a permanent block, not a one-time
    #      review outcome).
    other_unresolved = FraudFlag.objects.filter(order=order, resolved=False).exclude(pk=flag.pk).exists()
    ever_confirmed_fraud = FraudFlag.objects.filter(order=order, is_confirmed_fraud=True).exists()

    if other_unresolved:
        messages.success(request, f'Flag on {order.order_ref} cleared — other flags remain, payout still held.')
    elif ever_confirmed_fraud:
        messages.warning(request, f'{order.order_ref} has a confirmed-fraud flag on record — payout stays held.')
    else:
        release_vendor_payout(order)
        messages.success(request, f'Flag on {order.order_ref} cleared. Payout released.')

    return redirect('fraud:flagged_orders')