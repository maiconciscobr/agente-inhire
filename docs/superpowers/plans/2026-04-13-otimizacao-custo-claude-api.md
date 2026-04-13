# Otimizacao de Custo da API Claude — Plano de Implementacao

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduzir custo da API Claude em 20-35% eliminando double-calls, usando Haiku para tarefas triviais, e comprimindo tool definitions — com instrumentacao para medir o antes/depois.

**Architecture:** Adicionar logging de tokens em todas as chamadas Claude (Fase 1), depois aplicar 4 otimizacoes no `claude_client.py` e `slack.py` (Fase 2). O `ClaudeService` ganha um segundo modelo (`fast_model` = Haiku) e `chat()` ganha parametro `max_tokens` opcional. O `detect_intent()` muda de `tool_choice: any` para `auto` com parsing robusto de responses mistos.

**Tech Stack:** Python 3.12, Anthropic SDK 0.43.0, FastAPI, Redis

**Spec:** `docs/superpowers/specs/2026-04-13-otimizacao-custo-claude-api.md`

---

### Task 1: Instrumentacao — logging de tokens em todas as chamadas Claude

**Files:**
- Modify: `app/services/claude_client.py:1-10` (imports)
- Modify: `app/services/claude_client.py:346-350` (ClaudeService.__init__)
- Modify: `app/services/claude_client.py:370-378` (chat)
- Modify: `app/services/claude_client.py:380-403` (detect_intent)
- Modify: `app/services/claude_client.py:426-454` (classify_briefing_reply)
- Modify: `app/services/claude_client.py:456-505` (parse_routine_request)

- [ ] **Step 1: Adicionar import de time e constantes de pricing**

No topo de `app/services/claude_client.py`, adicionar `import time` e o dict de pricing:

```python
import json
import logging
import time

import anthropic

from config import Settings

logger = logging.getLogger("agente-inhire.claude")
usage_logger = logging.getLogger("agente-inhire.claude.usage")

# Pricing per 1M tokens (USD) — atualizar se pricing mudar
PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
}
```

- [ ] **Step 2: Criar o helper `_log_usage` no `ClaudeService`**

Adicionar apos o `_build_system` (depois da linha 368):

```python
def _log_usage(self, method: str, resp, latency_ms: int):
    """Log token usage and estimated cost for every Claude API call."""
    try:
        usage = resp.usage
        model = resp.model or self.model
        prices = PRICING.get(model, PRICING["claude-sonnet-4-20250514"])

        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
        cache_creation = getattr(usage, "cache_creation_input_tokens", 0)
        cache_read = getattr(usage, "cache_read_input_tokens", 0)

        cost = (
            (input_tokens - cache_creation - cache_read) * prices["input"] / 1_000_000
            + output_tokens * prices["output"] / 1_000_000
            + cache_creation * prices["cache_write"] / 1_000_000
            + cache_read * prices["cache_read"] / 1_000_000
        )

        usage_logger.info(json.dumps({
            "method": method,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
            "stop_reason": resp.stop_reason,
            "latency_ms": latency_ms,
            "estimated_cost_usd": round(cost, 6),
        }))
    except Exception as e:
        logger.warning("Erro ao logar usage: %s", e)
```

- [ ] **Step 3: Instrumentar o metodo `chat()`**

Substituir o metodo `chat` atual (linhas 370-378):

```python
async def chat(self, messages: list[dict], system: str | None = None,
               dynamic_context: str | None = None) -> str:
    t0 = time.monotonic()
    resp = await self.client.messages.create(
        model=self.model,
        max_tokens=4096,
        system=self._build_system(system or SYSTEM_PROMPT_STATIC, dynamic_context),
        messages=messages,
    )
    self._log_usage("chat", resp, int((time.monotonic() - t0) * 1000))
    return resp.content[0].text
```

- [ ] **Step 4: Instrumentar o metodo `detect_intent()`**

