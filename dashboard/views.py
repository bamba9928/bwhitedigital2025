import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.shortcuts import render
from django.utils import timezone
from django.views.generic import TemplateView

from accounts.models import User
from contracts.models import Contrat, Client
from payments.models import PaiementApporteur

logger = logging.getLogger(__name__)


# ---------- Utilitaires ----------


def _safe_sum(qs, field):
    """Somme robuste en Decimal."""
    result = qs.aggregate(total=Sum(field))["total"]
    return result or Decimal("0")


def _compute_stats(contrats, today, commission_field: str):
    """
    Stats contrats + encaissements sur le même périmètre.
    Prend en paramètre quel champ de commission agréger.
    """
    contrats_mois = contrats.filter(
        date_effet__year=today.year, date_effet__month=today.month
    )

    # Encaissements liés aux contrats filtrés
    encaissements = PaiementApporteur.objects.filter(contrat__in=contrats)
    enc_attente = encaissements.filter(status="EN_ATTENTE")
    enc_payes = encaissements.filter(status="PAYE")

    return {
        # Contrats
        "prime_mois": _safe_sum(contrats_mois, "prime_ttc"),
        "commissions_totales": _safe_sum(contrats, commission_field),
        "total_primes_filtre": _safe_sum(contrats, "prime_ttc"),
        "total_commissions_filtre": _safe_sum(contrats, commission_field),
        "total_net_filtre": _safe_sum(
            contrats, "net_a_reverser"
        ),  # Net à reverser à Askia
        # Encaissements (Statut du paiement Apporteur -> BWHITE)
        "nb_encaissements": encaissements.count(),
        "en_attente": enc_attente.count(),
        "payes": enc_payes.count(),
        # CORRIGÉ: Utilise 'montant_a_payer' de votre nouveau modèle
        "montant_en_attente": _safe_sum(enc_attente, "montant_a_payer"),
        "montant_paye": _safe_sum(enc_payes, "montant_a_payer"),
        "montant_a_payer_total": _safe_sum(encaissements, "montant_a_payer"),
    }
