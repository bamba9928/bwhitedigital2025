import requests
from django.conf import settings
from decimal import Decimal, InvalidOperation
import logging
import time
import re
from datetime import datetime, date
from typing import Dict, Any, Optional, List, Tuple, Union

logger = logging.getLogger(__name__)

REGION_PREFIXES = (
    "AB",
    "AC",
    "DK",
    "TH",
    "SL",
    "DB",
    "LG",
    "TC",
    "KL",
    "KD",
    "ZG",
    "FK",
    "KF",
    "KG",
    "MT",
    "SD",
    "DL",
)

r"^(" + "|".join(REGION_PREFIXES) + r")-?\d{4}-?[A-Z]{2}$"

PATTERNS = {
    "REGIONAL": re.compile("^({'|'.join(REGION_PREFIXES)})-?\d{{4}}-?[A-Z]{{1,2}}$"),
    "ANCIEN": re.compile(r"^[A-Z]{2}-?\d{3}-?[A-Z]{2}$"),
    "AD": re.compile(r"^AD-?\d{4}$"),
    "EX": re.compile(r"^\d{4}-?EX$"),
    "EP": re.compile(r"^\d{4}-?EP\d{2}$"),
    "AP": re.compile(r"^\d{3}-?AP-?\d{4}$"),
    "TT": re.compile(r"^\d{4}-?TT-?[A-Z]$"),
    "AD_TT": re.compile(r"^AD\d{4}-?TT-?[A-Z]$"),
    "CH": re.compile(r"^CH-?\d{6}$"),
}


def _canon_immat(s: str) -> str:
    s = (s or "").upper()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", "", s)
    if re.search(r"[^A-Z0-9\-]", s):
        raise ValueError("Caractères non autorisés dans l'immatriculation")
    return s


def _format_immat_for_askia(v: str, typ: str) -> str:
    raw = v.replace("-", "")
    if typ == "REGIONAL":  # AB0000CD -> AB-0000-CD
        return "{raw[:2]}-{raw[2:6]}-{raw[6:]}"
    if typ == "ANCIEN":  # AA001BB -> AA-001-BB
        return "{raw[:2]}-{raw[2:5]}-{raw[5:]}"
    if typ == "AD":  # AD0001 -> AD-0001
        return "{raw[:2]}-{raw[2:]}"
    if typ == "EX":  # 0001EX -> 0001-EX
        return "{raw[:4]}-EX"
    if typ == "EP":  # 0001EP01 -> 0001-EP01
        return "{raw[:4]}-EP{raw[6:]}" if "-" in v else "{raw[:4]}-{raw[4:]}"
    if typ == "AP":  # 001AP0001 -> 001-AP-0001
        return "{raw[:3]}-AP-{raw[5:]}"
    if typ == "TT":  # 0001TTA -> 0001-TT-A
        return "{raw[:4]}-TT-{raw[-1]}"
    if typ == "AD_TT":  # AD0001TTA -> AD0001-TT-A
        return "{raw[:6]}-TT-{raw[-1]}"
    if typ == "CH":  # CH000001 -> CH-000001
        return "{raw[:2]}-{raw[2:]}"
    return v  # fallback


def _detect_immat_type(v: str) -> str | None:
    for typ, rx in PATTERNS.items():
        if rx.fullmatch(v):
            return typ
    return None


# Remplace la méthode existante
def _validate_immatriculation(self, immat: str) -> str:
    """
    Valide tous les formats SN supportés et renvoie la forme avec tirets pour Askia.
    Formats: Régional (DK-0001-BB), Ancien (AA-001-AA), AD, EX, EP, AP, TT, AD_TT, CH.
    """
    if not immat:
        raise ValueError("Immatriculation requise")

    v = _canon_immat(immat)
    typ = _detect_immat_type(v)
    if not typ:
        raise ValueError(
            "Format d'immatriculation invalide: '{immat}'. "
            "Formats acceptés: DK-0001-BB, AA-001-AA, AD-0001, 0001-EX, 0001-EP01, "
            "001-AP-0001, 0001-TT-A, AD0001-TT-A, CH-000001"
        )
    return _format_immat_for_askia(v, typ)