Substituir o metodo `detect_intent` atual (linhas 380-403):

```python
async def detect_intent(self, messages: list[dict],
                        dynamic_context: str | None = None) -> dict:
    t0 = time.monotonic()
    resp = await self.client.messages.create(
        model=self.model,
        max_tokens=1024,
        system=self._build_system(SYSTEM_PROMPT_STATIC, dynamic_context),
        tools=ELI_TOOLS,
        tool_choice={"type": "any"},
        messages=messages,
    )
    self._log_usage("detect_intent", resp, int((time.monotonic() - t0) * 1000))

    for block in resp.content:
        if block.type == "tool_use":
            return {"tool": block.name, "input": block.input}

    text = next((b.text for b in resp.content if hasattr(b, "text")), "")
    return {"tool": None, "text": text}
```

- [ ] **Step 5: Instrumentar `classify_briefing_reply()`**

Adicionar timing no metodo (linhas 426-454). Envolver a chamada `messages.create`:

```python
async def classify_briefing_reply(self, user_text: str, has_missing_info: bool) -> str:
    system = (
        "Você classifica a resposta de um recrutador durante a criação de uma vaga.\n"
        "O recrutador já passou o briefing inicial e foi perguntado se quer complementar.\n\n"
        "Classifique a mensagem em EXATAMENTE uma palavra:\n"
        "- proceed — quer prosseguir, criar a vaga, não tem mais info, manda gerar, "
        "qualquer variação de 'vai', 'cria', 'pode ser', 'prossiga', 'não tenho', 'tá bom', etc.\n"
        "- more_info — está fornecendo dados adicionais (responsabilidades, benefícios, stack, etc.)\n"
        "- cancel — quer cancelar, desistir, parar, mudar de assunto\n\n"
        "Responda APENAS: proceed, more_info ou cancel"
    )
    context = f"Tem info faltando: {'sim' if has_missing_info else 'não'}"
    t0 = time.monotonic()
    resp = await self.client.messages.create(
        model=self.model,
        max_tokens=20,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"[{context}]\nRecrutador disse: {user_text}"}],
    )
    self._log_usage("classify_briefing_reply", resp, int((time.monotonic() - t0) * 1000))
    result = resp.content[0].text.strip().lower()
    if result not in ("proceed", "more_info", "cancel"):
        return "proceed" if any(w in result for w in ["proceed", "prosseg"]) else "more_info"
    return result
```

- [ ] **Step 6: Instrumentar `parse_routine_request()`**

Adicionar timing na chamada `messages.create` dentro de `parse_routine_request` (linhas 494-505):

```python
    t0 = time.monotonic()
    resp = await self.client.messages.create(
        model=self.model,
        max_tokens=300,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": text}],
    )
    self._log_usage("parse_routine_request", resp, int((time.monotonic() - t0) * 1000))

    import json as json_mod
    raw = resp.content[0].text.strip()
```

- [ ] **Step 7: Commit da Fase 1**

```bash
git add app/services/claude_client.py
git commit -m "feat: instrumentacao de custo — logging de tokens em todas as chamadas Claude

Adiciona _log_usage() com input/output tokens, cache stats, latencia,
modelo, stop_reason, e custo estimado em USD. Formato JSON para query
com jq. Logger separado (agente-inhire.claude.usage) para filtragem."
```

---

### Task 2: Eliminar double-call do conversa_livre (tool_choice auto)

**Files:**
- Modify: `app/services/claude_client.py:380-403` (detect_intent — tool_choice + parsing)
- Modify: `app/routers/slack.py:672-686` (_handle_idle — fallback tool is None)
- Modify: `app/routers/slack.py:893-897` (_handle_idle — bloco conversa_livre)

- [ ] **Step 1: Reescrever `detect_intent()` com tool_choice auto e parsing robusto**

Substituir o `detect_intent` (que ja tem logging da Task 1):

