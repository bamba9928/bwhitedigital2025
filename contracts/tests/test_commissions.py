from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from contracts.models import Contrat, Client, Vehicule
from django.utils import timezone

User = get_user_model()


class CommissionCalculationTest(TestCase):
    def setUp(self):
        self.client = Client.objects.create(prenom="Test", nom="Client", telephone="770000000", adresse="Dakar")
        self.vehicule = Vehicule.objects.create(immatriculation="DK-1234-AA", marque="M00001", modele="COROLLA",
                                                categorie="510", puissance_fiscale=8, nombre_places=5,
                                                carburant="E00001")

        # Création des utilisateurs types
        self.admin = User.objects.create_user(username="admin", role="ADMIN")
        self.apporteur_platine = User.objects.create_user(username="platine", role="APPORTEUR", grade="PLATINE")
        self.apporteur_freemium = User.objects.create_user(username="freemium", role="APPORTEUR", grade="FREEMIUM")

    def test_commission_platine(self):
        """Test calcul pour un apporteur PLATINE (18% + 2000)"""
        contrat = Contrat(
            client=self.client, vehicule=self.vehicule, apporteur=self.apporteur_platine,
            prime_nette=Decimal("100000"), prime_ttc=Decimal("125000"),
            date_effet=timezone.now().date(), duree=12
        )
        contrat.save()  # Déclenche calculate_commission

        # Askia donne: 20% de 100000 + 3000 = 23000
        self.assertEqual(contrat.commission_askia, Decimal("23000.00"))
        # Platine reçoit: 18% de 100000 + 2000 = 20000
        self.assertEqual(contrat.commission_apporteur, Decimal("20000.00"))
        # Profit BWHITE: 23000 - 20000 = 3000
        self.assertEqual(contrat.commission_bwhite, Decimal("3000.00"))
        # Net à reverser: 125000 - 23000 = 102000
        self.assertEqual(contrat.net_a_reverser, Decimal("102000.00"))

    def test_commission_admin(self):
        """Test calcul pour un ADMIN (Apporteur reçoit 0)"""
        contrat = Contrat(
            client=self.client, vehicule=self.vehicule, apporteur=self.admin,
            prime_nette=Decimal("100000"), prime_ttc=Decimal("125000"),
            date_effet=timezone.now().date(), duree=12
        )
        contrat.save()

        self.assertEqual(contrat.commission_askia, Decimal("23000.00"))
        self.assertEqual(contrat.commission_apporteur, Decimal("0.00"))
        # BWHITE garde tout
        self.assertEqual(contrat.commission_bwhite, Decimal("23000.00"))