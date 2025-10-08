from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Count
from decimal import Decimal
from datetime import datetime, date, timedelta
from .models import Client, Vehicule, Contrat
from .forms import ClientForm, VehiculeForm, ContratSimulationForm
from .api_client import askia_client
from .referentiels import SOUS_CATEGORIES_520
from dateutil.relativedelta import relativedelta
import logging

logger = logging.getLogger(__name__)

# =========================
# Helpers
# =========================
def to_jsonable(value):
    """Convertit récursivement Decimal, date et datetime en str pour JSON/session"""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value
# =========================
# Vues Contrats
# =========================

@login_required
def nouveau_contrat(request):
    """Formulaire principal de création d'un nouveau contrat"""
    context = {
        'title': 'Nouveau Contrat',
        'client_form': ClientForm(),
        'vehicule_form': VehiculeForm(),
        'simulation_form': ContratSimulationForm(),
        'sous_categories_520': SOUS_CATEGORIES_520,
    }
    return render(request, 'contracts/nouveau_contrat.html', context)
@login_required
@require_http_methods(["POST"])
def simuler_tarif(request):
    """Vue HTMX pour simuler un tarif"""
    try:
        # Vérification champs requis
        required_fields = ["categorie", "carburant", "puissance_fiscale",
                           "nombre_places", "marque", "modele"]
        missing = [f for f in required_fields if not request.POST.get(f)]
        if missing:
            return render(request, 'contracts/partials/error.html', {
                'error': f"Champs manquants : {', '.join(missing)}"
            })

        # Date effet
        date_effet_str = request.POST.get('date_effet')
        if not date_effet_str:
            return render(request, 'contracts/partials/error.html', {
                'error': "La date d'effet est obligatoire pour émettre."
            })
        try:
            date_effet = datetime.strptime(date_effet_str, "%Y-%m-%d").date()
        except ValueError:
            return render(request, 'contracts/partials/error.html', {
                'error': "Date d'effet invalide"
            })

        # Gestion catégorie et charge utile
        categorie = request.POST.get('categorie')
        if categorie == '520':  # TPC
            sous_categorie = request.POST.get('sous_categorie') or '000'
            charge_utile = int(request.POST.get('charge_utile') or 3500)
        else:
            sous_categorie = '000'
            charge_utile = 0  # VP sans charge utile significative

        # Données véhicule pour l'API
        vehicule_data = {
            'categorie': categorie,
            'sous_categorie': sous_categorie,
            'carburant': request.POST['carburant'],
            'carrosserie': request.POST.get('carrosserie', '07'),
            'marque': request.POST['marque'],
            'modele': request.POST.get('modele', '').upper(),
            'puissance_fiscale': max(1, int(request.POST.get('puissance_fiscale') or 1)),
            'nombre_places': max(1, int(request.POST.get('nombre_places') or 1)),
            'charge_utile': charge_utile,
            'valeur_neuve': Decimal(request.POST.get('valeur_neuve') or 0),
            'valeur_venale': Decimal(request.POST.get('valeur_venale') or 0),
        }

        duree = int(request.POST.get('duree', 12))

        # Données affichage client & véhicule
        client_data = {
            'prenom': request.POST.get('prenom', '').upper().strip(),
            'nom': request.POST.get('nom', '').upper().strip(),
            'telephone': request.POST.get('telephone', '').strip(),
            'adresse': request.POST.get('adresse', '').upper().strip(),
        }

        vehicule_display = {
            'immatriculation': request.POST.get('immatriculation', '').upper().strip(),
            'marque': request.POST.get('marque_label', ''),
            'modele': request.POST.get('modele', '').upper(),
        }

        # Appel API Askia
        try:
            simulation = askia_client.get_simulation_auto(vehicule_data, duree)
        except Exception as e:
            return render(request, 'contracts/partials/error.html', {
                'error': f"Erreur API Askia : {str(e)}"
            })

        # Normalisation montants
        prime_nette = Decimal(str(simulation['prime_nette']))
        prime_ttc = Decimal(str(simulation['prime_ttc']))
        accessoires = Decimal(str(simulation.get('accessoires', 0)))
        fga = Decimal(str(simulation.get('fga', 0)))
        taxes = Decimal(str(simulation.get('taxes', 0)))
        commission_askia = Decimal(str(simulation.get('commission', 0)))

        # Commission apporteur
        commission = Decimal("0.00")
        net_a_reverser = prime_ttc
        if request.user.role == 'APPORTEUR':
            commission = request.user.calculate_commission(prime_nette)
            net_a_reverser = prime_ttc - commission

        # Sauvegarde session
        request.session['simulation_data'] = to_jsonable({
            'vehicule': vehicule_data,
            'duree': duree,
            'date_effet': date_effet,
            'tarif': {
                'prime_nette': prime_nette,
                'accessoires': accessoires,
                'fga': fga,
                'taxes': taxes,
                'prime_ttc': prime_ttc,
                'commission_askia': commission_askia,
                'commission': commission,
                'net_a_reverser': net_a_reverser,
            },
            'id_saisie': simulation.get('id_saisie'),
            'client': client_data,
            'vehicule_display': vehicule_display
        })

        # Contexte rendu partiel
        context = {
            'simulation': {
                'prime_nette': prime_nette,
                'accessoires': accessoires,
                'fga': fga,
                'taxes': taxes,
                'prime_ttc': prime_ttc,
                'commission': commission_askia,
            },
            'commission': commission,
            'net_a_reverser': net_a_reverser,
            'duree': duree,
            'date_effet': date_effet,
            'is_apporteur': request.user.role == 'APPORTEUR'
        }
        return render(request, 'contracts/partials/simulation_result.html', context)

    except Exception as e:
        return render(request, 'contracts/partials/error.html', {
            'error': str(e)
        })
