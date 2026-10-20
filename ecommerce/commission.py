"""
ecommerce/commission.py  —  the ONE place commission maths lives.

Policy (from the owner's diagram):
  * Product sale  : Lynctel keeps 5%, vendor receives 95%.
  * Delivery fee  : rider receives 90%, Lynctel keeps 10%.

Rates come from settings so they can change without touching code:
    COMMISSION_VENDOR_PCT = 5     # % Lynctel takes from product sales
    COMMISSION_RIDER_PCT  = 10    # % Lynctel takes from delivery fees

Rounding rule: the APP share is rounded to 2dp and the other party gets the
remainder, so app + payee ALWAYS equals the gross to the pesewa.
"""
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings

_CENT = Decimal('0.01')


def _pct(name, default):
    return Decimal(str(getattr(settings, name, default)))


def vendor_commission_pct(vendor=None):
    """
    Flat platform rate (COMMISSION_VENDOR_PCT, default 5).
    Vendor.commission_rate is honoured ONLY if COMMISSION_ALLOW_VENDOR_OVERRIDE = True.
    (Existing vendors all carry the old 4.00 default, which would silently defeat the 5% policy.)
    """
    if vendor is not None and getattr(settings, 'COMMISSION_ALLOW_VENDOR_OVERRIDE', False):
        rate = getattr(vendor, 'commission_rate', None)
        if rate is not None:
            return Decimal(str(rate))
    return _pct('COMMISSION_VENDOR_PCT', 5)


def rider_commission_pct():
    return _pct('COMMISSION_RIDER_PCT', 10)


def _split(gross, app_pct):
    gross = Decimal(str(gross or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    if gross <= 0:
        return {'gross': Decimal('0.00'), 'app': Decimal('0.00'),
                'payee': Decimal('0.00'), 'app_pct': app_pct}
    app = (gross * app_pct / Decimal('100')).quantize(_CENT, rounding=ROUND_HALF_UP)
    return {'gross': gross, 'app': app, 'payee': gross - app, 'app_pct': app_pct}


def split_product_sale(amount, vendor=None):
    """GH₵1000 -> app 50.00, payee (vendor) 950.00."""
    return _split(amount, vendor_commission_pct(vendor))


def split_delivery_fee(fee):
    """GH₵10 -> app 1.00, payee (rider) 9.00."""
    return _split(fee, rider_commission_pct())