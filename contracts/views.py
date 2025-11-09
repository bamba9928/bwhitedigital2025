from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime, date, timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Count
import re
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from dateutil.relativedelta import relativedelta
from .api_client import askia_client
from .forms import ClientForm, VehiculeForm, ContratSimulationForm, BASE_SELECT_CLASS
from .models import Client, Vehicule, Contrat
from .referentiels import SOUS_CATEGORIES_520, SOUS_CATEGORIES_550
from .validators import validate_immatriculation, normalize_immat_for_storage

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
# --- Téléphone SN ---
PHONE_RE = re.compile(r'^(70|71|75|76|77|78|30|33|34)\d{7}$')

def _phone_normalize(s: str) -> str:
    """Garde uniquement les chiffres, retire indicatif SN, retourne 9 chiffres."""
    if not isinstance(s, str):
        return ""
    digits = re.sub(r"\D", "", s)           # supprime espaces, +, -, etc.
    digits = re.sub(r"^(00221|221)", "", digits)  # retire 00221 ou 221
    return digits

def _phone_validate_or_err(raw: str) -> str:
    """Retourne le numéro normalisé si valide, sinon lève ValueError."""
    num = _phone_normalize(raw)
    if not PHONE_RE.fullmatch(num):
        raise ValueError(
            "Téléphone invalide. Format attendu Sénégal sans indicatif, ex: 77XXXXXXX."
        )
    return num

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
LABELS = {
    "categorie": "Catégorie",
    "carburant": "Carburant",
    "puissance_fiscale": "Puissance fiscale",
    "nombre_places": "Nombre de places",
    "marque": "Marque",
    "modele": "Modèle",
    "prenom": "Prénom",
    "nom": "Nom",
    "telephone": "Téléphone",
    "adresse": "Adresse",
    "date_effet": "Date d'effet",
}
def _g(req, key, default=""):
    v = req.POST.get(key, default)
    return v.strip() if isinstance(v, str) else v

def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)  # AAAA-MM-JJ
    except ValueError:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None
