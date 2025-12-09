import logging
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


class BictorysClient:
    """
    Client simple pour l'intégration Checkout de Bictorys (côté backend).

    - POST /pay/v1/charges avec la CLÉ SECRÈTE (X-API-Key)
    - Si payment_type est omis : redirection vers la page Checkout Bictorys
      où le client choisit (carte, OM, Wave, etc.)
    """

    def __init__(self) -> None:
        # URL de base : BICTORYS_BASE_URL doit être défini dans .env
        raw_base_url = (
            getattr(settings, "BICTORYS_BASE_URL", None)
            or "https://api.test.bictorys.com"  # fallback de sécurité
        )
        # On supprime un éventuel "/" final pour éviter les "//" dans les URLs
        self.base_url = raw_base_url.rstrip("/")

        # Clé SECRÈTE Bictorys pour les appels serveur -> API
        self.api_key = getattr(settings, "BICTORYS_SECRET_KEY", "")

        # Timeout pour les appels HTTP
        self.timeout = getattr(settings, "BICTORYS_TIMEOUT", 15)

    def _build_payment_reference(self, paiement) -> str:
        """Référence utilisée par Bictorys et renvoyée dans le webhook."""
        return f"BWHITE_PAY_{paiement.pk}"

    def initier_paiement(
        self,
        paiement,
        request,
        payment_type: str | None = None,
    ) -> str | None:
        """
        Crée la charge Checkout et renvoie l'URL de paiement Bictorys.

        - Retourne l'URL de redirection si succès
        - Retourne None en cas d'erreur
        """
        if not self.api_key:
            logger.error("BICTORYS_SECRET_KEY n'est pas configurée")
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
        error_url = success_url  # TODO: page dédiée "échec" si besoin

        # ==========================
        # customerObject
        # ==========================
        client = paiement.contrat.client
        customer_obj: dict[str, str] = {}

        nom_complet = getattr(client, "nom_complet", "") or (
            f"{getattr(client, 'prenom', '')} {getattr(client, 'nom', '')}".strip()
        )
        if nom_complet:
            customer_obj["name"] = nom_complet

        phone = getattr(client, "telephone", "") or getattr(client, "phone", "")
        if phone:
            phone_str = str(phone).strip().replace(" ", "")
            if not phone_str.startswith("+"):
                phone_str = f"+221{phone_str}"
            customer_obj["phone"] = phone_str

        email = getattr(client, "email", "")
        if email:
            customer_obj["email"] = email

        if customer_obj:
            customer_obj.setdefault("country", "SN")
            customer_obj.setdefault("locale", "fr-FR")

        # ==========================
        # Corps JSON
        # ==========================
        data: dict[str, Any] = {
            "amount": amount,
            "currency": "XOF",
            "paymentReference": payment_reference,
            "successRedirectUrl": success_url,
            "errorRedirectUrl": error_url,
        }

        contrat = getattr(paiement, "contrat", None)
        if contrat is not None and getattr(contrat, "id", None) is not None:
            # Assurons-nous que c'est bien une string propre
            data["merchantReference"] = str(contrat.id)

        if customer_obj:
            data["customerObject"] = customer_obj
            data["allowUpdateCustomer"] = True

        # ==========================
        # Query params (payment_type facultatif)
        # ==========================
        params: dict[str, str] = {}
        if payment_type:
            params["payment_type"] = payment_type

        # ==========================
        # Appel HTTP vers /pay/v1/charges
        # ==========================
        try:
            resp = requests.post(
                f"{self.base_url}/pay/v1/charges",
                params=params,
                json=data,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self.api_key,
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

        payment_url = (
            payload.get("redirectUrl")
            or payload.get("checkoutUrl")
            or payload.get("url")
        )
        if not payment_url:
            logger.error("Réponse Bictorys sans URL de paiement : %s", payload)
            return None

        charge_id = payload.get("id") or payload.get("chargeId")

        op_token = payload.get("opToken")
        if not op_token:
            checkout = payload.get("checkoutLinkObject") or {}
            op_token = checkout.get("opToken")

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
        Relit l'état d'une charge Bictorys via:
            GET /pay/v1/charges/{chargeId}

        Nécessite reference_transaction (chargeId) ET op_token.
        """
        if not self.api_key:
            logger.error("BICTORYS_SECRET_KEY n'est pas configurée")
            return None

        if not paiement.reference_transaction or not paiement.op_token:
            logger.error(
                "Paiement #%s sans reference_transaction ou op_token, "
                "impossible d'appeler GET /charges.",
                paiement.pk,
            )
            return None

        try:
            resp = requests.get(
                f"{self.base_url}/pay/v1/charges/{paiement.reference_transaction}",
                headers={
                    "Accept": "application/json",
                    "X-API-Key": self.api_key,
                    "Op-Token": paiement.op_token,
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