from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime, date, timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from dateutil.relativedelta import relativedelta
from .api_client import askia_client
from .forms import ClientForm, VehiculeForm, ContratSimulationForm
from .models import Client, Vehicule, Contrat
from .referentiels import SOUS_CATEGORIES_520, SOUS_CATEGORIES_550

logger = logging.getLogger(__name__)
# =========================
# Helpers
# =========================
def to_jsonable(value):
    """Convertit récursivement Decimal, date et datetime en str pour JSON/session."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value
def _is_hx(request) -> bool:
    """True si la requête provient d'HTMX."""
    return request.headers.get("HX-Request") == "true"


def _render_error(request, message: str, redirect_name: str = "contracts:nouveau_contrat"):
    """Rendu d'une erreur (partiel HTMX ou message + redirect)."""
    logger.warning("Erreur rendue à l'utilisateur : %s", message)  # Log de l'erreur
    if _is_hx(request):
        return render(request, "contracts/partials/error.html", {"error": message})
    messages.error(request, message)
    return redirect(redirect_name)
# =========================
# Vues Contrats
# =========================
@login_required
def nouveau_contrat(request):
    """Formulaire principal de création d'un nouveau contrat."""
    context = {
        "title": "Nouveau Contrat",
        "client_form": ClientForm(),
        "vehicule_form": VehiculeForm(),
        "simulation_form": ContratSimulationForm(),
        "sous_categories_520": SOUS_CATEGORIES_520,
        "sous_categories_550": SOUS_CATEGORIES_550,  # AJOUTÉ
    }
    return render(request, "contracts/nouveau_contrat.html", context)
