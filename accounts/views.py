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
from django.db import IntegrityError  # add this import at the top of accounts/views.py, if not already present

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
    Send OTP via Arkesel SMS.
    Returns True if the API call succeeded, False otherwise.
    Failure is logged but never raises — we don't want SMS to crash the flow.
    """
    api_key   = getattr(settings, 'ARKESEL_API_KEY',   '')
    sender_id = getattr(settings, 'ARKESEL_SENDER_ID', 'Lynctel')

    if not api_key:
        logger.warning('ARKESEL_API_KEY not set — skipping SMS OTP')
        return False

    # Normalise to E.164 international format (+233XXXXXXXXX)
    intl_phone = phone.strip()
    if intl_phone.startswith('0'):
        intl_phone = '+233' + intl_phone[1:]
    elif intl_phone.startswith('233') and not intl_phone.startswith('+'):
        intl_phone = '+' + intl_phone
    elif not intl_phone.startswith('+'):
        intl_phone = '+233' + intl_phone

    # Arkesel v2 API — key goes in header, not payload
    payload = {
        'sender':     sender_id,
        'message':    f'Your Lynctel password reset code is: {otp}. It expires in 10 minutes. Do not share it.',
        'recipients': [intl_phone],
    }
    headers = {
        'api-key':      api_key,
        'Content-Type': 'application/json',
    }

    try:
        resp = requests.post(
            'https://sms.arkesel.com/api/v2/sms/send',
            json=payload,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') == 'success':
            logger.info('OTP SMS sent to %s via Arkesel', phone)
            return True
        else:
            logger.error('Arkesel SMS failed for %s: %s', phone, data)
            return False
    except Exception as exc:
        logger.error('Arkesel SMS failed for %s: %s', phone, exc)
        return False

# ── OTP DELIVERY HELPERS ──────────────────────────────────
def _send_otp_sms(phone: str, otp: str) -> bool:
    """
    Send OTP via Arkesel SMS API v1 (GET-based).
    Returns True if the API call succeeded, False otherwise.
    Failure is logged but never raises.
    """
    api_key   = getattr(settings, 'ARKESEL_API_KEY',   '').strip()
    sender_id = getattr(settings, 'ARKESEL_SENDER_ID', 'Lynctel').strip()

    if not api_key:
        logger.warning('ARKESEL_API_KEY not set — skipping SMS OTP')
        return False

    # Normalise phone — Arkesel v1 accepts 0XXXXXXXXX or 233XXXXXXXXX
    intl_phone = phone.strip()
    if intl_phone.startswith('+'):
        intl_phone = intl_phone[1:]   # strip leading + → 233XXXXXXXXX
    elif intl_phone.startswith('0'):
        intl_phone = '233' + intl_phone[1:]  # 0XX → 233XX

    message = (
        f'Your Lynctel password reset code is: {otp}. '
        f'It expires in 10 minutes. Do not share it.'
    )

    params = {
        'action':  'send-sms',
        'api_key': api_key,
        'to':      intl_phone,
        'from':    sender_id,
        'sms':     message,
    }

    try:
        resp = requests.get(
            'https://sms.arkesel.com/sms/api',
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get('code') == 'ok':
            logger.info('OTP SMS sent to %s via Arkesel v1', phone)
            return True
        else:
            logger.error('Arkesel v1 SMS failed for %s: %s', phone, data)
            return False

    except Exception as exc:
        logger.error('Arkesel SMS failed for %s: %s', phone, exc)
        return False
 
def _send_otp_email(email: str, otp: str, phone: str) -> bool:
    """Send OTP via email in a daemon thread so a blocked/unreachable SMTP
    server never stalls the HTTP response or kills Daphne workers.
    Returns True immediately (fire-and-forget); failures are logged.
    """
    if not email:
        logger.warning('No email provided for OTP email to %s', phone)
        return False

    subject    = 'Your Lynctel password reset code'
    message    = (
        f'Hello,\n\n'
        f'Your Lynctel password reset code is: {otp}. It expires in 10 minutes.\n\n'
        'If you did not request this, please ignore this email.\n\n'
        'Thank you,\nLynctel Team'
    )
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'no-reply@lynctel.com'

    def _send():
        try:
            send_mail(subject, message, from_email, [email], fail_silently=False)
            logger.info('OTP email sent to %s for phone %s', email, phone)
        except Exception as exc:
            logger.error('OTP email failed for %s: %s', email, exc, exc_info=True)

    import threading
    threading.Thread(target=_send, daemon=True, name=f'otp-{phone}').start()
    return True   # caller gets True immediately; result logged in background
 
 
# ── STEP 1: enter phone ───────────────────────────────────
def forget_password(request):
    """
    User enters their phone number.
    OTP is sent via SMS (always) and also via email if the account has one.
    SMS and email are sent in background threads so they never block the response.
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

            # Store OTP in cache (10 min) and phone in session
            cache.set(f'pwd_reset_otp_{phone}', otp, timeout=600)
            request.session['pwd_reset_phone'] = phone

            # ── Send SMS in background thread (non-blocking) ──────
            # _send_otp_sms makes an HTTP request to Arkesel which
            # blocks under ASGI/Daphne if called synchronously.
            import threading
            threading.Thread(
                target=_send_otp_sms,
                args=(phone, otp),
                daemon=True,
            ).start()

            # ── Send email in background thread (non-blocking) ────
            # send_mail uses SMTP which is also a blocking call.
            if user.email:
                threading.Thread(
                    target=_send_otp_email,
                    args=(user.email, otp, phone),
                    daemon=True,
                ).start()

            # Respond immediately — don't wait for SMS/email to finish
            masked_phone = f'{phone[:4]}****{phone[-3:]}'
            messages.success(
                request,
                f'Reset code sent to {masked_phone}.'
                + (f' Also sent to your email.' if user.email else '')
            )

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
        user.address    = request.POST.get('address', '').strip()

        new_email = request.POST.get('email', '').strip() or None
        if new_email and new_email.lower() != (user.email or '').lower():
            if user.__class__.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
                messages.error(request, 'That email address is already in use by another account.')
                return redirect('/accounts/profile/#profile')
        user.email = new_email

        try:
            user.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('/accounts/profile/?profile_saved=1#profile')
        except IntegrityError:
            # Belt-and-suspenders: catches the rare race where two people
            # save the same email between our check above and this save.
            messages.error(request, 'That email address is already in use by another account.')
            return redirect('/accounts/profile/#profile')
        except Exception as e:
            logger.error(
                'Update profile error for user=%s: %s', user.pk, str(e),
                exc_info=True,
            )
            messages.error(request, 'Could not update profile. Please try again.')
            return redirect('/accounts/profile/#profile')

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
