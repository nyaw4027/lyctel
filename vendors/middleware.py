# vendors/middleware.py

from .models import Referral

class ReferralMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ref = request.GET.get('ref')

        if ref:
            try:
                referral = Referral.objects.get(code=ref)
                request.session['referral'] = referral.code
                referral.clicks += 1
                referral.save()
            except Referral.DoesNotExist:
                pass

        return self.get_response(request)