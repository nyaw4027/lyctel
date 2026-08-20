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

            # Merge guest cart
            try:
                from cart.views import merge_guest_cart
                merge_guest_cart(request, user)
            except Exception:
                pass

            # Credit referral link
            try:
                from vendors.views import _apply_referral_on_signup
                _apply_referral_on_signup(user, request)
            except Exception:
                pass

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
    # Already logged in → go to next or home
    if request.user.is_authenticated:
        next_url = request.GET.get('next', '/') or '/'
        if not next_url.startswith('/'):
            next_url = '/'
        return redirect(next_url)
 
    error    = None
    next_url = (request.GET.get('next')
                or request.POST.get('next')
                or '/')
 
    # Security: only allow relative-path redirects (prevent open redirect)
    if not next_url.startswith('/'):
        next_url = '/'
 
    if request.method == 'POST':
        phone    = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '').strip()
 
        if not phone or not password:
            error = 'Please enter your phone number and password.'
        else:
            from django.contrib.auth import authenticate, login
            user = authenticate(request, phone=phone, password=password)
            if user is not None:
                login(request, user)
 
                # Merge guest cart
                try:
                    from cart.views import merge_guest_cart
                    merge_guest_cart(request, user)
                except Exception:
                    pass
 
                # ← THIS is the fix: redirect to next_url, not to settings.LOGIN_REDIRECT_URL
                return redirect(next_url)
            else:
                error = 'Incorrect phone number or password. Please try again.'
 
    return render(request, 'accounts/login.html', {
        'error':     error,
        'next':      next_url,        # ← pass to template so hidden field has value
        'form_data': request.POST,
    })
 

# ── LOGOUT ────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been signed out.')
    return redirect('frontend:home')


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

def _mask_email(email: str) -> str:
    """Returns j***@gmail.com style masked email for display."""
    try:
        local, domain = email.split('@', 1)
        return f'{local[0]}***@{domain}'
    except Exception:
        return '***'

def forget_password(request):
    """
    User enters their phone number OR email address.
    OTP is sent via SMS (if phone found) and email (if email found).
    Both lookups are supported — whichever the user provides.
    """
    if request.user.is_authenticated:
        return redirect('frontend:home')

    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()

        if not identifier:
            messages.error(request, 'Please enter your phone number or email address.')
            return redirect('accounts:forget_password')

        try:
            import threading

            # ── Determine if input is email or phone ──────────────
            is_email = '@' in identifier
            user     = None

            if is_email:
                user = User.objects.filter(email__iexact=identifier).first()
            else:
                phone = normalize_phone(identifier)
                user  = User.objects.filter(phone=phone).first()
                if user:
                    identifier = phone   # normalise

            # Generic response — prevents account enumeration
            generic_msg = (
                'If that account exists, a reset code has been sent. '
                'Check your SMS and email inbox.'
            )

            if not user:
                messages.info(request, generic_msg)
                return redirect('accounts:forget_password')

            # Generate 6-digit OTP
            otp      = get_random_string(length=6, allowed_chars='0123456789')
            cache_key = f'pwd_reset_otp_{identifier}'
            cache.set(cache_key, otp, timeout=600)

            # Store identifier (phone or email) in session
            request.session['pwd_reset_identifier'] = identifier
            request.session['pwd_reset_is_email']   = is_email
            # Keep legacy key for verify_otp compatibility
            if not is_email:
                request.session['pwd_reset_phone'] = identifier

            sent_to = []

            # ── Send SMS (phone recovery or account has phone) ────
            sms_phone = None
            if not is_email:
                sms_phone = identifier
            elif user.phone:
                sms_phone = user.phone

            if sms_phone:
                threading.Thread(
                    target=_send_otp_sms, args=(sms_phone, otp), daemon=True
                ).start()
                masked = f'{sms_phone[:4]}****{sms_phone[-3:]}'
                sent_to.append(f'SMS to {masked}')

            # ── Send email (email recovery or account has email) ──
            email_addr = identifier if is_email else user.email
            if email_addr:
                threading.Thread(
                    target=_send_otp_email,
                    args=(email_addr, otp, identifier),
                    daemon=True,
                ).start()
                masked_email = _mask_email(email_addr)
                sent_to.append(f'email to {masked_email}')

            delivery = ' and '.join(sent_to) if sent_to else 'your contact'
            messages.success(request, f'Reset code sent via {delivery}.')

            if settings.DEBUG:
                messages.warning(request, f'[DEBUG] OTP: {otp}')

            return redirect('accounts:verify_otp')

        except Exception:
            logger.exception('Forgot password error for identifier=%s', identifier)
            messages.error(request, 'Something went wrong. Please try again.')
            return redirect('accounts:forget_password')

    return render(request, 'accounts/forget_password.html')
 
# ── STEP 2: verify OTP ────────────────────────────────────
 
def verify_otp(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')
 
    # Support both phone and email recovery
    identifier = (
        request.session.get('pwd_reset_identifier') or
        request.session.get('pwd_reset_phone')
    )
    is_email   = request.session.get('pwd_reset_is_email', False)
    phone      = None if is_email else identifier

    if not identifier:
        messages.error(request, 'Session expired. Please start again.')
        return redirect('accounts:forget_password')

    if is_email:
        masked = _mask_email(identifier)
    else:
        masked = f'{identifier[:4]}****{identifier[-3:]}'
 
    # ── Resend action ──────────────────────────────────────
    if request.method == 'POST' and request.POST.get('action') == 'resend':
        user = (
            User.objects.filter(email__iexact=identifier).first()
            if is_email
            else User.objects.filter(phone=identifier).first()
        )
        if user:
            otp = get_random_string(length=6, allowed_chars='0123456789')
            cache.set(f'pwd_reset_otp_{identifier}', otp, timeout=600)
            if phone or user.phone:
                _send_otp_sms(phone or user.phone, otp)
            if is_email or user.email:
                _send_otp_email(identifier if is_email else user.email, otp, identifier)
            messages.success(request, 'A new code has been sent.')
            if settings.DEBUG:
                messages.warning(request, f'[DEBUG] New OTP: {otp}')
        return redirect('accounts:verify_otp')
 
    # ── Verify action ──────────────────────────────────────
    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()
        stored_otp  = cache.get(f'pwd_reset_otp_{identifier}')
 
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
 
        cache.delete(f'pwd_reset_otp_{identifier}')
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
 
    identifier = (
        request.session.get('pwd_reset_identifier') or
        request.session.get('pwd_reset_phone')
    )
    is_email = request.session.get('pwd_reset_is_email', False)
    verified = request.session.get('pwd_reset_verified')

    if not identifier or not verified:
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
            user = (
                User.objects.get(email__iexact=identifier)
                if is_email
                else User.objects.get(phone=identifier)
            )
            user.set_password(new_pass)
            user.save()
 
            request.session.pop('pwd_reset_identifier', None)
            request.session.pop('pwd_reset_phone', None)
            request.session.pop('pwd_reset_is_email', None)
            request.session.pop('pwd_reset_verified', None)
 
            from django.contrib.auth import login
            login(request, user)
            messages.success(request, '✅ Password reset successfully! Welcome back.')
            return redirect('frontend:home')
 
        except User.DoesNotExist:
            messages.error(request, 'Account not found.')
            return redirect('accounts:forget_password')
        except Exception as e:
            logger.error('Reset password error for %s: %s', identifier, e, exc_info=True)
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