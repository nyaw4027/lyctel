from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
import json

from .models import LiveStream, StreamProduct, StreamGift, StreamViewer


# ── GUARD ─────────────────────────────────────────────────

def vendor_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            vendor = request.user.vendor
            if vendor.status != 'active':
                messages.warning(request, 'Your vendor account is not active.')
                return redirect('vendors:pending')
            request.vendor = vendor
        except Exception:
            messages.info(request, 'You need a vendor account to go live.')
            return redirect('vendors:apply')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── STREAM LIST (homepage "Live Now") ─────────────────────

def stream_list(request):
    """Public list of all currently live streams."""
    live_streams = LiveStream.objects.filter(
        status=LiveStream.Status.LIVE
    ).select_related('vendor').order_by('-current_viewers', '-started_at')

    recent_streams = LiveStream.objects.filter(
        status=LiveStream.Status.ENDED
    ).select_related('vendor').order_by('-ended_at')[:12]

    return render(request, 'livestream/stream_list.html', {
        'live_streams':   live_streams,
        'recent_streams': recent_streams,
        'cart_count':     _cart_count(request),
    })


# ── GO LIVE (vendor) ──────────────────────────────────────

@vendor_required
def go_live(request):
    """Vendor creates a stream and gets the broadcast page."""
    vendor = request.vendor

    # Check if vendor already has an active stream
    active = LiveStream.objects.filter(
        vendor=vendor, status=LiveStream.Status.LIVE
    ).first()
    if active:
        return redirect('livestream:broadcast', stream_id=active.id)

    if request.method == 'POST':
        title       = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        thumbnail   = request.FILES.get('thumbnail')

        if not title:
            messages.error(request, 'Give your stream a title.')
            return render(request, 'livestream/go_live.html', {
                'vendor':     vendor,
                'products':   vendor.products.filter(status='active'),
                'cart_count': 0,
            })

        stream = LiveStream.objects.create(
            vendor      = vendor,
            title       = title,
            description = description,
            thumbnail   = thumbnail,
            status      = LiveStream.Status.LIVE,
            started_at  = timezone.now(),
        )

        return redirect('livestream:broadcast', stream_id=stream.id)

    return render(request, 'livestream/go_live.html', {
        'vendor':     vendor,
        'products':   vendor.products.filter(status='active').prefetch_related('images'),
        'cart_count': 0,
    })


# ── BROADCAST PAGE (vendor camera + controls) ─────────────

@vendor_required
def broadcast(request, stream_id):
    """The page vendors use to stream from their camera."""
    vendor = request.vendor
    stream = get_object_or_404(
        LiveStream, id=stream_id, vendor=vendor
    )

    if stream.status == LiveStream.Status.ENDED:
        messages.info(request, 'This stream has ended.')
        return redirect('livestream:go_live')

    pinned = stream.pinned_products.select_related(
        'product'
    ).prefetch_related('product__images')

    # NEW: lets the template restore which product is currently highlighted
    # on page load/refresh, instead of always starting from an empty
    # client-side pin set (which made a refresh silently lose pin state).
    pinned_ids = list(
        stream.pinned_products.filter(is_highlighted=True).values_list('product_id', flat=True)
    )

    return render(request, 'livestream/broadcast.html', {
        'stream':       stream,
        'vendor':       vendor,
        'products':     vendor.products.filter(status='active').prefetch_related('images'),
        'pinned':       pinned,
        'pinned_ids':   pinned_ids,
        'cart_count':   0,
    })


# ── WATCH (viewer) ────────────────────────────────────────

def watch(request, stream_id):
    """Viewer page."""
    stream = get_object_or_404(LiveStream, id=stream_id)

    if stream.status == LiveStream.Status.ENDED:
        return render(request, 'livestream/ended.html', {
            'stream':     stream,
            'cart_count': _cart_count(request),
        })

    pinned = stream.pinned_products.filter(
        product__status='active'
    ).select_related('product').prefetch_related('product__images')

    from .models import StreamGift
    gifts_data = [
        {
            'type':  gift_type,
            'emoji': StreamGift.GIFT_EMOJIS[gift_type],
            'value': str(StreamGift.GIFT_VALUES[gift_type]),
            'label': gift_type.capitalize(),
        }
        for gift_type in StreamGift.GIFT_VALUES
    ]

    return render(request, 'livestream/watch.html', {
        'stream':     stream,
        'pinned':     pinned,
        'gifts':      gifts_data,
        'cart_count': _cart_count(request),
    })


