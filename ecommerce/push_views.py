
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required


@login_required
@require_POST
def save_push_subscription(request):
    """Save or update a push subscription for the current user."""
    try:
        data     = json.loads(request.body)
        endpoint = data.get('endpoint', '').strip()
        p256dh   = data.get('keys', {}).get('p256dh', '').strip()
        auth     = data.get('keys', {}).get('auth', '').strip()

        if not endpoint or not p256dh or not auth:
            return JsonResponse({'success': False, 'error': 'Missing fields'}, status=400)

        from ecommerce.models import PushSubscription
        PushSubscription.objects.update_or_create(
            endpoint = endpoint,
            defaults = {
                'user':      request.user,
                'p256dh':    p256dh,
                'auth':      auth,
                'is_active': True,
            },
        )
        return JsonResponse({'success': True})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def delete_push_subscription(request):
    """Remove a push subscription."""
    try:
        data     = json.loads(request.body)
        endpoint = data.get('endpoint', '').strip()
        if endpoint:
            from ecommerce.models import PushSubscription
            PushSubscription.objects.filter(
                user=request.user, endpoint=endpoint
            ).update(is_active=False)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)