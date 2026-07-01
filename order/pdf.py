"""
order/pdf.py

Generates a PDF receipt for a paid Order using reportlab (already in
requirements.txt). Called by the order_receipt view below.

File location: order/pdf.py
"""
from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)


# ── BRAND COLOURS ──────────────────────────────────────────
NAVY  = colors.HexColor('#0F1B2D')
GOLD  = colors.HexColor('#F5A623')
LIGHT = colors.HexColor('#FAFAF7')
GREY  = colors.HexColor('#6B7280')


def generate_order_receipt_pdf(order):
    """
    Returns an HttpResponse with a downloadable PDF receipt.
    order must have .items, .customer, and the standard Order fields.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm,
    )

    styles = getSampleStyleSheet()
    story  = []

    # ── Header ────────────────────────────────────────────
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Normal'],
        fontSize=22,
        textColor=NAVY,
        fontName='Helvetica-Bold',
        spaceAfter=2*mm,
    )
    sub_style = ParagraphStyle(
        'Sub',
        parent=styles['Normal'],
        fontSize=10,
        textColor=GREY,
        spaceAfter=1*mm,
    )
    label_style = ParagraphStyle(
        'Label',
        parent=styles['Normal'],
        fontSize=9,
        textColor=GREY,
    )
    value_style = ParagraphStyle(
        'Value',
        parent=styles['Normal'],
        fontSize=9,
        textColor=NAVY,
        fontName='Helvetica-Bold',
    )

    story.append(Paragraph('Lynctel', title_style))
    story.append(Paragraph('Quality Products Delivered in Ghana 🇬🇭', sub_style))
    story.append(HRFlowable(width='100%', thickness=2, color=GOLD, spaceAfter=5*mm))

    # ── Order meta ────────────────────────────────────────
    meta_data = [
        ['Order Reference', order.order_ref,
         'Date', order.created_at.strftime('%d %b %Y, %H:%M')],
        ['Customer',
         order.customer.get_full_name() or order.customer.phone or '—',
         'Payment', order.get_payment_status_display()],
        ['Delivery Phone', order.delivery_phone,
         'Status', order.get_status_display()],
        ['Delivery Address',
         f"{order.delivery_address}, {order.delivery_city}", '', ''],
    ]

    meta_table = Table(meta_data, colWidths=[35*mm, 60*mm, 30*mm, 45*mm])
    meta_table.setStyle(TableStyle([
        ('FONTNAME',    (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME',    (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, -1), 9),
        ('TEXTCOLOR',   (0, 0), (0, -1), GREY),
        ('TEXTCOLOR',   (2, 0), (2, -1), GREY),
        ('TEXTCOLOR',   (1, 0), (1, -1), NAVY),
        ('TEXTCOLOR',   (3, 0), (3, -1), NAVY),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 8*mm))

    # ── Items table ───────────────────────────────────────
    story.append(Paragraph('Order Items', ParagraphStyle(
        'SectionHead', parent=styles['Normal'],
        fontSize=11, textColor=NAVY, fontName='Helvetica-Bold', spaceAfter=3*mm
    )))

    items_header = [['Product', 'Qty', 'Unit Price', 'Subtotal']]
    items_rows   = []
    for item in order.items.all():
        items_rows.append([
            item.product_name,
            str(item.quantity),
            f'GHS {item.unit_price}',
            f'GHS {item.subtotal}',
        ])

    items_data = items_header + items_rows
    items_table = Table(items_data, colWidths=[90*mm, 15*mm, 35*mm, 30*mm])
    items_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND',  (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR',   (0, 0), (-1, 0), colors.white),
        ('FONTNAME',    (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',    (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        ('TOPPADDING',    (0, 0), (-1, 0), 5),
        # Data rows
        ('FONTSIZE',    (0, 1), (-1, -1), 9),
        ('TEXTCOLOR',   (0, 1), (-1, -1), NAVY),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('TOPPADDING',    (0, 1), (-1, -1), 4),
        ('ALIGN',       (1, 0), (-1, -1), 'RIGHT'),
        ('GRID',        (0, 0), (-1, -1), 0.25, colors.HexColor('#E5E7EB')),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 5*mm))

    # ── Totals ────────────────────────────────────────────
    totals_data = [
        ['', 'Subtotal',     f'GHS {order.subtotal}'],
        ['', 'Delivery fee', f'GHS {order.delivery_fee}'],
        ['', 'TOTAL',        f'GHS {order.total_amount}'],
    ]
    totals_table = Table(totals_data, colWidths=[90*mm, 40*mm, 40*mm])
    totals_table.setStyle(TableStyle([
        ('FONTSIZE',    (0, 0), (-1, -1), 9),
        ('TEXTCOLOR',   (1, 0), (1, -2), GREY),
        ('TEXTCOLOR',   (2, 0), (2, -2), NAVY),
        ('FONTNAME',    (1, 2), (2, 2),  'Helvetica-Bold'),
        ('TEXTCOLOR',   (1, 2), (2, 2),  NAVY),
        ('FONTSIZE',    (1, 2), (2, 2),  11),
        ('LINEABOVE',   (1, 2), (2, 2),  1, NAVY),
        ('ALIGN',       (1, 0), (-1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 10*mm))

    # ── Footer ────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=1, color=GREY, spaceAfter=4*mm))
    story.append(Paragraph(
        'Thank you for shopping with Lynctel! Questions? WhatsApp +233 55 804 0216',
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8,
                       textColor=GREY, alignment=1)
    ))
    story.append(Paragraph(
        'lynctel.up.railway.app',
        ParagraphStyle('FooterLink', parent=styles['Normal'], fontSize=8,
                       textColor=GOLD, alignment=1)
    ))

    doc.build(story)

    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="Lynctel-Receipt-{order.order_ref}.pdf"'
    )
    return response