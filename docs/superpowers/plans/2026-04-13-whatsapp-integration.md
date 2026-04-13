# WhatsApp Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrar envio de mensagens WhatsApp para candidatos via API InHire, com tool sob demanda e integracoes nos fluxos de reprovacao, agendamento e movimentacao.

**Architecture:** Novo metodo `send_whatsapp()` no `InHireClient` usando o mesmo `_request()` existente. Nova tool `enviar_whatsapp` no Claude. Helper `_normalize_phone()` + `_talent_phone()` em helpers.py. Ofertas de WhatsApp nos fluxos pos-acao via botoes de aprovacao. 4 novos callback_ids no handler de interacoes.

**Tech Stack:** Python 3.12, FastAPI, httpx, Anthropic SDK, Slack Web API (botoes), InHire WhatsApp API

---

### Task 1: Excepcoes tipadas + `send_whatsapp()` no InHireClient

**Files:**
- Modify: `app/services/inhire_client.py`

- [ ] **Step 1: Adicionar excepcoes tipadas no topo do arquivo (apos imports, antes da classe)**

Inserir apos `logger = logging.getLogger(...)` (linha 9):

```python
class WhatsAppWindowExpired(Exception):
    """422 — Janela de 24h do WhatsApp expirada."""
    pass

class WhatsAppInvalidPhone(Exception):
    """400 — Telefone invalido para WhatsApp."""
    pass
```

- [ ] **Step 2: Adicionar metodo `send_whatsapp` na classe InHireClient**

Inserir apos o bloco de `list_email_templates()` (apos linha 280):

```python
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
```

Nota: usa `self._client.request()` direto (nao `self._request()`) porque precisa checar status codes especificos antes de `raise_for_status()`.

- [ ] **Step 3: Verificar sintaxe**

Run: `python -c "import py_compile; py_compile.compile('app/services/inhire_client.py', doraise=True)"`
Expected: sem output (sucesso)

- [ ] **Step 4: Commit**

```bash
git add app/services/inhire_client.py
git commit -m "feat: send_whatsapp() + exceções tipadas no InHireClient (sessão 38)"
```

---

### Task 2: Helpers — `_normalize_phone()` e `_talent_phone()`

**Files:**
- Modify: `app/routers/handlers/helpers.py`

- [ ] **Step 1: Adicionar `_normalize_phone()` e `_talent_phone()` no final do arquivo**

Apos a funcao `_suggest_next_action()`:

```python
import re


def _normalize_phone(raw: str) -> str | None:
    """Normalize phone to international digits-only format for WhatsApp API.

    Examples:
        '+55 (11) 99999-8888' -> '5511999998888'
        '(11) 99999-8888'     -> '5511999998888'
        '11999998888'         -> '5511999998888'
    Returns None if result is not 10-15 digits.
    """
    digits = re.sub(r"\D", "", raw)
    # Brazilian numbers without country code
    if len(digits) in (10, 11) and not digits.startswith("55"):
        digits = "55" + digits
    if len(digits) < 10 or len(digits) > 15:
        return None
    return digits


def _talent_phone(a: dict) -> str | None:
    """Extract and normalize phone from a job-talent record."""
    raw = (
        a.get("talentPhone")
        or (a.get("talent") or {}).get("phone")
        or a.get("phone")
        or ""
    )
    if not raw:
        return None
    return _normalize_phone(raw)
```

- [ ] **Step 2: Verificar sintaxe**

Run: `python -c "import py_compile; py_compile.compile('app/routers/handlers/helpers.py', doraise=True)"`
Expected: sem output (sucesso)

- [ ] **Step 3: Commit**

```bash
git add app/routers/handlers/helpers.py
git commit -m "feat: _normalize_phone() e _talent_phone() em helpers (sessão 38)"
```

---

### Task 3: Tool `enviar_whatsapp` no claude_client.py + atualizar system prompt

**Files:**
- Modify: `app/services/claude_client.py`

- [ ] **Step 1: Adicionar tool `enviar_whatsapp` no array ELI_TOOLS**

