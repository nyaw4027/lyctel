
import logging
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.core.cache import cache

from order.models import Order
from ecommerce.models import User   # ← User lives in ecommerce/models.py

logger = logging.getLogger(__name__)


# ── SIGNUP ────────────────────────────────────────────────
def signup(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        phone      = request.POST.get('phone', '').strip()
        password   = request.POST.get('password', '')
        confirm    = request.POST.get('confirm_password', '')

        errors = {}
        if not first_name:       errors['first_name']       = 'First name is required.'
        if not phone:            errors['phone']            = 'Phone number is required.'
        if not password:         errors['password']         = 'Password is required.'
        if len(password) < 6:   errors['password']         = 'Password must be at least 6 characters.'
        if password != confirm:  errors['confirm_password'] = 'Passwords do not match.'
        if User.objects.filter(phone=phone).exists():
            errors['phone'] = 'An account with this number already exists.'

        if errors:
            return render(request, 'accounts/signup.html', {
                'errors': errors, 'form_data': request.POST
            })

        try:
            user = User.objects.create_user(
                username   = phone,
                phone      = phone,
                password   = password,
                first_name = first_name,
                last_name  = last_name,
                role       = 'customer',
            )
            login(request, user)
            messages.success(request, f'Welcome to Lynctel, {first_name}! 🎉')
            return redirect(request.GET.get('next', 'frontend:home'))

        except Exception as e:
            logger.error('Signup error for phone=%s: %s', phone, str(e), exc_info=True)
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
        phone    = request.POST.get('phone', '').strip()
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
            logger.error('Login error for phone=%s: %s', phone, str(e), exc_info=True)
            error = f'Login failed: {e}'

        return render(request, 'accounts/login.html', {
            'error': error, 'form_data': request.POST
        })

    return render(request, 'accounts/login.html', {
        'next': request.GET.get('next', '')
    })


# ── LOGOUT ────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    messages.success(request, 'You have been signed out.')
    return redirect('frontend:home')

def forgot_password(request):
    """
    Step 1:
    User enters phone number.
    Generate OTP and store it in cache.
    """

    if request.user.is_authenticated:
        return redirect("frontend:home")

    if request.method == "POST":
        phone = request.POST.get("phone", "").strip()

        if not phone:
            messages.error(request, "Please enter your phone number.")
            return redirect("accounts:forgot_password")

        try:
            user = User.objects.filter(phone=phone).first()

            # Always show same message whether account exists or not
            # Prevents account enumeration attacks.
            generic_message = (
                "If that number is registered, a reset code has been sent."
            )

            if not user:
                messages.info(request, generic_message)
                return redirect("accounts:forgot_password")

            # Generate 6-digit OTP
            otp = get_random_string(
                length=6,
                allowed_chars="0123456789"
            )

            # Store OTP for 10 minutes
            cache.set(
                f"pwd_reset_otp_{phone}",
                otp,
                timeout=600
            )

            # Store phone in session
            request.session["pwd_reset_phone"] = phone

            logger.warning(
                "PASSWORD RESET OTP for %s: %s",
                phone,
                otp
            )

            messages.success(request, generic_message)

            # Debug only
            if settings.DEBUG:
                messages.warning(
                    request,
                    f"[DEBUG OTP] {otp}"
                )

            return redirect("accounts:verify_otp")

        except Exception:
            logger.exception(
                "Forgot password error for phone=%s",
                phone
            )

            messages.error(
                request,
                "Something went wrong. Please try again."
            )

            return redirect("accounts:forgot_password")

    return render(
        request,
        "accounts/forgot_password.html"
    )


# ── FORGOT PASSWORD — step 2: enter OTP ──────────────────
def verify_otp(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')

    phone = request.session.get('pwd_reset_phone')
    if not phone:
        messages.error(request, 'Session expired. Please start again.')
        return redirect('accounts:forgot_password')

    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()
        stored_otp  = cache.get(f'pwd_reset_otp_{phone}')

        if not stored_otp:
            messages.error(request, 'Reset code has expired. Please request a new one.')
            return redirect('accounts:forgot_password')

        if entered_otp != stored_otp:
            messages.error(request, 'Incorrect code. Please try again.')
            return render(request, 'accounts/verify_otp.html', {
                'phone': phone,
                'masked': f'{phone[:4]}****{phone[-3:]}',
            })

        cache.delete(f'pwd_reset_otp_{phone}')
        request.session['pwd_reset_verified'] = True
        return redirect('accounts:reset_password')

    return render(request, 'accounts/verify_otp.html', {
        'phone':  phone,
        'masked': f'{phone[:4]}****{phone[-3:]}',
    })


# ── FORGOT PASSWORD — step 3: set new password ───────────
def reset_password(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')

    phone    = request.session.get('pwd_reset_phone')
    verified = request.session.get('pwd_reset_verified')

    if not phone or not verified:
        messages.error(request, 'Session expired. Please start again.')
        return redirect('accounts:forgot_password')

    if request.method == 'POST':
        new_pass = request.POST.get('new_password', '')
        confirm  = request.POST.get('confirm_password', '')

        errors = {}
        if len(new_pass) < 6:    errors['new_password']     = 'Password must be at least 6 characters.'
        if new_pass != confirm:  errors['confirm_password'] = 'Passwords do not match.'

        if errors:
            return render(request, 'accounts/reset_password.html', {'errors': errors})

        try:
            user = User.objects.get(phone=phone)
            user.set_password(new_pass)
            user.save()

            del request.session['pwd_reset_phone']
            del request.session['pwd_reset_verified']

            login(request, user)
            messages.success(request, '✅ Password reset successfully! Welcome back.')
            return redirect('frontend:home')

        except User.DoesNotExist:
            messages.error(request, 'Account not found.')
            return redirect('accounts:forgot_password')
        except Exception as e:
            logger.error('Reset password error for phone=%s: %s', phone, str(e), exc_info=True)
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
    total_spent      = orders.filter(payment_status='paid').aggregate(
                           t=Sum('total_amount'))['t'] or 0

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
            logger.error('Update profile error for user=%s: %s', user.pk, str(e), exc_info=True)
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
            request.session['password_error'] = 'Password must be at least 6 characters.'
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
            request.session['password_error'] = f'Could not change password: {e}'
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