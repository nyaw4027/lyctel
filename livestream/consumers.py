"""
livestream/consumers.py  (audit rewrite)

Signalling model (matches the existing watch.html / livestream.js protocol):
  * BROADCASTER (vendor) identifies itself with {type:'vendor_init'}. Only the
    stream owner can become broadcaster. The owner opening watch.html in another
    tab stays a normal viewer.
  * VIEWER sends 'offer'  -> delivered ONLY to the broadcaster (was: everyone).
  * BROADCASTER sends 'answer'/'ice' with peer_id -> delivered ONLY to that viewer.
  * VIEWER sends 'ice'/'answer' -> delivered ONLY to the broadcaster
    (or to peer_id when given).
  * Server sends {type:'vendor_ready'} to viewers when the broadcaster connects,
    so waiting viewers re-offer immediately instead of waiting for the 8s retry.
"""
import json
import asyncio
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import cache
from django.utils import timezone

log = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 64 * 1024          # SDP is ~10 KB; anything bigger is abuse
SIGNAL_LIMIT      = (150, 10.0)        # max signalling msgs / seconds (ICE bursts)
REACTION_LIMIT    = (6, 1.0)
POLL_TTL          = 60 * 60 * 6


class StreamConsumer(AsyncWebsocketConsumer):

    # ── lifecycle ─────────────────────────────────────────
    async def connect(self):
        self.stream_id      = str(self.scope['url_route']['kwargs']['stream_id'])
        self.room_group     = f'stream_{self.stream_id}'
        self.user           = self.scope['user']
        self.is_vendor      = False      # owner of the stream (chat/pin/end rights)
        self.is_broadcaster = False      # the ONE socket that sends video
        self._counted       = False
        self._in_group      = False
        self._buckets       = {}

        stream = await self._get_stream()
        if not stream:
            await self.close()
            return

        self.is_vendor = await self._is_stream_vendor(stream)

        try:
            await asyncio.wait_for(
                self.channel_layer.group_add(self.room_group, self.channel_name),
                timeout=8)
            self._in_group = True
        except Exception:
            log.warning('stream %s: group_add failed', self.stream_id)

        await self.accept()

        count = None
        if not self.is_vendor:                       # owner's tabs are not "viewers"
            try:
                count = await self._add_viewer(stream)
                self._counted = True
            except Exception:
                log.exception('stream %s: add_viewer failed', self.stream_id)
        if count is not None:
            await self._safe_group_send({'type': 'viewer_count_update', 'count': count})

        try:
            products = await self._get_pinned_products()
            await self.send(text_data=json.dumps({'type': 'pinned_products', 'products': products}))
        except Exception:
            log.exception('stream %s: pinned_products failed', self.stream_id)

        # late joiner during a poll
        poll = cache.get(self._poll_key())
        if poll:
            await self.send(text_data=json.dumps({
                'type': 'poll_start', 'question': poll['question'], 'options': poll['options']}))
            await self.send(text_data=json.dumps({'type': 'poll_update', 'tallies': poll['tallies']}))

    async def disconnect(self, close_code):
        try:
            if self._in_group:
                await self.channel_layer.group_discard(self.room_group, self.channel_name)
        except Exception:
            pass
        if self._counted:
            try:
                count = await self._remove_viewer()
                await self._safe_group_send({'type': 'viewer_count_update', 'count': count})
            except Exception:
                log.exception('stream %s: remove_viewer failed', self.stream_id)

    # ── helpers ───────────────────────────────────────────
    def _poll_key(self):
        return f'ls:poll:{self.stream_id}'

    async def _safe_group_send(self, event):
        try:
            await asyncio.wait_for(self.channel_layer.group_send(self.room_group, event), timeout=5)
        except Exception:
            log.warning('stream %s: group_send failed', self.stream_id)

    def _allow(self, bucket, limit):
        """Token-less sliding window: at most limit[0] events per limit[1] seconds."""
        now = timezone.now().timestamp()
        n, window = limit
        hits = [t for t in self._buckets.get(bucket, []) if now - t < window]
        if len(hits) >= n:
            self._buckets[bucket] = hits
            return False
        hits.append(now)
        self._buckets[bucket] = hits
        return True

    async def _relay(self, payload, audience='all'):
        await self._safe_group_send({'type': 'relay', 'payload': payload, 'audience': audience})

    # ── inbound ───────────────────────────────────────────
    async def receive(self, text_data=None, bytes_data=None):
        if not text_data or len(text_data) > MAX_MESSAGE_BYTES:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        t = data.get('type', '')

        # --- identify the broadcaster ---------------------
        if t == 'vendor_init':
            if self.is_vendor and not self.is_broadcaster:
                self.is_broadcaster = True
            if self.is_broadcaster:
                await self._touch()
                await self._relay({'type': 'vendor_ready'}, 'viewers')
            return

        # --- WebRTC signalling ----------------------------
        if t in ('offer', 'answer', 'ice'):
            if not self._allow('signal', SIGNAL_LIMIT):
                return
            await self._signal(t, data)
            return

        # --- chat -----------------------------------------
        if t == 'chat':
            if not self.user.is_authenticated:
                return
            message = str(data.get('message', '')).strip()[:300]
            if not message:
                return
            if not self._allow('chat', (1, 2.0)):
                return
            comment = await self._save_comment(message)
            await self._safe_group_send({
                'type': 'chat_message', 'message': message,
                'username': self.user.display_name, 'initials': self.user.initials,
                'user_id': self.user.id, 'comment_id': comment.id,
                'is_vendor': self.is_vendor,
                'sent_at': comment.sent_at.strftime('%H:%M'),
            })
            return

        # --- reactions / likes (throttled, relayed to everyone) --
        if t in ('like', 'reaction'):
            if not self._allow('react', REACTION_LIMIT):
                return
            await self._relay({'type': 'reaction',
                               'emoji': str(data.get('emoji', '❤️'))[:8]})
            return

        # --- polls ----------------------------------------
        if t == 'poll_start' and self.is_vendor:
            opts = data.get('options') or {}
            a, b = str(opts.get('a', ''))[:60], str(opts.get('b', ''))[:60]
            q = str(data.get('question', ''))[:140]
            if not (q and a and b):
                return
            poll = {'question': q, 'options': {'a': a, 'b': b}, 'tallies': {'a': 0, 'b': 0}}
            cache.set(self._poll_key(), poll, POLL_TTL)
            await self._relay({'type': 'poll_start', 'question': q, 'options': poll['options']}, 'viewers')
            return

        if t == 'poll_vote':
            opt = data.get('option')
            poll = cache.get(self._poll_key())
            if opt not in ('a', 'b') or not poll or not self.user.is_authenticated:
                return
            voted_key = f"{self._poll_key()}:v:{self.user.id}"
            if not cache.add(voted_key, 1, POLL_TTL):          # one vote per user
                return
            poll['tallies'][opt] = poll['tallies'].get(opt, 0) + 1
            cache.set(self._poll_key(), poll, POLL_TTL)
            await self._relay({'type': 'poll_update', 'tallies': poll['tallies']}, 'viewers')
            await self._relay({'type': 'poll_vote', 'option': opt}, 'broadcaster')
            return

        if t == 'poll_end' and self.is_vendor:
            cache.delete(self._poll_key())
            await self._relay({'type': 'poll_end'}, 'viewers')
            return

        # --- gifts must go through payment (HTTP) ---------
        if t == 'gift':
            return

        # --- pin product (vendor only) --------------------
        if t == 'pin_product':
            if not self.is_vendor:
                return
            product_id = data.get('product_id')
            if data.get('action', 'pin') == 'pin':
                product = await self._pin_product(product_id)
                if product:
                    await self._safe_group_send({'type': 'product_pinned', 'product': product})
            else:
                await self._unpin_product(product_id)
                await self._safe_group_send({'type': 'product_unpinned', 'product_id': str(product_id)})
            return

        # --- end stream (vendor only) ---------------------
        if t == 'end_stream':
            if not self.is_vendor:
                return
            await self._end_stream()
            cache.delete(self._poll_key())
            await self._safe_group_send({'type': 'stream_ended_event'})
            return

        if t == 'ping':
            if self.is_broadcaster:
                await self._touch()            # keeps the stream from being auto-closed as abandoned
            await self.send(text_data=json.dumps({'type': 'pong'}))

    async def _signal(self, t, data):
        """Route signalling point-to-point instead of spraying the whole room."""
        base = {'sender': self.channel_name, 'peer_id': data.get('peer_id')}
        if t == 'offer':
            # viewer -> broadcaster ; broadcaster -> viewers (legacy push offer)
            await self._safe_group_send({
                'type': 'webrtc_offer', 'sdp': data.get('sdp'),
                'to_broadcaster': not self.is_broadcaster, **base})
        elif t == 'answer':
            await self._route(t, 'sdp', data.get('sdp'), base)
        else:
            await self._route(t, 'candidate', data.get('candidate'), base)

    async def _route(self, t, field, value, base):
        target = base['peer_id']
        msg = {'type': t, field: value, 'sender': self.channel_name}
        if target and self.is_broadcaster:            # only the broadcaster may address a peer
            try:
                await self.channel_layer.send(str(target), {'type': 'direct', 'payload': msg})
            except Exception:
                pass
        elif not self.is_broadcaster:                 # viewers always talk to the broadcaster only
            await self._safe_group_send({'type': 'to_broadcaster', 'payload': msg})
        # broadcaster without peer_id is dropped on purpose (was: leaked to everyone)

    # ── outbound (group handlers) ─────────────────────────
    async def webrtc_offer(self, event):
        if event['sender'] == self.channel_name:
            return
        if event['to_broadcaster'] != self.is_broadcaster:
            return
        await self.send(text_data=json.dumps(
            {'type': 'offer', 'sdp': event['sdp'], 'sender': event['sender']}))

    async def direct(self, event):
        await self.send(text_data=json.dumps(event['payload']))

    async def to_broadcaster(self, event):
        if self.is_broadcaster:
            await self.send(text_data=json.dumps(event['payload']))

    async def relay(self, event):
        aud = event.get('audience', 'all')
        if aud == 'broadcaster' and not self.is_broadcaster:
            return
        if aud == 'viewers' and self.is_broadcaster:
            return
        await self.send(text_data=json.dumps(event['payload']))

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'chat', 'message': event['message'], 'username': event['username'],
            'initials': event['initials'], 'user_id': event['user_id'],
            'comment_id': event['comment_id'], 'is_vendor': event['is_vendor'],
            'sent_at': event['sent_at']}))

    async def gift_event(self, event):
        await self.send(text_data=json.dumps({
            'type': 'gift', 'gift_type': event['gift_type'], 'emoji': event['emoji'],
            'quantity': event['quantity'], 'total_value': event['total_value'],
            'username': event['username'], 'user_id': event['user_id']}))

    async def viewer_count_update(self, event):
        await self.send(text_data=json.dumps({'type': 'viewer_count', 'count': event['count']}))

    async def product_pinned(self, event):
        await self.send(text_data=json.dumps({'type': 'product_pinned', 'product': event['product']}))

    async def product_unpinned(self, event):
        await self.send(text_data=json.dumps({'type': 'product_unpinned', 'product_id': event['product_id']}))

    async def stream_ended_event(self, event):
        await self.send(text_data=json.dumps({'type': 'stream_ended'}))

    # ── DB helpers ────────────────────────────────────────
    @database_sync_to_async
    def _get_stream(self):
        from livestream.models import LiveStream
        try:
            return LiveStream.objects.select_related('vendor__owner').get(id=self.stream_id)
        except (LiveStream.DoesNotExist, ValueError):
            return None

    @database_sync_to_async
    def _is_stream_vendor(self, stream):
        return self.user.is_authenticated and stream.vendor.owner_id == self.user.id

    @database_sync_to_async
    def _add_viewer(self, stream):
        """current_viewers = live sockets (guests included). total_viewers = unique joins."""
        from django.db.models import F
        from livestream.models import StreamViewer, LiveStream
        is_new = True
        if self.user.is_authenticated:
            sv, created = StreamViewer.objects.get_or_create(
                stream=stream, user=self.user, defaults={'joined_at': timezone.now()})
            if not created:
                is_new = False
                StreamViewer.objects.filter(pk=sv.pk).update(left_at=None)   # re-join
        qs = LiveStream.objects.filter(pk=stream.pk)
        qs.update(current_viewers=F('current_viewers') + 1,
                  **({'total_viewers': F('total_viewers') + 1} if is_new else {}))
        cur = qs.values_list('current_viewers', flat=True).first() or 0
        LiveStream.objects.filter(pk=stream.pk, peak_viewers__lt=cur).update(peak_viewers=cur)
        return cur

    @database_sync_to_async
    def _remove_viewer(self):
        from django.db.models import F, Greatest
        from livestream.models import StreamViewer, LiveStream
        if self.user.is_authenticated:
            StreamViewer.objects.filter(
                stream_id=self.stream_id, user=self.user, left_at__isnull=True
            ).update(left_at=timezone.now())
        qs = LiveStream.objects.filter(pk=self.stream_id)
        qs.update(current_viewers=Greatest(F('current_viewers') - 1, 0))
        return qs.values_list('current_viewers', flat=True).first() or 0

    @database_sync_to_async
    def _save_comment(self, message):
        from livestream.models import StreamComment
        return StreamComment.objects.create(stream_id=self.stream_id, user=self.user, message=message)

    @database_sync_to_async
    def _get_pinned_products(self):
        from livestream.models import StreamProduct
        pins = StreamProduct.objects.filter(stream_id=self.stream_id) \
            .select_related('product').prefetch_related('product__images')
        return [self._product_dict(p.product, p.is_highlighted) for p in pins]

    @staticmethod
    def _product_dict(p, highlighted):
        return {'id': p.pk, 'name': p.name, 'price': str(p.final_price), 'slug': p.slug,
                'image': p.primary_image or '', 'is_highlighted': highlighted,
                'in_stock': p.is_in_stock}

    @database_sync_to_async
    def _pin_product(self, product_id):
        from livestream.models import StreamProduct, LiveStream
        from products.models import Product
        try:
            stream  = LiveStream.objects.get(id=self.stream_id)
            product = Product.objects.prefetch_related('images').get(pk=product_id, vendor=stream.vendor)
            pin, _  = StreamProduct.objects.get_or_create(stream=stream, product=product)
            StreamProduct.objects.filter(stream=stream).exclude(pk=pin.pk).update(is_highlighted=False)
            pin.is_highlighted = True
            pin.save(update_fields=['is_highlighted'])
            return self._product_dict(product, True)
        except Exception:
            return None

    @database_sync_to_async
    def _unpin_product(self, product_id):
        from livestream.models import StreamProduct
        StreamProduct.objects.filter(stream_id=self.stream_id, product_id=product_id).delete()

    @database_sync_to_async
    def _touch(self):
        from livestream.models import LiveStream
        LiveStream.objects.filter(id=self.stream_id, status=LiveStream.Status.LIVE) \
            .update(last_heartbeat=timezone.now())

    @database_sync_to_async
    def _end_stream(self):
        from livestream.models import LiveStream
        LiveStream.objects.filter(id=self.stream_id).exclude(status=LiveStream.Status.ENDED).update(
            status=LiveStream.Status.ENDED, ended_at=timezone.now(), current_viewers=0)