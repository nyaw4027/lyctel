# vendors/services.py (new file, or add to an existing services module)
import requests
from django.conf import settings

PAYSTACK_SECRET = getattr(settings, 'PAYSTACK_SECRET_KEY', '')

def create_paystack_subaccount(vendor):
    """
    Creates a Paystack subaccount for this vendor so their share of every
    sale can be split and settled directly to them — Lynctel never holds
    vendor funds once this is in place.
    """
    if vendor.paystack_subaccount_code:
        return vendor.paystack_subaccount_code  # already created

    resp = requests.post(
        'https://api.paystack.co/subaccount',
        headers={'Authorization': f'Bearer {PAYSTACK_SECRET}'},
        json={
            'business_name': vendor.shop_name,
            'settlement_bank': vendor.momo_network_bank_code,  # see note below
            'account_number': vendor.momo_number,
            'percentage_charge': 0,  # we control the split per-transaction instead
        },
        timeout=10,
    )
    data = resp.json()
    if data.get('status'):
        vendor.paystack_subaccount_code = data['data']['subaccount_code']
        vendor.save(update_fields=['paystack_subaccount_code'])
        return vendor.paystack_subaccount_code

    raise Exception(f"Paystack subaccount creation failed: {data.get('message')}")