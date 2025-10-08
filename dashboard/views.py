from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import datetime, timedelta
from django.views.generic import TemplateView
from contracts.models import Contrat, Client
from accounts.models import User
from payments.models import PaiementApporteur

# Utilitaire
def _safe_sum(queryset, field):
    """Retourne la somme d'un champ, jamais None."""
    return queryset.aggregate(total=Sum(field))['total'] or 0
def _compute_stats(contrats, today):
    """Retourne un dictionnaire avec stats mensuelles et totales pour un queryset de contrats"""
    # Calculs mensuels (mois en cours)
    contrats_mois = contrats.filter(
        date_effet__year=today.year,
        date_effet__month=today.month
    )

    return {
        'prime_mois': _safe_sum(contrats_mois, 'prime_ttc'),
        'commission_mois': _safe_sum(contrats_mois, 'commission_apporteur'),
        'en_attente': contrats.filter(status="EN_ATTENTE").count(),
        'commissions_totales': _safe_sum(contrats, 'commission_apporteur'),
        'total_primes_filtre': _safe_sum(contrats, 'prime_ttc'),
        'total_commissions_filtre': _safe_sum(contrats, 'commission_apporteur'),
        'total_net_filtre': _safe_sum(contrats, 'net_a_reverser'),
    }
@login_required
def home(request):
    today = timezone.now().date()
    first_day_month = today.replace(day=1)

    # ---- Récupération paramètres GET ----
    periode = request.GET.get('periode')
    statut = request.GET.get('statut')
    search = request.GET.get('search', '').strip()
    date_debut = request.GET.get('date_debut')
    date_fin = request.GET.get('date_fin')
    apporteur_id = request.GET.get('apporteur')

    # ---- Gestion des périodes prédéfinies ----
    if periode == 'jour':
        date_debut = today
    elif periode == 'semaine':
        date_debut = today - timedelta(days=7)
    elif periode == 'mois':
        date_debut = first_day_month
    elif periode == 'annee':
        date_debut = today.replace(month=1, day=1)

    # ---- Conversion dates personnalisées ----
    if request.GET.get('date_debut'):
        try:
            date_debut = datetime.strptime(request.GET['date_debut'], "%Y-%m-%d").date()
        except ValueError:
            date_debut = None
    if request.GET.get('date_fin'):
        try:
            date_fin = datetime.strptime(request.GET['date_fin'], "%Y-%m-%d").date()
        except ValueError:
            date_fin = None

    # Correction logique incohérente
    if date_debut and date_fin and date_fin < date_debut:
        date_fin = None

    # ---- Base queryset ----
    contrats = Contrat.objects.emis_avec_doc()

    # ---- Restrictions par rôle ----
    if request.user.role == 'APPORTEUR':
        contrats = contrats.filter(apporteur=request.user)
    elif request.user.role == 'ADMIN' and apporteur_id:
        contrats = contrats.filter(apporteur__id=apporteur_id)

    # ---- Application filtres ----
    if date_debut:
        contrats = contrats.filter(date_effet__gte=date_debut)
    if date_fin:
        contrats = contrats.filter(date_effet__lte=date_fin)
    if statut:
        contrats = contrats.filter(status=statut)
    if search:
        contrats = contrats.filter(
            Q(vehicule__immatriculation__icontains=search) |
            Q(client__nom__icontains=search) |
            Q(client__prenom__icontains=search)
        )

    # ---- ADMIN ----
    if request.user.role == 'ADMIN':
        # Stats générales
        total_contrats = contrats.count()
        total_clients = Client.objects.count()
        total_apporteurs = User.objects.filter(role='APPORTEUR').count()
        paiements_attente = PaiementApporteur.objects.filter(status="EN_ATTENTE").count()
        montant_attente = _safe_sum(contrats, 'net_a_reverser')

        # Stats admin
        contrats_admin = contrats.filter(apporteur=request.user)
        resume_admin = contrats_admin.aggregate(
            nb_contrats=Count('id'),
            total_primes=Sum('prime_ttc'),
            total_commissions=Sum('commission_apporteur'),
            total_net=Sum('net_a_reverser')
        )

        # Stats apporteurs
        top_apporteurs = contrats.filter(apporteur__role='APPORTEUR').values(
            'apporteur__id', 'apporteur__first_name', 'apporteur__last_name'
        ).annotate(
            total_primes=Sum('prime_ttc'),
            total_commissions=Sum('commission_apporteur'),
            total_net=Sum('net_a_reverser')
        ).order_by('-total_primes')[:5]

        recap_apporteurs = contrats.filter(apporteur__role='APPORTEUR').values(
            'apporteur__id', 'apporteur__first_name', 'apporteur__last_name'
        ).annotate(
            nb_contrats=Count('id'),
            total_primes=Sum('prime_ttc'),
            total_commissions=Sum('commission_apporteur'),
            total_net=Sum('net_a_reverser')
        ).order_by('-total_primes')

        context = {
            'title': "Dashboard Admin",
            'today': today,
            'total_contrats': total_contrats,
            'total_clients': total_clients,
            'total_apporteurs': total_apporteurs,
            'paiements_attente': paiements_attente,
            'montant_attente': montant_attente,
            'resume_admin': resume_admin,
            **_compute_stats(contrats, today),  # 🔥 stats factorisées
            'top_apporteurs': top_apporteurs,
            'recap_apporteurs': recap_apporteurs,
            'periode': periode,
            'statut': statut,
            'periode_choices': [
                ('jour', 'Aujourd’hui'),
                ('semaine', '7 derniers jours'),
                ('mois', 'Mois en cours'),
                ('annee', 'Année en cours'),
            ],
            'statut_choices': [c for c in Contrat.STATUS_CHOICES if c[0] != 'SIMULATION'],
            'apporteurs': User.objects.filter(role='APPORTEUR'),
            'apporteur_id': apporteur_id,
            'derniers_contrats_affiches': contrats.order_by('-created_at')[:10],
            'search': search,
            'date_debut': date_debut,
            'date_fin': date_fin,
        }

    # ---- APPORTEUR ----
    elif request.user.role == 'APPORTEUR':
        context = {
            'title': "Dashboard Apporteur",
            'today': today,
            'mes_contrats_total': contrats.count(),
            **_compute_stats(contrats, today),  # 🔥 stats factorisées
            'periode': periode,
            'statut': statut,
            'search': search,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'periode_choices': [
                ('jour', 'Aujourd’hui'),
                ('semaine', '7 derniers jours'),
                ('mois', 'Mois en cours'),
                ('annee', 'Année en cours'),
            ],
            'statut_choices': [c for c in Contrat.STATUS_CHOICES if c[0] != 'SIMULATION'],
            'derniers_contrats_affiches': contrats.order_by('-created_at')[:10],
        }

    else:
        context = {'title': "Dashboard"}

    return render(request, "dashboard/home.html", context)