```python
async def detect_intent(self, messages: list[dict],
                        dynamic_context: str | None = None) -> dict:
    """Use Claude tool calling to detect user intent.

    Returns:
        {"tool": "tool_name", "input": {...}, "text": "..."} if a tool was called
        {"tool": None, "text": "..."} if no tool was called (direct response)
    """
    t0 = time.monotonic()
    resp = await self.client.messages.create(
        model=self.model,
        max_tokens=2048,
        system=self._build_system(SYSTEM_PROMPT_STATIC, dynamic_context),
        tools=ELI_TOOLS,
        tool_choice={"type": "auto"},
        messages=messages,
    )
    self._log_usage("detect_intent", resp, int((time.monotonic() - t0) * 1000))

    tool_block = None
    text_parts = []
    for block in resp.content:
        if block.type == "tool_use" and tool_block is None:
            tool_block = block
        elif hasattr(block, "text") and block.text:
            text_parts.append(block.text)

    combined_text = "\n".join(text_parts) if text_parts else ""

    if tool_block:
        return {"tool": tool_block.name, "input": tool_block.input, "text": combined_text}

    return {"tool": None, "text": combined_text or ""}
```

- [ ] **Step 2: Atualizar _handle_idle no slack.py — bloco conversa_livre**

No `app/routers/slack.py`, substituir o bloco `conversa_livre` (linhas 895-897):

```python
    elif tool == "conversa_livre":
        # Use text from detect_intent if available, avoid double-call
        direct_text = result.get("text", "")
        if direct_text.strip():
            await _send(conv, slack, channel_id, direct_text)
        else:
            response = await claude.chat(conv.messages)
            await _send(conv, slack, channel_id, response)
```

- [ ] **Step 3: Verificar que o handler `tool is None` continua correto**

No `app/routers/slack.py`, linhas 683-686 — o bloco ja existente funciona sem mudanca:

```python
    if tool is None:
        # No tool called — use text response directly
        await _send(conv, slack, channel_id, result.get("text", "Não entendi. Pode reformular?"))
        return
```

Confirmar que nao precisa de mudanca (apenas verificar que o bloco existe e esta correto).

- [ ] **Step 4: Commit**

```bash
git add app/services/claude_client.py app/routers/slack.py
git commit -m "feat: tool_choice auto — elimina double-call no conversa_livre

detect_intent() agora usa tool_choice=auto em vez de any. Quando o
Claude responde diretamente (sem tool), o texto e usado sem uma segunda
chamada a chat(). Parsing robusto para responses mistos (text + tool_use).
max_tokens aumentado para 2048 no detect_intent."
```

---

### Task 3: Haiku para classificacao e parsing

**Files:**
- Modify: `app/config.py:19` (adicionar claude_model_fast)
- Modify: `app/services/claude_client.py:346-351` (ClaudeService.__init__)
- Modify: `app/services/claude_client.py` (classify_briefing_reply — model)
- Modify: `app/services/claude_client.py` (parse_routine_request — model + try/except)

- [ ] **Step 1: Adicionar `claude_model_fast` ao config**

Em `app/config.py`, adicionar a linha apos `claude_model`:

```python
    # Anthropic
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    claude_model_fast: str = "claude-haiku-4-5-20251001"
```

- [ ] **Step 2: Adicionar `self.fast_model` ao `__init__` do ClaudeService**

Em `app/services/claude_client.py`, no `__init__`:

```python
def __init__(self, settings: Settings):
    self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    self.model = settings.claude_model
    self.fast_model = settings.claude_model_fast
```

- [ ] **Step 3: Trocar modelo em `classify_briefing_reply()`**

Mudar `model=self.model` para `model=self.fast_model` na chamada `messages.create` dentro de `classify_briefing_reply`. Tambem remover `cache_control` (nunca ativava — prompt < 1024 tokens):

