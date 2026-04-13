# Gap Implementation Plan — Agente Eli

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar as 18 funcionalidades que dependem apenas de desenvolvimento no agente (sem endpoints novos da API InHire).

**Architecture:** Cada task modifica 1-2 arquivos existentes no projeto. Nenhum arquivo novo necessário exceto testes. Todas as mudanças são incrementais — cada task funciona independente das outras e pode ser deployada sozinha.

**Tech Stack:** Python 3.12, FastAPI, httpx, Anthropic SDK (Claude), Redis, APScheduler, Slack API.

**Spec de referência:** `docs/superpowers/specs/2026-04-13-gap-api-agente-design.md`

---

## File Map

| Arquivo | Responsabilidade | Tasks que o tocam |
|---|---|---|
| `app/services/inhire_client.py` | HTTP client InHire API | 1, 2, 3, 12 |
| `app/routers/handlers/candidates.py` | Triagem, shortlist, rejeição | 4, 5, 6, 7 |
| `app/routers/handlers/interviews.py` | Agendamento, carta oferta | 8, 9, 10, 12 |
| `app/routers/handlers/hunting.py` | Análise de perfil, sourcing | 3 |
| `app/routers/handlers/helpers.py` | Utilitários, _send, constantes | 5 |
| `app/routers/slack.py` | Orquestrador principal, handlers de botão | 3, 11, 13 |
| `app/routers/webhooks.py` | Webhook handlers (contratação, stage change) | 11, 13 |
| `app/services/claude_client.py` | Claude API, ELI_TOOLS | 5, 14 |
| `app/services/proactive_monitor.py` | Cron jobs, relatórios | 14, 15 |

---

## Wave 1 — Quick Wins (Baixa Complexidade)

### Task 1: Buscar talento por email

**Files:**
- Modify: `app/services/inhire_client.py`

Adicionar dois métodos ao `InHireClient` usando endpoints que já existem na API.

- [ ] **Step 1: Adicionar método `get_talent_by_email`**

Em `app/services/inhire_client.py`, adicionar após o método `add_existing_talent_to_job`:

```python
async def get_talent_by_email(self, email: str) -> dict | None:
    """Find a talent by exact email. Returns None if not found."""
    try:
        return await self._request("GET", f"/talents/email/{email}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
```

- [ ] **Step 2: Adicionar método `get_talent_by_linkedin`**

Logo abaixo, adicionar:

```python
async def get_talent_by_linkedin(self, username: str) -> dict | None:
    """Find a talent by LinkedIn username. Returns None if not found."""
    try:
        return await self._request("GET", f"/talents/linkedin/{username}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
```

- [ ] **Step 3: Testar manualmente no servidor**

SSH no servidor e testar via Python REPL:

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97
cd /var/www/agente-inhire
python3 -c "
import asyncio
from app.config import Settings
from app.services.inhire_auth import InHireAuth
from app.services.inhire_client import InHireClient

async def test():
    s = Settings()
    auth = InHireAuth(s)
    client = InHireClient(s, auth)
    result = await client.get_talent_by_email('teste@example.com')
    print('By email:', result)
    await client.close()

asyncio.run(test())
"
```

- [ ] **Step 4: Commit**

```bash
git add app/services/inhire_client.py
git commit -m "feat: buscar talento por email e LinkedIn (endpoints existentes)"
```

---

### Task 2: Buscar múltiplos talentos por ID

**Files:**
- Modify: `app/services/inhire_client.py`

- [ ] **Step 1: Adicionar método `get_talents_by_ids`**

Em `app/services/inhire_client.py`, após `get_talent_by_linkedin`:

```python
async def get_talents_by_ids(self, talent_ids: list[str]) -> list[dict]:
    """Fetch multiple talents by their IDs in a single request."""
    if not talent_ids:
        return []
    return await self._request("POST", "/talents/ids", json={"ids": talent_ids})
```

- [ ] **Step 2: Adicionar método `list_talents_paginated`**

```python
async def list_talents_paginated(self, limit: int = 50, start_key: str | None = None) -> dict:
    """List talents with pagination. Returns {results, startKey}."""
    payload: dict = {"limit": limit}
    if start_key:
        payload["startKey"] = start_key
    return await self._request("POST", "/talents/paginated", json=payload)
```

- [ ] **Step 3: Commit**

```bash
git add app/services/inhire_client.py
git commit -m "feat: buscar talentos por IDs em batch e listar paginado"
```

---

### Task 3: Fluxo "analisei perfil → adicionar à vaga"

**Files:**
- Modify: `app/routers/handlers/hunting.py`
- Modify: `app/routers/slack.py` (handler de botão de aprovação)

- [ ] **Step 1: Extrair dados do perfil na análise**

Em `app/routers/handlers/hunting.py`, modificar `_analyze_profile` para extrair dados estruturados do candidato após a análise do Claude. Adicionar após a linha `await _send(conv, slack, channel_id, response)` (linha ~48):

```python
    # Extract candidate data from profile text for potential add-to-job
    candidate_data = await claude.chat(
        messages=[{"role": "user", "content": f"Extraia os dados do candidato deste perfil em JSON:\n\n{text}"}],
        system=(
            "Extraia APENAS dados factuais em JSON. Campos: name, email, phone, linkedin_url. "
            "Se não encontrar um campo, use null. Retorne APENAS o JSON, sem markdown."
        ),
    )

    try:
        import json as _json
        parsed = _json.loads(candidate_data.strip().removeprefix("```json").removesuffix("```").strip())
        conv.set_context("analyzed_profile_data", parsed)
        conv.set_context("analyzed_profile_text", text)
    except Exception:
        conv.set_context("analyzed_profile_data", None)