# ── API: END STREAM ───────────────────────────────────────

@login_required
@require_POST
def end_stream(request, stream_id):
    try:
        vendor = request.user.vendor
    except Exception:
        return JsonResponse({'error': 'Not a vendor.'}, status=403)

    stream = get_object_or_404(LiveStream, id=stream_id, vendor=vendor)
    stream.status   = LiveStream.Status.ENDED
    stream.ended_at = timezone.now()
    stream.save(update_fields=['status', 'ended_at'])

    return JsonResponse({
        'success':        True,
        'total_viewers':  stream.total_viewers,
        'gifts_value':    str(stream.total_gifts_value),
        'sales_value':    str(stream.total_sales_value),
        'duration':       stream.duration_minutes,
    })


# ── API: PIN PRODUCT ──────────────────────────────────────

@login_required
@require_POST
def pin_product(request, stream_id):
    try:
        vendor = request.user.vendor
    except Exception:
        return JsonResponse({'error': 'Not a vendor.'}, status=403)

    stream     = get_object_or_404(LiveStream, id=stream_id, vendor=vendor)
    data       = json.loads(request.body)
    product_id = data.get('product_id')
    action     = data.get('action', 'pin')

    from products.models import Product
    product = get_object_or_404(Product, pk=product_id, vendor=vendor)

    if action == 'pin':
        pin, _ = StreamProduct.objects.get_or_create(stream=stream, product=product)
        StreamProduct.objects.filter(stream=stream).exclude(pk=pin.pk).update(
            is_highlighted=False
        )
        pin.is_highlighted = True
        pin.save(update_fields=['is_highlighted'])
        return JsonResponse({'success': True, 'action': 'pinned'})
    else:
        StreamProduct.objects.filter(stream=stream, product=product).delete()
        return JsonResponse({'success': True, 'action': 'unpinned'})


# ── API: SEND GIFT (form POST fallback) ───────────────────

@login_required
@require_POST
def send_gift(request, stream_id):
    stream    = get_object_or_404(LiveStream, id=stream_id, status=LiveStream.Status.LIVE)
    gift_type = request.POST.get('gift_type', 'rose')
    quantity  = max(1, int(request.POST.get('quantity', 1)))

    valid = [c[0] for c in StreamGift.GiftType.choices]
    if gift_type not in valid:
        return JsonResponse({'error': 'Invalid gift.'}, status=400)

    gift = StreamGift.objects.create(
        stream=stream, sender=request.user,
        gift_type=gift_type, quantity=quantity,
    )

    LiveStream.objects.filter(id=stream_id).update(
        total_gifts_value=stream.total_gifts_value + gift.total_value
    )

    return JsonResponse({
        'success':       True,
        'emoji':         StreamGift.GIFT_EMOJIS[gift_type],
        'total_value':   str(gift.total_value),
        'vendor_earns':  str(gift.vendor_earnings),
        'platform_earns': str(gift.platform_cut),
    })


# ── STREAM STATS (vendor dashboard panel) ─────────────────

@vendor_required
def stream_stats(request, stream_id):
    vendor = request.vendor
    stream = get_object_or_404(LiveStream, id=stream_id, vendor=vendor)
    gifts  = stream.gifts.select_related('sender').order_by('-sent_at')[:20]

    return render(request, 'livestream/stats.html', {
        'stream':     stream,
        'gifts':      gifts,
        'cart_count': 0,
    })


# ── HELPER ────────────────────────────────────────────────

def _cart_count(request):
    if request.user.is_authenticated:
        try:
            return request.user.cart.total_items
        except Exception:
            pass
    return 0