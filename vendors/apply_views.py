import uuid
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.utils import timezone

from .models import Vendor, VendorEarning


# ── STEP 1: Fill application form ─────────────────────────

def apply(request):
    """
    Two-step vendor registration:
    Step 1 → fill form, save to session
    Step 2 → pay GHS 100 registration fee via Flutterwave
    Step 3 → on payment success, create vendor account (pending admin approval)
    """
    # Already a vendor?
    if request.user.is_authenticated:
        try:
            vendor = request.user.vendor
            if vendor.status == Vendor.Status.ACTIVE:
                return redirect('vendors:dashboard')
            return render(request, 'vendors/pending.html', {'vendor': vendor})
        except Vendor.DoesNotExist:
            pass

    if request.method == 'POST':
        shop_name    = request.POST.get('shop_name', '').strip()
        description  = request.POST.get('description', '').strip()
        phone        = request.POST.get('phone', '').strip()
        location     = request.POST.get('location', '').strip()
        momo_number  = request.POST.get('momo_number', '').strip()
        momo_network = request.POST.get('momo_network', '')

        # Account fields (if not logged in)
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        password   = request.POST.get('password', '')

        errors = {}
        if not shop_name:   errors['shop_name']   = 'Shop name is required.'
        if not phone:       errors['phone']       = 'Phone number is required.'
        if not momo_number: errors['momo_number'] = 'MoMo payout number is required.'

        if not request.user.is_authenticated:
            if not first_name: errors['first_name'] = 'First name is required.'
            if not password:   errors['password']   = 'Password is required.'
            if len(password) < 6:
                errors['password'] = 'Password must be at least 6 characters.'
            from ecommerce.models import User
            if User.objects.filter(phone=phone).exists():
                errors['phone'] = 'An account with this number already exists. Sign in first.'

        if errors:
            return render(request, 'vendors/apply.html', {
                'errors': errors, 'form_data': request.POST
            })

        # Save application to session — complete after payment
        request.session['vendor_application'] = {
            'shop_name':    shop_name,
            'description':  description,
            'phone':        phone,
            'location':     location,
            'momo_number':  momo_number,
            'momo_network': momo_network,
            'first_name':   first_name,
            'last_name':    last_name,
            'password':     password,
        }

        # Build Flutterwave payment config for GHS 100 registration fee
        tx_ref = f"VENDOR-REG-{uuid.uuid4().hex[:10].upper()}"
        request.session['vendor_reg_tx_ref'] = tx_ref

        customer_email = (
            request.user.email if request.user.is_authenticated
            else f"{phone}@lynctel.com"
        )
        customer_name = (
            request.user.get_full_name() if request.user.is_authenticated
            else f"{first_name} {last_name}".strip()
        )

        flw_config = {
            'public_key':      settings.FLW_PUBLIC_KEY,
            'tx_ref':          tx_ref,
            'amount':          '100',
            'currency':        'GHS',
            'payment_options': 'mobilemoney,card',
            'redirect_url':    request.build_absolute_uri('/vendor/apply/payment/callback/'),
            'customer': {
                'email':        customer_email,
                'phone_number': phone,
                'name':         customer_name or shop_name,
            },
            'customizations': {
                'title':       'Lynctel Vendor Registration',
                'description': f'One-time registration fee for {shop_name}',
            },
            'meta': {'shop_name': shop_name},
        }

        return render(request, 'vendors/pay_registration.html', {
            'shop_name':  shop_name,
            'flw_config': json.dumps(flw_config),
            'FLW_PUBLIC_KEY': settings.FLW_PUBLIC_KEY,
        })

    return render(request, 'vendors/apply.html', {})


# ── STEP 2: Payment callback ──────────────────────────────

def apply_payment_callback(request):
    """
    Flutterwave redirects here after vendor pays the GHS 100 fee.
    Verify payment → create vendor account.
    """
    import requests as req

    status   = request.GET.get('status')
    tx_ref   = request.GET.get('tx_ref')
    trans_id = request.GET.get('transaction_id')

    application = request.session.get('vendor_application')
    saved_tx    = request.session.get('vendor_reg_tx_ref')

    if not application or tx_ref != saved_tx:
        messages.error(request, 'Invalid session. Please try again.')
        return redirect('vendors:apply')

    if status != 'successful' or not trans_id:
        messages.error(request, 'Payment was not completed. Please try again.')
        return redirect('vendors:apply')

    # Verify with Flutterwave
    try:
        resp = req.get(
            f"https://api.flutterwave.com/v3/transactions/{trans_id}/verify",
            headers={'Authorization': f'Bearer {settings.FLW_SECRET_KEY}'},
            timeout=10,
        )
        data = resp.json()
        verified = (
            data.get('status') == 'success'
            and data['data']['status'] == 'successful'
            and data['data']['currency'] == 'GHS'
            and float(data['data']['amount']) >= 100
        )
    except Exception:
        verified = False

    if not verified:
        messages.error(request, 'Payment verification failed. Contact support with ref: ' + tx_ref)
        return redirect('vendors:apply')

    # ── Create user account if not logged in ──────────────
    if not request.user.is_authenticated:
        from ecommerce.models import User
        phone = application['phone']
        # Double-check user doesn't exist (race condition)
        if User.objects.filter(phone=phone).exists():
            user = User.objects.get(phone=phone)
        else:
            user = User.objects.create_user(
                username   = phone,
                phone      = phone,
                password   = application['password'],
                first_name = application['first_name'],
                last_name  = application['last_name'],
                role       = 'customer',
            )
        login(request, user)
    else:
        user = request.user

    # ── Create vendor (pending approval) ─────────────────
    if hasattr(user, 'vendor'):
        vendor = user.vendor
    else:
        vendor = Vendor.objects.create(
            owner        = user,
            shop_name    = application['shop_name'],
            description  = application['description'],
            phone        = application['phone'],
            location     = application['location'],
            momo_number  = application['momo_number'],
            momo_network = application['momo_network'],
            status       = Vendor.Status.PENDING,
        )

    # Clear session
    del request.session['vendor_application']
    del request.session['vendor_reg_tx_ref']

    messages.success(
        request,
        f'Payment confirmed! Your shop "{vendor.shop_name}" application is under review. '
        f'We will approve within 24 hours.'
    )
    return redirect('vendors:pending')


# ── PENDING page ──────────────────────────────────────────

@login_required
def pending(request):
    try:
        vendor = request.user.vendor
    except Vendor.DoesNotExist:
        return redirect('vendors:apply')
    return render(request, 'vendors/pending.html', {'vendor': vendor})