@login_required
@require_http_methods(["POST"])
@transaction.atomic
def emettre_contrat(request):
    """Émet le contrat à partir de la simulation stockée en session."""
    try:
        simulation_data = request.session.get('simulation_data')
        if not simulation_data:
            msg = "Aucune simulation en cours. Veuillez refaire la simulation."
            if request.headers.get('HX-Request'):
                return render(request, 'contracts/partials/error.html', {'error': msg})
            messages.error(request, msg)
            return redirect('contracts:nouveau_contrat')

        # ==================== CLIENT ====================
        client_data = simulation_data.get('client') or {
            'prenom': request.POST.get('prenom', '').strip(),
            'nom': request.POST.get('nom', '').strip(),
            'telephone': request.POST.get('telephone', '').strip(),
            'adresse': request.POST.get('adresse', '').strip(),
        }

        if not all([client_data.get('prenom'), client_data.get('nom'),
                    client_data.get('telephone'), client_data.get('adresse')]):
            msg = "Veuillez remplir toutes les informations du client."
            if request.headers.get('HX-Request'):
                return render(request, 'contracts/partials/error.html', {'error': msg})
            messages.error(request, msg)
            return redirect('contracts:nouveau_contrat')

        client, _ = Client.objects.get_or_create(
            telephone=client_data['telephone'],
            defaults={
                'prenom': client_data['prenom'],
                'nom': client_data['nom'],
                'adresse': client_data['adresse'],
                'created_by': request.user,
            }
        )

        if not client.code_askia:
            try:
                client.code_askia = askia_client.create_client(client_data)
                client.save(update_fields=['code_askia'])
            except Exception as e:
                msg = f"Erreur création client ASKIA : {str(e)}"
                logger.error("Échec création client | Tel=%s | %s", client_data['telephone'], e)
                if request.headers.get('HX-Request'):
                    return render(request, 'contracts/partials/error.html', {'error': msg})
                messages.error(request, msg)
                return redirect('contracts:nouveau_contrat')

        # ==================== VÉHICULE ====================
        vehicule_data = simulation_data['vehicule']
        vehicule_display = simulation_data.get('vehicule_display', {})
        immat = (vehicule_display.get('immatriculation') or
                 request.POST.get('immatriculation') or '').upper().strip()

        if not immat:
            msg = "Immatriculation manquante."
            if request.headers.get('HX-Request'):
                return render(request, 'contracts/partials/error.html', {'error': msg})
            messages.error(request, msg)
            return redirect('contracts:nouveau_contrat')

        vehicule, _ = Vehicule.objects.get_or_create(
            immatriculation=immat,
            defaults={
                'marque': vehicule_display.get('marque') or request.POST.get('marque') or '',
                'modele': vehicule_display.get('modele') or request.POST.get('modele') or '',
                'categorie': vehicule_data['categorie'],
                'sous_categorie': vehicule_data.get('sous_categorie', ''),
                'charge_utile': vehicule_data.get('charge_utile') or 0,
                'puissance_fiscale': vehicule_data['puissance_fiscale'],
                'nombre_places': vehicule_data['nombre_places'],
                'carburant': vehicule_data['carburant'],
                'valeur_neuve': Decimal(str(vehicule_data.get('valeur_neuve') or 0)),
                'valeur_venale': Decimal(str(vehicule_data.get('valeur_venale') or 0)),
            }
        )

        # ==================== DATES ====================
        date_effet = simulation_data['date_effet']
        if isinstance(date_effet, str):
            date_effet = datetime.strptime(date_effet, "%Y-%m-%d").date()
        if not isinstance(date_effet, date):
            msg = "Date d'effet invalide."
            if request.headers.get('HX-Request'):
                return render(request, 'contracts/partials/error.html', {'error': msg})
            messages.error(request, msg)
            return redirect('contracts:nouveau_contrat')

        duree = int(simulation_data['duree'])
        date_echeance = date_effet + relativedelta(months=duree) - timedelta(days=1)

        # ==================== ÉMISSION ASKIA ====================
        contrat_data = {
            'client_code': client.code_askia,
            'date_effet': date_effet,
            'duree': duree,
            'immatriculation': immat,
            'id_saisie': simulation_data.get('id_saisie'),
            'categorie': vehicule_data['categorie'],
            'sous_categorie': vehicule_data.get('sous_categorie', '000'),
            'carburant': vehicule_data['carburant'],
            'carrosserie': vehicule_data.get('carrosserie', '07'),
            'marque': vehicule_data['marque'],
            'modele': vehicule_data.get('modele', ''),
            'puissance_fiscale': vehicule_data['puissance_fiscale'],
            'nombre_places': vehicule_data['nombre_places'],
            'charge_utile': vehicule_data.get('charge_utile', 0),
            'valeur_neuve': vehicule_data.get('valeur_neuve', 0),
            'valeur_venale': vehicule_data.get('valeur_venale', 0),
        }

        try:
            result = askia_client.create_contrat_auto(contrat_data)
        except Exception as api_error:
            error_msg = str(api_error)

            # Messages personnalisés selon le type d'erreur
            if "contrat en cours" in error_msg.lower() or "contrat existant" in error_msg.lower():
                msg = (
                    f"Un contrat actif existe déjà pour le véhicule {immat}. "
                    f"Vérifiez les contrats existants ou contactez le support."
                )
            elif "timeout" in error_msg.lower() or "délai" in error_msg.lower():
                msg = (
                    "Le serveur ASKIA met trop de temps à répondre. "
                    "Veuillez réessayer dans quelques instants. Si le problème persiste, "
                    "vérifiez d'abord si le contrat n'a pas été créé dans la liste des contrats."
                )
            elif "réseau" in error_msg.lower() or "network" in error_msg.lower():
                msg = (
                    "Problème de connexion au serveur ASKIA. "
                    "Vérifiez votre connexion internet et réessayez."
                )
            else:
                msg = f"Erreur lors de l'émission du contrat : {error_msg}"

            logger.error(
                "Échec émission contrat | Client=%s | Immat=%s | Erreur=%s",
                client.code_askia, immat, error_msg
            )

            if request.headers.get('HX-Request'):
                return render(request, 'contracts/partials/error.html', {'error': msg})
            messages.error(request, msg)
            return redirect('contracts:nouveau_contrat')

        numero_police = result.get('numero_police')
        numero_facture = result.get('numero_facture')

        if not numero_police:
            msg = "Échec émission : pas de numéro de police ASKIA."
            logger.error("Pas de numéro police | Réponse=%s", result)
            if request.headers.get('HX-Request'):
                return render(request, 'contracts/partials/error.html', {'error': msg})
            messages.error(request, msg)
            return redirect('contracts:nouveau_contrat')

        # ==================== DOCUMENTS ====================
        attestation = result.get('attestation', '')
        carte_brune = result.get('carte_brune', '')

        if not (attestation or carte_brune):
            logger.warning(
                "Contrat émis sans documents | Police=%s | Facture=%s",
                numero_police, numero_facture
            )

        # ==================== PERSISTANCE LOCALE ====================
        tarif = simulation_data['tarif']
        contrat = Contrat.objects.create(
            client=client,
            vehicule=vehicule,
            apporteur=request.user,
            numero_police=numero_police,
            duree=duree,
            date_effet=date_effet,
            date_echeance=date_echeance,
            prime_nette=Decimal(str(tarif['prime_nette'])),
            accessoires=Decimal(str(tarif['accessoires'])),
            fga=Decimal(str(tarif['fga'])),
            taxes=Decimal(str(tarif['taxes'])),
            prime_ttc=Decimal(str(tarif['prime_ttc'])),
            commission_askia=Decimal(str(tarif.get('commission_askia', 0))),
            status='EMIS',
            id_saisie_askia=simulation_data.get('id_saisie'),
            emis_at=timezone.now(),
            askia_response=result.get('raw_response', simulation_data),
            link_attestation=attestation,
            link_carte_brune=carte_brune,
        )

        # Note: commission_apporteur sera calculée automatiquement par le signal pre_save

        # Nettoyage session
        request.session.pop('simulation_data', None)

        logger.info(
            "Contrat créé avec succès | Police=%s | Client=%s | Apporteur=%s",
            numero_police, client.nom_complet, request.user.username
        )

        # ==================== RÉPONSE ====================
        if request.headers.get('HX-Request'):
            return render(request, 'contracts/partials/emission_success.html', {
                'contrat': contrat,
                'success_message': f"Contrat {contrat.numero_police} émis avec succès!"
            })

        messages.success(request, f"Contrat {contrat.numero_police} émis avec succès!")
        return redirect('contracts:detail_contrat', pk=contrat.pk)

    except Exception as e:
        msg = f"Erreur inattendue lors de l'émission : {str(e)}"
        logger.error("Erreur inattendue émission contrat | %s", e, exc_info=True)

        if request.headers.get('HX-Request'):
            return render(request, 'contracts/partials/error.html', {'error': msg})
        messages.error(request, msg)
        return redirect('contracts:nouveau_contrat')
