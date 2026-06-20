# chat/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q

from .models import ChatRoom, SupportRoom, Message
from vendors.models import Vendor
from ecommerce.rbac import admin_required


# ─────────────────────────────
# VENDOR CHAT (existing — unchanged)
# ─────────────────────────────
@login_required
def inbox(request):
    """Show all chat rooms for the current user."""
    user = request.user

    if hasattr(user, 'vendor'):
        rooms = ChatRoom.objects.filter(
            vendor=user.vendor
        ).select_related('buyer', 'vendor').prefetch_related('messages')
    else:
        rooms = ChatRoom.objects.filter(
            buyer=user
        ).select_related('buyer', 'vendor').prefetch_related('messages')

    room_data = []
    for room in rooms:
        last  = room.last_message()
        unread = room.unread_count_for(user)
        room_data.append({'room': room, 'last': last, 'unread': unread})

    return render(request, 'chat/inbox.html', {
        'room_data':  room_data,
        'cart_count': 0,
    })


@login_required
def room(request, room_id):
    """Open a specific vendor chat room."""
    user     = request.user
    chat_room = get_object_or_404(ChatRoom, id=room_id)

    is_buyer  = chat_room.buyer_id == user.pk
    is_vendor = hasattr(user, 'vendor') and chat_room.vendor.owner_id == user.pk

    if not (is_buyer or is_vendor):
        return redirect('chat:inbox')

    Message.objects.filter(room=chat_room, is_read=False).exclude(
        sender=user
    ).update(is_read=True)

    messages = chat_room.messages.select_related('sender').all()

    return render(request, 'chat/room.html', {
        'chat_room':  chat_room,
        'messages':   messages,
        'is_vendor':  is_vendor,
        'room_type':  'vendor',
        'ws_path':    f'/ws/chat/{chat_room.id}/',
        'cart_count': 0,
    })


@login_required
def start_chat(request, vendor_slug):
    """Start or resume a chat with a vendor (buyer initiates)."""
    vendor = get_object_or_404(Vendor, slug=vendor_slug)

    if request.user == vendor.owner:
        return redirect('vendors:shop', slug=vendor_slug)

    room, created = ChatRoom.objects.get_or_create(
        buyer=request.user,
        vendor=vendor,
    )
    return redirect('chat:room', room_id=room.id)


@login_required
def unread_count(request):
    """API endpoint — returns total unread count across vendor chat + support chat."""
    user = request.user

    if hasattr(user, 'vendor'):
        vendor_rooms = ChatRoom.objects.filter(vendor=user.vendor)
    else:
        vendor_rooms = ChatRoom.objects.filter(buyer=user)
    vendor_unread = sum(r.unread_count_for(user) for r in vendor_rooms)

    role = getattr(user, 'role', 'customer')
    if role in ('admin', 'staff'):
        support_rooms = SupportRoom.objects.exclude(status=SupportRoom.Status.RESOLVED)
    else:
        support_rooms = SupportRoom.objects.filter(customer=user)
    support_unread = sum(r.unread_count_for(user) for r in support_rooms)

    return JsonResponse({'unread': vendor_unread + support_unread})


# ─────────────────────────────
# SUPPORT CHAT (new — customer ↔ admin/staff)
# ─────────────────────────────
@login_required
def support_start(request):
    """
    Open (or resume) a live support conversation with Lynctel admin/staff.
    Optional context can be auto-attached via query params:
        ?category=order&order_ref=LX-12345
        ?category=vendor&vendor_slug=kofi-electronics
    """
    role = getattr(request.user, 'role', 'customer')
    if role in ('admin', 'staff'):
        # Staff/admin shouldn't "report" to themselves — send to the inbox instead
        return redirect('chat:support_admin_inbox')

    category   = request.GET.get('category', SupportRoom.Category.OTHER)
    order_ref  = request.GET.get('order_ref', '')
    vendor_slug = request.GET.get('vendor_slug', '')

    valid_categories = [c[0] for c in SupportRoom.Category.choices]
    if category not in valid_categories:
        category = SupportRoom.Category.OTHER

    # Reuse the most recent open/answered room rather than spawning duplicates
    existing = SupportRoom.objects.filter(
        customer=request.user
    ).exclude(status=SupportRoom.Status.RESOLVED).order_by('-updated_at').first()

    if existing:
        return redirect('chat:support_room', room_id=existing.id)

    vendor_obj = None
    if vendor_slug:
        vendor_obj = Vendor.objects.filter(slug=vendor_slug).first()

    support_room = SupportRoom.objects.create(
        customer=request.user,
        category=category,
        related_order_ref=order_ref,
        related_vendor=vendor_obj,
    )
    return redirect('chat:support_room', room_id=support_room.id)