```

- [ ] **Step 2: Oferecer botão "Adicionar à vaga" quando há vaga ativa**

Ainda em `_analyze_profile`, após o bloco acima, adicionar:

```python
    job_id = conv.get_context("current_job_id")
    if job_id and conv.get_context("analyzed_profile_data"):
        await _send_approval(
            conv, slack, channel_id,
            title="Adicionar candidato à vaga?",
            details=f"Adicionar à vaga *{job_name}*",
            callback_id="add_analyzed_profile",
        )
```

Atualizar o import no topo do arquivo:

```python
from routers.handlers.helpers import _send, _send_approval, _suggest_next_action
```

- [ ] **Step 3: Implementar handler do botão em `slack.py`**

Em `app/routers/slack.py`, no bloco que processa `callback_id` de interações (dentro de `_handle_interaction`), adicionar um novo case:

```python
elif callback_id == "add_analyzed_profile":
    if action_value == "approved":
        profile_data = conv.get_context("analyzed_profile_data", {})
        job_id = conv.get_context("current_job_id")
        if profile_data and job_id:
            # Check if talent already exists by email or LinkedIn
            existing = None
            if profile_data.get("email"):
                existing = await inhire.get_talent_by_email(profile_data["email"])
            if not existing and profile_data.get("linkedin_url"):
                username = profile_data["linkedin_url"].rstrip("/").split("/")[-1]
                existing = await inhire.get_talent_by_linkedin(username)

            try:
                if existing:
                    result = await inhire.add_existing_talent_to_job(job_id, existing["id"])
                    name = existing.get("name", "Candidato")
                else:
                    talent_payload = {
                        "name": profile_data.get("name", "Sem nome"),
                        "email": profile_data.get("email", ""),
                        "phone": profile_data.get("phone", ""),
                        "linkedinUsername": (profile_data.get("linkedin_url") or "").rstrip("/").split("/")[-1],
                    }
                    result = await inhire.add_talent_to_job(job_id, talent_payload, source="manual")
                    name = talent_payload["name"]

                await slack.post_message(
                    channel_id,
                    f"✅ *{name}* adicionado à vaga *{conv.get_context('current_job_name', '')}*!",
                )
            except Exception as e:
                logger.exception("Erro ao adicionar candidato analisado: %s", e)
                await slack.post_message(channel_id, f"❌ Não consegui adicionar: {e}")
    else:
        await slack.post_message(channel_id, "Ok, candidato não adicionado.")
```

- [ ] **Step 4: Testar E2E no Slack**

1. Definir vaga ativa: "me mostra os candidatos da vaga X"
2. Colar um perfil de LinkedIn: "analisa esse perfil: [colar texto]"
3. Verificar que aparece botão "Adicionar à vaga?"
4. Clicar "Aprovar" → verificar que candidato aparece na vaga no InHire

- [ ] **Step 5: Commit**

```bash
git add app/routers/handlers/hunting.py app/routers/slack.py
git commit -m "feat: fluxo analisar perfil → adicionar candidato à vaga"
```

---

### Task 4: Filtro de candidatos por etapa

**Files:**
- Modify: `app/routers/handlers/candidates.py`

- [ ] **Step 1: Adicionar parâmetro de filtro por stage em `_check_candidates`**

Em `app/routers/handlers/candidates.py`, modificar a assinatura de `_check_candidates` (linha 35):

```python
async def _check_candidates(conv, app, channel_id: str, job_id: str, stage_filter: str = ""):
```

- [ ] **Step 2: Implementar filtro após categorização**

Após o loop de categorização (após linha ~92), adicionar antes de `# Build report`:

```python
        # Filter by stage if requested
        if stage_filter:
            stage_lower = stage_filter.lower()
            all_candidates = high_fit + medium_fit + low_fit + no_score
            filtered = [c for c in all_candidates if stage_lower in c["stage"].lower()]

            if not filtered:
                await _send(
                    conv, slack, channel_id,
                    f"📋 *{job_name}*\nNenhum candidato na etapa *{stage_filter}*."
                    + _suggest_next_action(conv, total_candidates=len(applications)),
                )
                return

            # Rebuild categories with only filtered candidates
            filtered_ids = {c["id"] for c in filtered}
            high_fit = [c for c in high_fit if c["id"] in filtered_ids]
            medium_fit = [c for c in medium_fit if c["id"] in filtered_ids]
            low_fit = [c for c in low_fit if c["id"] in filtered_ids]
            no_score = [c for c in no_score if c["id"] in filtered_ids]
```

- [ ] **Step 3: Extrair stage_filter do tool_input no chamador**

Em `app/routers/slack.py`, no ponto onde `_check_candidates` é chamado (via `ver_candidatos` tool), passar o filtro de stage se Claude incluí-lo no tool call. Localizar a chamada e modificar:

```python
# Onde antes era:
await _check_candidates(conv, request.app, channel_id, job_id)

# Agora:
stage_filter = tool_input.get("stage_filter", "")
await _check_candidates(conv, request.app, channel_id, job_id, stage_filter=stage_filter)
```

- [ ] **Step 4: Adicionar parâmetro `stage_filter` na tool `ver_candidatos`**