@login_required
def detail_contrat(request, pk):
    """Vue détaillée d'un contrat"""
    contrat = get_object_or_404(Contrat, pk=pk)

    # Vérifier les permissions
    if request.user.role == 'APPORTEUR' and contrat.apporteur != request.user:
        messages.error(request, "Vous n'avez pas accès à ce contrat.")
        return redirect('dashboard:home')

    context = {
        'contrat': contrat,
        'title': f'Contrat {contrat.numero_police}'
    }
    return render(request, 'contracts/detail_contrat.html', context)
@require_http_methods(["GET"])
def check_immatriculation(request):
    immat = request.GET.get('immatriculation', '').strip().upper()

    if not immat:
        return HttpResponse("")  # Vide si pas de valeur

    # Vérifier si l'immatriculation existe déjà
    exists = Vehicule.objects.filter(immatriculation=immat).exists()

    if exists:
        return HttpResponse(
            '<span class="text-red-400 text-xs">'
            '<i class="fas fa-times-circle mr-1"></i>'
            'Cette immatriculation existe déjà'
            '</span>'
        )

    # Valider le format avec le validateur du modèle
    try:
        from django.core.exceptions import ValidationError
        validator = Vehicule.immat_validators[0]
        validator(immat)

        return HttpResponse(
            '<span class="text-green-500 text-xs">'
            '<i class="fas fa-check-circle mr-1"></i>'
            'Format valide'
            '</span>'
        )
    except ValidationError:
        return HttpResponse(
            '<span class="text-orange-400 text-xs">'
            '<i class="fas fa-exclamation-triangle mr-1"></i>'
            'Format invalide'
            '</span>'
        )
