from decimal import Decimal
from django.contrib import admin
from .models import PaiementApporteur, HistoriquePaiement


# --- ADMIN DE PAIEMENT APPORTEUR ---

@admin.register(PaiementApporteur)
class PaiementApporteurAdmin(admin.ModelAdmin):

    list_display = (
        'contrat',
        'get_apporteur',
        'montant_a_payer',
        'status',
        'methode_paiement',
        'created_at',
    )


    search_fields = (
        'contrat__numero_police',
        'reference_transaction',
        'contrat__client__prenom',
        'contrat__client__nom',
        'contrat__apporteur__first_name',
        'contrat__apporteur__last_name',
    )


    list_filter = ('status', 'methode_paiement', 'created_at')

    ordering = ('-created_at',)
    date_hierarchy = 'created_at'


    readonly_fields = ('created_at', 'updated_at')


    fieldsets = (
        ('Contrat', {
            'fields': ('contrat',)
        }),
        ('Montant dû', {

            'fields': ('montant_a_payer',)
        }),
        ('Déclaration', {
            'fields': ('methode_paiement', 'reference_transaction', 'numero_compte')
        }),
        ('Statut et notes', {
            'fields': ('status', 'notes')
        }),
        ('Meta', {
            'fields': ('created_at', 'updated_at')
        }),
    )


    def get_apporteur(self, obj):
        """Affiche le nom complet de l'apporteur lié au contrat."""
        a = getattr(obj.contrat, 'apporteur', None)
        return a.get_full_name() if a else '-'

    get_apporteur.short_description = 'Apporteur'

# --- ADMIN D'HISTORIQUE PAIEMENT ---

@admin.register(HistoriquePaiement)
class HistoriquePaiementAdmin(admin.ModelAdmin):

    list_display = ('paiement', 'action', 'effectue_par', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('paiement__contrat__numero_police', 'details')
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'