@login_required
@require_http_methods(["POST"])
def simuler_tarif(request):
    """Vue HTMX pour simuler un tarif automobile."""
    try:
        # Champs requis côté formulaire
        required_fields = ["categorie", "carburant", "puissance_fiscale",
                           "nombre_places", "marque", "modele"]
        missing = [f for f in required_fields if not request.POST.get(f)]
        if missing:
            return _render_error(request, f"Champs manquants : {', '.join(missing)}")

        date_effet_str = request.POST.get("date_effet")
        if not date_effet_str:
            return _render_error(request, "La date d'effet est obligatoire pour émettre.")

        try:
            date_effet = datetime.strptime(date_effet_str, "%Y-%m-%d").date()
        except ValueError:
            return _render_error(request, "Date d'effet invalide")

        today = datetime.now().date()
        if date_effet < today:
            return _render_error(
                request,
                f"La date d'effet ne peut pas être dans le passé "
                f"(fournie: {date_effet.strftime('%d/%m/%Y')}, "
                f"aujourd'hui: {today.strftime('%d/%m/%Y')})"
            )

        # Catégorie & champs dépendants
        categorie = request.POST.get("categorie")
        if categorie == "520":  # TPC
            sous_categorie = request.POST.get("sous_categorie") or "002"
            charge_utile = int(request.POST.get("charge_utile") or 3500)
        elif categorie == "550":  # 2 ROUES
            sous_categorie = request.POST.get("sous_categorie") or "009"
            charge_utile = None
        else:  # VP
            sous_categorie = "000"
            charge_utile = None

        vehicule_data = {
            "categorie": categorie,
            "sous_categorie": sous_categorie,
            "carburant": request.POST["carburant"],
            "carrosserie": request.POST.get("carrosserie", "07"),
            "marque": request.POST["marque"],
            "modele": (request.POST.get("modele") or "").upper(),
            "puissance_fiscale": max(1, int(request.POST.get("puissance_fiscale") or 1)),
            "nombre_places": max(1, int(request.POST.get("nombre_places") or 1)),
            "valeur_neuve": Decimal(request.POST.get("valeur_neuve") or 0),
            "valeur_venale": Decimal(request.POST.get("valeur_venale") or 0),
            "recour": int(request.POST.get("recour", 0)),
            "avr": int(request.POST.get("avr", 0)),
            "vol": int(request.POST.get("vol", 0)),
            "inc": int(request.POST.get("inc", 0)),
            "pt": int(request.POST.get("pt", 0)),
            "gb": int(request.POST.get("gb", 0)),
            "renv": int(request.POST.get("renv", 0)),
        }
        if charge_utile is not None:
            vehicule_data["charge_utile"] = charge_utile

        duree = int(request.POST.get("duree", 12))

        client_data = {
            "prenom": (request.POST.get("prenom") or "").upper().strip(),
            "nom": (request.POST.get("nom") or "").upper().strip(),
            "telephone": (request.POST.get("telephone") or "").strip(),
            "adresse": (request.POST.get("adresse") or "").upper().strip(),
        }
        vehicule_display = {
            "immatriculation": (request.POST.get("immatriculation") or "").upper().strip(),
            "marque": request.POST.get("marque_label", ""),
            "modele": (request.POST.get("modele") or "").upper(),
        }

        # Appel Askia simulation
        try:
            simulation = askia_client.get_simulation_auto(vehicule_data, duree)
        except Exception as e:
            logger.error("Erreur simulation Askia | %s", str(e), exc_info=True)
            return _render_error(request, f"Erreur API Askia : {str(e)}")

        # ========================================================================
        # CORRECTION : NOUVELLE LOGIQUE DE COMMISSION
        # ========================================================================
        prime_nette = Decimal(str(simulation["prime_nette"]))
        prime_ttc = Decimal(str(simulation["prime_ttc"]))
        accessoires = Decimal(str(simulation.get("accessoires", 0)))
        fga = Decimal(str(simulation.get("fga", 0)))
        taxes = Decimal(str(simulation.get("taxes", 0)))

        # Constantes de commission
        ASKIA_TAUX = Decimal("0.20")
        ASKIA_ACCESSOIRES = Decimal("3000")

        # 1. Commission Askia (Total pour BWHITE)
        commission_askia_bwhite = (prime_nette * ASKIA_TAUX) + ASKIA_ACCESSOIRES

        # 2. Commission Apporteur
        commission_apporteur = Decimal("0.00")
        if request.user.role == 'APPORTEUR':
            if request.user.grade == 'PLATINE':
                TAUX_APP = Decimal("0.18")
                FIXE_APP = Decimal("2000")
                commission_apporteur = (prime_nette * TAUX_APP) + FIXE_APP
            elif request.user.grade == 'FREEMIUM':
                TAUX_APP = Decimal("0.10")
                FIXE_APP = Decimal("1800")
                commission_apporteur = (prime_nette * TAUX_APP) + FIXE_APP

        # 3. Commission BWHITE (Profit)
        commission_bwhite_profit = commission_askia_bwhite - commission_apporteur

        # 4. Net à reverser (ce que BWHITE doit à Askia)
        net_a_reverser_askia = prime_ttc - commission_askia_bwhite
        # ========================================================================

        # Stockage session
        request.session["simulation_data"] = to_jsonable({
            "vehicule": vehicule_data,
            "duree": duree,
            "date_effet": date_effet,
            "tarif": {
                "prime_nette": prime_nette,
                "accessoires": accessoires,
                "fga": fga,
                "taxes": taxes,
                "prime_ttc": prime_ttc,
                "commission_askia": commission_askia_bwhite,  # Total BWHITE
                "commission_apporteur": commission_apporteur,  # Dû à l'apporteur
                "commission_bwhite": commission_bwhite_profit,  # Profit BWHITE
                "net_a_reverser": net_a_reverser_askia,  # Dû à Askia
            },
            "id_saisie": simulation.get("id_saisie"),
            "client": client_data,
            "vehicule_display": vehicule_display,
        })

        # Rendu partiel
        context = {
            "simulation": {
                "prime_nette": prime_nette,
                "accessoires": accessoires,
                "fga": fga,
                "taxes": taxes,
                "prime_ttc": prime_ttc,
                "commission": simulation.get("commission", 0),  # Commission API originale (pour info)
            },
            "commission": commission_apporteur,  # Ce que l'apporteur voit
            "net_a_reverser": net_a_reverser_askia,  # Ce que BWHITE doit à Askia
            "duree": duree,
            "date_effet": date_effet,
            "is_apporteur": request.user.role == "APPORTEUR",
        }
        return render(request, "contracts/partials/simulation_result.html", context)

    except Exception as e:
        logger.error("Erreur inattendue simuler_tarif | %s", str(e), exc_info=True)
        return _render_error(request, f"Erreur inattendue: {str(e)}")
