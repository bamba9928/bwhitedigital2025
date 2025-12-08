# payments/bictorys_client.py

import logging
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


class BictorysClient:
    """
    Client simple pour l'intégration Checkout de Bictorys.

    - POST /pay/v1/charges avec la clé PUBLIQUE (X-Api-Key)
    - Si payment_type est omis : redirection vers la page Checkout Bictorys
      où le client choisit (carte, OM, Wave, etc.)
    """

    def __init__(self) -> None:
        # URL de base : .env peut définir soit BICTORYS_BASE_URL soit BICTORYS_API_BASE_URL.
        raw_base_url = (
            getattr(settings, "BICTORYS_BASE_URL", None)
            or getattr(settings, "BICTORYS_API_BASE_URL", "https://api.test.bictorys.com")
        )
        # On supprime un éventuel "/" final pour éviter les "//" dans les URLs
        self.base_url = raw_base_url.rstrip("/")

        # Clé publique Bictorys (obligatoire pour /pay/v1/charges en Checkout)
        self.public_key = getattr(settings, "BICTORYS_PUBLIC_KEY", "")

        # Timeout pour les appels HTTP
        self.timeout = getattr(settings, "BICTORYS_TIMEOUT", 15)

    def _build_payment_reference(self, paiement) -> str:
        """
        Référence utilisée par Bictorys et renvoyée dans le webhook.
        Exemple: BWHITE_PAY_42
        """
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
        # Tu pourras mettre une page dédiée "échec" plus tard
        error_url = success_url

        # ==========================
        # Construction du customerObject
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
            phone_str = str(phone).strip()
            if not phone_str.startswith("+"):
                phone_str = f"+221{phone_str}"
            customer_obj["phone"] = phone_str

        email = getattr(client, "email", "")
        if email:
            customer_obj["email"] = email

        # Pays & locale par défaut si on a un customerObject
        if customer_obj:
            customer_obj.setdefault("country", "SN")
            customer_obj.setdefault("locale", "fr-FR")

        # ==========================
        # Corps JSON conforme Checkout
        # ==========================
        data: dict[str, Any] = {
            "amount": amount,
            "currency": "XOF",
            "paymentReference": payment_reference,
            "successRedirectUrl": success_url,
            "errorRedirectUrl": error_url,
        }

        # merchantReference : identifiant interne (ici, l'id du contrat)
        contrat = getattr(paiement, "contrat", None)
        if contrat is not None and getattr(contrat, "id", None) is not None:
            data["merchantReference"] = str(contrat.id)

        if customer_obj:
            data["customerObject"] = customer_obj
            # Si tu veux que Bictorys puisse mettre à jour le profil client :
            # data["allowUpdateCustomer"] = True
            data["allowUpdateCustomer"] = False

        # ==========================
        # Query params (payment_type facultatif)
        # Pour un pur Checkout, NE PAS envoyer payment_type.
        # ==========================
        params: dict[str, str] = {}
        if payment_type:
            # ex: "card", "orange_money", "mtn_money", "free_money"
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
        logger.info("Réponse Bictorys /charges : %s", payload)

        # URL de paiement retournée par Bictorys
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

        # On stocke ce qu'on a dans le PaiementApporteur
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
        if not self.public_key:
            logger.error("BICTORYS_PUBLIC_KEY n'est pas configurée")
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
                    "X-Api-Key": self.public_key,
                    "Op-Token": paiement.op_token,  # utilisation de l'opToken
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