@login_required
@require_http_methods(["GET"])
def check_client(request):
    """Vérifie si un client existe par téléphone"""
    telephone = request.GET.get('client_telephone', '')

    if not telephone:
        return JsonResponse({'exists': False})

    try:
        client = Client.objects.get(telephone=telephone)
        return render(request, 'contracts/partials/client_exists.html', {
            'client': client
        })
    except Client.DoesNotExist:
        return JsonResponse({'exists': False})
@login_required
@require_http_methods(["GET"])
def load_sous_categories(request):
    """Charge les sous-catégories pour une catégorie donnée"""
    categorie = request.GET.get('categorie')

    if categorie == '520':
        # TPC - sous-catégories obligatoires
        return render(request, 'contracts/partials/sous_categories.html', {
            'sous_categories': SOUS_CATEGORIES_520,
            'required': True
        })

    # Autres catégories - pas de sous-catégorie
    return render(request, 'contracts/partials/sous_categories.html', {
        'sous_categories': [],
        'required': False
    })
@login_required
def telecharger_documents(request, pk):
    """Télécharge l'attestation d'assurance d'un contrat"""
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    import io
    from datetime import datetime

    contrat = get_object_or_404(Contrat, pk=pk)

    # Vérifier les permissions
    if request.user.role == 'APPORTEUR' and contrat.apporteur != request.user:
        messages.error(request, "Vous n'avez pas accès à ce contrat.")
        return redirect('dashboard:home')

    # Créer le buffer
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm
    )

    # Styles
    styles = getSampleStyleSheet()

    style_titre = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )

    style_sous_titre = ParagraphStyle(
        'CustomSubTitle',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#3b82f6'),
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )

    style_section = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading3'],
        fontSize=12,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=10,
        fontName='Helvetica-Bold',
        backColor=colors.HexColor('#eff6ff')
    )

    style_normal = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        leading=14
    )

    # Fonction helper pour formater les dates
    def format_date(date_obj):
        """Formate une date ou retourne 'Non définie' si None"""
        return date_obj.strftime('%d/%m/%Y') if date_obj else 'Non définie'

    # Fonction helper pour formater les nombres
    def format_montant(montant):
        """Formate un montant ou retourne '0' si None"""
        if montant is None:
            return '0'
        return f"{montant:,.0f}".replace(',', ' ')

    # Contenu du document
    elements = []

    elements.append(Paragraph("BWHITE DIGITAL", style_titre))
    elements.append(Paragraph("Detail du contrat", style_sous_titre))
    elements.append(Spacer(1, 0.5 * cm))

    # Numéro de police
    data_police = [[Paragraph(f"<b>Police N°:</b> {contrat.numero_police or 'N/A'}", style_normal)]]
    table_police = Table(data_police, colWidths=[16 * cm])
    table_police.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#dbeafe')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1e40af')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#3b82f6'))
    ]))
    elements.append(table_police)
    elements.append(Spacer(1, 0.8 * cm))

    # Section Assuré
    elements.append(Paragraph("ASSURÉ", style_section))
    elements.append(Spacer(1, 0.3 * cm))

    data_assure = [
        ['Nom complet:', contrat.client.nom_complet if contrat.client else 'Non renseigné'],
        ['Téléphone:', contrat.client.telephone if contrat.client else 'Non renseigné'],
        ['Adresse:', getattr(contrat.client, 'adresse', 'Non renseignée') if contrat.client else 'Non renseignée']
    ]

    table_assure = Table(data_assure, colWidths=[5 * cm, 11 * cm])
    table_assure.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#475569')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0'))
    ]))
    elements.append(table_assure)
    elements.append(Spacer(1, 0.8 * cm))

    # Section Véhicule
    elements.append(Paragraph("VÉHICULE ASSURÉ", style_section))
    elements.append(Spacer(1, 0.3 * cm))

    vehicule = contrat.vehicule
    data_vehicule = [
        ['Immatriculation:', vehicule.immatriculation if vehicule else 'N/A'],
        ['Marque:', vehicule.get_marque_display() if vehicule and hasattr(vehicule, 'get_marque_display') else 'N/A'],
        ['Modèle:', vehicule.modele if vehicule else 'N/A'],
        ['Année:', str(getattr(vehicule, 'annee', 'N/A')) if vehicule else 'N/A'],
        ['Usage:', vehicule.get_usage_display() if vehicule and hasattr(vehicule, 'get_usage_display') else 'Privé']
    ]

    table_vehicule = Table(data_vehicule, colWidths=[5 * cm, 11 * cm])
    table_vehicule.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#475569')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0'))
    ]))
    elements.append(table_vehicule)
    elements.append(Spacer(1, 0.8 * cm))

    # Section Garanties
    elements.append(Paragraph("PÉRIODE DE GARANTIE", style_section))
    elements.append(Spacer(1, 0.3 * cm))

    data_garantie = [
        ['Date d\'effet:', format_date(contrat.date_effet)],
        ['Date d\'échéance:', format_date(contrat.date_echeance)],
        ['Type de garantie:', contrat.get_type_garantie_display() if hasattr(contrat,
                                                                             'get_type_garantie_display') else 'Responsabilité Civile']
    ]

    table_garantie = Table(data_garantie, colWidths=[5 * cm, 11 * cm])
    table_garantie.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#475569')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0'))
    ]))
    elements.append(table_garantie)
    elements.append(Spacer(1, 0.8 * cm))

    # Prime en évidence
    prime_text = f"<b>PRIME TTC:</b> {format_montant(contrat.prime_ttc)} FCFA"
    data_prime = [[Paragraph(prime_text, style_normal)]]
    table_prime = Table(data_prime, colWidths=[16 * cm])
    table_prime.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#dcfce7')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#166534')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#22c55e'))
    ]))
    elements.append(table_prime)
    elements.append(Spacer(1, 1.5 * cm))

    # Pied de page
    style_footer = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#64748b'),
        alignment=TA_CENTER
    )

    elements.append(Paragraph(
        f"Document généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
        style_footer
    ))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(Paragraph(
        "Ce document est valable uniquement si toutes les informations sont exactes et la prime payée.",
        style_footer
    ))

    # Générer le PDF
    doc.build(elements)

    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="attestation_{contrat.numero_police or "contrat"}.pdf"'

    return response