@login_required
@require_http_methods(["POST"])
@transaction.atomic
def emettre_contrat(request):
    """Émet le contrat à partir de la simulation stockée en session."""
    try:
        simulation_data = request.session.get("simulation_data")
        if not simulation_data:
            return _render_error(request, "Aucune simulation en cours. Veuillez refaire la simulation.")

        # ---------- CLIENT ----------
        client_data = simulation_data.get("client")
        if not all([client_data.get("prenom"), client_data.get("nom"),
                    client_data.get("telephone"), client_data.get("adresse")]):
            return _render_error(request, "Veuillez remplir toutes les informations du client.")

        client, _ = Client.objects.get_or_create(
            telephone=client_data["telephone"],
            defaults={
                "prenom": client_data["prenom"],
                "nom": client_data["nom"],
                "adresse": client_data["adresse"],
                "created_by": request.user,
            },
        )
        if not client.code_askia:
            try:
                client.code_askia = askia_client.create_client(client_data)
                client.save(update_fields=["code_askia"])
            except Exception as e:
                logger.error("Échec création client | Tel=%s | %s", client_data["telephone"], e)
                return _render_error(request, f"Erreur création client ASKIA : {str(e)}")

        # ---------- VÉHICULE ----------
        vehicule_data = simulation_data["vehicule"]
        vehicule_display = simulation_data.get("vehicule_display", {})
        immat = vehicule_display.get("immatriculation")
        if not immat:
            return _render_error(request, "Immatriculation manquante.")

        vehicule, _ = Vehicule.objects.get_or_create(
            immatriculation=immat,  # Le modèle clean() gère la normalisation
            defaults={
                "marque": vehicule_data["marque"],
                "modele": vehicule_data["modele"],
                "categorie": vehicule_data["categorie"],
                "sous_categorie": vehicule_data.get("sous_categorie"),
                "charge_utile": vehicule_data.get("charge_utile") or 0,
                "puissance_fiscale": vehicule_data["puissance_fiscale"],
                "nombre_places": vehicule_data["nombre_places"],
                "carburant": vehicule_data["carburant"],
                "valeur_neuve": Decimal(str(vehicule_data.get("valeur_neuve") or 0)),
                "valeur_venale": Decimal(str(vehicule_data.get("valeur_venale") or 0)),
            },
        )

        # ---------- DATES ----------
        date_effet = simulation_data["date_effet"]
        if isinstance(date_effet, str):
            date_effet = datetime.strptime(date_effet, "%Y-%m-%d").date()
        if not isinstance(date_effet, date):
            return _render_error(request, "Date d'effet invalide.")

        duree = int(simulation_data["duree"])
        date_echeance = date_effet + relativedelta(months=duree) - timedelta(days=1)

        # ---------- ÉMISSION ASKIA ----------
        contrat_data = {
            "client_code": client.code_askia,
            "date_effet": date_effet,
            "duree": duree,
            "immatriculation": immat,
            "id_saisie": simulation_data.get("id_saisie"),
            **vehicule_data  # Transmet toutes les données véhicule
        }

        try:
            result = askia_client.create_contrat_auto(contrat_data)
        except Exception as api_error:
            # ... (gestion des erreurs
            error_msg = str(api_error)
            if "contrat en cours" in error_msg.lower() or "contrat existant" in error_msg.lower():
                msg = (f"Un contrat actif existe déjà pour le véhicule {immat}. "
                       f"Vérifiez les contrats existants ou contactez le support.")
            elif any(k in error_msg.lower() for k in ["timeout", "délai", "attente"]):
                msg = ("Le serveur ASKIA met trop de temps à répondre. Réessayez. "
                       "Vérifiez d'abord si le contrat n'a pas été créé dans la liste des contrats.")
            elif any(k in error_msg.lower() for k in ["réseau", "network"]):
                msg = "Problème de connexion au serveur ASKIA. Vérifiez votre connexion et réessayez."
            else:
                msg = f"Erreur lors de l'émission du contrat : {error_msg}"
            logger.error("Échec émission contrat | Client=%s | Immat=%s | Erreur=%s",
                         client.code_askia, immat, error_msg)
            return _render_error(request, msg)

        numero_police = result.get("numero_police")
        numero_facture = result.get("numero_facture")
        if not numero_police:
            return _render_error(request, "Échec émission : pas de numéro de police ASKIA.")

        # ---------- DOCUMENTS ----------
        attestation = result.get("attestation", "")
        carte_brune = result.get("carte_brune", "")
        if not (attestation or carte_brune):
            logger.warning(
                "⚠️ Contrat émis sans documents | Police=%s | Facture=%s",
                numero_police, numero_facture
            )

        # ---------- PERSISTANCE LOCALE ----------
        tarif = simulation_data["tarif"]
        contrat = Contrat.objects.create(
            client=client,
            vehicule=vehicule,
            apporteur=request.user,
            numero_police=numero_police,
            numero_facture=numero_facture,  # AJOUTÉ
            duree=duree,
            date_effet=date_effet,
            date_echeance=date_echeance,
            prime_nette=Decimal(str(tarif["prime_nette"])),
            accessoires=Decimal(str(tarif["accessoires"])),
            fga=Decimal(str(tarif["fga"])),
            taxes=Decimal(str(tarif["taxes"])),
            prime_ttc=Decimal(str(tarif["prime_ttc"])),

            # NOUVELLE LOGIQUE COMMISSION
            commission_askia=Decimal(str(tarif.get("commission_askia", 0))),
            commission_apporteur=Decimal(str(tarif.get("commission_apporteur", 0))),
            commission_bwhite=Decimal(str(tarif.get("commission_bwhite", 0))),
            net_a_reverser=Decimal(str(tarif.get("net_a_reverser", 0))),

            status="EMIS",
            id_saisie_askia=simulation_data.get("id_saisie"),
            emis_at=timezone.now(),
            askia_response=result.get("raw_response", simulation_data),
            link_attestation=attestation,
            link_carte_brune=carte_brune,
        )

        # (Le signal post_save s'occupera de créer le PaiementApporteur)

        request.session.pop("simulation_data", None)
        logger.info("✅ Contrat créé | Police=%s | Client=%s | Apporteur=%s",
                    numero_police, client.nom_complet, request.user.username)

        # Réponse
        if _is_hx(request):
            return render(request, "contracts/partials/emission_success.html", {
                "contrat": contrat,
                "success_message": f"Contrat {contrat.numero_police} émis avec succès !",
            })
        messages.success(request, f"Contrat {contrat.numero_police} émis avec succès !")
        return redirect("contracts:detail_contrat", pk=contrat.pk)

    except Exception as e:
        logger.error("Erreur inattendue émission contrat | %s", e, exc_info=True)
        return _render_error(request, f"Erreur inattendue lors de l'émission : {str(e)}")
