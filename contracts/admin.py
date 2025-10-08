from django.contrib import admin
from .models import Client, Vehicule, Contrat


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('nom_complet', 'telephone', 'adresse', 'code_askia', 'created_by', 'created_at')
    search_fields = ('prenom', 'nom', 'telephone', 'code_askia')
    list_filter = ('created_by', 'created_at')
    ordering = ('-created_at',)

    fieldsets = (
        ('Informations personnelles', {
            'fields': ('prenom', 'nom', 'telephone', 'adresse', 'email')
        }),
        ('Informations système', {
            'fields': ('code_askia', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at', 'code_askia')


@admin.register(Vehicule)
class VehiculeAdmin(admin.ModelAdmin):
    list_display = ('immatriculation', 'marque', 'modele', 'categorie', 'carburant', 'puissance_fiscale')
    search_fields = ('immatriculation', 'modele')
    list_filter = ('categorie', 'carburant', 'marque')
    ordering = ('-created_at',)

    fieldsets = (
        ('Identification', {
            'fields': ('immatriculation', 'marque', 'modele')
        }),
        ('Caractéristiques', {
            'fields': ('categorie', 'sous_categorie', 'charge_utile', 'puissance_fiscale', 'nombre_places', 'carburant')
        }),
        ('Valeurs', {
            'fields': ('valeur_neuve', 'valeur_venale')
        }),
    )
    readonly_fields = ('created_at',)


@admin.register(Contrat)
class ContratAdmin(admin.ModelAdmin):
    list_display = ('numero_police', 'client', 'vehicule', 'apporteur', 'prime_ttc', 'status', 'date_effet')
    search_fields = ('numero_police', 'client__nom', 'client__prenom', 'vehicule__immatriculation')
    list_filter = ('status', 'apporteur', 'date_effet', 'duree')
    ordering = ('-created_at',)
    date_hierarchy = 'date_effet'

    fieldsets = (
        ('Informations principales', {
            'fields': ('numero_police', 'client', 'vehicule', 'apporteur', 'status')
        }),
        ('Période', {
            'fields': ('duree', 'date_effet', 'date_echeance')
        }),
        ('Tarification', {
            'fields': ('prime_nette', 'accessoires', 'fga', 'taxes', 'prime_ttc')
        }),
        ('Commission', {
            'fields': ('commission_apporteur', 'net_a_reverser')
        }),
        ('Données API', {
            'fields': ('id_saisie_askia', 'askia_response'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at', 'emis_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ('created_at', 'updated_at', 'commission_apporteur', 'net_a_reverser')

    def save_model(self, request, obj, form, change):
        obj.calculate_commission()
        super().save_model(request, obj, form, change)