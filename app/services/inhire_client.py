import logging
from typing import Any

import httpx

from config import Settings
from services.inhire_auth import InHireAuth

logger = logging.getLogger("agente-inhire.inhire")


class InHireClient:
    """HTTP client for InHire API operations."""

    def __init__(self, settings: Settings, auth: InHireAuth):
        self.base_url = settings.inhire_api_url
        self.auth = auth
        self._client = httpx.AsyncClient(timeout=30)

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        await self.auth.ensure_valid_token()
        resp = await self._client.request(
            method,
            f"{self.base_url}{path}",
            headers=self.auth.headers,
            **kwargs,
        )
        # Retry once on 401 (token may have expired mid-request)
        if resp.status_code == 401:
            logger.warning("Token expirado, re-autenticando...")
            await self.auth.login()
            resp = await self._client.request(
                method,
                f"{self.base_url}{path}",
                headers=self.auth.headers,
                **kwargs,
            )
        resp.raise_for_status()
        if resp.status_code == 204:
            return None
        return resp.json()

    # --- Jobs ---
    async def create_job(self, payload: dict) -> dict:
        """Create a job. Required fields: name, locationRequired, talentSuggestions."""
        logger.info("Criando vaga: %s", payload.get("name", ""))
        return await self._request("POST", "/jobs", json=payload)

    async def update_job(self, job_id: str, payload: dict) -> dict:
        logger.info("Atualizando vaga %s", job_id)
        return await self._request("PATCH", f"/jobs/{job_id}", json=payload)

    async def get_job(self, job_id: str) -> dict:
        return await self._request("GET", f"/jobs/{job_id}")

    async def delete_job(self, job_id: str):
        logger.info("Deletando vaga %s", job_id)
        return await self._request("DELETE", f"/jobs/{job_id}")

    # --- Requisitions ---
    async def create_requisition(self, payload: dict) -> dict:
        logger.info("Criando requisição")
        return await self._request("POST", "/requisitions", json=payload)

    async def get_requisitions(self, params: dict | None = None) -> list:
        return await self._request("GET", "/requisitions", params=params or {})

    # --- Applications / Job Talents ---
    async def list_applications(self, params: dict | None = None) -> list:
        """List applications. Note: returns empty for hunting candidates.
        Use list_job_talents() instead for complete candidate list."""
        return await self._request("GET", "/applications", params=params or {})

    async def get_application(self, app_id: str) -> dict:
        return await self._request("GET", f"/applications/{app_id}")

    async def list_job_talents(self, job_id: str) -> list:
        """List ALL candidates in a job (hunting + organic). Returns talent details, stage, screening."""
        return await self._request("GET", f"/job-talents/{job_id}/talents")

    async def update_application(self, app_id: str, payload: dict) -> dict:
        """Update application. Required field: status."""
        logger.info("Atualizando candidatura %s: %s", app_id, payload)
        return await self._request(
            "PATCH", f"/applications/{app_id}", json=payload
        )

    async def move_candidate(self, job_talent_id: str, stage_id: str, comment: str = "") -> dict:
        """Move candidate to a new stage.
        Endpoint: POST /job-talents/talents/{jobTalentId}/stages
        """
        logger.info("Movendo candidato %s para etapa %s", job_talent_id, stage_id)
        payload = {"stageId": stage_id}
        if comment:
            payload["comment"] = comment
        return await self._request(
            "POST", f"/job-talents/talents/{job_talent_id}/stages", json=payload
        )

    async def move_candidates_batch(self, stage_id: str, job_talent_ids: list[str]) -> dict:
        """Move multiple candidates to a stage in one call.
        Endpoint: POST /job-talents/talents/stages/batch
        """
        logger.info("Movendo %d candidatos em lote para etapa %s", len(job_talent_ids), stage_id)
        return await self._request(
            "POST", "/job-talents/talents/stages/batch",
            json={"stageId": stage_id, "jobTalents": [{"id": jt_id} for jt_id in job_talent_ids]},
        )

    async def reject_candidate(self, job_talent_id: str, reason: str = "other", comment: str = "") -> dict:
        """Reject a single candidate.
        Endpoint: POST /job-talents/talents/{jobTalentId}/statuses
        Valid reasons: overqualified, underqualified, location, other
        """
        logger.info("Reprovando candidato %s (reason=%s)", job_talent_id, reason)
        payload = {"status": "rejected", "reason": reason}
        if comment:
            payload["comment"] = comment
        return await self._request(
            "POST", f"/job-talents/talents/{job_talent_id}/statuses", json=payload
        )

    async def bulk_reject(self, job_talent_ids: list[str], reason: str = "other",
                          comment: str = "") -> dict:
        """Reject multiple candidates.
        Endpoint: POST /job-talents/talents/statuses/batch
        Falls back to individual calls if batch fails.
        reason must be enum: overqualified, underqualified, location, other
        comment is free text (used for devolutiva message).
        """
        logger.info("Reprovando %d candidatos em lote (reason=%s)", len(job_talent_ids), reason)
        payload = {
            "status": "rejected",
            "reason": reason,
            "jobTalents": [{"id": jt_id} for jt_id in job_talent_ids],
        }
        if comment:
            payload["comment"] = comment
        try:
            await self._request("POST", "/job-talents/talents/statuses/batch", json=payload)
            return {"rejected": len(job_talent_ids), "total": len(job_talent_ids)}
        except Exception as batch_err:
            logger.warning("Batch reject falhou (%s), tentando individual...", batch_err)
            rejected = 0
            for jt_id in job_talent_ids:
                try:
                    await self.reject_candidate(jt_id, reason=reason, comment=comment)
                    rejected += 1
                except Exception as e:
                    logger.error("Erro ao reprovar %s: %s", jt_id, e)
            return {"rejected": rejected, "total": len(job_talent_ids)}

    # --- Scorecards ---
    async def get_scorecards(self, params: dict | None = None) -> list:
        return await self._request("GET", "/scorecards", params=params or {})

    # --- Webhooks ---
    async def register_webhook(self, url: str, event: str, name: str) -> dict:
        """Register a single webhook. Fields: url, event, name."""
        logger.info("Registrando webhook: %s para evento %s", name, event)
        return await self._request(
            "POST", "/integrations/webhooks",
            json={"url": url, "event": event, "name": name, "rules": {}},
        )

    async def list_webhooks(self) -> list:
        return await self._request("GET", "/integrations/webhooks")

    # --- Files (CV upload) ---
    async def create_file_record(self, file_name: str, category: str = "resumes") -> dict:
        """Create a file metadata record in InHire.
        Endpoint: POST /files
        Returns: {id, category, name, userId, userName, createdAt}
        """
        import uuid
        file_id = str(uuid.uuid4())
        logger.info("Criando registro de arquivo: %s (category=%s)", file_name, category)
        return await self._request(
            "POST", "/files",
            json={"id": file_id, "category": category, "name": file_name},
        )

    # --- Job Talents (add talent to job) ---
    async def add_talent_to_job(self, job_id: str, talent_data: dict, source: str = "api",
                                files: list[dict] | None = None) -> dict:
        """Add a new talent directly to a job. Creates talent + links to job in one call.
        If files is provided, attaches CV records to the talent.
        files format: [{"id": "uuid", "fileCategory": "resumes", "name": "cv.pdf"}]
        """
        logger.info("Adicionando talento à vaga %s: %s", job_id, talent_data.get("name", ""))
        payload = {"source": source, "talent": talent_data}
        if files:
            payload["files"] = files
        return await self._request(
            "POST", f"/job-talents/{job_id}/talents",
            json=payload,
        )

    async def add_existing_talent_to_job(self, job_id: str, talent_id: str, source: str = "manual") -> dict:
        """Add an existing talent to a job by talent ID."""
        logger.info("Vinculando talento %s à vaga %s", talent_id, job_id)
        return await self._request(
            "POST", f"/job-talents/{job_id}/talents",
            json={"source": source, "talentId": talent_id},
        )

    # --- Appointments (base path: /job-talents/appointments) ---
    async def create_appointment(self, job_talent_id: str, payload: dict) -> dict:
        """Create an appointment. Required: name, startDateTime, endDateTime, guests, hasCallLink, userEmail."""
        logger.info("Criando agendamento para %s", job_talent_id)
        return await self._request(
            "POST", f"/job-talents/appointments/{job_talent_id}/create", json=payload
        )

    async def get_appointment(self, appointment_id: str) -> dict:
        return await self._request("GET", f"/job-talents/appointments/{appointment_id}/get")

    async def cancel_appointment(self, appointment_id: str) -> dict:
        return await self._request("POST", f"/job-talents/appointments/{appointment_id}/cancel")

    async def list_candidate_appointments(self, job_talent_id: str) -> list:
        return await self._request("GET", f"/job-talents/appointments/job-talent/{job_talent_id}")

    async def check_availability(self, params: dict | None = None) -> dict:
        return await self._request("GET", "/job-talents/appointments/availability/check", params=params or {})

    async def get_my_appointments(self) -> list:
        return await self._request("GET", "/job-talents/appointments/my-appointments")

    # --- Offer Letters ---
    async def create_offer_letter(self, payload: dict) -> dict:
        """Create an offer letter. Required: name, templateId, talent, approvals."""
        logger.info("Criando carta oferta: %s", payload.get("name", ""))
        return await self._request("POST", "/offer-letters", json=payload)

    async def get_offer_letter(self, offer_id: str) -> dict:
        return await self._request("GET", f"/offer-letters/{offer_id}")

    async def list_offer_letters(self) -> list:
        return await self._request("GET", "/offer-letters")

    async def cancel_offer_letter(self, offer_id: str) -> dict:
        logger.info("Cancelando carta oferta %s", offer_id)
        return await self._request("PATCH", f"/offer-letters/{offer_id}/cancel")

    async def send_offer_to_talent(self, offer_id: str) -> dict:
        """Send notification to talent to sign the offer."""
        logger.info("Enviando carta oferta %s ao candidato", offer_id)
        return await self._request(
            "POST", f"/offer-letters/{offer_id}/talents/notifications"
        )

    async def get_offer_document_url(self, offer_id: str) -> dict:
        return await self._request("GET", f"/offer-letters/document/{offer_id}")

    async def list_offer_templates(self) -> list:
        return await self._request("GET", "/offer-letters/templates")

    async def get_offer_settings(self) -> dict:
        return await self._request("GET", "/offer-letters/settings")

    async def close(self):
        await self._client.aclose()