@login_required
def detail_contrat(request, pk):
    """Vue détaillée d'un contrat."""
    contrat = get_object_or_404(Contrat, pk=pk)
    if getattr(request.user, "role", "") == "APPORTEUR" and contrat.apporteur != request.user:
        messages.error(request, "Vous n'avez pas accès à ce contrat.")
        return redirect("dashboard:home")
    return render(request, "contracts/detail_contrat.html", {
        "contrat": contrat,
        "title": f"Contrat {contrat.numero_police}",
    })
@require_http_methods(["GET"])
def check_immatriculation(request):
    """Validation instantanée de l'immatriculation (HTMX)."""
    immat = (request.GET.get("immatriculation", "") or "").strip().upper()
    if not immat:
        return HttpResponse("")

    immat_norm = immat.replace("-", "").replace(" ", "")

    # Valider le format avec le validateur
    try:
        from django.core.exceptions import ValidationError
        validator = Vehicule.immat_validators[0]
        validator(immat)  # Valide la version avec ou sans tirets
    except ValidationError:
        return HttpResponse(
            '<span class="text-orange-400 text-xs"><i class="fas fa-exclamation-triangle mr-1"></i>'
            "Format invalide</span>"
        )

    # Vérifier si l'immatriculation existe déjà
    # On vérifie la version normalisée (sans tirets)
    exists = Vehicule.objects.filter(immatriculation=immat_norm).exists()
    if exists:
        return HttpResponse(
            '<span class="text-red-400 text-xs"><i class="fas fa-times-circle mr-1"></i>'
            "Cette immatriculation existe déjà</span>"
        )

    return HttpResponse(
        '<span class="text-green-500 text-xs"><i class="fas fa-check-circle mr-1"></i>'
        "Format valide</span>"
    )