Em `app/services/claude_client.py`, na definição de `ver_candidatos` em `ELI_TOOLS`, adicionar:

```python
{
    "name": "ver_candidatos",
    "description": "Mostra candidatos de uma vaga com scores de triagem",
    "input_schema": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "UUID da vaga (opcional se já tem vaga ativa)"},
            "stage_filter": {"type": "string", "description": "Filtrar por etapa (ex: 'Entrevista', 'Triagem'). Se vazio, mostra todos."},
        },
    },
}
```

- [ ] **Step 5: Testar no Slack**

1. "Me mostra quem tá na entrevista da vaga X"
2. Verificar que Claude usa `stage_filter: "entrevista"` no tool call
3. Verificar que só candidatos nessa etapa aparecem

- [ ] **Step 6: Commit**

```bash
git add app/routers/handlers/candidates.py app/routers/slack.py app/services/claude_client.py
git commit -m "feat: filtro de candidatos por etapa via linguagem natural"
```

---

### Task 5: Motivo de rejeição inteligente

**Files:**
- Modify: `app/routers/handlers/candidates.py`
- Modify: `app/services/claude_client.py`

- [ ] **Step 1: Adicionar método `classify_rejection_reason` no `claude_client.py`**

Em `app/services/claude_client.py`, adicionar método na classe `ClaudeClient`:

```python
async def classify_rejection_reason(
    self, candidate_name: str, candidate_summary: str, job_name: str, job_requirements: str,
) -> str:
    """Classify rejection reason into InHire enum: overqualified, underqualified, location, other."""
    response = await self.chat(
        messages=[{
            "role": "user",
            "content": (
                f"Candidato: {candidate_name}\nResumo: {candidate_summary}\n"
                f"Vaga: {job_name}\nRequisitos: {job_requirements}\n\n"
                "Classifique o motivo de rejeição em UMA palavra: overqualified, underqualified, location, ou other.\n"
                "Responda APENAS a palavra."
            ),
        }],
        system="Você classifica motivos de rejeição de candidatos. Responda apenas: overqualified, underqualified, location, ou other.",
        model="claude-haiku-4-5-20251001",
    )
    reason = response.strip().lower()
    valid = {"overqualified", "underqualified", "location", "other"}
    return reason if reason in valid else "other"
```

- [ ] **Step 2: Usar classificação em `_reject_candidates`**

Em `app/routers/handlers/candidates.py`, modificar `_reject_candidates` (linha 263-270). Substituir:

```python
    # Generate rejection message (goes as comment, not reason — reason is enum)
    rejection_msg = await claude.generate_rejection_message(job_name)

    result = await inhire.bulk_reject(
        [c["id"] for c in to_reject],
        reason="other",
        comment=rejection_msg,
    )
```

Por:

```python
    # Generate personalized rejection for each candidate
    job_data = conv.get_context("job_data", {})
    job_requirements = json.dumps(job_data.get("requirements", []), ensure_ascii=False) if job_data else ""

    # Group by rejection reason for batch processing
    reason_groups: dict[str, list] = {}
    for c in to_reject:
        c_name = c.get("name", "")
        c_summary = f"Score: {c.get('score', 'N/A')}, Stage: {c.get('stage', '')}, Location: {c.get('location', '')}"
        reason = await claude.classify_rejection_reason(c_name, c_summary, job_name, job_requirements)
        reason_groups.setdefault(reason, []).append(c)

    # Reject each group with appropriate reason
    total_rejected = 0
    total_count = len(to_reject)
    rejection_msg = await claude.generate_rejection_message(job_name)

    for reason, candidates in reason_groups.items():
        r = await inhire.bulk_reject(
            [c["id"] for c in candidates],
            reason=reason,
            comment=rejection_msg,
        )
        total_rejected += r.get("rejected", 0)

    result = {"rejected": total_rejected, "total": total_count}
```

Adicionar `import json` no topo se não existir.

- [ ] **Step 3: Testar no Slack**

1. Ter uma vaga com candidatos triados
2. "Reprova quem ficou de fora"
3. Verificar nos logs que cada candidato teve `reason` classificado
4. No InHire UI, verificar que motivos variam (não são todos "other")

- [ ] **Step 4: Commit**

```bash
git add app/routers/handlers/candidates.py app/services/claude_client.py
git commit -m "feat: motivo de rejeição inteligente classificado por Claude"
```

---

### Task 6: Devolutiva personalizada por candidato

**Files:**
- Modify: `app/services/claude_client.py`
- Modify: `app/routers/handlers/candidates.py`

- [ ] **Step 1: Adicionar método `generate_personalized_rejection` no `claude_client.py`**

```python
async def generate_personalized_rejection(
    self, candidate_name: str, stage_reached: str, strengths: str, job_name: str,
) -> str:
    """Generate a personalized rejection message for a specific candidate."""
    response = await self.chat(
        messages=[{
            "role": "user",
            "content": (
                f"Candidato: {candidate_name}\n"
                f"Vaga: {job_name}\n"
                f"Etapa alcançada: {stage_reached}\n"
                f"Pontos fortes observados: {strengths}\n\n"
                "Gere uma devolutiva profissional e empática em 3-4 linhas.\n"
                "Seja específico — mencione a etapa que alcançou e pelo menos um ponto positivo.\n"
                "Tom: respeitoso, encorajador, sem clichês."
            ),
        }],
        system="Você gera devolutivas de processos seletivos. Seja empático e específico.",
        model="claude-haiku-4-5-20251001",
    )
    return response.strip()
```

