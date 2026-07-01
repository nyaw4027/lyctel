import logging
import json
import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.crypto import get_random_string

from order.models import Order
from ecommerce.models import User, normalize_phone

logger = logging.getLogger(__name__)


# ── SIGNUP ────────────────────────────────────────────────
def signup(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        phone      = normalize_phone(request.POST.get('phone', '').strip())
        password   = request.POST.get('password', '')
        confirm    = request.POST.get('confirm_password', '')

        # ── Validate inputs before touching the database
        errors = {}
        if not first_name:
            errors['first_name'] = 'First name is required.'
        if not phone:
            errors['phone'] = 'Phone number is required.'
        if not password:
            errors['password'] = 'Password is required.'
        elif len(password) < 6:
            errors['password'] = 'Password must be at least 6 characters.'
        if password and confirm and password != confirm:
            errors['confirm_password'] = 'Passwords do not match.'
        if phone and User.objects.filter(phone=phone).exists():
            errors['phone'] = 'An account with this number already exists.'

        if errors:
            return render(request, 'accounts/signup.html', {
                'errors': errors,
                'form_data': request.POST,
            })

        # ── Create the user
        try:
            user = User.objects.create_user(
                phone      = phone,
                username   = phone,
                password   = password,
                first_name = first_name,
                last_name  = last_name,
                role       = 'customer',
            )
            login(request, user)
            messages.success(request, f'Welcome to Lynctel, {first_name}! 🎉')
            return redirect(request.GET.get('next') or 'frontend:home')

        except Exception as e:
            logger.error(
                'Signup error for phone=%s: %s', phone, str(e), exc_info=True
            )
            messages.error(request, f'Could not create account: {e}')
            return render(request, 'accounts/signup.html', {
                'errors': {'__all__': str(e)},
                'form_data': request.POST,
            })

    return render(request, 'accounts/signup.html', {})


# ── LOGIN ─────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')

    if request.method == 'POST':
        phone    = normalize_phone(request.POST.get('phone', '').strip())
        password = request.POST.get('password', '')

        try:
            user_obj = User.objects.get(phone=phone)
            if user_obj.check_password(password):
                login(request, user_obj)
                next_url = request.POST.get('next') or request.GET.get('next', '')
                return redirect(next_url if next_url else 'frontend:home')
            else:
                error = 'Incorrect password.'
        except User.DoesNotExist:
            error = 'No account found with this phone number.'
        except Exception as e:
            logger.error(
                'Login error for phone=%s: %s', phone, str(e), exc_info=True
            )
            error = f'Login failed: {e}'

        return render(request, 'accounts/login.html', {
            'error': error,
            'form_data': request.POST,
        })

    return render(request, 'accounts/login.html', {
        'next': request.GET.get('next', ''),
    })


# ── LOGOUT ────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been signed out.')
    return redirect('frontend:home')


# ── OTP DELIVERY HELPERS ──────────────────────────────────

def _send_otp_sms(phone: str, otp: str) -> bool:
    """
    Send OTP via Termii SMS.
    Returns True if the API call succeeded, False otherwise.
    Failure is logged but never raises — we don't want SMS to crash the flow.
    """
    api_key = getattr(settings, 'TERMII_API_KEY', '').strip()
    sender  = getattr(settings, 'TERMII_SENDER_ID', 'Lynctel').strip()

    if not api_key:
        logger.warning('TERMII_API_KEY not set — skipping SMS OTP')
        return False

    # Normalise to international format for Termii (233XXXXXXXXX)
    intl_phone = phone
    if phone.startswith('0'):
        intl_phone = '233' + phone[1:]
    elif phone.startswith('+'):
        intl_phone = phone[1:]

    payload = {
        'to':      intl_phone,
        'from':    sender,
        'sms':     f'Your Lynctel password reset code is: {otp}. It expires in 10 minutes. Do not share it.',
        'type':    'plain',
        'api_key': api_key,
        'channel': 'generic',
    }

    try:
        resp = requests.post(
            'https://api.ng.termii.com/api/sms/send',
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        logger.info('OTP SMS sent to %s — Termii response: %s', phone, resp.text[:200])
        return True
    except Exception as exc:
        logger.error('Termii SMS failed for %s: %s', phone, exc)
        return False


def _send_otp_email(email: str, otp: str, phone: str) -> bool:
    """
    Send OTP via Django email.
    Returns True on success, False otherwise.
    """
    if not email:
        return False

    try:
        send_mail(
            subject='Your Lynctel Password Reset Code',
            message=(
                f'Your Lynctel password reset code is: {otp}\n\n'
                f'It expires in 10 minutes. Do not share it with anyone.\n\n'
                f'If you did not request this, ignore this email.'
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@lynctel.com'),
            recipient_list=[email],
            fail_silently=False,
            html_message=(
                f'<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;">'
                f'<h2 style="color:#0F1B2D;">Password Reset Code</h2>'
                f'<p style="color:#6b7280;">Use the code below to reset your Lynctel password.</p>'
                f'<div style="background:#FEF3D7;border-radius:12px;padding:24px;text-align:center;margin:24px 0;">'
                f'<p style="font-size:36px;font-weight:bold;letter-spacing:.3em;color:#0F1B2D;margin:0;">{otp}</p>'
                f'</div>'
                f'<p style="color:#9ca3af;font-size:13px;">Expires in 10 minutes. Never share this code.</p>'
                f'<p style="color:#9ca3af;font-size:13px;">If you did not request this, ignore this email.</p>'
                f'</div>'
            ),
        )
        logger.info('OTP email sent to %s', email)
        return True
    except Exception as exc:
        logger.error('Email OTP failed for %s: %s', email, exc)
        return False



# ── OTP DELIVERY HELPERS ──────────────────────────────────
 
def _send_otp_sms(phone: str, otp: str) -> bool:
    """
    Send OTP via Termii SMS.
    Returns True if the API call succeeded, False otherwise.
    Failure is logged but never raises — we don't want SMS to crash the flow.
    """
    api_key = getattr(settings, 'TERMII_API_KEY', '').strip()
    sender  = getattr(settings, 'TERMII_SENDER_ID', 'Lynctel').strip()
 
    if not api_key:
        logger.warning('TERMII_API_KEY not set — skipping SMS OTP')
        return False
 
    # Normalise to international format for Termii (233XXXXXXXXX)
    intl_phone = phone
    if phone.startswith('0'):
        intl_phone = '233' + phone[1:]
    elif phone.startswith('+'):
        intl_phone = phone[1:]
 
    payload = {
        'to':      intl_phone,
        'from':    sender,
        'sms':     f'Your Lynctel password reset code is: {otp}. It expires in 10 minutes. Do not share it.',
        'type':    'plain',
        'api_key': api_key,
        'channel': 'generic',
    }
 
    try:
        resp = requests.post(
            'https://api.ng.termii.com/api/sms/send',
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        logger.info('OTP SMS sent to %s — Termii response: %s', phone, resp.text[:200])
        return True
    except Exception as exc:
        logger.error('Termii SMS failed for %s: %s', phone, exc)
        return False
 
 
def _send_otp_email(email: str, otp: str, phone: str) -> bool:
    """
    Send OTP via Django email.
    Returns True on success, False otherwise.
    """
    if not email:
        return False
 
    try:
        send_mail(
            subject='Your Lynctel Password Reset Code',
            message=(
                f'Your Lynctel password reset code is: {otp}\n\n'
                f'It expires in 10 minutes. Do not share it with anyone.\n\n'
                f'If you did not request this, ignore this email.'
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@lynctel.com'),
            recipient_list=[email],
            fail_silently=False,
            html_message=(
                f'<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;">'
                f'<h2 style="color:#0F1B2D;">Password Reset Code</h2>'
                f'<p style="color:#6b7280;">Use the code below to reset your Lynctel password.</p>'
                f'<div style="background:#FEF3D7;border-radius:12px;padding:24px;text-align:center;margin:24px 0;">'
                f'<p style="font-size:36px;font-weight:bold;letter-spacing:.3em;color:#0F1B2D;margin:0;">{otp}</p>'
                f'</div>'
                f'<p style="color:#9ca3af;font-size:13px;">Expires in 10 minutes. Never share this code.</p>'
                f'<p style="color:#9ca3af;font-size:13px;">If you did not request this, ignore this email.</p>'
                f'</div>'
            ),
        )
        logger.info('OTP email sent to %s', email)
        return True
    except Exception as exc:
        logger.error('Email OTP failed for %s: %s', email, exc)
        return False
 
 
# ── STEP 1: enter phone ───────────────────────────────────
 
def forget_password(request):
    """
    User enters their phone number.
    OTP is sent via SMS (always) and also via email if the account has one.
    """
    if request.user.is_authenticated:
        return redirect('frontend:home')
 
    if request.method == 'POST':
        phone = normalize_phone(request.POST.get('phone', '').strip())
 
        if not phone:
            messages.error(request, 'Please enter your phone number.')
            return redirect('accounts:forget_password')
 
        try:
            user = User.objects.filter(phone=phone).first()
 
            # Generic message prevents account enumeration
            generic_msg = (
                'If that number is registered, a reset code has been sent '
                'via SMS and email (if you have one on file).'
            )
 
            if not user:
                messages.info(request, generic_msg)
                return redirect('accounts:forget_password')
 
            # Generate 6-digit OTP
            otp = get_random_string(length=6, allowed_chars='0123456789')
 
            # Store OTP + delivery channels used in cache (10 min)
            cache.set(f'pwd_reset_otp_{phone}', otp, timeout=600)
            request.session['pwd_reset_phone'] = phone
 
            # Attempt delivery via SMS and email
            sms_sent   = _send_otp_sms(phone, otp)
            email_sent = _send_otp_email(user.email, otp, phone) if user.email else False
 
            # Build a user-friendly delivery summary
            delivery_parts = []
            if sms_sent:
                masked_phone = f'{phone[:4]}****{phone[-3:]}'
                delivery_parts.append(f'SMS to {masked_phone}')
            if email_sent and user.email:
                domain      = user.email.split('@')[-1]
                masked_email = f'{user.email[:2]}****@{domain}'
                delivery_parts.append(f'email to {masked_email}')
 
            if delivery_parts:
                messages.success(
                    request,
                    f'Reset code sent via {" and ".join(delivery_parts)}.'
                )
            else:
                # Both channels failed — still don't reveal if account exists
                messages.info(request, generic_msg)
 
            # Always show OTP in DEBUG mode for easy testing
            if settings.DEBUG:
                messages.warning(request, f'[DEBUG] OTP: {otp}')
 
            return redirect('accounts:verify_otp')
 
        except Exception:
            logger.exception('Forgot password error for phone=%s', phone)
            messages.error(request, 'Something went wrong. Please try again.')
            return redirect('accounts:forget_password')
 
    return render(request, 'accounts/forget_password.html')
 
 
# ── STEP 2: verify OTP ────────────────────────────────────
 
def verify_otp(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')
 
    phone = request.session.get('pwd_reset_phone')
    if not phone:
        messages.error(request, 'Session expired. Please start again.')
        return redirect('accounts:forget_password')
 
    masked = f'{phone[:4]}****{phone[-3:]}'
 
    # ── Resend action ──────────────────────────────────────
    if request.method == 'POST' and request.POST.get('action') == 'resend':
        user = User.objects.filter(phone=phone).first()
        if user:
            otp = get_random_string(length=6, allowed_chars='0123456789')
            cache.set(f'pwd_reset_otp_{phone}', otp, timeout=600)
            _send_otp_sms(phone, otp)
            if user.email:
                _send_otp_email(user.email, otp, phone)
            messages.success(request, 'A new code has been sent.')
            if settings.DEBUG:
                messages.warning(request, f'[DEBUG] New OTP: {otp}')
        return redirect('accounts:verify_otp')
 
    # ── Verify action ──────────────────────────────────────
    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()
        stored_otp  = cache.get(f'pwd_reset_otp_{phone}')
 
        if not stored_otp:
            messages.error(
                request, 'Reset code has expired. Please request a new one.'
            )
            return redirect('accounts:forget_password')
 
        if entered_otp != stored_otp:
            messages.error(request, 'Incorrect code. Please try again.')
            return render(request, 'accounts/verify_otp.html', {
                'phone':  phone,
                'masked': masked,
            })
 
        cache.delete(f'pwd_reset_otp_{phone}')
        request.session['pwd_reset_verified'] = True
        return redirect('accounts:reset_password')
 
    return render(request, 'accounts/verify_otp.html', {
        'phone':  phone,
        'masked': masked,
    })
 
 
# ── STEP 3: set new password ──────────────────────────────
 
def reset_password(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')
 
    phone    = request.session.get('pwd_reset_phone')
    verified = request.session.get('pwd_reset_verified')
 
    if not phone or not verified:
        messages.error(request, 'Session expired. Please start again.')
        return redirect('accounts:forget_password')
 
    if request.method == 'POST':
        new_pass = request.POST.get('new_password', '')
        confirm  = request.POST.get('confirm_password', '')
 
        errors = {}
        if len(new_pass) < 6:
            errors['new_password'] = 'Password must be at least 6 characters.'
        if new_pass != confirm:
            errors['confirm_password'] = 'Passwords do not match.'
 
        if errors:
            return render(request, 'accounts/reset_password.html', {'errors': errors})
 
        try:
            user = User.objects.get(phone=phone)
            user.set_password(new_pass)
            user.save()
 
            request.session.pop('pwd_reset_phone', None)
            request.session.pop('pwd_reset_verified', None)
 
            from django.contrib.auth import login
            login(request, user)
            messages.success(request, '✅ Password reset successfully! Welcome back.')
            return redirect('frontend:home')
 
        except User.DoesNotExist:
            messages.error(request, 'Account not found.')
            return redirect('accounts:forget_password')
        except Exception as e:
            logger.error('Reset password error for %s: %s', phone, e, exc_info=True)
            messages.error(request, f'Could not reset password: {e}')
            return render(request, 'accounts/reset_password.html', {})
 
    return render(request, 'accounts/reset_password.html', {})


# ── PROFILE ───────────────────────────────────────────────
@login_required
def profile(request):
    user     = request.user
    is_admin = user.is_superuser or user.is_staff

    orders = Order.objects.filter(customer=user).order_by('-created_at')

    total_orders     = orders.count()
    delivered_orders = orders.filter(status='delivered').count()
    total_spent      = (
        orders.filter(payment_status='paid')
              .aggregate(t=Sum('total_amount'))['t'] or 0
    )

    tabs = [
        ('overview', '🏠', 'Overview'),
        ('orders',   '📦', 'My Orders'),
        ('profile',  '👤', 'Edit Profile'),
        ('security', '🔒', 'Security'),
    ]
    if is_admin:
        tabs.append(('admin', '⚙️', 'Admin Dashboard'))

    return render(request, 'accounts/profile.html', {
        'user':             user,
        'tabs':             tabs,
        'is_admin':         is_admin,
        'total_orders':     total_orders,
        'delivered_orders': delivered_orders,
        'total_spent':      total_spent,
        'recent_orders':    orders[:5],
        'all_orders':       orders,
        'addresses':        [],
        'profile_success':  request.GET.get('profile_saved'),
        'password_success': request.GET.get('password_saved'),
        'password_error':   request.session.pop('password_error', None),
        'cart_count':       0,
    })


# ── UPDATE PROFILE ────────────────────────────────────────
@login_required
def update_profile(request):
    if request.method == 'POST':
        user            = request.user
        user.first_name = request.POST.get('first_name', user.first_name).strip()
        user.last_name  = request.POST.get('last_name', '').strip()
        user.email      = request.POST.get('email', '').strip() or None
        user.address    = request.POST.get('address', '').strip()
        try:
            user.save()
            messages.success(request, 'Profile updated successfully.')
        except Exception as e:
            logger.error(
                'Update profile error for user=%s: %s', user.pk, str(e),
                exc_info=True,
            )
            messages.error(request, f'Could not update profile: {e}')
        return redirect('/accounts/profile/?profile_saved=1#profile')
    return redirect('accounts:profile')


# ── UPDATE PROFILE PICTURE ────────────────────────────────
@login_required
def update_picture(request):
    if request.method == 'POST' and 'profile_pic' in request.FILES:
        try:
            request.user.profile_pic = request.FILES['profile_pic']
            request.user.save()
            messages.success(request, 'Profile photo updated!')
        except Exception as e:
            logger.error('Update picture error: %s', str(e), exc_info=True)
            messages.error(request, f'Could not update photo: {e}')
    return redirect('accounts:profile')


# ── CHANGE PASSWORD ───────────────────────────────────────
@login_required
def change_password(request):
    if request.method == 'POST':
        current  = request.POST.get('current_password', '')
        new_pass = request.POST.get('new_password', '')
        confirm  = request.POST.get('confirm_password', '')

        if not request.user.check_password(current):
            request.session['password_error'] = 'Current password is incorrect.'
            return redirect('/accounts/profile/#security')

        if len(new_pass) < 6:
            request.session['password_error'] = (
                'Password must be at least 6 characters.'
            )
            return redirect('/accounts/profile/#security')

        if new_pass != confirm:
            request.session['password_error'] = 'New passwords do not match.'
            return redirect('/accounts/profile/#security')

        try:
            request.user.set_password(new_pass)
            request.user.save()
            update_session_auth_hash(request, request.user)
            return redirect('/accounts/profile/?password_saved=1#security')
        except Exception as e:
            logger.error('Change password error: %s', str(e), exc_info=True)
            request.session['password_error'] = (
                f'Could not change password: {e}'
            )
            return redirect('/accounts/profile/#security')

    return redirect('accounts:profile')


# ── DELETE ACCOUNT ────────────────────────────────────────
@login_required
def delete_account(request):
    if request.method == 'POST':
        user = request.user
        logout(request)
        user.delete()
        messages.success(request, 'Your account has been deleted.')
        return redirect('frontend:home')
    return render(request, 'accounts/delete_confirm.html', {})



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
            return JsonResponse({'success': False, 'error': 'Missing subscription data'}, status=400)

        from ecommerce.models import PushSubscription
        sub, created = PushSubscription.objects.update_or_create(
            endpoint  = endpoint,
            defaults  = {
                'user':      request.user,
                'p256dh':    p256dh,
                'auth':      auth,
                'is_active': True,
            },
        )
        return JsonResponse({'success': True, 'created': created})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def delete_push_subscription(request):
    """Remove a push subscription (user unsubscribed)."""
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