Inserir antes da tool `gerenciar_rotina` (que fica antes de `conversa_livre`):

```python
    {
        "name": "enviar_whatsapp",
        "description": (
            "Envia mensagem WhatsApp para um candidato. "
            "Use quando o recrutador pedir pra mandar WhatsApp, avisar candidato, "
            "comunicar por WhatsApp, notificar candidato, enviar mensagem, "
            "falar com candidato, avisar sobre entrevista/resultado, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "ID da vaga (se mencionada ou em contexto)",
                },
                "candidate_name": {
                    "type": "string",
                    "description": "Nome do candidato para enviar a mensagem",
                },
                "message_intent": {
                    "type": "string",
                    "description": "O que o recrutador quer comunicar ao candidato",
                },
            },
            "required": ["message_intent"],
        },
    },
```

- [ ] **Step 2: Remover WhatsApp da lista de limitacoes no system prompt**

No `SYSTEM_PROMPT` (string longa no topo), encontrar e remover a linha:
```
- Enviar WhatsApp para candidatos — não existe API pública do InTerview ainda
```

- [ ] **Step 3: Adicionar capacidade de WhatsApp na secao de capacidades do system prompt**

Na lista de pontos de pausa (bloco que diz "PARE e peça aprovação"), adicionar no item "Comunicar candidatos externamente":
```
- Comunicar candidatos externamente (WhatsApp — requer aprovação, funciona se candidato interagiu com InHire nas últimas 24h)
```

- [ ] **Step 4: Adicionar metodo `generate_whatsapp_message()` na classe ClaudeService**

Inserir apos `generate_rejection_message()` (apos linha 629):

```python
    async def generate_whatsapp_message(self, intent: str, candidate_name: str,
                                         job_name: str = "", context: str = "") -> str:
        """Generate a professional WhatsApp message for a candidate."""
        system = (
            "Gere uma mensagem profissional e cordial para enviar via WhatsApp a um candidato "
            "em um processo seletivo. A mensagem deve:\n"
            "- Ser breve (máximo 500 caracteres — é WhatsApp, não email)\n"
            "- Usar tom profissional mas acolhedor\n"
            "- Não usar markdown (WhatsApp não renderiza)\n"
            "- Incluir o nome do candidato\n"
            "- Mencionar a empresa se possível\n"
            "Retorne apenas o texto da mensagem, sem aspas."
        )
        user_msg = f"Candidato: {candidate_name}\nVaga: {job_name}\nContexto: {context}\nIntenção: {intent}"
        return await self.chat(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
        )
```

- [ ] **Step 5: Verificar sintaxe**

Run: `python -c "import py_compile; py_compile.compile('app/services/claude_client.py', doraise=True)"`
Expected: sem output (sucesso)

- [ ] **Step 6: Commit**

```bash
git add app/services/claude_client.py
git commit -m "feat: tool enviar_whatsapp + generate_whatsapp_message (sessão 38)"
```

---

### Task 4: Handler `_handle_send_whatsapp` no slack.py

**Files:**
- Modify: `app/routers/slack.py`

- [ ] **Step 1: Adicionar import das excepcoes no topo do slack.py**

Junto aos imports de services (proximo da linha 15):

```python
from services.inhire_client import WhatsAppWindowExpired, WhatsAppInvalidPhone
```

- [ ] **Step 2: Adicionar import de `_talent_phone` nos imports de helpers**

Na linha que importa de helpers (proximo da linha 25), adicionar `_talent_phone`:

Encontrar:
```python
from routers.handlers.helpers import _send, _send_approval, _resolve_job_id, _build_dynamic_context, _suggest_next_action
```

Adicionar `_talent_phone` ao final da lista de imports.

- [ ] **Step 3: Adicionar handler `_handle_send_whatsapp` antes de `_handle_approval`**

Inserir antes de `async def _handle_approval(` (~linha 1159):