@login_required
@require_http_methods(["GET"])
def check_client(request):
    """Vérifie si un client existe par téléphone (HTMX)."""
    telephone = request.GET.get("client_telephone", "")
    if not telephone:
        return JsonResponse({"exists": False})
    try:
        client = Client.objects.get(telephone=telephone)
        return render(request, "contracts/partials/client_exists.html", {"client": client})
    except Client.DoesNotExist:
        return JsonResponse({"exists": False})


@login_required
@require_http_methods(["GET"])
def load_sous_categories(request):
    """
    Charge le dropdown des sous-catégories (HTMX)
    en fonction de la catégorie sélectionnée.
    """
    categorie = request.GET.get('categorie')

    form = VehiculeForm()

    context = {
        'field': form['sous_categorie'],
        'required': False
    }

    if categorie == '520':  # TPC
        form.fields['sous_categorie'].choices = SOUS_CATEGORIES_520
        context['required'] = True
    elif categorie == '550':  # 2 Roues
        form.fields['sous_categorie'].choices = SOUS_CATEGORIES_550
        context['required'] = True
    else:
        # Si VP ou autre, on renvoie un contenu vide (le wrapper sera vide)
        return HttpResponse("")

    return render(request, "contracts/partials/_sous_categories_select.html", context)
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


@login_required
def liste_contrats(request):
    """Liste les contrats (filtrables), visibles uniquement s'ils disposent de documents (via emis_avec_doc)."""
    contrats = Contrat.objects.emis_avec_doc().select_related("client", "vehicule", "apporteur")

    if getattr(request.user, "role", "") == "APPORTEUR":
        contrats = contrats.filter(apporteur=request.user)

    # Filtres
    statut = request.GET.get("status")
    if statut:
        contrats = contrats.filter(status=statut)
    date_debut = request.GET.get("date_debut")
    if date_debut:
        contrats = contrats.filter(date_effet__gte=date_debut)
    date_fin = request.GET.get("date_fin")
    if date_fin:
        contrats = contrats.filter(date_effet__lte=date_fin)

    # Recherche
    client_id = request.GET.get("client")
    tel = (request.GET.get("tel") or "").strip()
    search_query = (request.GET.get("search") or "").strip()
    if client_id and client_id.isdigit():
        contrats = contrats.filter(client_id=client_id)
    elif tel:
        contrats = contrats.filter(client__telephone__icontains=tel)
    elif search_query:
        contrats = contrats.filter(
            Q(vehicule__immatriculation__icontains=search_query) |
            Q(client__nom__icontains=search_query) |
            Q(client__prenom__icontains=search_query) |
            Q(client__telephone__icontains=search_query) |
            Q(numero_police__icontains=search_query)
        )

    apporteur_id = request.GET.get("apporteur")
    if getattr(request.user, "role", "") == "ADMIN" and apporteur_id:
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
    """Liste des clients avec nombre de contrats valides."""
    clients = Client.objects.annotate(
        nb_contrats=Count(
            "contrats",
            filter=Q(contrats__status="EMIS") &
                   (Q(contrats__link_attestation__isnull=False) |
                    Q(contrats__link_carte_brune__isnull=False))
        )
    )

    if getattr(request.user, "role", "") == "APPORTEUR":
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


# =========================
# Échéances + Renouvellement
# =========================
@login_required
def echeances_aujourdhui(request):
    """Contrats AUTOMOBILE CLASSIQUE dont l'échéance est aujourd'hui."""
    # CORRECTION: Utilisation du manager 'objects' et filtre direct
    qs = Contrat.objects.filter(
        date_echeance=timezone.now().date(),
        status__in=["EMIS", "ACTIF"]  # On ne renouvelle que ce qui est actif/émis
    ).select_related("client", "vehicule")

    if getattr(request.user, "role", "") != "ADMIN":
        qs = qs.filter(apporteur=request.user)

    return render(request, "contracts/echeances_aujourdhui.html", {"contrats": qs})