def get_evolution_data(user):
    """Données d'évolution sur 12 mois pour graphiques"""
    data = []
    for i in range(12):
        date = timezone.now().date() - timedelta(days=i * 30)
        mois_debut = date.replace(day=1)

        if date.month == 12:
            mois_fin = date.replace(year=date.year + 1, month=1, day=1)
        else:
            mois_fin = date.replace(month=date.month + 1, day=1)

        stats = user.contrats_apportes.emis_avec_doc().filter(
            created_at__gte=mois_debut,
            created_at__lt=mois_fin
        ).aggregate(
            nombre=Count('id'),
            commissions=Sum('commission_apporteur')
        )

        data.append({
            'mois': date.strftime('%B %Y'),
            'nombre': stats['nombre'] or 0,
            'commissions': float(stats['commissions'] or 0)
        })

    return list(reversed(data))
@login_required
def statistiques(request):
    """Page de statistiques détaillées"""
    today = timezone.now().date()

    # ---- Récupération des paramètres ----
    periode = request.GET.get('periode')
    date_debut, date_fin = None, None

    # ---- Périodes prédéfinies ----
    if periode == 'jour':
        date_debut = today
    elif periode == 'semaine':
        date_debut = today - timedelta(days=7)
    elif periode == 'mois':
        date_debut = today.replace(day=1)
    elif periode == 'annee':
        date_debut = today.replace(month=1, day=1)

    # ---- Conversion dates personnalisées ----
    if request.GET.get('date_debut'):
        try:
            date_debut = datetime.strptime(request.GET['date_debut'], "%Y-%m-%d").date()
        except ValueError:
            date_debut = None

    if request.GET.get('date_fin'):
        try:
            date_fin = datetime.strptime(request.GET['date_fin'], "%Y-%m-%d").date()
        except ValueError:
            date_fin = None

    # Correction si incohérent
    if date_debut and date_fin and date_fin < date_debut:
        date_fin = None

    # ---- Base queryset ----
    contrats = Contrat.objects.emis_avec_doc()

    # Restriction rôle
    if request.user.role == 'APPORTEUR':
        contrats = contrats.filter(apporteur=request.user)

    # Application filtres date
    if date_debut:
        contrats = contrats.filter(date_effet__gte=date_debut)
    if date_fin:
        contrats = contrats.filter(date_effet__lte=date_fin)

    # ---- Statistiques agrégées ----
    stats_categories = contrats.values('vehicule__categorie').annotate(
        nombre=Count('id'),
        total_primes=Sum('prime_ttc')
    )

    stats_durees = contrats.values('duree').annotate(
        nombre=Count('id'),
        total_primes=Sum('prime_ttc')
    )

    # ---- Évolution sur 30 jours ----
    evolution = []
    for i in range(30):
        d = today - timedelta(days=i)
        stats_jour = contrats.filter(created_at__date=d).aggregate(
            nombre=Count('id'),
            primes=Sum('prime_ttc')
        )
        evolution.append({
            'date': d,
            'nombre': stats_jour['nombre'] or 0,
            'primes': stats_jour['primes'] or 0
        })

    # ---- Contexte ----
    context = {
        'title': 'Statistiques',
        'periode': periode,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'stats_categories': stats_categories,
        'stats_durees': stats_durees,
        'evolution': list(reversed(evolution)),  # plus ancien → plus récent
        'total_contrats': contrats.count(),
        **_compute_stats(contrats, today),  # 🔥 stats factorisées
    }

    return render(request, 'dashboard/statistiques.html', context)

@login_required
def profile(request):
    return render(request, 'accounts/profile.html')
def offline_view(request):
    """Vue pour la page hors-ligne"""
    return TemplateView.as_view(template_name='offline.html')(request)