@login_required
def support_room(request, room_id):
    """Open a specific support chat room (customer or staff/admin side)."""
    user = request.user
    s_room = get_object_or_404(SupportRoom, id=room_id)

    role = getattr(user, 'role', 'customer')
    is_owner = s_room.customer_id == user.pk
    is_staff = role in ('admin', 'staff')

    if not (is_owner or is_staff):
        return redirect('frontend:home')

    Message.objects.filter(support_room=s_room, is_read=False).exclude(
        sender=user
    ).update(is_read=True)

    # Staff claims the room on first open if unassigned
    if is_staff and not s_room.assigned_to:
        s_room.assigned_to = user
        if s_room.status == SupportRoom.Status.OPEN:
            s_room.status = SupportRoom.Status.ANSWERED
        s_room.save(update_fields=['assigned_to', 'status'])

    messages = s_room.messages.select_related('sender').all()

    return render(request, 'chat/room.html', {
        'support_room': s_room,
        'messages':     messages,
        'is_staff':     is_staff,
        'room_type':    'support',
        'ws_path':      f'/ws/support/{s_room.id}/',
        'cart_count':   0,
    })


@login_required
@require_POST
def support_resolve(request, room_id):
    """Staff/admin marks a support conversation as resolved."""
    role = getattr(request.user, 'role', 'customer')
    if role not in ('admin', 'staff'):
        return JsonResponse({'success': False}, status=403)

    from django.utils import timezone
    s_room = get_object_or_404(SupportRoom, id=room_id)
    s_room.status = SupportRoom.Status.RESOLVED
    s_room.resolved_at = timezone.now()
    s_room.save(update_fields=['status', 'resolved_at'])
    return JsonResponse({'success': True})


@login_required
def support_my_inbox(request):
    """Customer's own support conversation history."""
    rooms = SupportRoom.objects.filter(
        customer=request.user
    ).select_related('related_vendor').prefetch_related('messages')

    room_data = [
        {'room': r, 'last': r.last_message(), 'unread': r.unread_count_for(request.user)}
        for r in rooms
    ]
    return render(request, 'chat/support_my_inbox.html', {
        'room_data':  room_data,
        'cart_count': 0,
    })


@admin_required
def support_admin_inbox(request):
    """Admin/staff view of all support conversations, sorted by activity."""
    status_filter = request.GET.get('status', '')

    rooms = SupportRoom.objects.select_related(
        'customer', 'assigned_to', 'related_vendor'
    ).prefetch_related('messages')

    if status_filter:
        rooms = rooms.filter(status=status_filter)
    else:
        rooms = rooms.exclude(status=SupportRoom.Status.RESOLVED)

    room_data = [
        {'room': r, 'last': r.last_message(), 'unread': r.unread_count_for(request.user)}
        for r in rooms
    ]
    # Surface unread/unanswered conversations first
    room_data.sort(key=lambda e: (e['unread'] == 0, e['room'].updated_at), reverse=False)
    room_data.sort(key=lambda e: e['unread'] > 0, reverse=True)

    open_count     = SupportRoom.objects.filter(status=SupportRoom.Status.OPEN).count()
    answered_count = SupportRoom.objects.filter(status=SupportRoom.Status.ANSWERED).count()

    return render(request, 'chat/support_admin_inbox.html', {
        'room_data':      room_data,
        'status_filter':  status_filter,
        'status_choices': SupportRoom.Status.choices,
        'open_count':     open_count,
        'answered_count': answered_count,
    })


@login_required
@require_POST
def upload_attachment(request, room_type, room_id):
    """
    AJAX endpoint to upload an image attachment before/with sending a message.
    room_type is 'vendor' or 'support'.
    """
    if 'image' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No image provided.'}, status=400)

    image = request.FILES['image']
    if image.size > 5 * 1024 * 1024:
        return JsonResponse({'success': False, 'error': 'Image must be under 5MB.'}, status=400)

    user = request.user

    if room_type == 'vendor':
        target_room = get_object_or_404(ChatRoom, id=room_id)
        is_buyer  = target_room.buyer_id == user.pk
        is_vendor = hasattr(user, 'vendor') and target_room.vendor.owner_id == user.pk
        if not (is_buyer or is_vendor):
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        message = Message.objects.create(room=target_room, sender=user, attachment=image)
    elif room_type == 'support':
        target_room = get_object_or_404(SupportRoom, id=room_id)
        role = getattr(user, 'role', 'customer')
        is_owner = target_room.customer_id == user.pk
        is_staff = role in ('admin', 'staff')
        if not (is_owner or is_staff):
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        message = Message.objects.create(support_room=target_room, sender=user, attachment=image)
    else:
        return JsonResponse({'success': False, 'error': 'Invalid room type.'}, status=400)

    return JsonResponse({
        'success':      True,
        'message_id':   message.id,
        'attachment_url': message.attachment.url,
    })