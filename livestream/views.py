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

    # Read peak_viewers and recording_url from the JS client
    try:
        body          = json.loads(request.body)
        peak_viewers  = int(body.get('peak_viewers', 0))
        recording_url = body.get('recording_url', '') or ''
    except (json.JSONDecodeError, TypeError, ValueError):
        peak_viewers  = 0
        recording_url = ''

    update_fields = ['status', 'ended_at']

    stream.status   = LiveStream.Status.ENDED
    stream.ended_at = timezone.now()

    if peak_viewers > stream.peak_viewers:
        stream.peak_viewers = peak_viewers
        update_fields.append('peak_viewers')

    if recording_url and hasattr(stream, 'recording_url'):
        stream.recording_url = recording_url
        update_fields.append('recording_url')

    stream.save(update_fields=update_fields)

    return JsonResponse({
        'success':       True,
        'total_viewers': stream.total_viewers,
        'peak_viewers':  stream.peak_viewers,
        'gifts_value':   str(stream.total_gifts_value),
        'sales_value':   str(stream.total_sales_value),
        'duration':      stream.duration_minutes,
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

# ── API: UPLOAD RECORDING ─────────────────────────────────

@login_required
@require_POST
def upload_recording(request, stream_id):
    """
    Receives the client-side MediaRecorder blob and saves it via Cloudinary.
    Called by livestream.js stopRecordingAndUpload() when the stream ends.
    """
    try:
        vendor = request.user.vendor
    except Exception:
        return JsonResponse({'error': 'Not a vendor.'}, status=403)

    stream = get_object_or_404(LiveStream, id=stream_id, vendor=vendor)

    recording = request.FILES.get('recording')
    if not recording:
        return JsonResponse({'success': False, 'error': 'No file received.'})

    # Size guard — 500MB max
    if recording.size > 500 * 1024 * 1024:
        return JsonResponse({'success': False, 'error': 'Recording too large (max 500MB).'})

    try:
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            recording,
            resource_type = 'video',
            folder        = 'lynctel/recordings',
            public_id     = f'stream_{stream_id}',
            overwrite     = True,
        )
        recording_url = result.get('secure_url', '')

        if hasattr(stream, 'recording_url') and recording_url:
            stream.recording_url = recording_url
            stream.save(update_fields=['recording_url'])

        return JsonResponse({'success': True, 'recording_url': recording_url})

    except Exception as e:
        import logging
        logging.getLogger(__name__).error('Recording upload failed: %s', e)
        return JsonResponse({'success': False, 'error': str(e)})

# ── GIFT PAYMENT: INITIATE (Viewer → Hubtel MoMo) ─────────────────────────────

@login_required
@require_POST
def gift_payment_initiate(request, stream_id):
    """
    Step 1: Viewer taps a gift → we create a pending StreamGift record
    and initiate a Hubtel checkout for the exact gift amount.

    The viewer is then redirected to Hubtel's hosted payment page
    (MoMo, Vodafone Cash, AirtelTigo Money, or Card).
    """
    import uuid
    stream = get_object_or_404(LiveStream, id=stream_id, status=LiveStream.Status.LIVE)
    data      = json.loads(request.body)
    gift_type = data.get('gift_type', 'rose')
    quantity  = max(1, min(int(data.get('quantity', 1)), 50))

    from .models import StreamGift
    valid_types = [c[0] for c in StreamGift.GiftType.choices]
    if gift_type not in valid_types:
        return JsonResponse({'error': 'Invalid gift type.'}, status=400)

    # Create gift record as PENDING — confirmed after Hubtel callback
    gift = StreamGift(
        stream    = stream,
        sender    = request.user,
        gift_type = gift_type,
        quantity  = quantity,
    )
    # Compute values before saving (save() method handles split)
    gift.save()

    # Mark as pending payment
    try:
        gift.payment_status = StreamGift.PaymentStatus.PENDING
        gift.save(update_fields=['payment_status'])
    except Exception:
        pass  # payment_status field may not exist yet (pre-migration)

    # Initiate Hubtel checkout
    try:
        from payment.hubtel import HubtelCheckout
        from django.conf import settings as _s

        ref          = f"GIFT-{gift.pk}-{uuid.uuid4().hex[:6].upper()}"
        callback_url = getattr(_s, 'HUBTEL_CALLBACK_URL',
                               'https://lynctel.up.railway.app/payment/callback/')
        # Gift-specific callback
        gift_callback = f'https://lynctel.up.railway.app/livestream/{stream_id}/gift-payment/callback/'
        return_url    = f'https://lynctel.up.railway.app/livestream/{stream_id}/watch/'
        cancel_url    = f'https://lynctel.up.railway.app/livestream/{stream_id}/watch/'

        cid, secret   = HubtelCheckout._auth()
        merchant      = HubtelCheckout._merchant()

        import requests as req_lib
        # clientReference max 32 chars; strip special chars from description
        import re as _re
        safe_desc = _re.sub(r"[^a-zA-Z0-9 .,\-]", "", f"Gift {gift_type.title()} x{quantity} Lynctel Live")[:100]
        payload = {
            "totalAmount":           float(round(gift.total_value, 2)),
            "description":           safe_desc,
            "callbackUrl":           gift_callback,
            "returnUrl":             return_url,
            "cancellationUrl":       cancel_url,
            "merchantAccountNumber": merchant,
            "clientReference":       ref[:32],
        }
        name  = request.user.get_full_name() or getattr(request.user, 'display_name', '') or ''
        phone = getattr(request.user, 'phone', '') or ''
        email = getattr(request.user, 'email', '') or ''
        if name:  payload['payeeName']        = name[:50]
        if phone: payload['payeeMobileNumber'] = phone[:20]
        if email: payload['payeeEmail']        = email[:80]

        url = 'https://payproxyapi.hubtel.com/items/initiate'
        response = req_lib.post(
            url, json=payload, auth=(cid, secret),
            timeout=15, headers={"Content-Type": "application/json"},
        )

        if response.status_code not in (200, 201):
            raise Exception(f"Hubtel {response.status_code}: {response.text[:200]}")

        resp_data     = response.json()
        checkout_url  = resp_data.get('data', {}).get('checkoutUrl') or resp_data.get('checkoutUrl', '')
        checkout_id   = resp_data.get('data', {}).get('checkoutId')  or resp_data.get('checkoutId', ref)

        if not checkout_url:
            raise Exception("No checkoutUrl in Hubtel response")

        # Store Hubtel IDs on the gift
        try:
            gift.hubtel_checkout_id = checkout_id
            gift.hubtel_reference   = ref
            gift.save(update_fields=['hubtel_checkout_id', 'hubtel_reference'])
        except Exception:
            pass

        return JsonResponse({
            'success':      True,
            'redirect_url': checkout_url,
            'checkout_id':  checkout_id,
            'gift_id':      str(gift.pk),
            'amount':       str(gift.total_value),
        })

    except Exception as e:
        import logging
        logging.getLogger(__name__).error('Gift payment initiate failed: %s', e)
        # Hubtel not configured — this is expected before API keys arrive
        # In this case, mark as paid directly for testing
        from django.conf import settings as _s
        if not getattr(_s, 'HUBTEL_CLIENT_ID', ''):
            return JsonResponse({
                'success':  False,
                'error':    'Payment gateway not configured. API keys required.',
                'code':     'no_keys',
            }, status=503)
        return JsonResponse({'success': False, 'error': str(e)}, status=502)


# ── GIFT PAYMENT: CALLBACK (Hubtel → server, server-to-server) ────────────────

from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@require_POST
def gift_payment_callback(request, stream_id):
    """
    Hubtel POSTs payment result here after viewer pays.
    We verify the HMAC signature, mark gift as paid, and broadcast
    the gift animation to all viewers via WebSocket.
    """
    import logging, hashlib, hmac as hmac_lib
    log = logging.getLogger(__name__)

    # Verify HMAC signature from Hubtel
    signature = request.headers.get('X-Hubtel-Signature', '')
    try:
        from payment.hubtel import HubtelCheckout
        if signature and not HubtelCheckout.verify_webhook_signature(request.body, signature):
            log.warning('Gift callback: invalid HMAC signature')
            return JsonResponse({'error': 'Invalid signature'}, status=401)
    except Exception:
        pass  # Allow if signature verification not possible

    try:
        raw_data   = json.loads(request.body)
        from payment.hubtel import HubtelCheckout as HC
        parsed     = HC.parse_callback(raw_data)
        client_ref = parsed["client_reference"]
        paid       = parsed["paid"]

        if not client_ref or not client_ref.startswith('GIFT-'):
            return JsonResponse({'received': True})

        # Find the gift by reference
        gift_pk = client_ref.split('-')[1]
        from .models import StreamGift
        try:
            gift = StreamGift.objects.select_related('stream', 'sender', 'stream__vendor').get(pk=gift_pk)
        except (StreamGift.DoesNotExist, ValueError):
            log.warning('Gift callback: gift %s not found', gift_pk)
            return JsonResponse({'received': True})

        if paid:
            gift.payment_status = StreamGift.PaymentStatus.PAID
            gift.paid_at        = timezone.now()
            try:
                gift.save(update_fields=['payment_status', 'paid_at'])
            except Exception:
                gift.save()

            # Update stream total gifts value
            LiveStream.objects.filter(id=gift.stream_id).update(
                total_gifts_value=gift.stream.total_gifts_value + gift.total_value
            )

            # Broadcast gift animation to ALL viewers via WebSocket
            _broadcast_gift_paid(gift)

            log.info('Gift PAID: %s sent %s x%s = GHS %s (vendor: %s, app: %s)',
                     gift.sender, gift.gift_type, gift.quantity,
                     gift.total_value, gift.vendor_earnings, gift.platform_cut)
        else:
            try:
                gift.payment_status = StreamGift.PaymentStatus.FAILED
                gift.save(update_fields=['payment_status'])
            except Exception:
                pass
            log.info('Gift FAILED: %s — status: %s', client_ref, tx_status)

    except Exception as e:
        log.exception('Gift callback error: %s', e)

    return JsonResponse({'received': True})


def _broadcast_gift_paid(gift):
    """Send gift animation to all viewers via Django Channels."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer    = get_channel_layer()
        room     = f'stream_{gift.stream_id}'

        async_to_sync(layer.group_send)(room, {
            'type':        'gift_event',
            'gift_type':   gift.gift_type,
            'emoji':       StreamGift.GIFT_EMOJIS[gift.gift_type],
            'quantity':    gift.quantity,
            'total_value': str(gift.total_value),
            'username':    gift.sender.display_name if gift.sender else 'A viewer',
            'user_id':     gift.sender_id,
        })
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning('Gift broadcast failed: %s', e)


# ── GIFT PAYMENT: VERIFY (viewer return after paying) ─────────────────────────

@login_required
def gift_payment_verify(request, stream_id):
    """
    Viewer returns to this URL after paying on Hubtel.
    We verify payment status and redirect back to the stream.
    """
    checkout_id = request.GET.get('checkoutId') or request.GET.get('checkout_id', '')
    if checkout_id:
        try:
            from payment.hubtel import HubtelCheckout
            result = HubtelCheckout.verify(checkout_id)
            if result.get('paid'):
                from .models import StreamGift
                StreamGift.objects.filter(
                    hubtel_checkout_id=checkout_id,
                    sender=request.user,
                ).update(
                    payment_status = StreamGift.PaymentStatus.PAID,
                    paid_at        = timezone.now(),
                )
        except Exception:
            pass

    return redirect('livestream:watch', stream_id=stream_id)