```python
    t0 = time.monotonic()
    resp = await self.client.messages.create(
        model=self.fast_model,
        max_tokens=20,
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": f"[{context}]\nRecrutador disse: {user_text}"}],
    )
    self._log_usage("classify_briefing_reply", resp, int((time.monotonic() - t0) * 1000))
```

- [ ] **Step 4: Trocar modelo em `parse_routine_request()` e adicionar try/except**

Mudar `model=self.model` para `model=self.fast_model` e remover `cache_control`. Envolver o `json_mod.loads` em try/except robusto:

```python
    t0 = time.monotonic()
    resp = await self.client.messages.create(
        model=self.fast_model,
        max_tokens=300,
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": text}],
    )
    self._log_usage("parse_routine_request", resp, int((time.monotonic() - t0) * 1000))

    import json as json_mod
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json_mod.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Haiku retornou JSON invalido em parse_routine_request: %s", raw[:200])
        return {"action": "list"}
```

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/services/claude_client.py
git commit -m "feat: Haiku para classify_briefing e parse_routine

Tarefas triviais (classificacao ternaria e parsing JSON) agora usam
claude-haiku-4-5 em vez de Sonnet. 3x mais barato. cache_control
removido de prompts < 1024 tokens (nunca ativava). try/except no
parse_routine para JSON malformado com fallback seguro."
```

---

### Task 4: Comprimir tool definitions (8 de 15)

**Files:**
- Modify: `app/services/claude_client.py:76-343` (ELI_TOOLS)

- [ ] **Step 1: Encurtar `listar_vagas`**

```python
    {
        "name": "listar_vagas",
        "description": "Lista as vagas abertas do recrutador no InHire.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
```

- [ ] **Step 2: Encurtar `criar_vaga`**

```python
    {
        "name": "criar_vaga",
        "description": "Inicia abertura de uma nova vaga a partir do briefing do recrutador.",
        "input_schema": {
            "type": "object",
            "properties": {
                "briefing": {
                    "type": "string",
                    "description": "Texto completo do recrutador descrevendo a vaga",
                },
            },
            "required": ["briefing"],
        },
    },
```

- [ ] **Step 3: Encurtar `mover_candidatos`**

```python
    {
        "name": "mover_candidatos",
        "description": "Avanca candidatos aprovados para a proxima etapa do pipeline.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga (UUID)."},
            },
            "required": [],
        },
    },
```

- [ ] **Step 4: Encurtar `reprovar_candidatos`**

```python
    {
        "name": "reprovar_candidatos",
        "description": "Reprova candidatos em lote com envio de devolutiva profissional.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga (UUID)."},
            },
            "required": [],
        },
    },
```

- [ ] **Step 5: Encurtar `agendar_entrevista`**

```python
    {
        "name": "agendar_entrevista",
        "description": "Agenda uma entrevista com candidato.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga (UUID)."},
            },
            "required": [],
        },
    },
```

- [ ] **Step 6: Encurtar `carta_oferta`**

```python
    {
        "name": "carta_oferta",
        "description": "Cria e envia carta oferta para um candidato aprovado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "ID da vaga (UUID)."},
            },
            "required": [],
        },
    },
```

- [ ] **Step 7: Encurtar `ver_memorias`**

```python
    {
        "name": "ver_memorias",
        "description": (
            "Mostra o que o Eli sabe/lembra sobre o recrutador: padroes de decisao, "
            "vagas acompanhadas, configuracoes personalizadas."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
```

- [ ] **Step 8: Encurtar `conversa_livre`**

```python
    {
        "name": "conversa_livre",
        "description": "Fallback para perguntas gerais sobre recrutamento ou qualquer assunto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pergunta": {
                    "type": "string",
                    "description": "A pergunta ou mensagem do recrutador",
                },
            },
            "required": ["pergunta"],
        },
    },
