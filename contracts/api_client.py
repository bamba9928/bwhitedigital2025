import logging
import re
import time
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, Optional, List, Tuple, Union
from functools import lru_cache, cache

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# =========================
# Immatriculation SN
# =========================
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

_REGIONAL_PATTERN_STR = f"^({'|'.join(REGION_PREFIXES)})-?\d{{4}}-?[A-Z]{{1,2}}$"

PATTERNS = {
    "REGIONAL": re.compile(_REGIONAL_PATTERN_STR),
    "ANCIEN": re.compile(r"^[A-Z]{2}-?\d{3}-?[A-Z]{2}$"),
    "AD_TT": re.compile(r"^AD-?\d{4}-?TT-?[A-Z]$"),
    "EX": re.compile(r"^\d{4}-?EX$"),
    "EP": re.compile(r"^\d{4}-?EP\d{2}$"),
    "AP": re.compile(r"^\d{3}-?AP-?\d{4}$"),
    "TT": re.compile(r"^\d{4}-?TT-?[A-Z]$"),
    "CH": re.compile(r"^CH-?\d{6}$"),
    "EP_EX": re.compile(r"^\d{4}-?EP\d{2}-?EX$"),
}


def _canon_immat(s: str) -> str:
    v = (s or "").upper()
    v = v.replace("–", "-").replace("—", "-")
    v = re.sub(r"\s+", "", v)
    if re.search(r"[^A-Z0-9\-]", v):
        raise ValueError("Caractères non autorisés dans l'immatriculation")
    return v


def _detect_immat_type(v: str) -> str | None:
    for typ, rx in PATTERNS.items():
        if rx.fullmatch(v):
            return typ
    return None


def _format_immat_for_askia(v: str, typ: str) -> str:
    raw = v.replace("-", "")
    if typ == "REGIONAL":  # AB0000CD -> AB-0000-CD
        return f"{raw[:2]}-{raw[2:6]}-{raw[6:]}"
    if typ == "ANCIEN":  # AA001BB -> AA-001-BB
        return f"{raw[:2]}-{raw[2:5]}-{raw[5:]}"
    if typ == "AD":  # AD0001 -> AD-0001
        return f"{raw[:2]}-{raw[2:]}"
    if typ == "EX":  # 0001EX -> 0001-EX
        return f"{raw[:4]}-EX"  # <- CORRECTION P0 (f-string)
    if typ == "EP":  # 0001EP01 -> 0001-EP01
        return f"{raw[:4]}-{raw[4:]}"
    if typ == "AP":  # 001AP0001 -> 001-AP-0001
        return f"{raw[:3]}-AP-{raw[5:]}"  # <- CORRECTION P0 (f-string)
    if typ == "TT":  # 0001TTA -> 0001-TT-A
        return f"{raw[:4]}-TT-{raw[-1]}"
    if typ == "AD_TT":  # AD0001TTA -> AD0001-TT-A
        return f"{raw[:6]}-TT-{raw[-1]}"
    if typ == "CH":  # CH000001 -> CH-000001
        return f"{raw[:2]}-{raw[2:]}"  # <- CORRECTION P0 (f-string)
    if typ == "EP_EX":  # 0001EP01EX -> 0001-EP01-EX
        return f"{raw[:4]}-{raw[4:8]}-EX"
    return v


def _validate_immatriculation(immat: str) -> str:
    if not immat:
        raise ValueError("Immatriculation requise")
    v = _canon_immat(immat)
    typ = _detect_immat_type(v)
    if not typ:
        raise ValueError(
            f"Format d'immatriculation invalide: '{immat}'. "
            "Formats acceptés: DK-0001-BB, AA-001-AA, AD-0001, 0001-EX, 0001-EP01, "
            "001-AP-0001, 0001-TT-A, AD0001-TT-A, CH-000001, 0001-EP01-EX"
        )
    return _format_immat_for_askia(v, typ)