- [ ] **Step 2: Usar devolutiva personalizada na rejeição com WhatsApp**

Em `app/routers/handlers/candidates.py`, modificar o bloco de WhatsApp (linhas ~284-300). Onde monta `with_phone`, personalizar a mensagem:

```python
    # Offer WhatsApp devolutiva if comms enabled and candidates have phone
    user_data = app.state.user_mapping.get_user(conv.user_id) or {}
    if user_data.get("comms_enabled", True):
        with_phone = []
        for c in to_reject:
            phone = _talent_phone(c)
            if phone:
                c_name = c.get("name", "Sem nome")
                c_stage = c.get("stage", "")
                c_score = str(c.get("score", ""))
                personalized_msg = await claude.generate_personalized_rejection(
                    c_name, c_stage, f"Score: {c_score}", job_name,
                )
                with_phone.append({"phone": phone, "candidate_name": c_name, "message": personalized_msg})
```

- [ ] **Step 3: Testar no Slack**

1. Reprovar candidatos de uma vaga
2. Verificar que o prompt de WhatsApp mostra devolutiva personalizada (não genérica)
3. Verificar que cada candidato receberia mensagem diferente

- [ ] **Step 4: Commit**

```bash
git add app/services/claude_client.py app/routers/handlers/candidates.py
git commit -m "feat: devolutiva personalizada por candidato na rejeição"
```

---

### Task 7: Sugestão de reprovação do InHire

**Files:**
- Modify: `app/services/inhire_client.py`
- Modify: `app/routers/handlers/candidates.py`

- [ ] **Step 1: Adicionar método no client**

Em `app/services/inhire_client.py`:

```python
async def get_reproval_suggestion(self, job_talent_id: str) -> dict | None:
    """Get AI-generated reproval email suggestion from InHire."""
    try:
        return await self._request("POST", f"/job-talents/reproval/suggestion/{job_talent_id}")
    except Exception:
        return None
```

- [ ] **Step 2: Usar sugestão antes de gerar devolutiva própria**

Em `_reject_candidates`, antes de gerar `rejection_msg`, tentar usar sugestão do InHire como base:

```python
    # Try InHire's own reproval suggestion first (for first candidate as template)
    inhire_suggestion = None
    if to_reject:
        inhire_suggestion = await inhire.get_reproval_suggestion(to_reject[0]["id"])

    if inhire_suggestion and inhire_suggestion.get("body"):
        rejection_msg = inhire_suggestion["body"]
    else:
        rejection_msg = await claude.generate_rejection_message(job_name)
```

- [ ] **Step 3: Commit**

```bash
git add app/services/inhire_client.py app/routers/handlers/candidates.py
git commit -m "feat: usar sugestão de reprovação do InHire como fallback"
```

---

## Wave 2 — Oferta e Entrevista

### Task 8: URL do documento de oferta

**Files:**
- Modify: `app/routers/handlers/interviews.py`

- [ ] **Step 1: Buscar URL do documento após criar oferta**

Em `app/routers/handlers/interviews.py`, na função onde a oferta é criada (após `result = await inhire.create_offer_letter(payload)`, linha ~241), adicionar:

```python
        # Get document URL for preview
        doc_url = ""
        if offer_id:
            try:
                doc_info = await inhire.get_offer_document_url(offer_id)
                doc_url = doc_info.get("url", "") if isinstance(doc_info, dict) else str(doc_info)
            except Exception:
                pass

        doc_line = f"\n📄 <{doc_url}|Ver documento da oferta>" if doc_url else ""

        await _send(
            conv, slack, channel_id,
            f"✅ Carta oferta criada!\n\n"
            f"*Candidato:* {candidate_name}\n"
            f"*ID:* `{offer_id}`\n"
            f"*Status:* {status}"
            f"{doc_line}\n\n"
            f"O aprovador receberá uma notificação para revisar e assinar.\n"
            f"Após aprovação, a carta será enviada ao candidato automaticamente.",
        )
```

Remover o `await _send(...)` original que já existe (linhas ~245-253) pra não duplicar.

- [ ] **Step 2: Commit**

```bash
git add app/routers/handlers/interviews.py
git commit -m "feat: mostrar link do documento de oferta após criação"
```

---

### Task 9: Seleção inteligente de template de oferta

**Files:**
- Modify: `app/routers/handlers/interviews.py`

- [ ] **Step 1: Permitir escolha de template**

Em `_handle_offer_input` (linha 105), antes de criar a oferta, modificar a lógica de seleção de template. Onde hoje está `if templates: payload["templateId"] = templates[0].get("id", "")` (linha ~232-233), substituir por:

```python
        # Select template — if user specified a number, use it; otherwise ask
        template_choice = details.get("template_index")
        if templates:
            if template_choice is not None and 0 <= template_choice < len(templates):
                selected_template = templates[template_choice]
            elif len(templates) == 1:
                selected_template = templates[0]
            else:
                selected_template = templates[0]  # fallback to first

            payload["templateId"] = selected_template.get("id", "")
```

- [ ] **Step 2: Parsear escolha de template no input do usuário**

Na parte de `_handle_offer_input` onde Claude parseia o input (via `claude.chat()`), adicionar `template_index` como campo extraído. Na mensagem exibida em `_start_offer_flow`, os templates já são listados com números — só precisa parsear a escolha:

```python
        # Add template_index to parsed details if user mentioned a template
        if templates and len(templates) > 1:
            for i, t in enumerate(templates):
                t_name = t.get("name", "").lower()
                if t_name and t_name in text.lower():
                    details["template_index"] = i
                    break
```

- [ ] **Step 3: Commit**

```bash
git add app/routers/handlers/interviews.py
git commit -m "feat: seleção de template de oferta quando há múltiplos disponíveis"
```

---

### Task 10: Coletar data de início na oferta

**Files:**
- Modify: `app/routers/handlers/interviews.py`

- [ ] **Step 1: Adicionar campo na mensagem de coleta**

Em `_start_offer_flow`, modificar a mensagem de instruções (linha ~88-94):

```python
        msg += (
            "\nMe diga:\n"
            "• *Número* do candidato\n"
            "• *Salário* oferecido\n"
            "• *Data de início* prevista\n"
            "• *Email do aprovador* (quem precisa aprovar antes de enviar)\n\n"
            "Exemplo: `1 salário 18000 início 01/06/2026 aprovador joao@empresa.com`\n"
            "Ou me passe as informações de forma livre."
        )
```

- [ ] **Step 2: Usar data de início no payload**

Em `_handle_offer_input`, no bloco de `templateVariableValues` (linha ~234-239), substituir:

```python
            payload["templateVariableValues"] = {
                "salario": str(details.get("salary", "")),
                "nomeCargo": job_name,
                "nomeCandidato": candidate_name,
                "dataInicio": details.get("start_date", ""),
            }
```

O Claude já recebe texto livre e extrai campos — `start_date` vai ser parseado naturalmente se o prompt de extração incluir esse campo.

- [ ] **Step 3: Commit**

```bash
git add app/routers/handlers/interviews.py
git commit -m "feat: coletar e usar data de início na carta oferta"
```

---

### Task 11: Devolutiva em massa pós-fechamento de vaga

**Files:**
- Modify: `app/routers/webhooks.py`

- [ ] **Step 1: Ler o handler de contratação existente**

Ler `app/routers/webhooks.py` para entender o handler de comemoração de contratação (que já detecta stage "Contratado").

- [ ] **Step 2: Adicionar lógica de devolutiva em massa**

No handler de webhook que detecta contratação, após a celebração, adicionar:

```python
    # After celebration, check if there are remaining active candidates to reject
    try:
        all_candidates = await inhire.list_job_talents(job_id)
        active_remaining = [
            c for c in all_candidates
            if c.get("status") not in ("rejected", "dropped", "hired")
            and c.get("id") != job_talent_id  # exclude the hired one
        ]

        if active_remaining:
            # Notify recruiter about remaining candidates
            msg = (
                f"🎯 A vaga *{job_name}* tem uma contratação! Mas ainda há "
                f"*{len(active_remaining)} candidato(s)* no processo.\n\n"
                f"Quer que eu envie devolutiva profissional para todos eles?"
            )
            # Store for approval flow
            await redis.set(
                f"pending_closure_reject:{job_id}",
                json.dumps([c.get("id") for c in active_remaining]),
                ex=86400,  # 24h TTL
            )
            await slack.post_message(recruiter_channel, msg)
    except Exception as e:
        logger.warning("Erro ao verificar candidatos remanescentes após contratação: %s", e)
```

- [ ] **Step 3: Adicionar handler de resposta afirmativa**

Quando o recrutador responde "sim" (no fluxo normal de `_handle_idle`), detectar o contexto de closure pending e executar a reprovação em massa com devolutiva personalizada usando os métodos das Tasks 5 e 6.

- [ ] **Step 4: Testar E2E**

1. Mover um candidato para stage "Contratado" no InHire UI
2. Verificar que webhook dispara celebração
3. Verificar que mensagem aparece sobre candidatos remanescentes
4. Responder "sim" → verificar que devolutivas são enviadas

- [ ] **Step 5: Commit**

```bash
git add app/routers/webhooks.py app/routers/slack.py
git commit -m "feat: devolutiva em massa automática pós-fechamento de vaga"
```

---

### Task 12: Atualizar entrevista (remarcar)

**Files:**
- Modify: `app/services/inhire_client.py`
- Modify: `app/routers/handlers/interviews.py`

- [ ] **Step 1: Adicionar método no client**

Em `app/services/inhire_client.py`:

```python
async def update_appointment(self, appointment_id: str, payload: dict) -> dict | None:
    """Update an existing appointment (reschedule)."""
    return await self._request("PATCH", f"/job-talents/appointments/{appointment_id}/patch", json=payload)
```

- [ ] **Step 2: Adicionar fluxo de remarcação no handler**

Em `app/routers/handlers/interviews.py`, adicionar função:

```python
async def _reschedule_appointment(conv, app, channel_id: str, text: str):
    """Reschedule an existing appointment."""
    slack = app.state.slack
    inhire = app.state.inhire
    claude = app.state.claude

    job_talent_id = conv.get_context("scheduling_job_talent_id")
    if not job_talent_id:
        await _send(conv, slack, channel_id, "Preciso saber qual candidato remarcar. Me diz o nome ou seleciona a vaga primeiro.")
        return

    # List existing appointments for this candidate
    try:
        appointments = await inhire.list_candidate_appointments(job_talent_id)
        if not appointments:
            await _send(conv, slack, channel_id, "Este candidato não tem entrevistas agendadas.")
            return

        # Use latest appointment
        latest = appointments[-1]
        appointment_id = latest.get("id", "")

        # Parse new datetime from user text (same as scheduling flow)
        parsed = await claude.chat(
            messages=[{"role": "user", "content": f"Extraia data e hora desta mensagem: {text}"}],
            system="Extraia datetime em formato ISO 8601. Responda APENAS o datetime.",
            model="claude-haiku-4-5-20251001",
        )

        new_start = parsed.strip()
        update_payload = {"startDateTime": new_start}

        await inhire.update_appointment(appointment_id, update_payload)
        await _send(conv, slack, channel_id, f"✅ Entrevista remarcada para *{new_start}*!")

    except Exception as e:
        logger.exception("Erro ao remarcar entrevista: %s", e)
        await _send(conv, slack, channel_id, f"❌ Não consegui remarcar: {e}")

    conv.state = FlowState.IDLE
```

- [ ] **Step 3: Commit**

```bash
git add app/services/inhire_client.py app/routers/handlers/interviews.py
git commit -m "feat: remarcar entrevista sem cancelar e recriar"
```

---

### Task 13: Lembrete de entrevista

**Files:**
- Modify: `app/routers/handlers/interviews.py`
- Modify: `app/main.py` (se necessário adicionar scheduler job)

- [ ] **Step 1: Agendar lembrete ao criar entrevista**

Em `app/routers/handlers/interviews.py`, após a criação bem-sucedida do appointment (no final de `_handle_scheduling_input`), adicionar:

```python
    # Schedule reminder 2 hours before interview
    try:
        from datetime import datetime, timedelta, timezone

        start_str = appointment_payload.get("startDateTime", "")
        if start_str:
            clean = start_str.replace("Z", "").replace(".000", "").split("+")[0]
            start_dt = datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
            reminder_time = start_dt - timedelta(hours=2)

            if reminder_time > datetime.now(timezone.utc):
                scheduler = app.state.scheduler
                scheduler.add_job(
                    _send_interview_reminder,
                    trigger="date",
                    run_date=reminder_time,
                    args=[app, channel_id, candidate_name, job_name, start_str],
                    id=f"reminder_{appointment_id}",
                    replace_existing=True,
                )
                logger.info("Lembrete agendado para %s", reminder_time)
    except Exception as reminder_err:
        logger.warning("Não agendou lembrete: %s", reminder_err)
```

- [ ] **Step 2: Implementar função de lembrete**

No mesmo arquivo, adicionar no topo (após imports):

```python
async def _send_interview_reminder(app, channel_id: str, candidate_name: str, job_name: str, datetime_str: str):
    """Send interview reminder to recruiter via Slack."""
    slack = app.state.slack
    try:
        await slack.post_message(
            channel_id,
            f"⏰ *Lembrete:* Entrevista com *{candidate_name}* para a vaga *{job_name}* "
            f"começa em 2 horas ({datetime_str}).\n\n"
            f"Tudo pronto? Se precisar remarcar, é só me avisar!",
        )
    except Exception as e:
        logger.warning("Falha ao enviar lembrete: %s", e)
```

- [ ] **Step 3: Commit**

```bash
git add app/routers/handlers/interviews.py
git commit -m "feat: lembrete automático 2h antes da entrevista"
```

---

## Wave 3 — Analytics

### Task 14: Funil de conversão

**Files:**
- Modify: `app/routers/handlers/hunting.py` (onde `_job_status_report` vive)

- [ ] **Step 1: Encontrar e ler `_job_status_report`**

Localizar a função que gera o relatório de status da vaga. Ler o código completo.

- [ ] **Step 2: Adicionar cálculo de funil**

Na função de status report, após montar `stage_counts`, adicionar:

```python
    # Calculate conversion funnel
    if stages and applications:
        total = len(applications)
        funnel_lines = ["*Funil de conversão:*"]
        for stage in stages:
            stage_name = stage.get("name", "")
            count = stage_counts.get(stage_name, 0)
            pct = (count / total * 100) if total > 0 else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            funnel_lines.append(f"  {stage_name}: {bar} {count} ({pct:.0f}%)")
        funnel_text = "\n".join(funnel_lines)
```

Incluir `funnel_text` na mensagem de status.

- [ ] **Step 3: Commit**

```bash
git add app/routers/handlers/hunting.py
git commit -m "feat: funil de conversão visual no status da vaga"
```

---

### Task 15: Relatório semanal consolidado

**Files:**
- Modify: `app/services/proactive_monitor.py`

- [ ] **Step 1: Ler o `proactive_monitor.py` atual**

Entender a estrutura do briefing diário existente e o cron scheduler.

- [ ] **Step 2: Adicionar job de relatório semanal**

Adicionar no scheduler (onde o briefing diário de 9h é configurado) um novo cron job para segunda-feira 9:30 BRT:

```python
async def _weekly_report(self):
    """Generate weekly consolidated report for all recruiters."""
    for user_id in self._get_active_users():
        try:
            user_data = self.user_mapping.get_user(user_id)
            channel_id = user_data.get("channel_id", "")
            if not channel_id:
                continue

            # Get all active jobs
            jobs = await self.inhire.list_jobs_paginated(limit=50)
            active_jobs = [j for j in jobs.get("results", []) if j.get("status") == "active"]

            if not active_jobs:
                continue

            report_lines = ["📊 *Relatório Semanal*\n"]
            total_candidates = 0
            jobs_at_risk = 0

            for job in active_jobs:
                job_id = job.get("id", "")
                job_name = job.get("name", "")
                candidates = await self.inhire.list_job_talents(job_id)
                count = len(candidates)
                total_candidates += count

                # Calculate SLA
                created = job.get("createdAt", "")
                days_open = 0
                if created:
                    from datetime import datetime, timezone
                    try:
                        c_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        days_open = (datetime.now(timezone.utc) - c_dt).days
                    except Exception:
                        pass

                status_emoji = "🟢" if days_open < 15 else "🟡" if days_open < 30 else "🔴"
                if days_open >= 30:
                    jobs_at_risk += 1

                # Stage distribution
                stage_names = {}
                for c in candidates:
                    s = c.get("stage", {})
                    sn = s.get("name", "?") if isinstance(s, dict) else str(s)
                    stage_names[sn] = stage_names.get(sn, 0) + 1

                stages_str = " → ".join(f"{k}({v})" for k, v in stage_names.items())
                report_lines.append(
                    f"{status_emoji} *{job_name}* — {count} candidatos, {days_open}d aberta\n"
                    f"  Pipeline: {stages_str}\n"
                )

            report_lines.append(
                f"\n*Resumo:* {len(active_jobs)} vagas ativas, {total_candidates} candidatos, "
                f"{jobs_at_risk} em risco (30d+)"
            )

            await self.slack.post_message(channel_id, "\n".join(report_lines))

        except Exception as e:
            logger.warning("Erro no relatório semanal para %s: %s", user_id, e)
```

- [ ] **Step 3: Registrar o cron job no scheduler**

No `__init__` ou `start()` do ProactiveMonitor:

```python
self.scheduler.add_job(
    self._weekly_report,
    trigger="cron",
    day_of_week="mon",
    hour=9, minute=30,
    timezone="America/Sao_Paulo",
    id="weekly_report",
    replace_existing=True,
)
```

- [ ] **Step 4: Testar executando manualmente**

```python
await monitor._weekly_report()
```

- [ ] **Step 5: Commit**

```bash
git add app/services/proactive_monitor.py
git commit -m "feat: relatório semanal consolidado de todas as vagas (seg 9:30 BRT)"
```

---

### Task 16: Comparação entre vagas

**Files:**
- Modify: `app/routers/handlers/hunting.py`
- Modify: `app/services/claude_client.py` (adicionar tool)

- [ ] **Step 1: Adicionar tool `comparar_vagas` no ELI_TOOLS**

Em `app/services/claude_client.py`, adicionar à lista `ELI_TOOLS`:

```python
{
    "name": "comparar_vagas",
    "description": "Compara performance de vagas abertas (SLA, candidatos, funil)",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}
```

- [ ] **Step 2: Implementar handler `_compare_jobs`**

Em `app/routers/handlers/hunting.py`:

```python
async def _compare_jobs(conv, app, channel_id: str):
    """Compare active jobs performance side by side."""
    slack = app.state.slack
    inhire = app.state.inhire

    await _send(conv, slack, channel_id, "Comparando suas vagas... ⏳")

    try:
        jobs = await inhire._request("POST", "/jobs/paginated/lean", json={"limit": 20})
        active = [j for j in jobs.get("results", []) if j.get("status") == "active"]

        if not active:
            await _send(conv, slack, channel_id, "Nenhuma vaga ativa pra comparar.")
            return

        from datetime import datetime, timezone
        comparisons = []

        for job in active[:10]:  # Limit to 10
            job_id = job.get("id", "")
            job_name = job.get("name", "")
            candidates = await inhire.list_job_talents(job_id)

            days_open = 0
            created = job.get("createdAt", "")
            if created:
                try:
                    c_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    days_open = (datetime.now(timezone.utc) - c_dt).days
                except Exception:
                    pass

            comparisons.append({
                "name": job_name,
                "candidates": len(candidates),
                "days_open": days_open,
                "velocity": len(candidates) / max(days_open, 1),
            })

        # Sort by velocity (best performing first)
        comparisons.sort(key=lambda x: x["velocity"], reverse=True)

        msg = "📊 *Comparação de Vagas*\n\n"
        for i, c in enumerate(comparisons, 1):
            emoji = "🏆" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"*{i}.*"
            msg += (
                f"{emoji} *{c['name']}*\n"
                f"  Candidatos: {c['candidates']} | Dias aberta: {c['days_open']} | "
                f"Velocidade: {c['velocity']:.1f} cand/dia\n\n"
            )

        await _send(conv, slack, channel_id, msg)

    except Exception as e:
        logger.exception("Erro ao comparar vagas: %s", e)
        await _send(conv, slack, channel_id, f"❌ Erro ao comparar: {e}")
```

- [ ] **Step 3: Registrar handler no roteamento de tools no `slack.py`**

- [ ] **Step 4: Testar no Slack**

1. "Compara minhas vagas"
2. Verificar ranking com métricas

- [ ] **Step 5: Commit**

```bash
git add app/routers/handlers/hunting.py app/services/claude_client.py app/routers/slack.py
git commit -m "feat: comparação de performance entre vagas ativas"
```

---

### Task 17: Notificação automática de mudança de etapa

**Files:**
- Modify: `app/routers/webhooks.py`

- [ ] **Step 1: Ler webhook handler atual**

Entender como o webhook de stage change chega hoje e se já é processado.