```

- [ ] **Step 9: Verificar que as 7 tools criticas NAO foram alteradas**

Confirmar que estas tools mantiveram as descriptions originais intactas:
- `ver_candidatos` — deve conter "foco nas PESSOAS", "scores de fit"
- `gerar_shortlist` — deve conter "ranking comparativo"
- `status_vaga` — deve conter "SLA", "pipeline", "foco na VAGA"
- `buscar_talentos` — deve conter "banco de talentos", "busca full-text"
- `analisar_perfil` — deve conter "colar um texto de perfil"
- `guia_inhire` — deve conter topicos de exemplo
- `gerenciar_rotina` — deve conter triggers em linguagem natural

- [ ] **Step 10: Commit**

```bash
git add app/services/claude_client.py
git commit -m "feat: comprimir tool definitions — 8 de 15 encurtadas

Descricoes redundantes removidas de tools com nomes auto-explicativos.
7 tools com distincao sutil mantidas intactas (ver_candidatos,
gerar_shortlist, status_vaga, buscar_talentos, analisar_perfil,
guia_inhire, gerenciar_rotina). Economia ~600-900 tokens/chamada."
```

---

### Task 5: max_tokens dedicados por tarefa (nice-to-have)

**Files:**
- Modify: `app/services/claude_client.py` (chat — parametro max_tokens)
- Modify: `app/services/claude_client.py` (extract_job_data, generate_job_description, summarize_candidates, generate_rejection_message, summarize_conversation — passar max_tokens)
- Modify: `app/services/proactive_monitor.py:749` (weekly consolidation — max_tokens)
- Modify: `app/routers/slack.py:398-401` (CV extraction inline — max_tokens)
- Modify: `app/routers/slack.py:494-499` (CV fit analysis inline — max_tokens)

- [ ] **Step 1: Adicionar parametro `max_tokens` ao `chat()`**

Mudar a assinatura de `chat()`:

```python
async def chat(self, messages: list[dict], system: str | None = None,
               dynamic_context: str | None = None, max_tokens: int = 4096) -> str:
    t0 = time.monotonic()
    resp = await self.client.messages.create(
        model=self.model,
        max_tokens=max_tokens,
        system=self._build_system(system or SYSTEM_PROMPT_STATIC, dynamic_context),
        messages=messages,
    )
    self._log_usage("chat", resp, int((time.monotonic() - t0) * 1000))
    return resp.content[0].text
```

- [ ] **Step 2: Aplicar max_tokens nos metodos internos do ClaudeService**

`extract_job_data` — na chamada `self.chat(...)` ao final do metodo:
```python
        raw = await self.chat(
            messages=[{"role": "user", "content": briefing}],
            system=system,
            max_tokens=1024,
        )
```

`generate_job_description` — na chamada `self.chat(...)`:
```python
        return await self.chat(
            messages=[...],
            system=system,
            max_tokens=2048,
        )
```

`summarize_candidates` — na chamada `self.chat(...)`:
```python
        return await self.chat(
            messages=[...],
            system=system,
            max_tokens=2048,
        )
```

`generate_rejection_message` — na chamada `self.chat(...)`:
```python
        return await self.chat(
            messages=[...],
            system=system,
            max_tokens=512,
        )
```

`summarize_conversation` — na chamada `self.chat(...)`:
```python
        return await self.chat(
            messages=[{"role": "user", "content": f"Resuma esta conversa:\n\n{formatted}"}],
            system=system,
            max_tokens=512,
        )
```

- [ ] **Step 3: Aplicar max_tokens na weekly consolidation**

Em `app/services/proactive_monitor.py`, na chamada `self.claude.chat(...)` dentro de `_consolidate_user_patterns` (~linha 749):

```python
        insight = await self.claude.chat(
            messages=[{
                "role": "user",
                "content": (
                    f"Histórico de decisões de {recruiter_name} "
                    f"({total} decisões):\n\n{decisions_text}"
                ),
            }],
            system=system,
            max_tokens=256,
        )
