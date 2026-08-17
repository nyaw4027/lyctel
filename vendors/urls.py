from django.urls import path
from . import views
from order.pdf import vendor_invoice_pdf

app_name = 'vendors'

urlpatterns = [
    # ── Public ────────────────────────────────────────────────────────────────
    path('shops/',                              views.directory,        name='list'),
    path('shops/<slug:slug>/',                  views.shop_page,        name='detail'),

    # ── Referral landing (public — no login) ──────────────────────────────────
    path('ref/<str:code>/',                     views.referral_landing, name='referral_landing'),

    # ── Vendor onboarding ────────────────────────────────────────────────────
    path('vendor/apply/',                       views.apply,            name='apply'),
    path('vendor/pending/',                     views.pending,          name='pending'),

    # ── Vendor dashboard ─────────────────────────────────────────────────────
    path('vendor/dashboard/',                   views.dashboard,        name='dashboard'),
    path('vendor/dispatch/',                    views.dispatch_ride,    name='dispatch'),

    # ── Products ──────────────────────────────────────────────────────────────
    path('vendor/products/add/',                views.product_add,      name='product_add'),
    path('vendor/products/<int:pk>/edit/',      views.product_edit,     name='product_edit'),
    path('vendor/products/<int:pk>/delete/',    views.product_delete,   name='product_delete'),

    # ── Earnings ──────────────────────────────────────────────────────────────
    path('vendor/earnings/',                    views.earnings,         name='earnings'),

    # ── Analytics ─────────────────────────────────────────────────────────────
    path('vendor/analytics/',                   views.vendor_analytics, name='analytics'),

    # ── Referral management ───────────────────────────────────────────────────
    path('vendor/referrals/',                   views.referral_stats,   name='referral_stats'),
    path('vendor/referrals/generate/',          views.generate_referral,name='generate_referral'),

    # ── Monthly invoice PDF ───────────────────────────────────────────────────
    path('vendor/invoice/<int:year>/<int:month>/',
                                                vendor_invoice_pdf,     name='invoice_pdf'),
]