@login_required
@transaction.atomic
def renouveler_contrat_auto(request, pk: int):
    """
    Renouvelle un contrat auto en appelant l'API Askia 'renouv'
    et CRÉE un NOUVEAU contrat localement.
    """
    if request.method != "POST":
        logger.warning("Tentative de GET sur renouveler_contrat_auto (POST requis)")
        return redirect("dashboard:home")

    try:
        contrat_ancien = (Contrat.objects
                          .select_related("client", "vehicule", "apporteur")
                          .get(pk=pk))
    except Contrat.DoesNotExist:
        messages.error(request, "Contrat original introuvable.")
        return redirect("dashboard:home")

    # Vérifier les permissions
    if getattr(request.user, "role", "") != "ADMIN" and contrat_ancien.apporteur_id != request.user.id:
        messages.error(request, "Vous n'êtes pas autorisé à renouveler ce contrat.")
        return redirect("dashboard:home")

    # Préparer les données pour l'API
    dure = int(request.POST.get("dure", contrat_ancien.duree))  # Réutilise l'ancienne durée par défaut

    due_date = contrat_ancien.date_echeance
    effet_date = due_date + timedelta(days=1)
    effet_str = effet_date.strftime("%d/%m/%Y")  # Format requis par ASKIA

    # Récupérer les options du contrat précédent
    v = contrat_ancien.vehicule
    opts = {
        "vaf": v.valeur_neuve or 0,
        "vvn": v.valeur_venale or 0,
        # TODO: Stocker les garanties sur le modèle Contrat si vous voulez les réutiliser
        "recour": 0,
        "vol": 0,
        "inc": 0,
        "pt": 0,
        "gb": 0,
    }

    # Appeler l'API de renouvellement
    try:
        data = askia_client.renew_contrat_auto(
            cli_code=contrat_ancien.client.code_askia,
            numero_police=contrat_ancien.numero_police,
            dure=dure,
            effet=effet_str,
            **opts,
        )
    except Exception as e:
        messages.error(request, f"Le renouvellement API a échoué : {e}")
        return redirect("contracts:liste_contrats")  # Redirige vers la liste

    # ========================================================================
    # CORRECTION : CRÉER UN NOUVEAU CONTRAT, NE PAS MODIFIER L'ANCIEN
    # ========================================================================

    # 1. Mettre l'ancien contrat en 'EXPIRE'
    contrat_ancien.status = "EXPIRE"
    contrat_ancien.save(update_fields=["status", "updated_at"])

    # 2. Préparer les données pour le NOUVEAU contrat
    numero_facture = data.get("numeroFacture")
    new_police = data.get("numeroPolice")
    new_due_date = effet_date + relativedelta(months=dure) - timedelta(days=1)

    prime_nette = askia_client._safe_decimal(data.get("primenette"))
    prime_ttc = askia_client._safe_decimal(data.get("primettc"))
    accessoires = askia_client._safe_decimal(data.get("accessoire"))
    fga = askia_client._safe_decimal(data.get("fga"))
    taxes = askia_client._safe_decimal(data.get("taxe"))

    # Recalculer TOUTES les commissions
    temp_contrat = Contrat(
        prime_nette=prime_nette,
        apporteur=contrat_ancien.apporteur
    )
    temp_contrat.calculate_commission()  # Utilise la logique du modèle

    liens = data.get("lien", {}) or {}

    # 3. Créer le nouveau contrat
    nouveau_contrat = Contrat.objects.create(
        client=contrat_ancien.client,
        vehicule=contrat_ancien.vehicule,
        apporteur=contrat_ancien.apporteur,  # Garde l'apporteur original
        numero_police=new_police,
        numero_facture=numero_facture,
        duree=dure,
        date_effet=effet_date,
        date_echeance=new_due_date,
        prime_nette=prime_nette,
        accessoires=accessoires,
        fga=fga,
        taxes=taxes,
        prime_ttc=prime_ttc,

        # Commissions recalculées
        commission_askia=temp_contrat.commission_askia,
        commission_apporteur=temp_contrat.commission_apporteur,
        commission_bwhite=temp_contrat.commission_bwhite,
        net_a_reverser=temp_contrat.net_a_reverser,

        status="EMIS",
        emis_at=timezone.now(),
        askia_response=data,
        link_attestation=liens.get("linkAttestation", ""),
        link_carte_brune=liens.get("linkCarteBrune", ""),
    )

    messages.success(request, f"Contrat {new_police} renouvelé avec succès.")
    return redirect("contracts:detail_contrat", pk=nouveau_contrat.pk)


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def annuler_contrat(request, pk):
    """Annule localement un contrat et tente l'annulation d'attestation côté Askia (ADMIN)."""
    contrat = get_object_or_404(Contrat, pk=pk)

    if getattr(request.user, "role", "") != "ADMIN":
        messages.error(request, "Action non autorisée.")
        return redirect("contracts:detail_contrat", pk=pk)

    if contrat.status == "ANNULE":
        messages.info(request, "Ce contrat est déjà annulé.")
        return redirect("contracts:detail_contrat", pk=pk)

    api_ok, api_msg = True, ""
    try:
        if contrat.numero_facture:
            # CORRECTION: Appel de la méthode qui existe maintenant
            resp = askia_client.annuler_attestation(contrat.numero_facture)
            api_msg = resp.get("message", "Succès API")
        else:
            api_ok, api_msg = False, "Numéro de facture manquant, annulation locale uniquement."
            logger.warning("Annulation locale seulement (pas de N° facture) pour Police %s", contrat.numero_police)

    except Exception as e:
        api_ok, api_msg = False, str(e)
        logger.error("Échec annulation Askia pour Facture %s: %s", contrat.numero_facture, e)

    # CORRECTION: Utilisation des champs qui existent (ajoutés au modèle)
    contrat.status = "ANNULE"
    contrat.annule_at = timezone.now()
    contrat.annule_par = request.user
    contrat.annule_raison = (request.POST.get("raison") or "Annulé par Admin")[:255]
    contrat.link_attestation = ""  # Effacer les liens
    contrat.link_carte_brune = ""
    contrat.save(update_fields=[
        "status", "annule_at", "annule_par", "annule_raison",
        "link_attestation", "link_carte_brune", "updated_at",
    ])

    # Annulation du paiement apporteur associé
    try:
        from payments.models import PaiementApporteur, HistoriquePaiement
        p = PaiementApporteur.objects.filter(contrat=contrat).first()
        if p and p.status not in {"ANNULE"}:
            p.status = "ANNULE"
            p.save(update_fields=["status", "updated_at"])
            HistoriquePaiement.objects.create(
                paiement=p, action="ANNULATION", effectue_par=request.user,
                details="Contrat annulé par Admin → Paiement marqué ANNULE"
            )
    except Exception as e:
        logger.warning("MAJ paiement apporteur échouée lors d'annulation contrat: %s", e)

    if api_ok:
        messages.success(request, f"Contrat annulé. Annulation Askia réussie: {api_msg}")
    else:
        messages.warning(request, f"Contrat annulé localement. Échec annulation Askia: {api_msg}")

    return redirect("contracts:detail_contrat", pk=pk)


@login_required
def detail_client(request, pk):
    """Fiche client avec ses contrats valides uniquement (avec scope apporteur)."""
    client = get_object_or_404(Client, pk=pk)

    if getattr(request.user, "role", "") == "APPORTEUR":
        contrats = (Contrat.objects.emis_avec_doc()
                    .filter(client=client, apporteur=request.user)
                    .select_related("vehicule", "apporteur")
                    .order_by("-created_at"))
    else:
        contrats = (Contrat.objects.emis_avec_doc()
                    .filter(client=client)
                    .select_related("vehicule", "apporteur")
                    .order_by("-created_at"))

    return render(request, "contracts/detail_client.html", {
        "title": f"Fiche Client - {client.nom_complet}",
        "client": client,
        "contrats": contrats,
    })