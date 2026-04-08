from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from ecommerce.models import User


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        phone      = request.POST.get('phone', '').strip()
        email      = request.POST.get('email', '').strip()
        password1  = request.POST.get('password1', '')
        password2  = request.POST.get('password2', '')

        errors = {}
        if not first_name:              errors['first_name'] = 'Enter your first name.'
        if not phone:                   errors['phone']      = 'Enter your phone number.'
        if not password1:               errors['password1']  = 'Enter a password.'
        if password1 != password2:      errors['password2']  = 'Passwords do not match.'
        if len(password1) < 6:          errors['password1']  = 'Password must be at least 6 characters.'
        if User.objects.filter(phone=phone).exists():
            errors['phone'] = 'An account with this phone number already exists.'

        if errors:
            return render(request, 'accounts/signup.html', {
                'errors': errors, 'form_data': request.POST
            })

        user = User.objects.create_user(
            username   = phone,
            phone      = phone,
            email      = email,
            password   = password1,
            first_name = first_name,
            last_name  = last_name,
            role       = User.Role.CUSTOMER,
        )
        login(request, user)
        messages.success(request, f'Welcome, {first_name}! Your account is ready.')
        return redirect(request.GET.get('next', 'frontend:home'))

    return render(request, 'accounts/signup.html', {})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('frontend:home')

    if request.method == 'POST':
        phone    = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        next_url = request.POST.get('next', '')

        user = authenticate(request, username=phone, password=password)

        if user:
            login(request, user)
            messages.success(request, f'Welcome back, {user.first_name or user.phone}!')
            return redirect(next_url or 'frontend:home')
        else:
            return render(request, 'accounts/login.html', {
                'error': 'Invalid phone number or password.',
                'phone': phone,
                'next': next_url,
            })

    return render(request, 'accounts/login.html', {
        'next': request.GET.get('next', '')
    })


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been signed out.')
    return redirect('frontend:home')