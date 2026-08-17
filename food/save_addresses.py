"""
food/saved_addresses.py

Saved delivery address system (item 8).

SETUP:
  1. Add to food/models.py:
       class SavedAddress(models.Model):
           customer    = models.ForeignKey(settings.AUTH_USER_MODEL,
                                           on_delete=models.CASCADE,
                                           related_name='saved_addresses')
           label       = models.CharField(max_length=60)   # "Home", "Office"
           address     = models.TextField()
           latitude    = models.FloatField()
           longitude   = models.FloatField()
           is_default  = models.BooleanField(default=False)
           created_at  = models.DateTimeField(auto_now_add=True)
           class Meta:
               ordering = ['-is_default', '-created_at']
               constraints = [
                   models.UniqueConstraint(
                       fields=['customer'], condition=Q(is_default=True),
                       name='unique_default_address'
                   )
               ]

  2. Run: python manage.py makemigrations food --name saved_addresses
  3. Add URLs to food/urls.py:
       path('addresses/',        views.saved_address_list,   name='addresses'),
       path('addresses/save/',   views.saved_address_save,   name='address_save'),
       path('addresses/<int:pk>/delete/', views.saved_address_delete, name='address_delete'),
"""
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET


@require_GET
@login_required
def saved_address_list(request):
    """GET /food/addresses/ — returns user's saved addresses as JSON."""
    try:
        from food.models import SavedAddress
        addrs = SavedAddress.objects.filter(customer=request.user)[:5]
        return JsonResponse({'addresses': [
            {'id': a.pk, 'label': a.label, 'address': a.address,
             'lat': a.latitude, 'lng': a.longitude, 'is_default': a.is_default}
            for a in addrs
        ]})
    except Exception as e:
        return JsonResponse({'addresses': [], 'error': str(e)})


@require_POST
@login_required
def saved_address_save(request):
    """POST /food/addresses/save/ — save the current checkout address."""
    try:
        from food.models import SavedAddress
        d = json.loads(request.body)
        label   = d.get('label', 'Home').strip() or 'Home'
        address = d.get('address', '').strip()
        lat     = float(d.get('lat', 0))
        lng     = float(d.get('lng', 0))

        if not address or not lat or not lng:
            return JsonResponse({'success': False, 'error': 'Missing fields'})

        # Keep max 5 addresses per user
        existing = SavedAddress.objects.filter(customer=request.user)
        if existing.count() >= 5:
            existing.order_by('created_at').first().delete()

        addr = SavedAddress.objects.create(
            customer=request.user, label=label,
            address=address, latitude=lat, longitude=lng,
        )
        return JsonResponse({'success': True, 'id': addr.pk})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@require_POST
@login_required
def saved_address_delete(request, pk):
    try:
        from food.models import SavedAddress
        SavedAddress.objects.filter(pk=pk, customer=request.user).delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})