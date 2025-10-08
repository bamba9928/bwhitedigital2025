from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime, timedelta

from accounts.models import User
from .models import PaiementApporteur, HistoriquePaiement, RecapitulatifCommissions
from contracts.models import Contrat


@login_required
def liste_paiements(request):
    """Liste des paiements (Admin: tous, Apporteur: les siens)"""
    paiements = PaiementApporteur.objects.select_related('contrat', 'contrat__client', 'contrat__apporteur')

    if request.user.role == 'APPORTEUR':
        paiements = paiements.filter(contrat__apporteur=request.user)

    # Filtres
    status = request.GET.get('status')
    if status:
        paiements = paiements.filter(status=status)

    apporteur_id = request.GET.get('apporteur')
    if apporteur_id and request.user.role == 'ADMIN':
        paiements = paiements.filter(contrat__apporteur_id=apporteur_id)

    date_debut = request.GET.get('date_debut')
    if date_debut:
        paiements = paiements.filter(created_at__gte=date_debut)

    date_fin = request.GET.get('date_fin')
    if date_fin:
        paiements = paiements.filter(created_at__lte=date_fin)

    # Statistiques
    stats = {
        'total': paiements.count(),
        'en_attente': paiements.filter(status='EN_ATTENTE').count(),
        'payes': paiements.filter(status='PAYE').count(),
        'montant_total': paiements.aggregate(Sum('montant_commission'))['montant_commission__sum'] or 0,
        'montant_en_attente': paiements.filter(status='EN_ATTENTE').aggregate(Sum('montant_commission'))[
                                  'montant_commission__sum'] or 0,
        'montant_paye': paiements.filter(status='PAYE').aggregate(Sum('montant_commission'))[
                            'montant_commission__sum'] or 0,
    }

    context = {
        'title': 'Gestion des Paiements',
        'paiements': paiements.order_by('-created_at'),
        'stats': stats,
        'apporteurs': User.objects.filter(role='APPORTEUR') if request.user.role == 'ADMIN' else None,
    }

    return render(request, 'payments/liste_paiements.html', context)

@login_required
def mes_commissions(request):
    """Vue des commissions pour un apporteur"""
    if request.user.role != 'APPORTEUR':
        messages.error(request, "Cette page est réservée aux apporteurs")
        return redirect('dashboard:home')

    # Période sélectionnée
    mois = request.GET.get('mois')
    if mois:
        try:
            date_mois = datetime.strptime(mois, '%Y-%m')
            debut_mois = date_mois.date()
            if date_mois.month == 12:
                fin_mois = debut_mois.replace(year=debut_mois.year + 1, month=1)
            else:
                fin_mois = debut_mois.replace(month=debut_mois.month + 1)
        except:
            debut_mois = timezone.now().date().replace(day=1)
            fin_mois = (debut_mois + timedelta(days=32)).replace(day=1)
    else:
        debut_mois = timezone.now().date().replace(day=1)
        fin_mois = (debut_mois + timedelta(days=32)).replace(day=1)

    # Contrats du mois
    contrats = Contrat.objects.filter(
        apporteur=request.user,
        created_at__gte=debut_mois,
        created_at__lt=fin_mois,
        status='EMIS'
    )

    # Paiements
    paiements = PaiementApporteur.objects.filter(
        contrat__apporteur=request.user,
        contrat__created_at__gte=debut_mois,
        contrat__created_at__lt=fin_mois
    ).select_related('contrat', 'contrat__client')

    # Statistiques
    stats = {
        'nb_contrats': contrats.count(),
        'total_primes': contrats.aggregate(Sum('prime_ttc'))['prime_ttc__sum'] or 0,
        'total_commissions': contrats.aggregate(Sum('commission_apporteur'))['commission_apporteur__sum'] or 0,
        'total_net_reverser': contrats.aggregate(Sum('net_a_reverser'))['net_a_reverser__sum'] or 0,
        'commissions_payees': paiements.filter(status='PAYE').aggregate(Sum('montant_commission'))[
                                  'montant_commission__sum'] or 0,
        'commissions_attente': paiements.filter(status='EN_ATTENTE').aggregate(Sum('montant_commission'))[
                                   'montant_commission__sum'] or 0,
    }

    context = {
        'title': 'Mes Commissions',
        'mois_actuel': debut_mois,
        'contrats': contrats,
        'paiements': paiements,
        'stats': stats
    }

    return render(request, 'payments/mes_commissions.html', context)


@login_required
def valider_paiement(request, pk):
    """Valider un paiement (Admin uniquement)"""
    if request.user.role != 'ADMIN':
        messages.error(request, "Accès non autorisé")
        return redirect('dashboard:home')

    paiement = get_object_or_404(PaiementApporteur, pk=pk)

    if request.method == 'POST':
        methode = request.POST.get('methode_paiement')
        reference = request.POST.get('reference_transaction')
        numero_compte = request.POST.get('numero_compte')
        notes = request.POST.get('notes')

        if not methode:
            messages.error(request, "Veuillez sélectionner une méthode de paiement")
            return redirect('payments:valider_paiement', pk=pk)

        # Marquer comme payé
        paiement.marquer_comme_paye(
            methode=methode,
            reference=reference,
            validated_by=request.user
        )
        paiement.numero_compte = numero_compte
        paiement.notes = notes
        paiement.save()

        # Créer l'historique
        HistoriquePaiement.objects.create(
            paiement=paiement,
            action='VALIDATION',
            effectue_par=request.user,
            details=f"Paiement validé - Méthode: {paiement.get_methode_paiement_display()}, Référence: {reference}"
        )

        messages.success(request, "Paiement validé avec succès!")
        return redirect('payments:liste_paiements')

    context = {
        'title': 'Valider le paiement',
        'paiement': paiement
    }

    return render(request, 'payments/valider_paiement.html', context)


@login_required
def recapitulatif_mensuel(request):
    """Récapitulatif mensuel des commissions"""
    if request.user.role != 'ADMIN':
        # Pour les apporteurs, rediriger vers mes_commissions
        return redirect('payments:mes_commissions')

    # Mois sélectionné
    mois = request.GET.get('mois')
    if mois:
        try:
            date_mois = datetime.strptime(mois, '%Y-%m').date()
        except:
            date_mois = timezone.now().date().replace(day=1)
    else:
        date_mois = timezone.now().date().replace(day=1)

    # Mettre à jour les récapitulatifs
    from accounts.models import User
    for apporteur in User.objects.filter(role='APPORTEUR'):
        RecapitulatifCommissions.update_or_create_for_month(apporteur, date_mois)

    # Récupérer les récapitulatifs
    recapitulatifs = RecapitulatifCommissions.objects.filter(
        mois=date_mois
    ).select_related('apporteur')

    # Totaux
    totaux = recapitulatifs.aggregate(
        total_contrats=Sum('nombre_contrats'),
        total_primes=Sum('total_primes_ttc'),
        total_commissions=Sum('total_commissions'),
        total_verse=Sum('total_verse'),
        total_attente=Sum('total_en_attente')
    )

    context = {
        'title': 'Récapitulatif Mensuel',
        'mois': date_mois,
        'recapitulatifs': recapitulatifs,
        'totaux': totaux
    }

    return render(request, 'payments/recapitulatif_mensuel.html', context)