@login_required
def liste_contrats(request):
    """Liste unifiée des contrats valides (émis + avec doc)"""
    contrats = Contrat.objects.emis_avec_doc().select_related("client", "vehicule", "apporteur")

    if request.user.role == "APPORTEUR":
        contrats = contrats.filter(apporteur=request.user)

    statut = request.GET.get("status")
    if statut:
        contrats = contrats.filter(status=statut)

    date_debut = request.GET.get("date_debut")
    if date_debut:
        contrats = contrats.filter(date_effet__gte=date_debut)

    date_fin = request.GET.get("date_fin")
    if date_fin:
        contrats = contrats.filter(date_effet__lte=date_fin)

    search_query = request.GET.get("search", "").strip()
    if search_query:
        contrats = contrats.filter(
            Q(vehicule__immatriculation__icontains=search_query) |
            Q(client__nom__icontains=search_query) |
            Q(client__prenom__icontains=search_query) |
            Q(numero_police__icontains=search_query)
        )

    apporteur_id = request.GET.get("apporteur")
    if request.user.role == "ADMIN" and apporteur_id:
        contrats = contrats.filter(apporteur_id=apporteur_id)

    contrats = contrats.order_by("-created_at")
    paginator = Paginator(contrats, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "contracts/liste_contrats.html", {
        "title": "Liste des Contrats",
        "contrats": page_obj,
        "search_query": search_query,
        "status_filter": statut,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "apporteur_filter": apporteur_id,
    })