```python
async def _handle_send_whatsapp(conv, app, channel_id: str, tool_input: dict):
    """Handle free-form WhatsApp message sending."""
    slack = app.state.slack
    inhire = app.state.inhire
    claude = app.state.claude

    job_id = _resolve_job_id(conv, tool_input)
    candidate_name = tool_input.get("candidate_name", "")
    message_intent = tool_input.get("message_intent", "")

    if not job_id:
        await _send(conv, slack, channel_id, "Pra qual vaga? Posso te mostrar suas vagas se quiser.")
        return

    # Find candidate
    try:
        talents = await inhire.list_job_talents(job_id)
    except Exception:
        await _send(conv, slack, channel_id, "Não consegui acessar os candidatos dessa vaga.")
        return

    candidate = None
    if candidate_name:
        name_lower = candidate_name.lower()
        for t in talents:
            t_name = (t.get("talent") or {}).get("name") or t.get("talentName") or ""
            if name_lower in t_name.lower():
                candidate = t
                break

    if not candidate:
        # List candidates with phone
        with_phone = []
        for t in talents[:20]:
            phone = _talent_phone(t)
            t_name = (t.get("talent") or {}).get("name") or t.get("talentName") or "Sem nome"
            if phone:
                with_phone.append(t_name)
        if with_phone:
            names = "\n".join(f"• {n}" for n in with_phone)
            await _send(conv, slack, channel_id, f"Qual candidato? Estes têm telefone:\n{names}")
        else:
            await _send(conv, slack, channel_id, "Nenhum candidato dessa vaga tem telefone cadastrado.")
        return

    phone = _talent_phone(candidate)
    if not phone:
        c_name = (candidate.get("talent") or {}).get("name") or candidate.get("talentName") or "candidato"
        await _send(conv, slack, channel_id, f"{c_name} não tem telefone cadastrado.")
        return

    c_name = (candidate.get("talent") or {}).get("name") or candidate.get("talentName") or "Candidato"
    job_name = conv.get_context("current_job_name", "")

    # Generate message with Claude
    msg_text = await claude.generate_whatsapp_message(
        intent=message_intent,
        candidate_name=c_name,
        job_name=job_name,
    )

    # Store in context for approval callback
    conv.set_context("whatsapp_pending", {
        "phone": phone,
        "message": msg_text,
        "candidate_name": c_name,
    })

    await _send_approval(
        conv, slack, channel_id,
        title=f"WhatsApp para {c_name}",
        details=f"📱 *Para:* {phone}\n\n{msg_text}",
        callback_id="whatsapp_free_approval",
    )
    conv.state = FlowState.WAITING_WHATSAPP_APPROVAL
```

- [ ] **Step 4: Adicionar dispatch no `_handle_idle`**

Encontrar (proximo da linha 892):
```python
    elif tool == "gerenciar_rotina":
```

Inserir ANTES dessa linha:
```python
    elif tool == "enviar_whatsapp":
        await _handle_send_whatsapp(conv, app, channel_id, tool_input)
```

- [ ] **Step 5: Verificar sintaxe**

Run: `python -c "import py_compile; py_compile.compile('app/routers/slack.py', doraise=True)"`
Expected: sem output (sucesso)

- [ ] **Step 6: Commit**

```bash
git add app/routers/slack.py
git commit -m "feat: handler _handle_send_whatsapp + dispatch no _handle_idle (sessão 38)"
```

---

### Task 5: Adicionar `WAITING_WHATSAPP_APPROVAL` no FlowState

**Files:**
- Modify: `app/services/conversation.py`

- [ ] **Step 1: Adicionar estado ao enum FlowState**

Encontrar a classe `FlowState` e adicionar:

```python
    WAITING_WHATSAPP_APPROVAL = "waiting_whatsapp_approval"
```

Inserir apos o ultimo estado existente (provavelmente `CREATING_OFFER`).

- [ ] **Step 2: Atualizar dict de handlers no slack.py se necessario**

O `WAITING_WHATSAPP_APPROVAL` usa o mesmo handler generico `_handle_waiting_approval` que os outros estados WAITING_*. Verificar no dict de handlers (slack.py ~linha 287) que o padrao `WAITING_*` ja cobre este caso. Se nao, adicionar:

```python
    FlowState.WAITING_WHATSAPP_APPROVAL: _handle_waiting_approval,
```

- [ ] **Step 3: Verificar sintaxe**

Run: `python -c "import py_compile; py_compile.compile('app/services/conversation.py', doraise=True)"`
Expected: sem output (sucesso)

- [ ] **Step 4: Commit**

```bash
git add app/services/conversation.py app/routers/slack.py
git commit -m "feat: FlowState.WAITING_WHATSAPP_APPROVAL (sessão 38)"
```

---

### Task 6: Callback handlers de WhatsApp no `_handle_approval`

**Files:**
- Modify: `app/routers/slack.py`

- [ ] **Step 1: Adicionar handler para `whatsapp_free_approval` no `_handle_approval`**

Encontrar (proximo da linha 1278):
```python
        elif callback_id == "offer_approval":
```

Inserir ANTES dessa linha:

```python
        elif callback_id == "whatsapp_free_approval":
            if action_id == "approve":
                pending = conv.get_context("whatsapp_pending", {})
                if pending:
                    try:
                        result = await inhire.send_whatsapp(pending["phone"], pending["message"])
                        await _send(
                            conv, slack, channel_id,
                            f"✅ WhatsApp enviado pra *{pending.get('candidate_name', 'candidato')}*!",
                        )
                    except WhatsAppWindowExpired:
                        await _send(
                            conv, slack, channel_id,
                            f"Não consegui enviar — *{pending.get('candidate_name', 'o candidato')}* "
                            f"não interagiu com o WhatsApp do InHire nas últimas 24h.",
                        )
                    except WhatsAppInvalidPhone:
                        await _send(
                            conv, slack, channel_id,
                            f"O telefone de *{pending.get('candidate_name', 'candidato')}* não parece válido pra WhatsApp.",
                        )
                    except Exception as e:
                        logger.exception("Erro WhatsApp: %s", e)
                        await _send(conv, slack, channel_id, "Erro ao enviar WhatsApp. Tenta de novo em alguns minutos?")
                conv.set_context("whatsapp_pending", None)
                conv.state = FlowState.IDLE
            elif action_id in ("adjust", "reject"):
                conv.set_context("whatsapp_pending", None)
                conv.state = FlowState.IDLE
                await _send(conv, slack, channel_id, "Ok, não enviei nada.")

        elif callback_id == "whatsapp_rejection_approval":
            if action_id == "approve":
                pending_list = conv.get_context("whatsapp_rejection_pending", [])
                sent = 0
                failed = 0
                for item in pending_list:
                    try:
                        await inhire.send_whatsapp(item["phone"], item["message"])
                        sent += 1
                    except (WhatsAppWindowExpired, WhatsAppInvalidPhone):
                        failed += 1
                    except Exception:
                        failed += 1
                msg = f"✅ Devolutiva enviada por WhatsApp pra {sent} candidato(s)."
                if failed:
                    msg += f"\n⚠️ {failed} não receberam (sem WhatsApp ativo ou telefone inválido)."
                await _send(conv, slack, channel_id, msg)
                conv.set_context("whatsapp_rejection_pending", None)
                conv.state = FlowState.IDLE
            elif action_id in ("adjust", "reject"):
                conv.set_context("whatsapp_rejection_pending", None)
                conv.state = FlowState.IDLE
                await _send(conv, slack, channel_id, "Ok, não enviei nenhuma devolutiva por WhatsApp.")

        elif callback_id == "whatsapp_move_approval":
            if action_id == "approve":
                pending_list = conv.get_context("whatsapp_move_pending", [])
                sent = 0
                failed = 0
                for item in pending_list:
                    try:
                        await inhire.send_whatsapp(item["phone"], item["message"])
                        sent += 1
                    except (WhatsAppWindowExpired, WhatsAppInvalidPhone):
                        failed += 1
                    except Exception:
                        failed += 1
                msg = f"✅ {sent} candidato(s) avisado(s) por WhatsApp!"
                if failed:
                    msg += f"\n⚠️ {failed} não receberam (sem WhatsApp ativo ou telefone inválido)."
                await _send(conv, slack, channel_id, msg)
                conv.set_context("whatsapp_move_pending", None)
                conv.state = FlowState.IDLE
            elif action_id in ("adjust", "reject"):
                conv.set_context("whatsapp_move_pending", None)
                conv.state = FlowState.IDLE
                await _send(conv, slack, channel_id, "Ok, não avisei ninguém.")

        elif callback_id == "whatsapp_interview_approval":
            if action_id == "approve":
                pending = conv.get_context("whatsapp_interview_pending", {})
                if pending:
                    try:
                        await inhire.send_whatsapp(pending["phone"], pending["message"])
                        await _send(
                            conv, slack, channel_id,
                            f"✅ Confirmação de entrevista enviada por WhatsApp pra *{pending.get('candidate_name', 'candidato')}*!",
                        )
                    except WhatsAppWindowExpired:
                        await _send(
                            conv, slack, channel_id,
                            f"Não consegui enviar — o candidato não interagiu com o WhatsApp do InHire nas últimas 24h.",
                        )
                    except (WhatsAppInvalidPhone, Exception) as e:
                        logger.exception("Erro WhatsApp entrevista: %s", e)
                        await _send(conv, slack, channel_id, "Erro ao enviar WhatsApp.")
                conv.set_context("whatsapp_interview_pending", None)
                conv.state = FlowState.IDLE
            elif action_id in ("adjust", "reject"):
                conv.set_context("whatsapp_interview_pending", None)
                conv.state = FlowState.IDLE
                await _send(conv, slack, channel_id, "Ok, não enviei a confirmação.")
```

