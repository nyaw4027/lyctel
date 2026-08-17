"""
order/pdf.py — PDF receipt generation (items 10 + 13)

Add to order/urls.py:
    path('<str:order_ref>/receipt/', views.order_receipt_pdf, name='receipt'),

Add to vendors/urls.py:
    path('vendor/invoice/<int:year>/<int:month>/', views.vendor_invoice_pdf, name='invoice'),
"""
import io
from decimal import Decimal
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm


NAVY  = colors.HexColor('#0F1B2D')
GOLD  = colors.HexColor('#F5A623')
LIGHT = colors.HexColor('#f9fafb')


def _base_doc(buf, title):
    return SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
        title=title,
    )


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle('BrandTitle', fontSize=22, textColor=NAVY,
                          fontName='Helvetica-Bold', spaceAfter=2))
    s.add(ParagraphStyle('SubHead', fontSize=10, textColor=colors.grey,
                          spaceAfter=8))
    s.add(ParagraphStyle('SectionHead', fontSize=11, textColor=NAVY,
                          fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4))
    s.add(ParagraphStyle('Small', fontSize=8, textColor=colors.grey))
    return s


# ── Order Receipt PDF ─────────────────────────────────────────────────────────

@login_required
def order_receipt_pdf(request, order_ref):
    from order.models import Order
    order = get_object_or_404(Order, order_ref=order_ref, customer=request.user)
    buf   = io.BytesIO()
    doc   = _base_doc(buf, f'Receipt {order_ref}')
    s     = _styles()
    story = []

    # Header
    story += [
        Paragraph('Lynctel', s['BrandTitle']),
        Paragraph('lynctel.up.railway.app', s['SubHead']),
        HRFlowable(width='100%', color=GOLD, thickness=2, spaceAfter=12),
        Paragraph(f'<b>Order Receipt</b>', s['SectionHead']),
        Paragraph(f'Order: <b>{order.order_ref}</b>', s['Normal']),
        Paragraph(f'Date: {order.created_at.strftime("%d %b %Y, %H:%M")}', s['Normal']),
        Paragraph(f'Status: {order.get_payment_status_display()}', s['Normal']),
        Spacer(1, 8),
    ]

    # Customer info
    story += [
        Paragraph('Customer', s['SectionHead']),
        Paragraph(f'{order.customer.get_full_name() or order.customer.phone}', s['Normal']),
        Paragraph(f'{order.delivery_address or ""}', s['Normal']),
        Spacer(1, 8),
    ]

    # Items table
    story.append(Paragraph('Items', s['SectionHead']))
    rows = [['Item', 'Qty', 'Unit Price', 'Total']]
    for item in order.items.all():
        rows.append([
            item.product.name if hasattr(item, 'product') else item.name,
            str(item.quantity),
            f'GHS {item.price}',
            f'GHS {item.subtotal}',
        ])

    tbl = Table(rows, colWidths=[90*mm, 20*mm, 35*mm, 35*mm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), NAVY),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [LIGHT, colors.white]),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#e5e7eb')),
        ('ALIGN',      (1,0), (-1,-1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (0,-1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))

    # Totals
    sub  = getattr(order, 'subtotal',      order.total_amount)
    dfee = getattr(order, 'delivery_fee',  0)
    tot  = getattr(order, 'total_amount',  sub)
    vat  = (Decimal(str(sub)) * Decimal('0.15')).quantize(Decimal('0.01'))

    totals = Table([
        ['Subtotal', f'GHS {sub}'],
        ['Delivery', f'GHS {dfee}'],
        ['VAT (15%)', f'GHS {vat}'],
        ['TOTAL',    f'GHS {tot}'],
    ], colWidths=[130*mm, 50*mm])
    totals.setStyle(TableStyle([
        ('ALIGN',    (1,0), (1,-1), 'RIGHT'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('TEXTCOLOR',(0,-1), (-1,-1), NAVY),
        ('FONTSIZE', (0,0),  (-1,-1), 9),
        ('LINEABOVE',(0,-1), (-1,-1), 1, NAVY),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(totals)
    story += [
        Spacer(1,16),
        HRFlowable(width='100%', color=colors.HexColor('#e5e7eb'), thickness=1),
        Paragraph('Thank you for shopping with Lynctel! 🛍️', s['Small']),
        Paragraph('Questions? WhatsApp: +233558040216', s['Small']),
    ]

    doc.build(story)
    buf.seek(0)
    resp = HttpResponse(buf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="lynctel-receipt-{order_ref}.pdf"'
    return resp


# ── Vendor Monthly Invoice PDF ────────────────────────────────────────────────

@login_required
def vendor_invoice_pdf(request, year, month):
    from datetime import date
    from django.db.models import Sum, Count
    from order.models import Order, OrderItem

    try:
        vendor = request.user.vendor
    except Exception:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Vendor account required')

    start = date(year, month, 1)
    end   = date(year, month+1, 1) if month < 12 else date(year+1, 1, 1)

    items_qs = OrderItem.objects.filter(
        product__vendor=vendor,
        order__payment_status='paid',
        order__created_at__date__gte=start,
        order__created_at__date__lt=end,
    ).select_related('order', 'product')

    stats = items_qs.aggregate(gross=Sum('subtotal'), orders=Count('order', distinct=True))
    gross = Decimal(str(stats['gross'] or 0))
    commission = (gross * Decimal('0.04')).quantize(Decimal('0.01'))
    net = gross - commission

    buf = io.BytesIO()
    doc = _base_doc(buf, f'Invoice {vendor.shop_name} {year}-{month:02d}')
    s   = _styles()
    story = []

    story += [
        Paragraph('Lynctel', s['BrandTitle']),
        Paragraph('Vendor Monthly Invoice', s['SubHead']),
        HRFlowable(width='100%', color=GOLD, thickness=2, spaceAfter=12),
    ]

    story += [
        Paragraph('Invoice Details', s['SectionHead']),
        Paragraph(f'Vendor: <b>{vendor.shop_name}</b>', s['Normal']),
        Paragraph(f'Period: <b>{start.strftime("%B %Y")}</b>', s['Normal']),
        Paragraph(f'Total Orders: <b>{stats["orders"]}</b>', s['Normal']),
        Spacer(1, 8),
    ]

    # Transaction table (max 30 rows)
    story.append(Paragraph('Sales Breakdown', s['SectionHead']))
    rows = [['Date', 'Order', 'Product', 'Qty', 'Amount']]
    for item in items_qs.order_by('order__created_at')[:30]:
        rows.append([
            item.order.created_at.strftime('%d %b'),
            item.order.order_ref,
            item.product.name[:30],
            str(item.quantity),
            f'GHS {item.subtotal}',
        ])
    if items_qs.count() > 30:
        rows.append(['...', f'+{items_qs.count()-30} more', '', '', ''])

    tbl = Table(rows, colWidths=[20*mm, 35*mm, 70*mm, 15*mm, 25*mm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), NAVY),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [LIGHT, colors.white]),
        ('GRID',       (0,0), (-1,-1), 0.3, colors.HexColor('#e5e7eb')),
        ('ALIGN',      (-1,0), (-1,-1), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
    ]))
    story += [tbl, Spacer(1, 12)]

    # Summary
    summary = Table([
        ['Gross Sales',     f'GHS {gross}'],
        ['Platform Fee (4%)', f'- GHS {commission}'],
        ['NET PAYOUT',       f'GHS {net}'],
    ], colWidths=[130*mm, 50*mm])
    summary.setStyle(TableStyle([
        ('ALIGN',    (1,0), (1,-1), 'RIGHT'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('TEXTCOLOR',(0,-1), (-1,-1), colors.HexColor('#16a34a')),
        ('FONTSIZE', (0,0),  (-1,-1), 10),
        ('LINEABOVE',(0,-1), (-1,-1), 1.5, NAVY),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story += [
        summary, Spacer(1,16),
        HRFlowable(width='100%', color=colors.HexColor('#e5e7eb'), thickness=1),
        Paragraph(f'Invoice generated by Lynctel — {date.today().strftime("%d %b %Y")}', s['Small']),
        Paragraph('Questions? vendors@lynctel.com | +233558040216', s['Small']),
    ]

    doc.build(story)
    buf.seek(0)
    resp = HttpResponse(buf, content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="lynctel-invoice-{vendor.shop_name}-{year}-{month:02d}.pdf"'
    return resp