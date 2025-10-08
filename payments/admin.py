from django.contrib import admin
from .models import PaiementApporteur, HistoriquePaiement, RecapitulatifCommissions


@admin.register(PaiementApporteur)
class PaiementApporteurAdmin(admin.ModelAdmin):
    list_display = ('contrat', 'get_apporteur', 'montant_commission', 'montant_verse', 'status', 'methode_paiement',
                    'date_paiement')
    search_fields = ('contrat__numero_police', 'reference_transaction')
    list_filter = ('status', 'methode_paiement', 'date_paiement')
    ordering = ('-created_at',)
    date_hierarchy = 'date_paiement'

    def get_apporteur(self, obj):
        return obj.contrat.apporteur.get_full_name()

    get_apporteur.short_description = 'Apporteur'

    fieldsets = (
        ('Contrat', {
            'fields': ('contrat',)
        }),
        ('Montants', {
            'fields': ('montant_commission', 'montant_verse')
        }),
        ('Paiement', {
            'fields': ('status', 'methode_paiement', 'reference_transaction', 'numero_compte')
        }),
        ('Validation', {
            'fields': ('date_paiement', 'date_validation', 'validated_by', 'notes')
        }),
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(HistoriquePaiement)
class HistoriquePaiementAdmin(admin.ModelAdmin):
    list_display = ('paiement', 'action', 'effectue_par', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('paiement__contrat__numero_police', 'details')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'


@admin.register(RecapitulatifCommissions)
class RecapitulatifCommissionsAdmin(admin.ModelAdmin):
    list_display = ('apporteur', 'mois', 'nombre_contrats', 'total_primes_ttc', 'total_commissions', 'total_en_attente')
    list_filter = ('apporteur', 'mois')
    search_fields = ('apporteur__username', 'apporteur__first_name', 'apporteur__last_name')
    ordering = ('-mois',)
    date_hierarchy = 'mois'