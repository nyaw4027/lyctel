from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('signup/',                  views.signup,           name='signup'),
    path('login/',                   views.login_view,       name='login'),
    path('logout/',                  views.logout_view,      name='logout'),
    path('profile/',                 views.profile,          name='profile'),
    path('profile/update/',          views.update_profile,   name='update_profile'),
    path('profile/picture/',         views.update_picture,   name='update_picture'),
    path('profile/password/',        views.change_password,  name='change_password'),
    path('profile/delete/',          views.delete_account,   name='delete_account'),

    # ── Password recovery ─────────────────────────────────
    path('forgot-password/',         views.forgot_password,  name='forgot_password'),
    path('forgot-password/verify/',  views.verify_otp,       name='verify_otp'),
    path('forgot-password/reset/',   views.reset_password,   name='reset_password'),
]