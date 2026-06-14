# chat/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q

from .models import ChatRoom, Message
from vendors.models import Vendor


@login_required
def inbox(request):
    """Show all chat rooms for the current user."""
    user = request.user

    if hasattr(user, 'vendor'):
        # Vendor sees rooms where they are the vendor
        rooms = ChatRoom.objects.filter(
            vendor=user.vendor
        ).select_related('buyer', 'vendor').prefetch_related('messages')
    else:
        # Customer sees their own rooms
        rooms = ChatRoom.objects.filter(
            buyer=user
        ).select_related('buyer', 'vendor').prefetch_related('messages')

    # Annotate with last message + unread count
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
    """Open a specific chat room."""
    user     = request.user
    chat_room = get_object_or_404(ChatRoom, id=room_id)

    # Permission check
    is_buyer  = chat_room.buyer_id == user.pk
    is_vendor = hasattr(user, 'vendor') and chat_room.vendor.owner_id == user.pk

    if not (is_buyer or is_vendor):
        return redirect('chat:inbox')

    # Mark messages as read
    Message.objects.filter(room=chat_room, is_read=False).exclude(
        sender=user
    ).update(is_read=True)

    messages = chat_room.messages.select_related('sender').all()

    return render(request, 'chat/room.html', {
        'chat_room':  chat_room,
        'messages':   messages,
        'is_vendor':  is_vendor,
        'cart_count': 0,
    })


@login_required
def start_chat(request, vendor_slug):
    """Start or resume a chat with a vendor (buyer initiates)."""
    vendor = get_object_or_404(Vendor, slug=vendor_slug)

    if request.user == vendor.owner:
        # Vendor can't chat with themselves
        return redirect('vendors:shop', slug=vendor_slug)

    room, created = ChatRoom.objects.get_or_create(
        buyer=request.user,
        vendor=vendor,
    )
    return redirect('chat:room', room_id=room.id)


@login_required
def unread_count(request):
    """API endpoint — returns total unread message count for the navbar badge."""
    user = request.user

    if hasattr(user, 'vendor'):
        rooms = ChatRoom.objects.filter(vendor=user.vendor)
    else:
        rooms = ChatRoom.objects.filter(buyer=user)

    total = sum(r.unread_count_for(user) for r in rooms)
    return JsonResponse({'unread': total})