@login_required
def liste_clients(request):
    """Liste des clients avec nb de contrats valides"""
    clients = Client.objects.annotate(
        nb_contrats=Count(
            "contrats",
            filter=Q(contrats__status="EMIS") &
                   (Q(contrats__link_attestation__isnull=False) | Q(contrats__link_carte_brune__isnull=False))
        )
    )

    if request.user.is_apporteur:
        clients = clients.filter(contrats__apporteur=request.user).distinct()

    search_query = request.GET.get("search", "").strip()
    if search_query:
        clients = clients.filter(
            Q(nom__icontains=search_query) |
            Q(prenom__icontains=search_query) |
            Q(telephone__icontains=search_query) |
            Q(adresse__icontains=search_query)
        )

    clients = clients.order_by("nom", "prenom")
    paginator = Paginator(clients, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "contracts/liste_clients.html", {
        "title": "Liste des Clients",
        "clients": page_obj,
        "search_query": search_query,
    })
@login_required
def detail_client(request, pk):
    """Fiche client avec ses contrats valides uniquement"""
    client = get_object_or_404(Client, pk=pk)

    if request.user.is_apporteur:
        contrats = Contrat.objects.emis_avec_doc().filter(client=client, apporteur=request.user)
    else:
        contrats = Contrat.objects.emis_avec_doc().filter(client=client)

    contrats = contrats.select_related("vehicule", "apporteur").order_by("-created_at")

    return render(request, "contracts/detail_client.html", {
        "title": f"Fiche Client - {client.nom_complet}",
        "client": client,
        "contrats": contrats,
    })