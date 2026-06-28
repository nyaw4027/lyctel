from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import FraudFlag


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
    flag.resolved        = True
    flag.resolved_by     = request.user
    flag.resolved_at     = timezone.now()
    flag.resolution_note = request.POST.get('note', '').strip()
    flag.save()
    messages.success(request, f'Flag on {flag.order.order_ref} marked resolved.')
    return redirect('fraud:flagged_orders')