class AskiaAPIClient:
    """Client pour communiquer avec l'API ASKIA."""

    def __init__(self):
        self.base_url = settings.ASKIA_BASE_URL
        self.headers = {
            "Accept": "application/json",
            "appClient": settings.ASKIA_APP_CLIENT,
        }
        self.pv_code = str(settings.ASKIA_PV_CODE)
        self.br_code = str(settings.ASKIA_BR_CODE)

    def _mask_sensitive_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Masque les données sensibles dans un dictionnaire (récursif)."""
        if not isinstance(data, dict):
            return data

        masked = {}
        sensitive_keys = ["numtel", "email", "numident", "telephone", "numero_piece"]

        for key, value in data.items():
            if key.lower() in sensitive_keys:
                masked[key] = "*****"
            elif isinstance(value, dict):
                masked[key] = self._mask_sensitive_data(value)
            elif isinstance(value, list):
                masked[key] = [
                    self._mask_sensitive_data(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                masked[key] = value

        return masked

    def _clean_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Nettoie les paramètres en retirant les valeurs None."""
        return {k: v for k, v in params.items() if v is not None}

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        timeout: int = 30,
        max_retries: int = 2,
        allow_retry: bool = True,
    ) -> dict[str, Any]:
        """
        Appel API ASKIA avec gestion robuste des erreurs réseau et métier.

        Args:
            endpoint: Point de terminaison de l'API.
            method: Méthode HTTP (GET ou POST).
            params: Paramètres de la requête.
            timeout: Délai d'attente en secondes.
            max_retries: Nombre maximal de tentatives en cas d'échec.
            allow_retry: Autorise les retries en cas d'erreur.

        Returns:
            Réponse JSON de l'API.

        Raises:
            Exception: En cas d'erreur réseau, HTTP ou métier.
        """
        url = "{self.base_url}/{endpoint}"
        method = (method or "GET").upper()

        # Nettoyage des paramètres
        params = self._clean_params(params or {})
        safe_params = self._mask_sensitive_data(params)

        retries = max_retries if allow_retry else 0
        resp = None

        for attempt in range(retries + 1):
            try:
                if method == "GET":
                    resp = requests.get(
                        url, headers=self.headers, params=params, timeout=timeout
                    )
                else:
                    headers = {**self.headers, "Content-Type": "application/json"}
                    resp = requests.post(
                        url, headers=headers, json=params, timeout=timeout
                    )
                break
            except requests.exceptions.Timeout as e:
                if attempt < retries:
                    wait_time = (attempt + 1) * 2
                    logger.warning(
                        "Timeout API Askia %s (tentative %d/%d) | Nouvelle tentative dans %ds",
                        endpoint,
                        attempt + 1,
                        retries + 1,
                        wait_time,
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        "Timeout API Askia %s après %d tentatives | %s | params=%s",
                        endpoint,
                        retries + 1,
                        e,
                        safe_params,
                    )
                    raise Exception(
                        "Délai d'attente dépassé pour l'API Askia après {retries + 1} tentatives"
                    )
            except requests.exceptions.RequestException as e:
                logger.error(
                    "Erreur réseau API Askia %s | %s | params=%s",
                    endpoint,
                    e,
                    safe_params,
                )
                raise Exception("Erreur réseau vers l'API Askia: {e}")

        # Vérification du statut HTTP
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            try:
                preview = resp.json()
            except Exception:
                preview = resp.text[:400] if resp.text else ""
            logger.error(
                "HTTP %s sur %s | body=%s | params=%s",
                resp.status_code,
                endpoint,
                preview,
                safe_params,
            )
            raise Exception("Erreur HTTP Askia {resp.status_code}")

        # Parsing JSON
        try:
            data = resp.json()
        except ValueError:
            logger.error("Réponse non-JSON sur %s | body=%s", endpoint, resp.text[:400])
            raise Exception("Réponse API Askia invalide (non JSON)")

        # Détection d'erreurs métier
        if isinstance(data, dict):
            status_raw = str(data.get("status", "")).upper()
            error_val = data.get("error")
            code_raw = data.get("code")
            message = data.get("message") or data.get("msg")

            if message and "contrat en cours" in message.lower():
                logger.error(
                    "Erreur métier Askia (contrat existant) sur %s | msg=%s | params=%s",
                    endpoint,
                    message,
                    safe_params,
                )
                raise Exception("Contrat existant : {message}")

            flags_false = (
                data.get("success") is False
                or data.get("statut") is False
                or status_raw in {"KO", "ERROR", "NOK", "FAIL"}
                or (
                    isinstance(error_val, (str, int))
                    and str(error_val) not in {"", "0", "None"}
                )
            )
            code_bad = (code_raw is not None) and (
                str(code_raw).strip() not in {"", "0", "None", "OK", "SUCCESS"}
            )

            if flags_false or code_bad:
                msg = (
                    message
                    or (error_val if isinstance(error_val, str) and error_val else None)
                    or data.get("detail")
                    or "Erreur métier Askia"
                )
                logger.error(
                    "Erreur métier Askia sur %s | msg=%s | data=%s | params=%s",
                    endpoint,
                    msg,
                    self._mask_sensitive_data(data),
                    safe_params,
                )
                raise Exception("Erreur métier Askia : {msg}")

        return data

    def _safe_decimal(self, value: Any, default: Decimal = Decimal("0")) -> Decimal:
        """Convertit une valeur en Decimal de manière sécurisée."""
        if value is None or value == "":
            return default
        try:
            return Decimal(str(value))
        except (ValueError, InvalidOperation):
            logger.warning("Conversion Decimal échouée pour: %s", value)
            return default

    # --------------------------
    # Simulation Automobile
    # --------------------------
    def get_simulation_auto(
        self, vehicule_data: dict[str, Any], duree: int
    ) -> dict[str, Decimal | str]:
        """
        Obtient une simulation tarifaire pour un véhicule.

        Args:
            vehicule_data: Dictionnaire contenant les données du véhicule.
            duree: Durée de la simulation en mois.

        Returns:
            Dictionnaire contenant les résultats de la simulation.

        Raises:
            ValueError: Si des champs obligatoires sont manquants.
        """
        # Validation
        if not vehicule_data.get("categorie"):
            raise ValueError("Catégorie véhicule requise pour simulation")
        if not vehicule_data.get("carburant"):
            raise ValueError("Type de carburant requis pour simulation")

        puissance = max(1, int(vehicule_data.get("puissance_fiscale") or 1))
        nb_places = max(1, int(vehicule_data.get("nombre_places") or 1))

        params = {
            "cat": vehicule_data["categorie"],
            "scatCode": vehicule_data.get("sous_categorie", "000"),
            "nrg": vehicule_data["carburant"],
            "pfs": puissance,
            "nbP": nb_places,
            "dure": duree,
            "vaf": str(self._safe_decimal(vehicule_data.get("valeur_neuve"))),
            "vvn": str(self._safe_decimal(vehicule_data.get("valeur_venale"))),
            "recour": int(vehicule_data.get("recour", 0)),
            "avr": int(vehicule_data.get("avr", 0)),
            "vol": int(vehicule_data.get("vol", 0)),
            "inc": int(vehicule_data.get("inc", 0)),
            "pt": int(vehicule_data.get("pt", 0)),
            "gb": int(vehicule_data.get("gb", 0)),
            "renv": int(vehicule_data.get("renv", 0)),
        }

        # CORRECTION: chrgUtil seulement pour catégorie 520 (Utilitaires)
        if vehicule_data["categorie"] == "520":
            params["chrgUtil"] = int(vehicule_data.get("charge_utile") or 3500)

        result = self._make_request("srwb/automobile", params=params)

        return {
            "prime_nette": self._safe_decimal(result.get("primenette")),
            "accessoires": self._safe_decimal(result.get("accessoire")),
            "fga": self._safe_decimal(result.get("fga")),
            "taxes": self._safe_decimal(result.get("taxe")),
            "prime_ttc": self._safe_decimal(result.get("primettc")),
            "commission": self._safe_decimal(result.get("commission")),
            "id_saisie": result.get("idSaisie", ""),
            "raw_response": result,
        }

    # --------------------------
    # Client
    # --------------------------
    def create_client(self, client_data: dict[str, Any]) -> str:
        """
        Crée un client dans le système ASKIA et retourne son code.

        Args:
            client_data: Dictionnaire contenant les données du client.

        Returns:
            Code du client créé.

        Raises:
            ValueError: Si des champs obligatoires sont manquants.
            Exception: En cas d'erreur API.
        """
        # Validation
        if not client_data.get("nom") or not client_data.get("prenom"):
            raise ValueError("Nom et prénom requis pour créer un client")
        if not client_data.get("telephone"):
            raise ValueError("Numéro de téléphone requis pour créer un client")

        params = {
            "pvCode": self.pv_code,
            "nom": client_data["nom"],
            "pnom": client_data["prenom"],
            "numident": client_data.get("numero_piece", ""),
            "numtel": client_data["telephone"],
            "email": client_data.get("email", ""),
            "adresse": client_data.get("adresse", ""),
            "paysCode": "P00001",
            "dtNaissance": client_data.get("date_naissance", "01/01/1990"),
        }

        result = self._make_request("srwbclient/createclient", params=params)

        cli_code = result.get("cliCode") or result.get("cliNumero")
        if not cli_code:
            logger.error("Échec création client Askia. Réponse brute: %s", result)
            raise Exception("Aucun code client retourné par Askia")

        logger.info(
            "Client créé avec succès | Code=%s | Nom=%s %s",
            cli_code,
            client_data["nom"],
            client_data["prenom"],
        )
        return cli_code

    def get_client(self, client_code: str) -> dict[str, Any]:
        """
        Récupère les informations d'un client depuis ASKIA.

        Args:
            client_code: Code du client.

        Returns:
            Dictionnaire contenant les informations du client.
        """
        params = {"cliCode": client_code}
        return self._make_request("srwbclient/getclient", params=params)

    # --------------------------
    # Contrat Automobile
    # --------------------------

    def verify_contrat_exists(self, numero_facture: str) -> dict[str, Any] | None:
        """
        Vérifie si un contrat existe déjà dans Askia.

        Returns:
            Dict avec infos du contrat si existe, None sinon
        """
        try:
            result = self._make_request(
                "quittance/getfacture",
                params={"numeroFacture": numero_facture},
                timeout=10,
                allow_retry=False,
            )
            if result and result.get("numeroPolice"):
                logger.info(
                    "Contrat existant détecté | Facture=%s | Police=%s",
                    numero_facture,
                    result.get("numeroPolice"),
                )
                return result
            return None
        except Exception as e:
            logger.debug("Vérification contrat échouée (normal si inexistant): %s", e)
            return None

    def create_contrat_auto(
        self, contrat_data: dict[str, Any]
    ) -> dict[str, str | Decimal]:
        """
        Crée un contrat automobile dans ASKIA et récupère aussi ses documents.

        Args:
            contrat_data: Dictionnaire contenant les données du contrat.

        Returns:
            Dictionnaire contenant les résultats de la création du contrat.

        Raises:
            ValueError: Si des champs obligatoires sont manquants.
            Exception: En cas d'erreur API.
        """
        # Validation des champs obligatoires
        required_fields = [
            "client_code",
            "categorie",
            "carburant",
            "date_effet",
            "immatriculation",
            "marque",
            "modele",
            "duree",
        ]
        for field in required_fields:
            if not contrat_data.get(field):
                raise ValueError("Champ requis manquant : {field}")

        # Validation de l'immatriculation
        try:
            immat = self._validate_immatriculation(contrat_data["immatriculation"])
        except ValueError as e:
            logger.error("Validation immatriculation échouée: %s", e)
            raise

        # Conversion date effet
        effet_raw = contrat_data["date_effet"]
        try:
            if isinstance(effet_raw, date):
                effet = effet_raw
            elif isinstance(effet_raw, str):
                effet = datetime.strptime(effet_raw, "%Y-%m-%d").date()
            else:
                raise ValueError(
                    "Type de date non supporté: {type(effet_raw).__name__}"
                )
        except (ValueError, AttributeError) as e:
            logger.error(
                "Format date_effet invalide | Valeur=%s | Type=%s | Erreur=%s",
                effet_raw,
                type(effet_raw),
                e,
            )
            raise ValueError(
                "date_effet doit être une date valide au format YYYY-MM-DD ou un objet date Python "
                "(reçu: {type(effet_raw).__name__})"
            )

        # Vérification que la date n'est pas dans le passé
        aujourd_hui = datetime.now().date()
        if effet < aujourd_hui:
            raise ValueError(
                "La date d'effet ne peut pas être dans le passé. "
                "Date fournie: {effet.strftime('%d/%m/%Y')}, "
                "Date actuelle: {aujourd_hui.strftime('%d/%m/%Y')}"
            )

        # Vérification préventive si id_saisie existe
        id_saisie = contrat_data.get("id_saisie")
        if id_saisie:
            possible_factures = [
                "{datetime.now().year}{id_saisie}",
                id_saisie,
            ]

            for num_facture in possible_factures:
                existing = self.verify_contrat_exists(num_facture)
                if existing:
                    logger.warning(
                        "Contrat déjà créé | Facture=%s | Police=%s",
                        existing.get("numeroFacture"),
                        existing.get("numeroPolice"),
                    )
                    liens = existing.get("lien", {}) or {}
                    return {
                        "numero_police": existing.get("numeroPolice"),
                        "numero_facture": existing.get("numeroFacture"),
                        "numero_client": existing.get("numeroClient"),
                        "prime_ttc": self._safe_decimal(existing.get("primettc")),
                        "attestation": liens.get("linkAttestation", ""),
                        "carte_brune": liens.get("linkCarteBrune", ""),
                        "raw_response": existing,
                        "was_existing": True,
                    }

        # Construction des paramètres selon la doc Askia
        params = {
            "cliCode": contrat_data["client_code"],
            "cat": contrat_data["categorie"],
            "scatCode": contrat_data.get("sous_categorie", "000"),
            "carrCode": contrat_data.get("carrosserie", "07"),  # Par défaut "07"
            "nrg": contrat_data["carburant"],
            "pfs": max(1, int(contrat_data.get("puissance_fiscale") or 1)),
            "nbP": max(1, int(contrat_data.get("nombre_places") or 1)),
            "dure": contrat_data["duree"],
            "effet": effet.strftime("%d/%m/%Y"),
            "numImmat": immat,
            "mqCode": contrat_data["marque"],
            "modele": contrat_data["modele"],
            "vaf": str(self._safe_decimal(contrat_data.get("valeur_neuve"))),
            "vvn": str(self._safe_decimal(contrat_data.get("valeur_venale"))),
            "recour": int(contrat_data.get("recour", 0)),
            "vol": int(contrat_data.get("vol", 0)),
            "inc": int(contrat_data.get("inc", 0)),
            "pt": int(contrat_data.get("pt", 0)),
            "gb": int(contrat_data.get("gb", 0)),
        }

        # CORRECTION CRITIQUE: chrgUtil uniquement pour catégorie 520
        if contrat_data["categorie"] == "520":
            charge_utile = int(contrat_data.get("charge_utile") or 3500)
            params["chrgUtil"] = charge_utile

        if id_saisie:
            params["idSaisie"] = id_saisie

        # Tentative de création
        try:
            logger.info(
                "Tentative création contrat | Client=%s | Immat=%s | IdSaisie=%s",
                contrat_data["client_code"],
                immat,
                id_saisie,
            )

            result = self._make_request(
                "srwbauto/create",
                method="GET",
                params=params,
                timeout=90,
                allow_retry=False,
            )

        except Exception as timeout_error:
            # En cas de timeout, vérifier si le contrat a été créé
            if "timeout" in str(timeout_error).lower() and id_saisie:
                logger.warning("Timeout détecté | Vérification création dans 10s...")
                time.sleep(10)

                for num_facture in possible_factures:
                    existing = self.verify_contrat_exists(num_facture)
                    if existing:
                        logger.info(
                            "✅ Contrat créé malgré timeout | Facture=%s",
                            existing.get("numeroFacture"),
                        )
                        liens = existing.get("lien", {}) or {}
                        return {
                            "numero_police": existing.get("numeroPolice"),
                            "numero_facture": existing.get("numeroFacture"),
                            "numero_client": existing.get("numeroClient"),
                            "prime_ttc": self._safe_decimal(existing.get("primettc")),
                            "attestation": liens.get("linkAttestation", ""),
                            "carte_brune": liens.get("linkCarteBrune", ""),
                            "raw_response": existing,
                            "recovered_after_timeout": True,
                        }

                logger.error("Timeout confirmé sans création | Immat=%s", immat)
                raise Exception(
                    "Délai d'attente dépassé (90s). Le contrat n'a pas pu être créé. "
                    "Veuillez réessayer dans quelques instants."
                )
            else:
                raise

        # Vérification du format de réponse
        if not isinstance(result, dict):
            logger.error("Réponse API invalide (non dict) | Type: %s", type(result))
            raise Exception("Format de réponse API invalide")

        numero_police = result.get("numeroPolice")
        numero_facture = result.get("numeroFacture")

        if not numero_police or not numero_facture:
            logger.error(
                "Échec émission contrat | Payload=%s | Réponse=%s",
                self._mask_sensitive_data(params),
                result,
            )
            raise Exception(
                result.get("message")
                or result.get("msg")
                or "Échec émission: police/facture manquant"
            )

        logger.info(
            "✅ Contrat créé avec succès | Police=%s | Facture=%s | Client=%s",
            numero_police,
            numero_facture,
            contrat_data["client_code"],
        )

        # Récupération des documents
        liens = result.get("lien", {}) or {}
        attestation = liens.get("linkAttestation", "")
        carte_brune = liens.get("linkCarteBrune", "")

        if not (attestation or carte_brune):
            logger.warning(
                "Liens absents | Facture=%s | Tentative get_documents",
                numero_facture,
            )
            try:
                docs = self.get_documents(numero_facture)
                attestation = docs.get("attestation", "")
                carte_brune = docs.get("carte_brune", "")
            except Exception as e:
                logger.warning("Échec récupération documents (non bloquant) | %s", e)

        return {
            "numero_police": numero_police,
            "numero_facture": numero_facture,
            "numero_client": result.get("numeroClient"),
            "prime_ttc": self._safe_decimal(result.get("primettc")),
            "attestation": attestation,
            "carte_brune": carte_brune,
            "raw_response": result,
        }

    # --------------------------
    # Référentiels
    # --------------------------
    def get_referentiel_marques(self) -> list[tuple[str, str]]:
        """Retourne la liste des marques de véhicules."""
        try:
            result = self._make_request("referentiel/marques")
            return [(m["code"], m["libelle"]) for m in result]
        except Exception:
            from contracts.referentiels import MARQUES

            return MARQUES

    def get_referentiel_categories(self) -> list[tuple[str, str]]:
        """Retourne la liste des catégories de véhicules."""
        params = {"brCode": self.br_code}
        try:
            result = self._make_request("referentiel/categories", params=params)
            return [(c["code"], c["libelle"]) for c in result]
        except Exception:
            from contracts.referentiels import CATEGORIES

            return CATEGORIES

    def get_referentiel_sous_categories(
        self, categorie_code: str
    ) -> list[tuple[str, str]]:
        """Retourne la liste des sous-catégories pour une catégorie donnée."""
        params = {"catCode": categorie_code}
        try:
            result = self._make_request("referentiel/scategories", params=params)
            return [(sc["code"], sc["libelle"]) for sc in result]
        except Exception:
            if categorie_code == "520":
                from contracts.referentiels import SOUS_CATEGORIES_520

                return SOUS_CATEGORIES_520
            return []

    def get_referentiel_carrosseries(
        self, sous_categorie_code: str = "000"
    ) -> list[tuple[str, str]]:
        """Retourne la liste des carrosseries selon la doc API."""
        params = {"scatCode": sous_categorie_code}
        try:
            result = self._make_request("referentiel/carrosseries", params=params)
            return [(c["code"], c["libelle"]) for c in result]
        except Exception:
            # Fallback avec carrosseries par défaut
            return [("07", "Berline")]

    # --------------------------
    # Documents
    # --------------------------
    def get_documents(self, numero_facture: str) -> dict[str, str]:
        """Retourne les liens d'attestation et de carte brune."""
        params = {"numeroFacture": numero_facture}
        result = self._make_request("quittance/getfacture", params=params)
        liens = result.get("lien", {}) or {}
        return {
            "attestation": liens.get("linkAttestation") or "",
            "carte_brune": liens.get("linkCarteBrune") or "",
            "raw_response": result,
        }

    def get_quittance(self, numero_facture: str) -> dict[str, Any]:
        """Retourne les informations de quittance pour une facture."""
        params = {"numeroFacture": numero_facture}
        return self._make_request("quittance/getfacture", params=params)

    def get_carte_grise(self, numero_facture: str) -> dict[str, Any]:
        """Retourne les informations de carte grise pour une facture."""
        params = {"numeroFacture": numero_facture}
        return self._make_request("quittance/getcartegrise", params=params)


# Instance singleton
askia_client = AskiaAPIClient()


def askia_auto_renouveler(
    *,
    cli_code: str,
    numero_police: str,
    dure: int,
    effet: str,  # 'dd/mm/YYYY'
    vaf: int | str = 0,
    vvn: int | str = 0,
    recour: int = 0,
    vol: int = 0,
    inc: int = 0,
    pt: int = 0,
    gb: int = 0,
) -> tuple[bool, dict[str, Any] | str]:
    """
    Wrapper de compatibilité si des vues importent encore la fonction.
    Délègue à askia_client.renew_contrat_auto(...).
    """
    try:
        data = askia_client.renew_contrat_auto(
            cli_code=cli_code,
            numero_police=numero_police,
            dure=dure,
            effet=effet,
            vaf=vaf,
            vvn=vvn,
            recour=recour,
            vol=vol,
            inc=inc,
            pt=pt,
            gb=gb,
        )
        return True, data
    except Exception as e:
        return False, str(e)
