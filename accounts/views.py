from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count

from ecommerce.models import User
from order.models import Order


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
        if not first_name: errors['first_name'] = 'First name is required.'
        if not phone:      errors['phone']      = 'Phone number is required.'
        if not password:   errors['password']   = 'Password is required.'
        if len(password) < 6: errors['password'] = 'Password must be at least 6 characters.'
        if password != confirm: errors['confirm_password'] = 'Passwords do not match.'
        if User.objects.filter(phone=phone).exists():
            errors['phone'] = 'An account with this number already exists.'

        if errors:
            return render(request, 'accounts/signup.html', {
                'errors': errors, 'form_data': request.POST
            })

        user = User.objects.create_user(
            username=phone, phone=phone, password=password,
            first_name=first_name, last_name=last_name, role='customer',
        )
        login(request, user)
        messages.success(request, f'Welcome to Lynctel, {first_name}!')
        return redirect(request.GET.get('next', 'frontend:home'))

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


# ── PROFILE ───────────────────────────────────────────────

@login_required
def profile(request):
    user = request.user

    # Order stats
    orders          = Order.objects.filter(customer=user).order_by('-created_at')
    total_orders    = orders.count()
    delivered_orders = orders.filter(status='delivered').count()
    total_spent     = orders.filter(
        payment_status='paid'
    ).aggregate(t=Sum('total_amount'))['t'] or 0

    recent_orders = orders[:5]
    all_orders    = orders

    # Tab nav
    tabs = [
        ('overview', '🏠', 'Overview'),
        ('orders',   '📦', 'My Orders'),
        ('profile',  '👤', 'Edit Profile'),
        ('security', '🔒', 'Security'),
    ]

    context = {
        'user':             user,
        'tabs':             tabs,
        'total_orders':     total_orders,
        'delivered_orders': delivered_orders,
        'total_spent':      total_spent,
        'recent_orders':    recent_orders,
        'all_orders':       all_orders,
        'addresses':        [],
        'profile_success':  request.GET.get('profile_saved'),
        'password_success': request.GET.get('password_saved'),
        'password_error':   request.session.pop('password_error', None),
        'cart_count':       0,
    }
    return render(request, 'accounts/profile.html', context)


# ── UPDATE PROFILE ────────────────────────────────────────

@login_required
def update_profile(request):
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name).strip()
        user.last_name  = request.POST.get('last_name', '').strip()
        user.email      = request.POST.get('email', '').strip()
        user.address    = request.POST.get('address', '').strip()
        user.save()
        return redirect('/accounts/profile/?profile_saved=1#profile')
    return redirect('accounts:profile')


# ── UPDATE PROFILE PICTURE ────────────────────────────────

@login_required
def update_picture(request):
    if request.method == 'POST' and 'profile_pic' in request.FILES:
        request.user.profile_pic = request.FILES['profile_pic']
        request.user.save()
        messages.success(request, 'Profile photo updated!')
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

        request.user.set_password(new_pass)
        request.user.save()
        update_session_auth_hash(request, request.user)
        return redirect('/accounts/profile/?password_saved=1#security')

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