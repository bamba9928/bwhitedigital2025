# payments/bictorys_client.py

import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


class BictorysClient:
    """
    Client simple pour l'intégration Checkout de Bictorys.

    - POST /pay/v1/charges avec la clé PUBLIQUE (X-API-Key)
    - Si payment_type est omis : redirection vers la page Checkout Bictorys
      où le client choisit (carte, OM, Wave, etc.)
    """

    def __init__(self) -> None:
        # D’après tes settings
        self.base_url = getattr(
            settings,
            "BICTORYS_API_BASE_URL",
            "https://api.test.bictorys.com ",  # Sandbox par défaut
        )
        self.public_key = settings.BICTORYS_PUBLIC_KEY
        self.timeout = getattr(settings, "BICTORYS_TIMEOUT", 15)

    def _build_payment_reference(self, paiement) -> str:
        """
        Référence utilisée par Bictorys et renvoyée dans le webhook.
        Exemple: BWHITE_PAY_42
        """
        return f"BWHITE_PAY_{paiement.pk}"

    def initier_paiement(self, paiement, request, payment_type: str | None = None) -> str | None:
        """
        Crée la charge Checkout et renvoie l'URL de paiement Bictorys.

        - Retourne l'URL de redirection si succès
        - Retourne None en cas d'erreur
        """
        if not self.public_key:
            logger.error("BICTORYS_PUBLIC_KEY n'est pas configurée")
            return None

        # On s'assure que le PaiementApporteur a un ID
        if not paiement.pk:
            paiement.save()

        # Montant en XOF (entier, pas de centimes)
        montant = Decimal(paiement.montant_a_payer or 0).quantize(Decimal("1"))
        amount = int(montant)
        if amount <= 0:
            logger.error(
                "Montant Bictorys invalide (<=0) pour PaiementApporteur #%s",
                paiement.pk,
            )
            return None

        payment_reference = self._build_payment_reference(paiement)

        # URLs de redirection après le paiement (interface Bictorys)
        success_url = request.build_absolute_uri(reverse("payments:mes_paiements"))
        error_url = success_url  # tu pourras mettre une autre page d'erreur plus tard

        # Infos client (facultatif, mais propre)
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

        # Corps JSON conforme à la doc
        # Tu choisis le mode "collect par montant" (amount) et non "invoiceId"
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

        # Query params (payment_type facultatif)
        params: dict = {}
        if payment_type:
            # ex: "card", "orange_money", "mtn_money", "free_money"
            params["payment_type"] = payment_type

        try:
            resp = requests.post(
                f"{self.base_url}/pay/v1/charges",
                params=params,
                json=data,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "X-API-Key": self.public_key,  # Nom exact d’après la doc
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
        logger.info("Réponse Bictorys /charges : %s", payload)

        # La doc parle d’un lien de confirmation / lien de paiement
        payment_url = (
            payload.get("redirectUrl")
            or payload.get("checkoutUrl")
            or payload.get("url")
        )
        if not payment_url:
            logger.error("Réponse Bictorys sans URL de paiement : %s", payload)
            return None

        # ID de la charge
        charge_id = payload.get("id") or payload.get("chargeId")

        # opToken (souvent dans un objet de type CheckoutLinkObject)
        op_token = payload.get("opToken")
        if not op_token:
            checkout = payload.get("checkoutLinkObject") or {}
            op_token = checkout.get("opToken")

        # On stocke ce qu'on a
        update_fields = ["updated_at"]
        if charge_id:
            paiement.reference_transaction = charge_id
            update_fields.append("reference_transaction")
        if op_token:
            paiement.op_token = op_token
            update_fields.append("op_token")

        if len(update_fields) > 1:
            paiement.save(update_fields=update_fields)

        return payment_url

    def recuperer_charge(self, paiement) -> dict | None:
        """
        Relit l'état d'une charge Bictorys via GET /pay/v1/charges/{chargeId}.
        Nécessite reference_transaction (chargeId) et op_token.
        """
        if not self.public_key:
            logger.error("BICTORYS_PUBLIC_KEY n'est pas configurée")
            return None

        if not paiement.reference_transaction or not paiement.op_token:
            logger.error(
                "Paiement #%s sans reference_transaction ou op_token, impossible d'appeler GET /charges.",
                paiement.pk,
            )
            return None

        try:
            resp = requests.get(
                f"{self.base_url}/pay/v1/charges/{paiement.reference_transaction}",
                headers={
                    "accept": "application/json",
                    "X-Api-Key": self.public_key,
                    "Op-Token": paiement.op_token,  # <- utilisation de l'opToken
                },
                timeout=self.timeout,
            )
        except Exception as exc:
            logger.error("Erreur réseau Bictorys GET /charges/{id} : %s", exc)
            return None

        if not resp.ok:
            logger.error(
                "Erreur Bictorys GET /charges/%s (%s) : %s",
                paiement.reference_transaction,
                resp.status_code,
                resp.text,
            )
            return None

        data = resp.json()
        logger.info("Charge Bictorys relue pour paiement #%s : %s", paiement.pk, data)
        return data


bictorys_client = BictorysClient()