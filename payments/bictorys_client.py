import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


class BictorysClient:
    """
    Client simple pour l'intégration Checkout de Bictorys.
    - POST /pay/v1/charges avec la clé PUBLIQUE (X-Api-Key)
    - Bictorys renvoie une URL de paiement vers laquelle on redirige l'apporteur
    """

    def __init__(self) -> None:
        self.base_url = getattr(
            settings,
            "BICTORYS_API_BASE_URL",
            "https://api.test.bictorys.com",
        )
        self.public_key = settings.BICTORYS_PUBLIC_KEY
        self.timeout = getattr(settings, "BICTORYS_TIMEOUT", 15)

    def _build_payment_reference(self, paiement) -> str:
        """
        Référence utilisée par Bictorys et renvoyée dans le webhook.
        Exemple: BWHITE_PAY_42
        """
        return f"BWHITE_PAY_{paiement.pk}"

    def initier_paiement(self, paiement, request) -> str | None:
        """
        Crée la charge Checkout et renvoie l'URL de paiement.
        Retourne None en cas d'erreur.
        """
        if not self.public_key:
            logger.error("BICTORYS_PUBLIC_KEY n'est pas configurée")
            return None

        # On s'assure que le paiement a un ID
        if not paiement.pk:
            paiement.save()

        # Montant en XOF (entier)
        montant = Decimal(paiement.montant_a_payer or 0).quantize(Decimal("1"))
        amount = int(montant)

        payment_reference = self._build_payment_reference(paiement)

        success_url = request.build_absolute_uri(
            reverse("payments:mes_paiements")
        )
        error_url = success_url

        client = paiement.contrat.client
        customer_obj: dict[str, str] = {}

        nom_complet = getattr(client, "nom_complet", "") or (
            f"{getattr(client, 'prenom', '')} {getattr(client, 'nom', '')}".strip()
        )
        if nom_complet:
            customer_obj["name"] = nom_complet

        phone = getattr(client, "telephone", "") or getattr(client, "phone", "")
        if phone:
            phone = str(phone).strip()
            if not phone.startswith("+"):
                phone = f"+221{phone}"
            customer_obj["phone"] = phone

        email = getattr(client, "email", "")
        if email:
            customer_obj["email"] = email

        data: dict = {
            "amount": amount,
            "currency": "XOF",
            "country": "SN",
            "paymentReference": payment_reference,
            "successRedirectUrl": success_url,
            "errorRedirectUrl": error_url,
        }
        if customer_obj:
            data["customerObject"] = customer_obj

        try:
            resp = requests.post(
                f"{self.base_url}/pay/v1/charges",
                json=data,
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": self.public_key,
                },
                timeout=self.timeout,
            )
        except Exception as exc:
            logger.error("Erreur réseau Bictorys /charges : %s", exc)
            return None

        if not resp.ok:
            logger.error(
                "Erreur Bictorys /charges (%s) : %s",
                resp.status_code,
                resp.text,
            )
            return None

        payload = resp.json()

        payment_url = (
            payload.get("redirectUrl")
            or payload.get("checkoutUrl")
            or payload.get("url")
        )
        if not payment_url:
            logger.error("Réponse Bictorys sans URL de paiement : %s", payload)
            return None

        charge_id = payload.get("id") or payload.get("chargeId")
        if charge_id:
            paiement.reference_transaction = charge_id
            paiement.save(update_fields=["reference_transaction", "updated_at"])

        return payment_url


bictorys_client = BictorysClient()