```

- [ ] **Step 4: Aplicar max_tokens nas chamadas inline do slack.py (CV)**

Em `app/routers/slack.py`, CV extraction (~linha 398):
```python
            raw = await claude.chat(
                messages=[{"role": "user", "content": f"Extraia os dados deste currículo:\n\n{cv_text[:4000]}"}],
                system=extract_system,
                max_tokens=512,
            )
```

CV fit analysis (~linha 494):
```python
            fit_analysis = await claude.chat(
                messages=[{
                    "role": "user",
                    "content": f"Vaga: {job_name}\nRequisitos: {json_module.dumps(job_data.get('requirements', []), ensure_ascii=False)}\n\nCandidato:\n{json_module.dumps(candidate_data, ensure_ascii=False)}",
                }],
                system="Analise o fit deste candidato com a vaga. Retorne:\n*Fit:* 🟢 Alto / 🟡 Médio / 🔴 Baixo\n*Justificativa:* 1-2 linhas\nUse formatação Slack.",
                max_tokens=512,
            )
```

- [ ] **Step 5: Commit**

```bash
git add app/services/claude_client.py app/services/proactive_monitor.py app/routers/slack.py
git commit -m "feat: max_tokens dedicados por tarefa

chat() agora aceita max_tokens opcional (default 4096, zero impacto em
chamadores existentes). Metodos internos usam valores adequados:
extraction=1024, JD/shortlist=2048, rejection/summarize=512,
consolidation=256. Previne output runaway."
```

---

### Task 6: Deploy e validacao

**Files:**
- Nenhuma mudanca de codigo — comandos de deploy e verificacao

- [ ] **Step 1: Verificar que o servidor ainda inicia localmente**

```bash
cd app && python -c "from services.claude_client import ClaudeService; from config import Settings; print('Import OK')"
```

Expected: `Import OK` sem erros de import.

- [ ] **Step 2: Verificar que config carrega o novo campo**

```bash
cd app && python -c "from config import get_settings; s = get_settings(); print(f'model={s.claude_model}, fast={s.claude_model_fast}')"
```

Expected: `model=claude-sonnet-4-20250514, fast=claude-haiku-4-5-20251001`

- [ ] **Step 3: Deploy no servidor**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "cd /var/www/agente-inhire && git pull && systemctl restart agente-inhire"
```

- [ ] **Step 4: Verificar logs de usage apos primeira interacao**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "journalctl -u agente-inhire --since '5 min ago' | grep 'claude.usage'"
```

Expected: linhas JSON com `method`, `model`, `input_tokens`, `output_tokens`, `estimated_cost_usd`.

- [ ] **Step 5: Testar conversa_livre — confirmar que nao faz double-call**

Enviar no Slack: "oi, tudo bem?" e verificar nos logs:
- Deve haver 1 chamada `detect_intent` (nao 2 como antes)
- Se `tool` for `null` no result, o texto direto foi usado
- Se `tool` for `conversa_livre`, verificar se `text` do result foi usado (sem segunda chamada `chat`)

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97 "journalctl -u agente-inhire --since '2 min ago' | grep 'claude.usage' | jq -r '.method'"
```

Expected: uma unica linha `detect_intent` (nao seguida de `chat`).

- [ ] **Step 6: Testar routing — confirmar que tools continuam funcionando**

Enviar no Slack: "me mostra minhas vagas" e verificar:
- Log deve mostrar `detect_intent` com tool chamada (`listar_vagas`)
- Resposta deve listar as vagas normalmente

- [ ] **Step 7: Testar Haiku — confirmar classify_briefing**

Iniciar criacao de vaga, depois responder "pode criar assim mesmo". Verificar:
- Log de `classify_briefing_reply` deve mostrar `model: claude-haiku-4-5-20251001`
- Resposta deve ser `proceed` (fluxo continua normalmente)

- [ ] **Step 8: Commit tag de release**

```bash
git tag -a v2.1.0-cost-optimization -m "Otimizacao de custo da API Claude — Fases 1+2"
```
