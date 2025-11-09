from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from .api_client import _validate_immatriculation, _canon_immat

# ==================================
# 📞 Validateur de Téléphone
# ==================================
SENEGAL_PHONE_VALIDATOR = RegexValidator(
    regex=r'^(70|71|75|76|77|78|30|33|34)\d{7}$',
    message="Le numéro doit être au format sénégalais (ex: 771234567)"
)

def normalize_phone_for_storage(phone: str) -> str:
    if not phone:
        return ""
    return "".join(filter(str.isdigit, str(phone)))

# ==================================
# 🚗 Validateur d'Immatriculation
# ==================================

def validate_immatriculation(value):
    """
    Validateur Django qui utilise la logique de validation de l'api_client.
    """
    try:

        _validate_immatriculation(str(value))
    except ValueError as e:

        raise ValidationError(str(e), code='invalid_immat')

def normalize_immat_for_storage(immat: str) -> str:
    """
    Normalise une immatriculation pour le stockage DB (sans tirets)
    en utilisant le canoniseur de l'api_client.
    """
    immat_norm = _canon_immat(immat)
    return immat_norm.replace("-", "")