- [ ] **Step 2: Verificar sintaxe**

Run: `python -c "import py_compile; py_compile.compile('app/routers/slack.py', doraise=True)"`
Expected: sem output (sucesso)

- [ ] **Step 3: Commit**

```bash
git add app/routers/slack.py
git commit -m "feat: callback handlers de WhatsApp no _handle_approval (sessão 38)"
```

---

### Task 7: Integrar oferta de WhatsApp nos fluxos existentes

**Files:**
- Modify: `app/routers/handlers/candidates.py`
- Modify: `app/routers/handlers/interviews.py`

- [ ] **Step 1: Adicionar imports em candidates.py**

No topo de `candidates.py`, adicionar aos imports existentes:

```python
from routers.handlers.helpers import _send, _send_approval, _talent_phone
```

(Ajustar a linha de import existente para incluir `_talent_phone`.)

- [ ] **Step 2: Adicionar oferta WhatsApp apos reprovacao em `_reject_candidates`**

Encontrar o final de `_reject_candidates` (apos a mensagem de sucesso, antes de `conv.state = FlowState.IDLE`):

Substituir:
```python
    await _send(
        conv, slack, channel_id,
        f"Feito! {result['rejected']}/{result['total']} reprovados e devolutiva enviada.\n"
        f"> {rejection_msg[:300]}"
        + tip,
    )
    conv.state = FlowState.IDLE
```

Por:
```python
    await _send(
        conv, slack, channel_id,
        f"Feito! {result['rejected']}/{result['total']} reprovados e devolutiva enviada.\n"
        f"> {rejection_msg[:300]}"
        + tip,
    )

    # Offer WhatsApp devolutiva if comms enabled and candidates have phone
    user_data = app.state.user_mapping.get_user(conv.user_id) or {}
    if user_data.get("comms_enabled", True):
        with_phone = []
        for c in to_reject:
            phone = _talent_phone(c)
            if phone:
                c_name = (c.get("talent") or {}).get("name") or c.get("talentName") or "Sem nome"
                with_phone.append({"phone": phone, "candidate_name": c_name, "message": rejection_msg})
        if with_phone:
            conv.set_context("whatsapp_rejection_pending", with_phone)
            await _send_approval(
                conv, slack, channel_id,
                title="Enviar devolutiva por WhatsApp?",
                details=f"{len(with_phone)} candidato(s) com telefone.\nMensagem:\n> {rejection_msg[:200]}",
                callback_id="whatsapp_rejection_approval",
            )
            return

    conv.state = FlowState.IDLE
```