# =========================
# Client API Askia
# =========================
class AskiaAPIClient:
    """Client pour l'API ASKIA (GET JSON majoritairement)."""

    def __init__(self) -> None:
        self.base_url = settings.ASKIA_BASE_URL.rstrip("/")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "appClient": settings.ASKIA_APP_CLIENT,
            }
        )

        self.pv_code = str(settings.ASKIA_PV_CODE)
        self.br_code = str(settings.ASKIA_BR_CODE)

    # ---------- Core ----------
    @staticmethod
    def _mask_sensitive_data(data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            return data
        masked: dict[str, Any] = {}
        sensitive = {"numtel", "email", "numident", "telephone", "numero_piece"}
        for k, v in data.items():
            if k.lower() in sensitive:
                masked[k] = "*****"
            elif isinstance(v, dict):
                masked[k] = AskiaAPIClient._mask_sensitive_data(v)
            elif isinstance(v, list):
                masked[k] = [
                    AskiaAPIClient._mask_sensitive_data(x) if isinstance(x, dict) else x
                    for x in v
                ]
            else:
                masked[k] = v
        return masked

    @staticmethod
    def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in (params or {}).items() if v is not None}

    def _request_json(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        timeout: int = 30,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """GET JSON avec retries et gestion d'erreurs métier Askia."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        params = self._clean_params(params or {})
        safe = self._mask_sensitive_data(params)

        resp: requests.Response | None = None
        for attempt in range(max_retries + 1):
            try:

                resp = self.session.get(url, params=params, timeout=timeout)
            except requests.exceptions.Timeout as e:
                if attempt < max_retries:
                    wait = 2 * (attempt + 1)
                    logger.warning(
                        "Timeout %s (%d/%d). Retry dans %ss",
                        endpoint,
                        attempt + 1,
                        max_retries + 1,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                logger.error(
                    "Timeout %s après %d tentatives | %s | params=%s",
                    endpoint,
                    max_retries + 1,
                    e,
                    safe,
                )
                raise Exception(f"Timeout API Askia: {endpoint}")
            except requests.exceptions.RequestException as e:
                logger.error("Erreur réseau %s | %s | params=%s", endpoint, e, safe)
                raise Exception(f"Erreur réseau API Askia: {e}")

            if 500 <= resp.status_code < 600 and attempt < max_retries:
                wait = 0.6 * (attempt + 1)
                logger.warning(
                    "HTTP %s sur %s (%d/%d). Retry dans %.1fs | params=%s",
                    resp.status_code,
                    endpoint,
                    attempt + 1,
                    max_retries + 1,
                    wait,
                    safe,
                )
                time.sleep(wait)
                continue
            break

        assert resp is not None
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            preview = ""
            try:
                preview = resp.json()
            except Exception:
                preview = resp.text[:400] if resp.text else ""
            logger.error(
                "HTTP %s %s | body=%s | params=%s",
                resp.status_code,
                endpoint,
                preview,
                safe,
            )
            raise Exception(f"Erreur HTTP Askia {resp.status_code}")

        try:
            data = resp.json()
        except ValueError:
            logger.error(
                "Réponse non JSON sur %s | preview=%r", endpoint, resp.text[:400]
            )
            raise Exception("Réponse API Askia invalide (non JSON)")

        if isinstance(data, dict):
            status_raw = str(data.get("status", "")).upper()
            error_val = data.get("error")
            code_raw = data.get("code")
            message = data.get("message") or data.get("msg")

            if message and "contrat en cours" in str(message).lower():

                raise Exception(f"Contrat déjà existant: {message}")

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
                    "Erreur métier %s | msg=%s | data=%s | params=%s",
                    endpoint,
                    msg,
                    self._mask_sensitive_data(data),
                    safe,
                )
                raise Exception(f"Erreur métier Askia: {msg}")

        return data

    def _request_raw(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """GET brut pour PDF/HTML/JSON."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        params = self._clean_params(params or {})
        r = self.session.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r

    @staticmethod
    def _safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
        if value is None or value == "":
            return default
        try:
            return Decimal(str(value))
        except (ValueError, InvalidOperation):
            logger.warning("Conversion Decimal échouée pour: %s", value)
            return default

    # ---------- Simulation ----------
    def get_simulation_auto(
        self, vehicule_data: dict[str, Any], duree: int
    ) -> dict[str, Decimal | str | dict[str, Any]]:
        """Tarif auto classique: /srwb/automobile"""
        if not vehicule_data.get("categorie"):
            raise ValueError("Catégorie requise")
        if not vehicule_data.get("carburant"):
            raise ValueError("Carburant requis")

        pfs = max(1, int(vehicule_data.get("puissance_fiscale") or 1))
        nbp = max(1, int(vehicule_data.get("nombre_places") or 1))

        params = {
            "cat": vehicule_data["categorie"],
            "scatCode": vehicule_data.get("sous_categorie", "000"),
            "nrg": vehicule_data["carburant"],
            "pfs": pfs,
            "nbP": nbp,
            "dure": int(duree),
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
        if vehicule_data["categorie"] == "520":
            params["chrgUtil"] = int(vehicule_data.get("charge_utile") or 3500)

        if not params["scatCode"]:
            params["scatCode"] = "000"

        result = self._request_json("srwb/automobile", params=params)
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

    # ---------- Clients ----------
    def create_client(self, client_data: dict[str, Any]) -> str:
        if not client_data.get("nom") or not client_data.get("prenom"):
            raise ValueError("Nom et prénom requis")
        if not client_data.get("telephone"):
            raise ValueError("Téléphone requis")

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
        result = self._request_json("srwbclient/createclient", params=params)
        cli_code = result.get("cliCode") or result.get("cliNumero")
        if not cli_code:
            logger.error("Aucun code client retourné | %s", result)
            raise Exception("Échec création client Askia")
        return str(cli_code)

    def get_client(self, client_code: str) -> dict[str, Any]:
        return self._request_json(
            "srwbclient/getclient", params={"cliCode": client_code}
        )

    # ---------- Contrat ----------
    def _try_recover_contract(self, id_saisie: str) -> dict[str, Any] | None:
        """Tente de récupérer et formater un contrat existant par id_saisie"""
        candidates = (f"{datetime.now().year}{id_saisie}", id_saisie)
        for nf in candidates:
            if existing := self.verify_contrat_exists(nf):
                liens = existing.get("lien") or {}
                return {
                    "numero_police": existing.get("numeroPolice"),
                    "numero_facture": existing.get("numeroFacture"),
                    "numero_client": existing.get("numeroClient"),
                    "prime_ttc": self._safe_decimal(existing.get("primettc")),
                    "attestation": liens.get("linkAttestation", ""),
                    "carte_brune": liens.get("linkCarteBrune", ""),
                    "raw_response": existing,
                }
        return None

    def create_contrat_auto(self, contrat_data: dict[str, Any]) -> dict[str, Any]:
        """Émission auto classique: /srwbauto/create"""
        required = [
            "client_code",
            "categorie",
            "carburant",
            "date_effet",
            "immatriculation",
            "marque",
            "modele",
            "duree",
        ]
        for f in required:
            if not contrat_data.get(f):
                raise ValueError(f"Champ requis manquant: {f}")

        # immatriculation normalisée
        immat = _validate_immatriculation(contrat_data["immatriculation"])

        # date effet
        effet_raw = contrat_data["date_effet"]
        if isinstance(effet_raw, date):
            effet = effet_raw
        elif isinstance(effet_raw, str):
            try:
                effet = datetime.strptime(effet_raw, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("date_effet doit être au format YYYY-MM-DD")
        else:
            raise ValueError(f"Type de date non supporté: {type(effet_raw).__name__}")

        if effet < datetime.now().date():
            raise ValueError(
                f"Date d'effet dans le passé: {effet.strftime('%d/%m/%Y')}"
            )

        id_saisie = contrat_data.get("id_saisie")

        if id_saisie and (existing := self._try_recover_contract(id_saisie)):
            return {**existing, "was_existing": True}

        params = {
            "cliCode": contrat_data["client_code"],
            "cat": contrat_data["categorie"],
            "scatCode": contrat_data.get("sous_categorie", "000"),
            "carrCode": contrat_data.get("carrosserie", "07"),
            "nrg": contrat_data["carburant"],
            "pfs": max(1, int(contrat_data.get("puissance_fiscale") or 1)),
            "nbP": max(1, int(contrat_data.get("nombre_places") or 1)),
            "dure": int(contrat_data["duree"]),
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
        if contrat_data["categorie"] == "520":
            params["chrgUtil"] = int(contrat_data.get("charge_utile") or 3500)
        if id_saisie:
            params["idSaisie"] = id_saisie

        try:
            result = self._request_json(
                "srwbauto/create", params=params, timeout=90, max_retries=0
            )
        except Exception:
            if id_saisie:
                for _ in range(3):
                    if recovered := self._try_recover_contract(id_saisie):
                        return {**recovered, "recovered_after_error": True}
                    time.sleep(5)
            raise

        if not isinstance(result, dict):
            raise Exception("Réponse API invalide")

        numero_police = result.get("numeroPolice")
        numero_facture = result.get("numeroFacture")
        if not numero_police or not numero_facture:
            raise Exception(
                result.get("message")
                or result.get("msg")
                or "Émission: police/facture manquants"
            )

        liens = result.get("lien", {}) or {}
        attestation = liens.get("linkAttestation", "")
        carte_brune = liens.get("linkCarteBrune", "")
        if not (attestation or carte_brune):
            try:
                docs = self.get_documents(numero_facture)
                attestation = docs.get("attestation", "") or attestation
                carte_brune = docs.get("carte_brune", "") or carte_brune
            except Exception as e:
                logger.warning("Récup docs post-émission KO (non bloquant) | %s", e)

        return {
            "numero_police": numero_police,
            "numero_facture": numero_facture,
            "numero_client": result.get("numeroClient"),
            "prime_ttc": self._safe_decimal(result.get("primettc")),
            "attestation": attestation,
            "carte_brune": carte_brune,
            "raw_response": result,
        }

    def renew_contrat_auto(
        self,
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
    ) -> dict[str, Any]:
        params = {
            "cliCode": cli_code,
            "numeroPolice": numero_police,
            "dure": int(dure),
            "effet": effet,
            "vaf": str(self._safe_decimal(vaf)),
            "vvn": str(self._safe_decimal(vvn)),
            "recour": int(recour),
            "vol": int(vol),
            "inc": int(inc),
            "pt": int(pt),
            "gb": int(gb),
        }
        return self._request_json(
            "srwbauto/renouv", params=params, timeout=90, max_retries=0
        )

    # ---------- Référentiels ----------

    @cache
    def get_referentiel_marques(self) -> list[tuple[str, str]]:
        try:
            result = self._request_json("referentiel/marques")
            return [(m["code"], m["libelle"]) for m in result]
        except Exception:
            from contracts.referentiels import MARQUES as FALLBACK

            return FALLBACK

    @cache
    def get_referentiel_categories(self) -> list[tuple[str, str]]:
        try:
            result = self._request_json(
                "referentiel/categories", params={"brCode": self.br_code}
            )
            return [(c["code"], c["libelle"]) for c in result]
        except Exception:
            from contracts.referentiels import CATEGORIES as FALLBACK

            return FALLBACK

    @cache
    def get_referentiel_sous_categories(
        self, categorie_code: str
    ) -> list[tuple[str, str]]:
        try:
            # La doc contient parfois /souscategories et /scategories. On standardise sur /scategories.
            result = self._request_json(
                "referentiel/scategories", params={"catCode": categorie_code}
            )
            if not result:
                return []
            return [(sc["code"], sc["libelle"]) for sc in result]
        except Exception:
            if categorie_code == "520":
                from contracts.referentiels import SOUS_CATEGORIES_520 as FALLBACK

                return FALLBACK
            if categorie_code == "550":
                from contracts.referentiels import SOUS_CATEGORIES_550 as FALLBACK

                return FALLBACK
            return []

    @cache
    def get_referentiel_carrosseries(
        self, sous_categorie_code: str = "000"
    ) -> list[tuple[str, str]]:
        try:
            result = self._request_json(
                "referentiel/carrosseries", params={"scatCode": sous_categorie_code}
            )
            return [(c["code"], c["libelle"]) for c in result]
        except Exception:
            return [("07", "Berline")]

    # ---------- Documents ----------
    def get_facture(self, numero_facture: str) -> dict[str, Any]:
        """
        /quittance/getfacture : peut répondre JSON ou PDF.
        Retourne:
          - {"ok": True, "type": "json", "data": {...}}
          - {"ok": True, "type": "pdf", "content": b"..."}
          - {"ok": False, "error": "..."}
        """
        try:
            r = self._request_raw(
                "quittance/getfacture",
                params={"numeroFacture": numero_facture},
                timeout=30,
            )
        except requests.RequestException as e:
            logger.error("getfacture KO | %s | %s", numero_facture, e)
            return {"ok": False, "error": "exception", "detail": str(e)}

        ct = (r.headers.get("Content-Type") or "").lower()
        if "application/json" in ct:
            try:
                return {"ok": True, "type": "json", "data": r.json()}
            except ValueError:
                logger.error(
                    "getfacture JSON invalide | %s | preview=%r",
                    numero_facture,
                    r.text[:400],
                )
                return {"ok": False, "error": "json_invalide"}
        if "application/pdf" in ct or "octet-stream" in ct:
            return {"ok": True, "type": "pdf", "content": r.content}

        logger.error(
            "getfacture format inattendu | ct=%s | preview=%r", ct, r.text[:400]
        )
        return {"ok": False, "error": "format_inattendu"}

    def get_quittance_json(self, numero_facture: str) -> dict[str, Any] | None:
        """Forcer Accept JSON pour extraire numeroPolice/numeroClient, etc."""
        try:
            # Copier les headers de la session et forcer 'Accept'
            custom_headers = self.session.headers.copy()
            custom_headers["Accept"] = "application/json"

            r = self.session.get(
                f"{self.base_url}/quittance/getfacture",
                headers=custom_headers,
                params={"numeroFacture": numero_facture},
                timeout=15,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug("get_quittance_json KO | %s | %s", numero_facture, e)
            return None

    def verify_contrat_exists(self, numero_facture: str) -> dict[str, Any] | None:
        data = self.get_quittance_json(numero_facture)
        if data and isinstance(data, dict) and data.get("numeroPolice"):
            return data
        return None

    def get_documents(self, numero_facture: str) -> dict[str, Any]:
        """
        Conformément à la doc, on lit /quittance/getfacture (JSON) et on extrait les liens.
        Renvoie: {"facture", "attestation", "carte_brune", "raw_response"}
        """
        data = self._request_json(
            "quittance/getfacture", params={"numeroFacture": numero_facture}
        )
        liens = data.get("lien", {}) or {}
        return {
            "attestation": liens.get("linkAttestation") or "",
            "carte_brune": liens.get("linkCarteBrune") or liens.get("cartegrise") or "",
            "raw_response": data,
        }

    def get_carte_grise(self, numero_facture: str) -> dict[str, Any]:
        """/quittance/getcartegrise : utile si besoin d’infos additionnelles côté SI."""
        return self._request_json(
            "quittance/getcartegrise", params={"numeroFacture": numero_facture}
        )

    def annuler_attestation(self, numero_facture: str) -> dict[str, Any]:
        """
        5. Annuler Attestation QrCode
        GET /quittance/annulerqrcode?numeroFacture=...
        """
        if not numero_facture:
            raise ValueError("Numéro de facture requis pour annulation")

        return self._request_json(
            "quittance/annulerqrcode", params={"numeroFacture": numero_facture}
        )

# Instance réutilisable
askia_client = AskiaAPIClient()