@login_required
def home(request):
    today = timezone.now().date()
    first_day_month = today.replace(day=1)

    # Paramètres GET
    periode = request.GET.get("periode")
    statut = request.GET.get("statut")
    search = request.GET.get("search", "").strip()
    date_debut_str = request.GET.get("date_debut")
    date_fin_str = request.GET.get("date_fin")
    apporteur_id = request.GET.get("apporteur")

    date_debut, date_fin = None, None

    # Périodes rapides
    if periode == "jour":
        date_debut, date_fin = today, today
    elif periode == "semaine":
        date_debut, date_fin = today - timedelta(days=7), today
    elif periode == "mois":
        date_debut, date_fin = first_day_month, today
    elif periode == "annee":
        date_debut, date_fin = today.replace(month=1, day=1), today

    # Dates personnalisées (prioritaires)
    if date_debut_str:
        try:
            date_debut = datetime.strptime(date_debut_str, "%Y-%m-%d").date()
        except ValueError:
            date_debut = None
    if date_fin_str:
        try:
            date_fin = datetime.strptime(date_fin_str, "%Y-%m-%d").date()
        except ValueError:
            date_fin = None

    if date_debut and date_fin and date_fin < date_debut:
        date_fin = None

    # Base queryset + optimisations
    contrats = Contrat.objects.emis_avec_doc().select_related(
        "client", "vehicule", "apporteur"
    )

    # Restrictions rôle
    if request.user.role == "APPORTEUR":
        contrats = contrats.filter(apporteur=request.user)
    elif request.user.is_staff and apporteur_id:  # MODIFIÉ (Admin OU Commercial)
        contrats = contrats.filter(apporteur__id=apporteur_id)

    # Filtres
    if date_debut:
        contrats = contrats.filter(date_effet__gte=date_debut)
    if date_fin:
        contrats = contrats.filter(date_effet__lte=date_fin)
    if statut:
        contrats = contrats.filter(status=statut)
    if search:
        s_norm = search.replace("-", "").replace(" ", "")
        contrats = contrats.filter(
            Q(vehicule__immatriculation__icontains=s_norm)
            | Q(client__nom__icontains=search)
            | Q(client__prenom__icontains=search)
            | Q(numero_police__icontains=search)
        )

    # --- Définition du Contexte ---

    # Admin et Commercial (is_staff)
    if request.user.is_staff:  # MODIFIÉ
        total_contrats = contrats.count()
        total_clients = Client.objects.count()
        total_apporteurs = User.objects.filter(role="APPORTEUR").count()

        # Encaissements (Paiements Apporteur -> BWHITE)
        encaissements = PaiementApporteur.objects.filter(contrat__in=contrats)
        paiements_attente = encaissements.filter(status="EN_ATTENTE").count()
        montant_attente = _safe_sum(
            encaissements.filter(status="EN_ATTENTE"), "montant_a_payer"
        )

        # Le champ de commission pour les stats dépend du rôle
        if request.user.is_true_admin:
            # L'Admin voit le profit BWHITE
            commission_field_for_stats = "commission_bwhite"
        else:
            # Le Commercial voit la commission de l'apporteur
            commission_field_for_stats = "commission_apporteur"

        # Stats spécifiques au VRAI Admin
        resume_admin = {}
        if request.user.is_true_admin:
            contrats_admin = contrats.filter(apporteur=request.user)
            resume_admin = contrats_admin.aggregate(
                nb_contrats=Count("id"),
                total_primes=Sum("prime_ttc"),
                total_commissions=Sum("commission_bwhite"),  # Profit BWHITE
                total_net=Sum("net_a_reverser"),
            )

        # Top 5 apporteurs (visible par Admin et Commercial)
        top_apporteurs = (
            contrats.filter(apporteur__role="APPORTEUR")
            .values("apporteur__id", "apporteur__first_name", "apporteur__last_name")
            .annotate(
                total_primes=Sum("prime_ttc"),
                total_commissions=Sum(
                    "commission_apporteur"
                ),  # Ce que l'apporteur gagne
                total_net=Sum("net_a_reverser"),  # Ce que BWHITE doit à Askia
            )
            .order_by("-total_primes")[:5]
        )

        # Récapitulatif de tous les apporteurs (visible par Admin et Commercial)
        recap_apporteurs = (
            contrats.filter(apporteur__role="APPORTEUR")
            .values("apporteur__id", "apporteur__first_name", "apporteur__last_name")
            .annotate(
                nb_contrats=Count("id"),
                total_primes=Sum("prime_ttc"),
                total_commissions_apporteur=Sum(
                    "commission_apporteur"
                ),  # Dû à l'apporteur
                total_commissions_bwhite=Sum("commission_bwhite"),  # Profit BWHITE
                total_net=Sum("net_a_reverser"),  # Dû à Askia
            )
            .order_by("-total_primes")
        )

        context = {
            "title": "Dashboard Staff",  # Titre géré par le template
            "today": today,
            "total_contrats": total_contrats,
            "total_clients": total_clients,
            "total_apporteurs": total_apporteurs,
            "paiements_attente": paiements_attente,
            "montant_attente": montant_attente,
            "resume_admin": resume_admin,  # Sera vide pour le Commercial
            **_compute_stats(contrats, today, commission_field=commission_field_for_stats),
            "top_apporteurs": top_apporteurs,
            "recap_apporteurs": recap_apporteurs,
            "periode": periode,
            "statut": statut,
            "periode_choices": [
                ("jour", "Aujourd’hui"),
                ("semaine", "7 derniers jours"),
                ("mois", "Mois en cours"),
                ("annee", "Année en cours"),
            ],
            "statut_choices": [
                c for c in Contrat.STATUS_CHOICES if c[0] != "SIMULATION"
            ],
            "apporteurs": User.objects.filter(role="APPORTEUR"),
            "apporteur_id": apporteur_id,
            "derniers_contrats_affiches": contrats.order_by("-created_at")[:10],
            "search": search,
            "date_debut": date_debut,
            "date_fin": date_fin,
        }

    # Apporteur
    elif request.user.role == "APPORTEUR":
        context = {
            "title": "Dashboard Apporteur",
            "today": today,
            "mes_contrats_total": contrats.count(),
            # Stats (Apporteur voit sa commission 'commission_apporteur')
            **_compute_stats(contrats, today, commission_field="commission_apporteur"),
            "periode": periode,
            "statut": statut,
            "search": search,
            "date_debut": date_debut.isoformat() if date_debut else "",
            "date_fin": date_fin.isoformat() if date_fin else "",
            "periode_choices": [
                ("jour", "Aujourd’hui"),
                ("semaine", "7 derniers jours"),
                ("mois", "Mois en cours"),
                ("annee", "Année en cours"),
            ],
            "statut_choices": [
                c for c in Contrat.STATUS_CHOICES if c[0] != "SIMULATION"
            ],
            "derniers_contrats_affiches": contrats.order_by("-created_at")[:10],
        }

    else:
        # Fallback (ne devrait pas arriver pour un utilisateur authentifié)
        context = {"title": "Dashboard"}

    return render(request, "dashboard/home.html", context)
