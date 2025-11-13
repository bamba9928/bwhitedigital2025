from decimal import Decimal
from django.contrib import admin
from .models import PaiementApporteur, HistoriquePaiement


# --- ADMIN DE PAIEMENT APPORTEUR ---

@admin.register(PaiementApporteur)
class PaiementApporteurAdmin(admin.ModelAdmin):
    list_display = (
        "contrat",
        "get_apporteur",
        "montant_a_payer",
        "status",
        "methode_paiement",
        "created_at",
    )
    list_select_related = ("contrat", "contrat__apporteur")

    search_fields = (
        "contrat__numero_police",
        "reference_transaction",
        "contrat__client__prenom",
        "contrat__client__nom",
        "contrat__apporteur__first_name",
        "contrat__apporteur__last_name",
    )

    list_filter = ("status", "methode_paiement", "created_at")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at", "contrat", "montant_a_payer")
    autocomplete_fields = ["contrat"]

    fieldsets = (
        ("Contrat", {"fields": ("contrat",)}),
        ("Montant dû", {"fields": ("montant_a_payer",)}),
        (
            "Déclaration (par l'apporteur)",
            {
                "fields": (
                    "methode_paiement",
                    "reference_transaction",
                    "numero_compte",
                ),
                "description": "Informations fournies par l'apporteur lors de sa déclaration.",
            },
        ),
        ("Statut et notes (Admin)", {"fields": ("status", "notes")}),
        ("Meta", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Apporteur", ordering="contrat__apporteur")
    def get_apporteur(self, obj):
        """Affiche le nom complet de l'apporteur lié au contrat."""
        a = getattr(obj.contrat, "apporteur", None)
        return a.get_full_name() if a else "-"


# --- ADMIN D'HISTORIQUE PAIEMENT ---
@admin.register(HistoriquePaiement)
class HistoriquePaiementAdmin(admin.ModelAdmin):
    list_display = ("paiement", "action", "effectue_par", "created_at")
    list_filter = ("action", "created_at")

    list_select_related = ("paiement", "effectue_par", "paiement__contrat")

    search_fields = ("paiement__contrat__numero_police", "details")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