- [ ] **Step 3: Adicionar oferta WhatsApp apos mover candidatos em `_move_approved_candidates`**

Encontrar o final de `_move_approved_candidates` — apos o bloco que oferece reprovar restantes (apos `callback_id="rejection_approval"`), adicionar oferta de WhatsApp.

Encontrar o trecho que segue apos `conv.state = FlowState.WAITING_REJECTION_APPROVAL` ou apos o `else` que nao tem remaining. Inserir o seguinte bloco no final da funcao (apos o if/else de remaining):

Localizar a linha:
```python
                callback_id="rejection_approval",
            )
            conv.state = FlowState.WAITING_REJECTION_APPROVAL
        else:
```

Ler ate o final do else para identificar onde inserir. O bloco de oferta WhatsApp deve vir quando NAO ha candidatos para reprovar (no else) ou como acao separada. Pela complexidade, a oferta de WhatsApp para mover vai ficar na callback de `shortlist_approval` no `_handle_approval`, nao aqui.

**Abordagem simplificada:** adicionar a oferta de WhatsApp no callback `shortlist_approval` do `_handle_approval` no `slack.py`, apos o `_move_approved_candidates` retornar. Isso e mais limpo porque o fluxo de mover ja pode desencadear reprovacao.

Inserir no `_handle_approval`, dentro do `elif callback_id == "shortlist_approval":`, apos `await _move_approved_candidates(conv, app, channel_id)`:

No slack.py, encontrar:
```python
        elif callback_id == "shortlist_approval":
            if action_id == "approve":
                await _move_approved_candidates(conv, app, channel_id)
```

Nao modificar aqui — a oferta WhatsApp pra movimentacao sera implementada como melhoria futura (a funcao `_move_approved_candidates` ja chama `_send_approval` para reprovar restantes, e encadear dois botoes seguidos seria confuso para o recrutador). **Priorizar a tool livre e a devolutiva pos-reprovacao.**

- [ ] **Step 4: Adicionar import em interviews.py**

No topo de `interviews.py`, adicionar:

```python
from routers.handlers.helpers import _talent_phone
```

- [ ] **Step 5: Adicionar oferta WhatsApp apos agendar entrevista**

Em `_handle_scheduling_input`, encontrar o bloco de sucesso (apos `await _send(conv, slack, channel_id, ...` que mostra "Entrevista agendada!"):

Substituir:
```python
        await _send(
            conv, slack, channel_id,
            f"✅ Entrevista agendada!\n\n"
            f"*Candidato:* {candidate_name}\n"
            f"*Vaga:* {job_name}\n"
            f"*Data:* {dt_readable}\n"
            f"*ID:* `{appt_id}`\n\n"
            f"O agendamento foi registrado no InHire. "
            f"Lembre de enviar o convite com o link da reunião ao candidato.",
        )
        conv.state = FlowState.IDLE
```

Por:
```python
        await _send(
            conv, slack, channel_id,
            f"✅ Entrevista agendada!\n\n"
            f"*Candidato:* {candidate_name}\n"
            f"*Vaga:* {job_name}\n"
            f"*Data:* {dt_readable}\n"
            f"*ID:* `{appt_id}`",
        )

        # Offer WhatsApp confirmation
        phone = _talent_phone(candidate)
        user_data = app.state.user_mapping.get_user(conv.user_id) or {}
        if phone and user_data.get("comms_enabled", True):
            claude = app.state.claude
            msg_text = await claude.generate_whatsapp_message(
                intent=f"Confirmar entrevista agendada para {dt_readable}",
                candidate_name=candidate_name,
                job_name=job_name,
            )
            conv.set_context("whatsapp_interview_pending", {
                "phone": phone,
                "message": msg_text,
                "candidate_name": candidate_name,
            })
            await _send_approval(
                conv, slack, channel_id,
                title="Confirmar por WhatsApp?",
                details=f"📱 *Para:* {candidate_name}\n\n{msg_text}",
                callback_id="whatsapp_interview_approval",
            )
            return

        conv.state = FlowState.IDLE
```