def get_evolution_data(user):
    """Évolution 12 mois. Séries en float, calculs en Decimal."""
    data = []
    today = timezone.now().date()

    # Alignement avec home/statistiques
    if getattr(user, "is_true_admin", False):
        commission_field = "commission_bwhite"
    else:
        commission_field = "commission_apporteur"

    # Filtre de base selon le rôle
    base_qs = (
        user.contrats_apportes.emis_avec_doc()
        if user.role == "APPORTEUR"
        else Contrat.objects.emis_avec_doc()
    )

    for i in range(12):
        approx = today - timedelta(days=i * 30)
        mois_debut = approx.replace(day=1)
        if mois_debut.month == 12:
            mois_fin = mois_debut.replace(year=mois_debut.year + 1, month=1, day=1)
        else:
            mois_fin = mois_debut.replace(month=mois_debut.month + 1, day=1)

        stats = base_qs.filter(
            created_at__gte=mois_debut, created_at__lt=mois_fin
        ).aggregate(
            nombre=Count("id"),
            commissions=Sum(commission_field),
        )

        data.append(
            {
                "mois": mois_debut.strftime("%B %Y"),
                "nombre": stats["nombre"] or 0,
                "commissions": float(stats["commissions"] or Decimal("0")),
            }
        )

    return list(reversed(data))
@login_required
def statistiques(request):
    """Page statistiques détaillées."""
    today = timezone.now().date()

    periode = request.GET.get("periode")
    date_debut_str = request.GET.get("date_debut")
    date_fin_str = request.GET.get("date_fin")

    date_debut, date_fin = None, None

    if periode == "jour":
        date_debut, date_fin = today, today
    elif periode == "semaine":
        date_debut, date_fin = today - timedelta(days=7), today
    elif periode == "mois":
        date_debut, date_fin = today.replace(day=1), today
    elif periode == "annee":
        date_debut, date_fin = today.replace(month=1, day=1), today

    if date_debut_str:
        try:
            date_debut = datetime.strptime(date_debut_str, "%Y-%m-%d").date()
        except ValueError:
            date_debut = None
    if date_fin_str:
        try:
            date_fin = datetime.strptime(date_fin_str, "%Y-%m-%d").date()
        except ValueError:
            date_fin = None

    if date_debut and date_fin and date_fin < date_debut:
        date_fin = None

    contrats = Contrat.objects.emis_avec_doc().select_related(
        "client", "vehicule", "apporteur"
    )
    commission_field = "commission_apporteur"  # Par défaut (Apporteur ou Commercial)
    if request.user.role == "APPORTEUR":
        contrats = contrats.filter(apporteur=request.user)
    elif request.user.is_true_admin:
        commission_field = "commission_bwhite"  # Seul l'Admin voit le profit

    if date_debut:
        contrats = contrats.filter(date_effet__gte=date_debut)
    if date_fin:
        contrats = contrats.filter(date_effet__lte=date_fin)

    stats_categories = contrats.values("vehicule__categorie").annotate(
        nombre=Count("id"), total_primes=Sum("prime_ttc")
    )
    stats_durees = contrats.values("duree").annotate(
        nombre=Count("id"), total_primes=Sum("prime_ttc")
    )

    evolution = []
    for i in range(30):
        d = today - timedelta(days=i)
        stats_jour = contrats.filter(created_at__date=d).aggregate(
            nombre=Count("id"), primes=Sum("prime_ttc")
        )
        evolution.append(
            {
                "date": d.isoformat(),
                "nombre": stats_jour["nombre"] or 0,
                "primes": float(stats_jour["primes"] or Decimal("0")),
            }
        )

    context = {
        "title": "Statistiques",
        "periode": periode,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "stats_categories": stats_categories,
        "stats_durees": stats_durees,
        "evolution": list(reversed(evolution)),
        "total_contrats": contrats.count(),
        **_compute_stats(contrats, today, commission_field=commission_field),
    }

    return render(request, "dashboard/statistiques.html", context)


@login_required
def profile(request):
    # Géré par 'accounts/views.py', mais on garde un fallback si l'URL est ici
    try:
        from accounts.views import profile as accounts_profile

        return accounts_profile(request)
    except ImportError:
        logger.error("Impossible d'importer accounts.views.profile")
        return render(request, "accounts/profile.html")


def offline_view(request):
    return TemplateView.as_view(template_name="offline.html")(request)