- [ ] **Step 2: Adicionar notificação ao candidato**

No handler de webhook, quando detectar mudança de etapa (que não seja rejeição nem contratação):

```python
    # Notify candidate of stage advancement via email
    if new_stage and new_stage not in ("Contratado", "Rejeitado"):
        try:
            job_talent_id = payload.get("jobTalentId", "")
            candidate_email = payload.get("talentEmail", "")
            candidate_name = payload.get("talentName", "")
            job_name = payload.get("jobName", "")

            if candidate_email and job_talent_id:
                subject = f"Atualização sobre sua candidatura — {job_name}"
                body = (
                    f"Olá {candidate_name},\n\n"
                    f"Gostaríamos de informar que sua candidatura para a vaga de "
                    f"{job_name} avançou para a etapa de {new_stage}.\n\n"
                    f"Em breve entraremos em contato com mais detalhes.\n\n"
                    f"Atenciosamente,\nEquipe de Recrutamento"
                )
                await inhire.send_email([job_talent_id], subject, body)
                logger.info("Notificação de avanço enviada para %s", candidate_email)
        except Exception as e:
            logger.warning("Erro ao notificar candidato sobre mudança de etapa: %s", e)
```

- [ ] **Step 3: Adicionar flag de opt-in por recrutador**

Respeitar config do recrutador — só enviar se `auto_stage_notification` estiver habilitado:

```python
    user_config = user_mapping.get_user(recruiter_id) or {}
    if user_config.get("auto_stage_notification", False):
        # ... enviar notificação
```

- [ ] **Step 4: Commit**

```bash
git add app/routers/webhooks.py
git commit -m "feat: notificação automática ao candidato quando muda de etapa"
```

---

### Task 18: Previsão de fechamento (Claude)

**Files:**
- Modify: `app/routers/handlers/hunting.py`

- [ ] **Step 1: Adicionar previsão no `_job_status_report`**

Após montar o relatório de status com SLA e distribuição por etapa, adicionar:

```python
    # AI-powered closing prediction
    if applications and stages:
        prediction_prompt = (
            f"Vaga: {job_name}\n"
            f"Dias aberta: {days_open}\n"
            f"Total candidatos: {len(applications)}\n"
            f"Distribuição por etapa: {json.dumps(stage_counts, ensure_ascii=False)}\n"
            f"Candidatos com score alto: {len(high_fit)}\n\n"
            f"Em UMA frase, estime quando esta vaga pode ser fechada e por quê. "
            f"Se a vaga está em risco, diga o que fazer."
        )
        prediction = await claude.chat(
            messages=[{"role": "user", "content": prediction_prompt}],
            system="Você é analista de recrutamento. Faça previsões diretas baseadas nos dados.",
            model="claude-haiku-4-5-20251001",
        )
        status_msg += f"\n\n🔮 *Previsão:* {prediction.strip()}"
```

- [ ] **Step 2: Testar no Slack**

1. "Status da vaga X"
2. Verificar que inclui previsão de fechamento ao final

- [ ] **Step 3: Commit**

```bash
git add app/routers/handlers/hunting.py
git commit -m "feat: previsão de fechamento de vaga por IA no relatório de status"
```

---

## Referência — Bloqueado por API InHire

Estas tasks dependem de endpoints que ainda não existem. A spec em `docs/superpowers/specs/2026-04-13-gap-api-agente-design.md` detalha os payloads esperados para cada endpoint.

| # | Funcionalidade | Endpoint necessário | Prioridade |
|---|---|---|---|
| B1 | Formulário de inscrição | `GET/PUT /jobs/{id}/application-form` | P1 |
| B2 | Configurar triagem IA | `POST /jobs/{id}/screening-config` | P1 |
| B3 | Divulgação em portais | `POST /jobs/{id}/publish` | P1 |
| B4 | Histórico de movimentação | `GET /job-talents/{jt}/history` | P1 |
| B5 | Feedback do entrevistador | `POST /scorecards` + liberar GET | P1 |
| B6 | Scorecard configurável | `POST /jobs/{id}/scorecard` | P2 |
| B7 | Screening sob demanda | `POST /job-talents/{jt}/screening/run` | P2 |
| B8 | Scores detalhados | `GET /jobs/{id}/screening-results` | P2 |
| B9 | Template com variáveis | `GET /offer-letters/templates/{id}` | P2 |
| B10 | Webhooks de oferta | `offer.signed`, `offer.approved` | P2 |
| B11 | Talent pools | `POST /talent-pools/{id}/talents` | P2 |
| B12 | Histórico de comunicação | `GET /comms/{jt}/history` | P2 |
| B13 | Registro de recusa | `POST /offer-letters/{id}/decline` | P2 |
| B14 | Pipeline customizado | `PUT /jobs/{id}/stages` | P3 |
| B15 | Templates de vaga | `GET /job-templates` | P3 |
| B16 | Tags em candidatos | `POST /job-talents/{jt}/tags` | P3 |
| B17 | Entrevistas batch | `POST /appointments/create-batch` | P3 |
| B18 | Envio de testes | `GET/POST /jobs/{id}/tests` | P3 |
| B19 | Kit de entrevista | `GET /jobs/{id}/interview-kit` | P3 |
| B20 | Integração calendário | Provider google/microsoft | P2 |
| B21 | Status pós-entrevista | Webhook `appointment.completed` | P2 |
| B22 | No-show tracking | Campo `status` no PATCH appointment | P3 |
