import logging
from typing import Any

import httpx

from config import Settings
from services.inhire_auth import InHireAuth

logger = logging.getLogger("agente-inhire.inhire")


class WhatsAppWindowExpired(Exception):
    """422 — Janela de 24h do WhatsApp expirada."""
    pass


class WhatsAppInvalidPhone(Exception):
    """400 — Telefone invalido para WhatsApp."""
    pass


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

    async def get_reproval_suggestion(self, job_talent_id: str) -> dict | None:
        """Get AI-generated reproval email suggestion from InHire."""
        try:
            return await self._request("POST", f"/job-talents/reproval/suggestion/{job_talent_id}")
        except Exception:
            return None

    # --- Timeline & History ---

    async def get_job_talent_timeline(self, job_talent_id: str) -> list[dict]:
        """Get chronological timeline of a candidate in a job (stages, statuses, transfers)."""
        return await self._request("GET", f"/job-talents/{job_talent_id}/timeline")

    async def get_stage_history_batch(self, job_talent_ids: list[str]) -> list[list[dict]]:
        """Get stage change history for multiple candidates in one request."""
        if not job_talent_ids:
            return []
        return await self._request("POST", "/job-talents/stages/history", json=job_talent_ids)

    # --- Scorecards ---
    async def get_scorecards(self, params: dict | None = None) -> list:
        return await self._request("GET", "/scorecards", params=params or {})

    async def get_job_scorecard(self, job_id: str) -> dict | None:
        """Get scorecard config for a job (skill categories and criteria)."""
        try:
            return await self._request("GET", f"/forms/scorecards/jobs/{job_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def create_job_scorecard(self, job_id: str, skill_categories: list[dict]) -> dict:
        """Create scorecard for a job with skill categories.

        skill_categories format: [{"name": "Técnico", "skills": [{"name": "Python"}, {"name": "FastAPI"}]}]
        """
        return await self._request("POST", "/forms/scorecards/jobs", json={
            "jobId": job_id,
            "skillCategories": skill_categories,
        })

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

    async def search_files(self, file_id: str = "", file_category: str = "resumes") -> list[dict]:
        """Search for files by ID or category. Correct endpoint per André (not GET /talents/{id}/files)."""
        payload: dict = {}
        if file_id:
            payload["id"] = file_id
        if file_category:
            payload["fileCategory"] = file_category
        return await self._request("POST", "/files/search", json=payload)

    # --- Forms ---

    async def get_job_form(self, job_id: str) -> list[dict]:
        """Get application form config for a job. Returns list of form items."""
        return await self._request(
            "GET", f"/forms/job-id/{job_id}", params={"includeTypeFileUpload": "true"},
        )

    async def update_form(self, form_id: str, payload: dict) -> dict:
        """Update form structure (title, fields, settings)."""
        return await self._request("PATCH", f"/forms/{form_id}", json=payload)

    async def configure_screening(self, job_id: str, screening_settings: dict,
                                   resume_analyzer: dict | None = None) -> dict:
        """Configure AI screening for a job (criteria, salary range, auto-actions)."""
        payload: dict = {"screeningSettings": screening_settings}
        if resume_analyzer is not None:
            payload["resumeAnalyzer"] = resume_analyzer
        return await self._request("PATCH", f"/jobs/{job_id}", json=payload)

    # --- Screening On-Demand ---

    async def analyze_resume(self, job_talent_id: str) -> dict | None:
        """Trigger resume analysis for a specific candidate. Requires CV attached."""
        try:
            return await self._request("POST", f"/job-talents/resume/analyze/{job_talent_id}", json={})
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 404):
                return None
            raise

    async def manual_screening(self, job_talent_id: str) -> dict | None:
        """Trigger manual screening for a candidate (works for hunting candidates without form).
        Returns screening result with score and status."""
        try:
            return await self._request("POST", f"/job-talents/{job_talent_id}/screening/manual", json={})
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 403, 404):
                return None
            raise

    async def get_resume_analysis(self, job_talent_id: str) -> dict | None:
        """Get detailed resume analysis (score per criterion with evidence)."""
        try:
            return await self._request("GET", f"/job-talents/{job_talent_id}/resume-analysis")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_screening_analysis(self, job_talent_id: str) -> dict | None:
        """Get detailed screening analysis (all criteria scores)."""
        try:
            return await self._request("GET", f"/job-talents/{job_talent_id}/screening-analysis")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

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

    async def get_talent_by_email(self, email: str) -> dict | None:
        """Find a talent by exact email. Returns None if not found."""
        try:
            return await self._request("GET", f"/talents/email/{email}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_talent_by_linkedin(self, username: str) -> dict | None:
        """Find a talent by LinkedIn username. Returns None if not found."""
        try:
            return await self._request("GET", f"/talents/linkedin/{username}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_talents_by_ids(self, talent_ids: list[str]) -> list[dict]:
        """Fetch multiple talents by their IDs in a single request."""
        if not talent_ids:
            return []
        return await self._request("POST", "/talents/ids", json={"ids": talent_ids})

    async def list_talents_paginated(self, limit: int = 50, start_key: str | None = None) -> dict:
        """List talents with pagination. Returns {results, startKey}."""
        payload: dict = {"limit": limit}
        if start_key:
            payload["startKey"] = start_key
        return await self._request("POST", "/talents/paginated", json=payload)

    # --- Appointments (base path: /job-talents/appointments) ---
    async def create_appointment(self, job_talent_id: str, payload: dict) -> dict:
        """Create an appointment. Required: name, startDateTime, endDateTime, guests, hasCallLink, userEmail."""
        logger.info("Criando agendamento para %s", job_talent_id)
        return await self._request(
            "POST", f"/job-talents/appointments/{job_talent_id}/create", json=payload
        )

    async def update_appointment(self, appointment_id: str, payload: dict) -> dict | None:
        """Update an existing appointment (reschedule)."""
        logger.info("Atualizando agendamento %s", appointment_id)
        return await self._request("PATCH", f"/job-talents/appointments/{appointment_id}/patch", json=payload)

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

    # --- Email (base path: /comms/emails) ---
    async def send_email(self, to_job_talent_ids: list[str], subject: str, body: str,
                         from_email: str = "noreply@inhire.app") -> None:
        """Send email to candidates via InHire comms service (Amazon SES)."""
        logger.info("Enviando email: %s para %d destinatários", subject, len(to_job_talent_ids))
        await self._request(
            "POST", "/comms/emails/submissions",
            json={
                "from": from_email,
                "subject": subject,
                "body": body,
                "emailProvider": "amazon",
                "jobTalentIds": to_job_talent_ids,
            },
        )

    async def list_email_templates(self) -> list:
        """List available email templates."""
        return await self._request("GET", "/comms/emails/templates")

    # --- WhatsApp ---
    async def send_whatsapp(self, phone: str, message: str) -> dict:
        """Send WhatsApp message to a candidate via InHire subscription-assistant."""
        # Validate phone locally
        clean_phone = "".join(c for c in phone if c.isdigit())
        if len(clean_phone) < 10 or len(clean_phone) > 15:
            raise WhatsAppInvalidPhone(f"Telefone invalido: {phone}")

        # Truncate message if too long
        if len(message) > 4096:
            message = message[:4093] + "..."

        logger.info("Enviando WhatsApp para %s (%d chars)", clean_phone[:4] + "****", len(message))

        await self.auth.ensure_valid_token()
        resp = await self._client.request(
            "POST",
            f"{self.base_url}/subscription-assistant/tenant/{self.auth.tenant}/send",
            headers=self.auth.headers,
            json={"phone": clean_phone, "message": message},
        )

        if resp.status_code == 422:
            raise WhatsAppWindowExpired("Janela de 24h expirada")
        if resp.status_code == 400:
            raise WhatsAppInvalidPhone(resp.text)
        resp.raise_for_status()
        return resp.json()

    # --- Automations ---

    async def create_automation(self, payload: dict) -> dict:
        """Create a workflow automation (trigger + action + conditions)."""
        return await self._request("POST", "/workflows/automations", json=payload)

    async def list_automations(self, job_id: str | None = None) -> list[dict]:
        """List all automations, optionally filtered by job."""
        params = {}
        if job_id:
            params = {"field": "jobId", "input": job_id}
        return await self._request("GET", "/workflows/automations", params=params)

    async def delete_automation(self, automation_id: str) -> None:
        """Delete an automation."""
        await self._request("DELETE", f"/workflows/automations/{automation_id}")

    async def list_automation_executions(self, automation_id: str | None = None) -> list[dict]:
        """List automation executions, optionally filtered by automation."""
        params = {}
        if automation_id:
            params = {"field": "automationId", "input": automation_id}
        return await self._request("GET", "/workflows/executions", params=params)

    # --- Talent Search (Typesense) ---
    async def get_typesense_key(self) -> dict:
        """Get a scoped Typesense key for full-text talent search.
        Endpoint: GET /search-talents/security/key/talents?engine=typesense
        Returns: {key, indexName, validForInMilliseconds, appId}
        Key expires in 24h, isolated by tenant, read-only.
        """
        logger.info("Obtendo chave Typesense para busca de talentos")
        return await self._request(
            "GET", "/search-talents/security/key/talents",
            params={"engine": "typesense"},
        )

    # --- Tags ---

    async def add_tags_batch(self, job_talent_ids: list[str], tags: list[str]) -> dict:
        """Add tags to multiple candidates in batch."""
        return await self._request("POST", "/job-talents/tags/add/batch", json={
            "jobTalentIds": job_talent_ids,
            "tags": tags,
        })

    async def remove_tags_batch(self, job_talent_ids: list[str], tags: list[str]) -> dict:
        """Remove tags from multiple candidates in batch."""
        return await self._request("DELETE", "/job-talents/tags/delete/batch", json={
            "jobTalentIds": job_talent_ids,
            "tags": tags,
        })

    # --- AI Search ---

    async def gen_filter_job_talents(self, job_id: str, query: str) -> dict | None:
        """Generate Typesense filters from natural language using InHire AI.
        Endpoint: POST /search-talents/ai/generate-job-talent-filter
        Returns: {filter, sort, query, facetsValuesDoesNotExist} or None on error."""
        try:
            return await self._request(
                "POST", "/search-talents/ai/generate-job-talent-filter",
                json={"jobId": job_id, "query": query},
            )
        except httpx.HTTPStatusError as e:
            logger.warning("gen_filter_job_talents failed %d: %s", e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            logger.warning("gen_filter_job_talents error: %s", e)
            return None

    async def create_talent(self, data: dict) -> dict:
        """Create a basic talent record. Used for LinkedIn profiles before full data extraction.
        data should include at minimum: {name, linkedinUsername} or {name, email}."""
        return await self._request("POST", "/talents", json=data)

    # --- Job Publishing ---

    async def get_integrations(self) -> list[dict]:
        """List publishing integrations configured for the tenant (LinkedIn, Indeed, etc.)."""
        return await self._request("GET", "/integrations")

    async def publish_job(self, job_id: str, career_page_id: str, display_name: str,
                          active_job_boards: list[str], description: str = "",
                          status: str = "published") -> dict:
        """Publish a job to career page and job boards.

        active_job_boards options: linkedin, indeed, netVagas, talent, ondeTrabalhar, jobBoardPool
        """
        payload: dict = {
            "jobId": job_id,
            "careerPageId": career_page_id,
            "displayName": display_name,
            "status": status,
            "activeJobBoards": active_job_boards,
        }
        if description:
            payload["description"] = description
        return await self._request("POST", "/job-posts/pages", json=payload)

    async def unpublish_job(self, job_id: str) -> dict:
        """Unpublish a job from all channels."""
        return await self._request("PATCH", f"/job-posts/pages/{job_id}", json={
            "status": "unpublished",
        })

    async def close(self):
        await self._client.aclose()
