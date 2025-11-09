from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from datetime import datetime, date, timedelta, timezone
from contracts.models import Contrat
@login_required
def telecharger_documents(request, pk):
    """Génère un PDF de synthèse locale."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    import io as _io

    contrat = get_object_or_404(Contrat, pk=pk)
    if getattr(request.user, "role", "") == "APPORTEUR" and contrat.apporteur != request.user:
        messages.error(request, "Vous n'avez pas accès à ce contrat.")
        return redirect("dashboard:home")

    def format_date(d: date | None) -> str:
        return d.strftime("%d/%m/%Y") if d else "Non définie"

    def format_montant(m: Decimal | None) -> str:
        if m is None:
            return "0"
        s = f"{m:,.0f}".replace(",", " ")
        return s

    buffer = _io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
    )
    styles = getSampleStyleSheet()
    style_titre = ParagraphStyle(
        "CustomTitle", parent=styles["Heading1"], fontSize=22,
        textColor=colors.HexColor("#1e40af"), spaceAfter=30, alignment=TA_CENTER, fontName="Helvetica-Bold"
    )
    style_sous_titre = ParagraphStyle(
        "CustomSubTitle", parent=styles["Heading2"], fontSize=16,
        textColor=colors.HexColor("#3b82f6"), spaceAfter=20, alignment=TA_CENTER, fontName="Helvetica-Bold"
    )
    style_section = ParagraphStyle(
        "SectionTitle", parent=styles["Heading3"], fontSize=12,
        textColor=colors.HexColor("#1e40af"), spaceAfter=10, fontName="Helvetica-Bold",
        backColor=colors.HexColor("#eff6ff"), padding=5
    )
    style_normal = ParagraphStyle("CustomNormal", parent=styles["Normal"], fontSize=10, leading=14)
    style_footer = ParagraphStyle(
        "Footer", parent=styles["Normal"], fontSize=8,
        textColor=colors.HexColor("#64748b"), alignment=TA_CENTER
    )

    elements = [
        Paragraph("BWHITE DIGITAL", style_titre),
        Paragraph("Détail du contrat", style_sous_titre),
        Spacer(1, 0.5 * cm),
    ]

    # En-tête police
    data_police = [[Paragraph(f"<b>Police N° :</b> {contrat.numero_police or 'N/A'}", style_normal)]]
    table_police = Table(data_police, colWidths=[17 * cm])
    table_police.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#dbeafe")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1e40af")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#3b82f6")),
    ]))
    elements += [table_police, Spacer(1, 0.8 * cm)]

    # Assuré
    elements.append(Paragraph("ASSURÉ", style_section))
    elements.append(Spacer(1, 0.3 * cm))
    data_assure = [
        ["Nom complet:", contrat.client.nom_complet if contrat.client else "Non renseigné"],
        ["Téléphone:", contrat.client.telephone if contrat.client else "Non renseigné"],
        ["Adresse:", getattr(contrat.client, "adresse", "Non renseignée") if contrat.client else "Non renseignée"],
    ]
    table_assure = Table(data_assure, colWidths=[5 * cm, 12 * cm])
    table_assure.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements += [table_assure, Spacer(1, 0.8 * cm)]

    # Véhicule
    elements.append(Paragraph("VÉHICULE ASSURÉ", style_section))
    elements.append(Spacer(1, 0.3 * cm))
    v = contrat.vehicule
    data_vehicule = [
        ["Immatriculation:", v.immatriculation_formatted if v else "N/A"],
        ["Marque:", v.get_marque_display() if v and hasattr(v, "get_marque_display") else "N/A"],
        ["Modèle:", v.modele if v else "N/A"],
        ["Catégorie:", v.get_categorie_display() if v else "N/A"],
        ["Puissance:", f"{v.puissance_fiscale} CV" if v else "N/A"],
        ["Places:", v.nombre_places if v else "N/A"],
    ]
    table_vehicule = Table(data_vehicule, colWidths=[5 * cm, 12 * cm])
    table_vehicule.setStyle(table_assure.getStyle())
    elements += [table_vehicule, Spacer(1, 0.8 * cm)]

    # Période
    elements.append(Paragraph("PÉRIODE DE GARANTIE", style_section))
    elements.append(Spacer(1, 0.3 * cm))
    data_garantie = [
        ["Date d'effet:", format_date(contrat.date_effet)],
        ["Date d'échéance:", format_date(contrat.date_echeance)],
        ["Durée:", f"{contrat.duree} mois"],
        ["Type de garantie:", contrat.type_garantie],
    ]
    table_garantie = Table(data_garantie, colWidths=[5 * cm, 12 * cm])
    table_garantie.setStyle(table_assure.getStyle())
    elements += [table_garantie, Spacer(1, 0.8 * cm)]

    # Prime TTC
    prime_text = f"<b>PRIME TTC :</b> {format_montant(contrat.prime_ttc)} FCFA"
    table_prime = Table([[Paragraph(prime_text, style_normal)]], colWidths=[17 * cm])
    table_prime.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#dcfce7")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#166534")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#22c55e")),
    ]))
    elements += [table_prime, Spacer(1, 1.5 * cm)]

    now_str = timezone.localtime().strftime("%d/%m/%Y à %H:%M")
    elements.append(Paragraph(f"Document généré le {now_str}", style_footer))
    elements.append(Paragraph("Valable si les informations sont exactes et la prime payée.", style_footer))

    doc.build(elements)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    filename = f'attestation_{contrat.numero_police or "contrat"}.pdf'
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response