- [ ] **Step 6: Verificar sintaxe de ambos os arquivos**

Run: `python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['app/routers/handlers/candidates.py', 'app/routers/handlers/interviews.py']]"`
Expected: sem output (sucesso)

- [ ] **Step 7: Commit**

```bash
git add app/routers/handlers/candidates.py app/routers/handlers/interviews.py
git commit -m "feat: oferta WhatsApp após reprovar e agendar entrevista (sessão 38)"
```

---

### Task 8: Testar endpoint WhatsApp no servidor

**Files:**
- Nenhum — teste manual

- [ ] **Step 1: Testar conectividade com o endpoint**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "source /var/www/agente-inhire/venv/bin/activate && python3 -c \"
import asyncio, httpx
from config import Settings
from services.inhire_auth import InHireAuth

async def test():
    s = Settings()
    auth = InHireAuth(s)
    await auth.login()
    client = httpx.AsyncClient(timeout=30)
    # Test with obviously fake phone to see if endpoint responds (expect 400, not 404/502)
    resp = await client.request(
        'POST',
        f'{s.inhire_api_url}/subscription-assistant/tenant/{auth.tenant}/send',
        headers=auth.headers,
        json={'phone': '0000', 'message': 'test'},
    )
    print(f'Status: {resp.status_code}')
    print(f'Body: {resp.text[:200]}')
    await client.aclose()

asyncio.run(test())
\""
```

Expected: status 400 (telefone invalido) — confirma que o endpoint existe e responde.

- [ ] **Step 2: Se receber 404 — avisar Andre que o endpoint nao esta em producao**

Se status for 404: o endpoint ainda nao foi deployado em `api.inhire.app`. Mandar mensagem pro Andre pedindo pra verificar.

- [ ] **Step 3: Commit final de documentacao se tudo OK**

Se o teste passar, nenhum commit adicional necessario neste step.

---

### Task 9: Deploy e validacao

**Files:**
- Deploy: todos os arquivos modificados nas Tasks 1-7

- [ ] **Step 1: Copiar arquivos para o servidor**

```bash
for f in services/inhire_client.py services/claude_client.py services/conversation.py routers/handlers/helpers.py routers/handlers/candidates.py routers/handlers/interviews.py routers/slack.py; do
    scp -i ~/.ssh/n8n_rescue_key "app/$f" root@65.109.160.97:/var/www/agente-inhire/$f
done
```

- [ ] **Step 2: Restart do servico**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "systemctl restart agente-inhire"
```

- [ ] **Step 3: Verificar logs de startup**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "sleep 4 && journalctl -u agente-inhire -n 20 --no-pager"
```

Expected: sem erros, startup normal.

- [ ] **Step 4: Health check**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "curl -s http://localhost:8100/health"
```

Expected: `{"status":"ok","service":"agente-inhire"}`

- [ ] **Step 5: Testar no Slack — tool livre**

Enviar DM pro Eli: "manda um whatsapp pro joao avisando que ele passou pra proxima etapa"

Expected: Eli resolve candidato, gera mensagem, mostra preview com botao de aprovacao.

- [ ] **Step 6: Atualizar CLAUDE.md e DIARIO_DO_PROJETO.md**

Adicionar melhoria #29 na tabela do CLAUDE.md:
```
| 29 | **WhatsApp integration** — envio via API InHire, tool livre + oferta pós-ação | ✅ | 38 |
```

Registrar sessao 38 no diario.

- [ ] **Step 7: Commit final**

```bash
git add CLAUDE.md DIARIO_DO_PROJETO.md
git commit -m "docs: sessão 38 — integração WhatsApp completa"
```
