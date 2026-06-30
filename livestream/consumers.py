import json
import asyncio
from decimal import Decimal
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


class StreamConsumer(AsyncWebsocketConsumer):
    """
    Single WebSocket consumer that handles everything for one live stream.

    WebRTC signaling model:
      - The VENDOR (broadcaster) is the only one who sends 'offer' on
        startCamera(). That offer is broadcast to the whole room; each
        VIEWER answers it individually with their own channel_name as
        peer_id so the vendor can create one RTCPeerConnection per viewer.
      - VIEWERS also send their own 'offer' on page load (startViewing())
        to request the stream. This offer must include the viewer's
        channel_name as `sender` when relayed to the vendor, so the
        vendor's handleViewerOffer() can key its peerConnections map
        correctly and route the matching 'answer' back to THAT viewer only.

    CLIENT → SERVER message types:
      offer        — WebRTC SDP offer  (viewer requests stream OR vendor pushes one)
      answer       — WebRTC SDP answer (in reply to an offer)
      ice          — ICE candidate relay
      chat         — Chat message
      gift         — Viewer sends a gift
      pin_product  — Vendor pins/unpins a product
      end_stream   — Vendor ends the stream
      ping         — Keepalive

    SERVER → CLIENT message types:
      offer / answer / ice  — WebRTC signaling passthrough (always includes `sender`)
      chat                  — New chat message
      gift                  — Gift animation broadcast
      viewer_count          — Current viewer count update
      pinned_products       — Initial pinned products list (sent on connect)
      product_pinned        — New product pinned
      product_unpinned      — Product removed
      stream_ended          — Stream has ended
      error                 — Something went wrong
    """

    async def connect(self):
        self.stream_id   = self.scope['url_route']['kwargs']['stream_id']
        self.room_group  = f'stream_{self.stream_id}'
        self.user        = self.scope['user']
        self.is_vendor   = False

        stream = await self._get_stream()
        if not stream:
            await self.close()
            return

        self.is_vendor = await self._is_stream_vendor(stream)

        try:
            await asyncio.wait_for(
                self.channel_layer.group_add(self.room_group, self.channel_name),
                timeout=8,
            )
        except (asyncio.TimeoutError, Exception):
            # Redis hiccup on first connect — accept the socket anyway so
            # the client doesn't see a hard failure; group features (chat,
            # gifts, pin updates) may be briefly unavailable until the next
            # successful operation, but the WebRTC video/audio path itself
            # does not depend on the channel layer at all.
            pass

        await self.accept()

        await self._add_viewer(stream)

        try:
            count = await asyncio.wait_for(self._get_viewer_count(), timeout=5)
            await asyncio.wait_for(
                self.channel_layer.group_send(self.room_group, {
                    'type':  'viewer_count_update',
                    'count': count,
                }),
                timeout=5,
            )
        except (asyncio.TimeoutError, Exception):
            pass

        products = await self._get_pinned_products()
        await self.send(text_data=json.dumps({
            'type':     'pinned_products',
            'products': products,
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group, self.channel_name)
        await self._remove_viewer()

        count = await self._get_viewer_count()
        await self.channel_layer.group_send(self.room_group, {
            'type':  'viewer_count_update',
            'count': count,
        })

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type', '')

        # ── WebRTC signaling ──────────────────────────────
        if msg_type == 'offer':
            # Relay to the room, always tagging who sent it so the
            # receiving side (vendor or viewer) can route correctly.
            await self.channel_layer.group_send(self.room_group, {
                'type':   'webrtc_offer',
                'sdp':    data.get('sdp'),
                'sender': self.channel_name,
            })

        elif msg_type == 'answer':
            # peer_id tells the server WHO should receive this answer.
            # The viewer answering a vendor offer sets peer_id to the
            # vendor's channel_name (from data.sender on the offer they
            # received). The vendor answering a viewer's offer sets
            # peer_id to that viewer's channel_name.
            await self.channel_layer.group_send(self.room_group, {
                'type':    'webrtc_answer',
                'sdp':     data.get('sdp'),
                'sender':  self.channel_name,
                'peer_id': data.get('peer_id'),
            })

        elif msg_type == 'ice':
            await self.channel_layer.group_send(self.room_group, {
                'type':      'webrtc_ice',
                'candidate': data.get('candidate'),
                'sender':    self.channel_name,
                'peer_id':   data.get('peer_id'),
            })

        # ── Chat ──────────────────────────────────────────
        elif msg_type == 'chat':
            if not self.user.is_authenticated:
                return
            message = str(data.get('message', '')).strip()[:300]
            if not message:
                return

            comment = await self._save_comment(message)
            await self.channel_layer.group_send(self.room_group, {
                'type':       'chat_message',
                'message':    message,
                'username':   self.user.display_name,
                'initials':   self.user.initials,
                'user_id':    self.user.id,
                'comment_id': comment.id,
                'is_vendor':  self.is_vendor,
                'sent_at':    comment.sent_at.strftime('%H:%M'),
            })

        # ── Gift ──────────────────────────────────────────
        elif msg_type == 'gift':
            if not self.user.is_authenticated:
                await self.send(text_data=json.dumps({
                    'type':    'error',
                    'message': 'You must be logged in to send gifts.',
                }))
                return

            gift_type = data.get('gift_type', 'rose')
            quantity  = max(1, min(int(data.get('quantity', 1)), 100))

            gift = await self._save_gift(gift_type, quantity)
            if not gift:
                await self.send(text_data=json.dumps({
                    'type':    'error',
                    'message': 'Invalid gift type.',
                }))
                return

            await self.channel_layer.group_send(self.room_group, {
                'type':        'gift_event',
                'gift_type':   gift_type,
                'emoji':       gift['emoji'],
                'quantity':    quantity,
                'total_value': str(gift['total_value']),
                'username':    self.user.display_name,
                'user_id':     self.user.id,
            })

        # ── Pin product (vendor only) ──────────────────────
        elif msg_type == 'pin_product':
            if not self.is_vendor:
                return
            product_id = data.get('product_id')
            action     = data.get('action', 'pin')

            if action == 'pin':
                product_data = await self._pin_product(product_id)
                if product_data:
                    await self.channel_layer.group_send(self.room_group, {
                        'type':    'product_pinned',
                        'product': product_data,
                    })
            else:
                await self._unpin_product(product_id)
                await self.channel_layer.group_send(self.room_group, {
                    'type':       'product_unpinned',
                    'product_id': str(product_id),
                })

        # ── End stream (vendor only) ──────────────────────
        elif msg_type == 'end_stream':
            if not self.is_vendor:
                return
            await self._end_stream()
            await self.channel_layer.group_send(self.room_group, {
                'type': 'stream_ended_event',
            })

        # ── Ping ─────────────────────────────────────────
        elif msg_type == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))

    # ── Group message handlers (server → this client) ─────

    async def webrtc_offer(self, event):
        # Don't echo back to whoever sent it.
        if event['sender'] != self.channel_name:
            await self.send(text_data=json.dumps({
                'type':   'offer',
                'sdp':    event['sdp'],
                'sender': event['sender'],
            }))

    async def webrtc_answer(self, event):
        target = event.get('peer_id')
        if target and target == self.channel_name:
            await self.send(text_data=json.dumps({
                'type':   'answer',
                'sdp':    event['sdp'],
                'sender': event['sender'],
            }))
        elif not target and event['sender'] != self.channel_name:
            # Fallback for any legacy client not yet sending peer_id
            await self.send(text_data=json.dumps({
                'type':   'answer',
                'sdp':    event['sdp'],
                'sender': event['sender'],
            }))

    async def webrtc_ice(self, event):
        target = event.get('peer_id')
        if target and target == self.channel_name:
            await self.send(text_data=json.dumps({
                'type':      'ice',
                'candidate': event['candidate'],
                'sender':    event['sender'],
            }))
        elif not target and event['sender'] != self.channel_name:
            await self.send(text_data=json.dumps({
                'type':      'ice',
                'candidate': event['candidate'],
                'sender':    event['sender'],
            }))

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type':       'chat',
            'message':    event['message'],
            'username':   event['username'],
            'initials':   event['initials'],
            'user_id':    event['user_id'],
            'comment_id': event['comment_id'],
            'is_vendor':  event['is_vendor'],
            'sent_at':    event['sent_at'],
        }))

    async def gift_event(self, event):
        await self.send(text_data=json.dumps({
            'type':        'gift',
            'gift_type':   event['gift_type'],
            'emoji':       event['emoji'],
            'quantity':    event['quantity'],
            'total_value': event['total_value'],
            'username':    event['username'],
            'user_id':     event['user_id'],
        }))

    async def viewer_count_update(self, event):
        await self.send(text_data=json.dumps({
            'type':  'viewer_count',
            'count': event['count'],
        }))

    async def product_pinned(self, event):
        await self.send(text_data=json.dumps({
            'type':    'product_pinned',
            'product': event['product'],
        }))

    async def product_unpinned(self, event):
        await self.send(text_data=json.dumps({
            'type':       'product_unpinned',
            'product_id': event['product_id'],
        }))

    async def stream_ended_event(self, event):
        await self.send(text_data=json.dumps({'type': 'stream_ended'}))

    # ── DB helpers (sync_to_async) ────────────────────────

    @database_sync_to_async
    def _get_stream(self):
        from livestream.models import LiveStream
        try:
            return LiveStream.objects.select_related('vendor__owner').get(
                id=self.stream_id
            )
        except LiveStream.DoesNotExist:
            return None

    @database_sync_to_async
    def _is_stream_vendor(self, stream):
        if not self.user.is_authenticated:
            return False
        return stream.vendor.owner_id == self.user.id

    @database_sync_to_async
    def _add_viewer(self, stream):
        from livestream.models import StreamViewer
        if self.user.is_authenticated:
            StreamViewer.objects.get_or_create(
                stream=stream,
                user=self.user,
                defaults={'joined_at': timezone.now()},
            )
        stream.total_viewers += 1
        stream.save(update_fields=['total_viewers'])

    @database_sync_to_async
    def _remove_viewer(self):
        from livestream.models import StreamViewer
        if self.user.is_authenticated:
            StreamViewer.objects.filter(
                stream_id=self.stream_id,
                user=self.user,
                left_at__isnull=True,
            ).update(left_at=timezone.now())

    @database_sync_to_async
    def _get_viewer_count(self):
        from livestream.models import StreamViewer
        return StreamViewer.objects.filter(
            stream_id=self.stream_id,
            left_at__isnull=True,
        ).count()

    @database_sync_to_async
    def _save_comment(self, message):
        from livestream.models import StreamComment
        return StreamComment.objects.create(
            stream_id=self.stream_id,
            user=self.user,
            message=message,
        )

    @database_sync_to_async
    def _save_gift(self, gift_type, quantity):
        from livestream.models import StreamGift, LiveStream
        valid_types = [c[0] for c in StreamGift.GiftType.choices]
        if gift_type not in valid_types:
            return None

        gift = StreamGift.objects.create(
            stream_id=self.stream_id,
            sender=self.user,
            gift_type=gift_type,
            quantity=quantity,
        )

        LiveStream.objects.filter(id=self.stream_id).update(
            total_gifts_value=gift.total_value
        )

        return {
            'emoji':       StreamGift.GIFT_EMOJIS[gift_type],
            'total_value': gift.total_value,
        }

    @database_sync_to_async
    def _get_pinned_products(self):
        from livestream.models import StreamProduct
        pins = StreamProduct.objects.filter(
            stream_id=self.stream_id
        ).select_related('product').prefetch_related('product__images')
        result = []
        for pin in pins:
            p = pin.product
            result.append({
                'id':             p.pk,
                'name':           p.name,
                'price':          str(p.final_price),
                'slug':           p.slug,
                'image':          p.primary_image or '',
                'is_highlighted': pin.is_highlighted,
                'in_stock':       p.is_in_stock,
            })
        return result

    @database_sync_to_async
    def _pin_product(self, product_id):
        from livestream.models import StreamProduct, LiveStream
        from products.models import Product
        try:
            stream  = LiveStream.objects.get(id=self.stream_id)
            product = Product.objects.prefetch_related('images').get(
                pk=product_id, vendor=stream.vendor
            )
            pin, _ = StreamProduct.objects.get_or_create(
                stream=stream, product=product
            )
            StreamProduct.objects.filter(stream=stream).exclude(
                pk=pin.pk
            ).update(is_highlighted=False)
            pin.is_highlighted = True
            pin.save(update_fields=['is_highlighted'])

            return {
                'id':             product.pk,
                'name':           product.name,
                'price':          str(product.final_price),
                'slug':           product.slug,
                'image':          product.primary_image or '',
                'is_highlighted': True,
                'in_stock':       product.is_in_stock,
            }
        except Exception:
            return None

    @database_sync_to_async
    def _unpin_product(self, product_id):
        from livestream.models import StreamProduct
        StreamProduct.objects.filter(
            stream_id=self.stream_id, product_id=product_id
        ).delete()

    @database_sync_to_async
    def _end_stream(self):
        from livestream.models import LiveStream
        LiveStream.objects.filter(id=self.stream_id).update(
            status=LiveStream.Status.ENDED,
            ended_at=timezone.now(),
        )