@login_required
@require_http_methods(["POST"])
def simuler_tarif(request):
    """Vue HTMX pour simuler un tarif automobile."""
    try:
        # 0) Champs requis client + véhicule
        required_fields = [
            "categorie", "carburant", "puissance_fiscale",
            "nombre_places", "marque", "modele",
            "prenom", "nom", "telephone", "adresse",
        ]
        missing_keys = [k for k in required_fields if not _g(request, k)]
        if missing_keys:
            return _render_error(
                request,
                "Champs manquants : " + ", ".join(LABELS.get(k, k) for k in missing_keys)
            )

        # 1) Téléphone: normalisation + validation stricte
        try:
            tel_norm = _phone_validate_or_err(_g(request, "telephone"))
        except ValueError as e:
            return _render_error(request, str(e))

        # 2) Date d'effet valide et non passée
        date_effet_str = _g(request, "date_effet")
        date_effet = _parse_date(date_effet_str)
        if not date_effet:
            return _render_error(request, "Date d'effet invalide. Formats: AAAA-MM-JJ ou JJ/MM/AAAA.")
        today = timezone.localdate()
        if date_effet < today:
            return _render_error(
                request,
                (
                    "La date d'effet ne peut pas être dans le passé "
                    f"(fournie: {date_effet.strftime('%d/%m/%Y')}, "
                    f"aujourd'hui: {today.strftime('%d/%m/%Y')})."
                )
            )

        # 3) Catégorie & champs dépendants
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

        # 4) Données véhicule
        vehicule_data = {
            "categorie": categorie,
            "sous_categorie": sous_categorie,
            "carburant": request.POST["carburant"],
            "carrosserie": request.POST.get("carrosserie", "07"),
            "marque": request.POST["marque"],
            "modele": (request.POST.get("modele") or "").upper(),
            "puissance_fiscale": max(1, int(request.POST.get("puissance_fiscale") or 1)),
            "nombre_places": max(1, int(request.POST.get("nombre_places") or 1)),
            "valeur_neuve": Decimal(str(request.POST.get("valeur_neuve") or 0)),
            "valeur_venale": Decimal(str(request.POST.get("valeur_venale") or 0)),
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

        # 5) Données client + affichage véhicule
        client_data = {
            "prenom": (request.POST.get("prenom") or "").upper().strip(),
            "nom": (request.POST.get("nom") or "").upper().strip(),
            "telephone": tel_norm,
            "adresse": (request.POST.get("adresse") or "").upper().strip(),
        }
        vehicule_display = {
            "immatriculation": (request.POST.get("immatriculation") or "").upper().strip(),
            "marque": request.POST.get("marque_label", ""),
            "modele": (request.POST.get("modele") or "").upper(),
        }

        # 6) Appel Askia simulation
        try:
            simulation = askia_client.get_simulation_auto(vehicule_data, duree)
        except Exception as e:
            logger.error("Erreur simulation Askia | %s", str(e), exc_info=True)
            return _render_error(request, f"Erreur API Askia : {str(e)}")

        prime_nette = Decimal(str(simulation["prime_nette"]))
        prime_ttc = Decimal(str(simulation["prime_ttc"]))
        accessoires = Decimal(str(simulation.get("accessoires", 0)))
        fga = Decimal(str(simulation.get("fga", 0)))
        taxes = Decimal(str(simulation.get("taxes", 0)))

        # 7) Commissions via le modèle
        temp_contrat = Contrat(
            prime_nette=prime_nette,
            prime_ttc=prime_ttc,
            apporteur=request.user,
            duree=duree,
            date_effet=date_effet,
        )
        temp_contrat.calculate_commission()

        commission_askia_bwhite = temp_contrat.commission_askia
        commission_apporteur = temp_contrat.commission_apporteur
        commission_bwhite_profit = temp_contrat.commission_bwhite
        net_a_reverser_askia = temp_contrat.net_a_reverser

        # 8) Session
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
                "commission_askia": commission_askia_bwhite,
                "commission_apporteur": commission_apporteur,
                "commission_bwhite": commission_bwhite_profit,
                "net_a_reverser": net_a_reverser_askia,
            },
            "id_saisie": simulation.get("id_saisie"),
            "client": client_data,
            "vehicule_display": vehicule_display,
        })

        # 9) Rendu partiel
        context = {
            "simulation": {
                "prime_nette": prime_nette,
                "accessoires": accessoires,
                "fga": fga,
                "taxes": taxes,
                "prime_ttc": prime_ttc,
                "commission": simulation.get("commission", 0),
            },
            "commission": commission_apporteur,
            "net_a_reverser": net_a_reverser_askia,
            "duree": duree,
            "date_effet": date_effet,
            "is_apporteur": getattr(request.user, "role", "") == "APPORTEUR",
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
        # 1. Extraire les données brutes de la session
        client_data = simulation_data.get("client")
        vehicule_data_api = simulation_data.get("vehicule")  # Données brutes pour l'API
        vehicule_display = simulation_data.get("vehicule_display", {})

        # 2. Reconstruire les dictionnaires pour les formulaires
        vehicule_form_data = {
            "immatriculation": vehicule_display.get("immatriculation"),
            "marque": vehicule_data_api.get("marque"),
            "modele": vehicule_data_api.get("modele"),
            "categorie": vehicule_data_api.get("categorie"),
            "sous_categorie": vehicule_data_api.get("sous_categorie"),
            "charge_utile": vehicule_data_api.get("charge_utile") or 0,
            "puissance_fiscale": vehicule_data_api.get("puissance_fiscale"),
            "nombre_places": vehicule_data_api.get("nombre_places"),
            "carburant": vehicule_data_api.get("carburant"),
            "valeur_neuve": vehicule_data_api.get("valeur_neuve") or 0,
            "valeur_venale": vehicule_data_api.get("valeur_venale") or 0,
        }

        # 3. Instancier et valider les formulaires
        client_form = ClientForm(client_data)
        vehicule_form = VehiculeForm(vehicule_form_data)

        if not client_form.is_valid():
            # Renvoyer la première erreur trouvée
            first_error = list(client_form.errors.values())[0][0]
            logger.warning(f"Échec validation client: {first_error}")
            return _render_error(request, f"Client invalide: {first_error}")

        if not vehicule_form.is_valid():
            # Renvoyer la première erreur trouvée
            first_error = list(vehicule_form.errors.values())[0][0]
            logger.warning(f"Échec validation véhicule: {first_error}")
            return _render_error(request, f"Véhicule invalide: {first_error}")

        # 4. Si la validation réussit, utiliser les données nettoyées
        client_cleaned_data = client_form.cleaned_data
        vehicule_cleaned_data = vehicule_form.cleaned_data

        # ---------- CLIENT (utilise les données nettoyées) ----------
        client, _ = Client.objects.get_or_create(
            telephone=client_cleaned_data["telephone"],  # Champ unique nettoyé
            defaults={
                "prenom": client_cleaned_data["prenom"],
                "nom": client_cleaned_data["nom"],
                "adresse": client_cleaned_data["adresse"],
                "created_by": request.user,
            },
        )
        if not client.code_askia:
            try:
                # L'API Askia attend les données brutes (non-capitalisées, etc.)
                client.code_askia = askia_client.create_client(client_data)
                client.save(update_fields=["code_askia"])
            except Exception as e:
                logger.error("Échec création client | Tel=%s | %s", client_data["telephone"], e)
                return _render_error(request, f"Erreur création client ASKIA : {str(e)}")

        # ---------- VÉHICULE (utilise les données nettoyées) ----------
        immat = vehicule_cleaned_data["immatriculation"]  # Déjà normalisé par le formulaire

        vehicule, _ = Vehicule.objects.get_or_create(
            immatriculation=immat,
            defaults=vehicule_cleaned_data  # Passe toutes les données nettoyées
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
            "immatriculation": immat,  # Utilise l'immatriculation nettoyée
            "id_saisie": simulation_data.get("id_saisie"),
            **vehicule_data_api  # Transmet les données d'origine (attendues par l'API)
        }

        try:
            result = askia_client.create_contrat_auto(contrat_data)
        except Exception as api_error:

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
            client=client,  # Objet Client validé
            vehicule=vehicule,  # Objet Véhicule validé
            apporteur=request.user,
            numero_police=numero_police,
            numero_facture=numero_facture,
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

    # Valider le format avec le nouveau validateur
    try:

        validate_immatriculation(immat)

    except ValidationError as e:
        return HttpResponse(
            f'<span class="text-orange-400 text-xs"><i class="fas fa-exclamation-triangle mr-1"></i>'
            f"{e.message}</span>"
        )

    immat_norm = normalize_immat_for_storage(immat)

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
    categorie = request.GET.get('categorie', '').strip()

    if categorie not in ['520', '550']:
        return HttpResponse("")

    form = VehiculeForm()
    required = True
    label = 'Genre / Sous-catégorie'
    choices = []

    if categorie == '520':
        choices = SOUS_CATEGORIES_520
        label = 'Sous-catégorie (TPC)'
    elif categorie == '550':
        choices = SOUS_CATEGORIES_550
        label = 'Genre (2 Roues)'

    form.fields['sous_categorie'].choices = [('', '-- Sélectionner --')] + choices
    form.fields['sous_categorie'].required = required
    form.fields['sous_categorie'].widget.attrs.update({
        'class': BASE_SELECT_CLASS,
        'id': 'id_sous_categorie',
        'name': 'sous_categorie',
        'required': 'required'
    })
    form.fields['sous_categorie'].widget.attrs.pop('disabled', None)
    form.fields['sous_categorie'].widget.attrs.pop('style', None)

    return render(request, "contracts/partials/_sous_categories_select.html", {
        'field': form['sous_categorie'],
        'required': required,
        'label': label,
    })
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

    if getattr(request.user, "role", "") != "ADMIN" and contrat_ancien.apporteur_id != request.user.id:
        messages.error(request, "Vous n'êtes pas autorisé à renouveler ce contrat.")
        return redirect("dashboard:home")

    dure = int(request.POST.get("dure", contrat_ancien.duree))  # Réutilise l'ancienne durée par défaut

    due_date = contrat_ancien.date_echeance
    effet_date = due_date + timedelta(days=1)
    effet_str = effet_date.strftime("%d/%m/%Y")

    v = contrat_ancien.vehicule
    opts = {
        "vaf": v.valeur_neuve or 0,
        "vvn": v.valeur_venale or 0,
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
        return redirect("contracts:liste_contrats")

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
        prime_ttc=prime_ttc,
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
    """
    Annule un contrat.
    - Si API OK : Statut 'ANNULE', suppression des liens documents.
    - Si API KO : Statut 'ANNULE_LOCAL', conservation des liens pour retry futur.
    """
    contrat = get_object_or_404(Contrat, pk=pk)

    if getattr(request.user, "role", "") != "ADMIN":
        messages.error(request, "Action non autorisée.")
        return redirect("contracts:detail_contrat", pk=pk)

    if contrat.status in ["ANNULE", "ANNULE_LOCAL"]:
        messages.info(request, "Ce contrat est déjà annulé.")
        return redirect("contracts:detail_contrat", pk=pk)

    api_success = False
    api_msg = ""

    # 1. Tentative Annulation API
    if contrat.numero_facture:
        try:

            resp = askia_client.annuler_attestation(contrat.numero_facture)

            api_success = True
            api_msg = resp.get("message", "Succès API")

        except Exception as e:
            logger.error("Échec annulation Askia pour Facture %s: %s", contrat.numero_facture, e)
            api_msg = str(e)
            api_success = False
    else:

        api_success = True
        api_msg = "Annulation locale (pas de N° facture Askia)"

    # 2. Mise à jour locale
    old_status = contrat.status
    new_status = 'ANNULE' if api_success else 'ANNULE_LOCAL'

    contrat.status = new_status
    contrat.annule_at = timezone.now()
    contrat.annule_par = request.user
    contrat.annule_raison = (request.POST.get("raison") or "Annulé par Admin")[:255]

    # On ne supprime les documents que si l'annulation est confirmée côté Askia
    if api_success:
        contrat.link_attestation = ""
        contrat.link_carte_brune = ""

    contrat.save(update_fields=[
        "status", "annule_at", "annule_par", "annule_raison",
        "link_attestation", "link_carte_brune", "updated_at",
    ])

    logger.info(
        "Contrat %s annulé | Ancien statut: %s -> Nouveau: %s | API OK: %s",
        contrat.numero_police, old_status, new_status, api_success
    )

    # 3. Annulation du paiement apporteur associé (toujours annulé car le contrat n'est plus valide)
    try:
        from payments.models import PaiementApporteur, HistoriquePaiement
        p = PaiementApporteur.objects.filter(contrat=contrat).first()
        if p and p.status != "ANNULE":
            p.status = "ANNULE"
            p.save(update_fields=["status", "updated_at"])
            HistoriquePaiement.objects.create(
                paiement=p,
                action="STATUS_CHANGE",
                effectue_par=request.user,
                details=f"Annulation suite à l'annulation du contrat {contrat.numero_police}"
            )
    except Exception as e:
        logger.warning("Erreur MAJ paiement lors d'annulation contrat %s: %s", contrat.pk, e)

    # 4. Feedback utilisateur
    if api_success:
        messages.success(request, f"Contrat annulé avec succès. (Réponse API: {api_msg})")
    else:
        messages.warning(
            request,
            f"⚠️ Contrat annulé LOCALEMENT uniquement. L'API Askia n'a pas pu être jointe ou a refusé. "
            f"Erreur: {api_msg}. Le statut est 'Annulé (Local)', veuillez réessayer plus tard."
        )

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