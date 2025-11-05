from django.core.management.base import BaseCommand
from contracts.models import Contrat
from contracts.api_client import askia_client
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Récupère les liens attestation/carte brune pour les contrats en attente"

    def handle(self, *args, **opts):
        qs = Contrat.objects.filter(status="PENDING_DOCS").exclude(numero_facture__isnull=True)
        count = 0
        for c in qs:
            docs = askia_client.get_documents(c.numero_facture)
            att, cb = docs.get("attestation"), docs.get("carte_brune")
            if att or cb:
                c.link_attestation = att or c.link_attestation
                c.link_carte_brune = cb or c.link_carte_brune
                c.status = "EMIS"
                c.updated_at = timezone.now()
                c.save(update_fields=["link_attestation","link_carte_brune","status","updated_at"])
                count += 1
        logger.info("retry_pending_docs: %d contrat(s) mis à jour", count)