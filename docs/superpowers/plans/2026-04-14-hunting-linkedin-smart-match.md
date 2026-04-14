# Hunting LinkedIn + Smart Match — Plano de Implementacao

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar duas tools ao Eli — Smart Match (busca IA no banco de talentos) e Processar LinkedIn (cola URLs → extrai dados → vincula a vaga)

**Architecture:** Dois handlers novos em `hunting.py`, duas tools em `claude_client.py` ELI_TOOLS, dois metodos novos em `inhire_client.py`. Reutiliza 9 metodos existentes (analyze_resume, manual_screening, add_tags_batch, etc.)

**Tech Stack:** FastAPI, Python 3.12, httpx (async), Redis (rate limit), Typesense, InHire API

**Spec:** `docs/superpowers/specs/2026-04-14-hunting-linkedin-smart-match-design.md`

---

## File Map

| File | Acao | Responsabilidade |
|---|---|---|
| `app/services/inhire_client.py` | Modificar (~L490) | +2 metodos: `gen_filter_job_talents`, `create_talent` |
| `app/services/claude_client.py` | Modificar (~L385) | +2 tools em ELI_TOOLS: `smart_match`, `processar_linkedin` |
| `app/routers/handlers/hunting.py` | Modificar (append) | +2 handlers: `_smart_match`, `_process_linkedin_profiles` |
| `app/routers/slack.py` | Modificar (~L30, ~L908) | +2 imports, +2 entradas no elif chain |

---

### Task 1: Metodos novos no inhire_client.py

**Files:**
- Modify: `app/services/inhire_client.py:490` (apos secao Tags, antes de Job Publishing)

- [ ] **Step 1: Adicionar `gen_filter_job_talents` e `create_talent`**

Inserir apos a linha `# --- Tags ---` (apos `remove_tags_batch`, antes de `# --- Job Publishing ---`):

```python
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
```

- [ ] **Step 2: Verificar que nao quebrou imports**

Run: `cd /c/Users/maico/OneDrive/Desktop/GitHub/agente\ inhire && python -c "from services.inhire_client import InHireClient; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/inhire_client.py
git commit -m "feat: add gen_filter_job_talents and create_talent to inhire client"
```

---

### Task 2: Tools novas no claude_client.py (ELI_TOOLS)

**Files:**
- Modify: `app/services/claude_client.py` (inserir antes da tool `conversa_livre` que eh a ultima)

- [ ] **Step 1: Adicionar tool `smart_match`**

Inserir ANTES da tool `conversa_livre` (antes da linha `"name": "conversa_livre"`):

```python
    {
        "name": "smart_match",
        "description": (
            "Busca inteligente no banco de talentos. Cruza requisitos da vaga "
            "com CVs usando IA. Encontra candidatos compatíveis automaticamente. "
            "Use quando o recrutador pedir para achar, encontrar, buscar candidatos "
            "compatíveis para a vaga, match de talentos, ou sourcing no banco interno."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Critérios de busca em linguagem natural (opcional, usa requisitos da vaga se vazio)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Máximo de candidatos para retornar (default 15)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "processar_linkedin",
        "description": (
            "Processa perfis do LinkedIn colados pelo recrutador. "
            "Extrai dados, cria talento no InHire, vincula à vaga e avalia fit. "
            "Use quando o recrutador colar URLs do LinkedIn (linkedin.com/in/...) "
            "ou mencionar perfis do LinkedIn para adicionar, processar ou avaliar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs ou usernames do LinkedIn extraídos da mensagem",
                },
            },
            "required": ["urls"],
        },
    },
```

- [ ] **Step 2: Verificar que nao quebrou imports**

Run: `cd /c/Users/maico/OneDrive/Desktop/GitHub/agente\ inhire && python -c "from services.claude_client import ELI_TOOLS; print(f'{len(ELI_TOOLS)} tools'); names = [t['name'] for t in ELI_TOOLS]; assert 'smart_match' in names; assert 'processar_linkedin' in names; print('OK')"`
Expected: `N tools` e `OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/claude_client.py
git commit -m "feat: add smart_match and processar_linkedin tools to ELI_TOOLS"
```

---

### Task 3: Handler `_smart_match` no hunting.py

**Files:**
- Modify: `app/routers/handlers/hunting.py` (append ao final do arquivo)

- [ ] **Step 1: Adicionar imports necessarios no topo do hunting.py**

Adicionar ao topo (apos os imports existentes):

```python
import re
from urllib.parse import urlparse
```

- [ ] **Step 2: Adicionar handler `_smart_match`**

Append ao final do arquivo:

```python
async def _smart_match(conv, app, channel_id: str, tool_input: dict):
    """Smart match: find talents in InHire pool using AI-powered search + screening."""
    slack = app.state.slack
    inhire = app.state.inhire
    talent_search = app.state.talent_search

    job_id = conv.get_context("current_job_id")
    job_name = conv.get_context("current_job_name", "")
    job_data = conv.get_context("job_data", {})

    if not job_id:
        await _send(conv, slack, channel_id, "Preciso saber a vaga pra buscar. Me diz qual vaga ou crie uma primeiro.")
        return

    max_results = tool_input.get("max_results", 15)
    extra_query = tool_input.get("query", "")

    # Build search query from job data + recruiter input
    query_parts = []
    if job_name:
        query_parts.append(job_name)
    if job_data.get("requirements"):
        reqs = job_data["requirements"]
        if isinstance(reqs, list):
            query_parts.append(" ".join(reqs[:5]))
        elif isinstance(reqs, str):
            query_parts.append(reqs[:200])
    if extra_query:
        query_parts.append(extra_query)

    query = " ".join(query_parts).strip()
    if not query:
        query = job_name or "candidato"

    await _send(conv, slack, channel_id, f"Buscando talentos compatíveis com *{job_name}*... 🎯")

    # Rate limit: 5 searches per hour per user
    try:
        import redis as redis_lib
        from config import get_settings
        r = redis_lib.from_url(get_settings().redis_url, decode_responses=True)
        rate_key = f"inhire:smart_match_rate:{conv.user_id}"
        count = r.incr(rate_key)
        if count == 1:
            r.expire(rate_key, 3600)
        if count > 5:
            await _send(conv, slack, channel_id, "Muitas buscas seguidas — espera um pouco e tenta de novo. 🕐")
            return
    except Exception:
        pass  # Rate limit is best-effort

    # Try AI-powered search first, fallback to direct Typesense
    hits = []
    try:
        ai_filter = await inhire.gen_filter_job_talents(job_id, query)
        if ai_filter and ai_filter.get("query"):
            search_query = ai_filter["query"]
            results = await talent_search.search(search_query, max_results=max_results)
            hits = results.get("hits", [])
    except Exception as e:
        logger.warning("AI search failed, falling back to direct search: %s", e)

    # Fallback: direct Typesense search
    if not hits:
        try:
            results = await talent_search.search(query, max_results=max_results)
            hits = results.get("hits", [])
        except Exception as e:
            logger.exception("Talent search failed: %s", e)
            await _send(conv, slack, channel_id, "Ops, deu ruim na busca. Tenta de novo daqui a pouco? 🤔")
            return

    if not hits:
        await _send(
            conv, slack, channel_id,
            f"Não achei ninguém compatível com *{job_name}* no banco de talentos. "
            "Quer que eu gere uma busca LinkedIn pra hunting externo?",
        )
        return

    # Load existing candidates to avoid duplicates
    existing_talents = await inhire.list_job_talents(job_id)
    existing_talent_ids = {c.get("talentId", "") for c in existing_talents}

    # Process each hit: add to job + tag + screen
    added = []
    already_linked = []
    failed = []

    for hit in hits:
        talent_id = hit.get("id", "")
        name = hit.get("name", "Sem nome")

        if not talent_id:
            continue

        if talent_id in existing_talent_ids:
            already_linked.append({"name": name, "talent_id": talent_id, **hit})
            continue

        try:
            resp = await inhire.add_existing_talent_to_job(job_id, talent_id, source="smart-match")
            jt_id = resp.get("id", f"{job_id}*{talent_id}")
            added.append({"name": name, "talent_id": talent_id, "jt_id": jt_id, **hit})
            existing_talent_ids.add(talent_id)
        except Exception as e:
            logger.warning("Failed to add talent %s to job: %s", talent_id, e)
            failed.append(name)

    # Tag new candidates
    new_jt_ids = [a["jt_id"] for a in added if a.get("jt_id")]
    if new_jt_ids:
        try:
            await inhire.add_tags_batch(new_jt_ids, ["smart-match"])
        except Exception as e:
            logger.warning("Failed to tag smart-match candidates: %s", e)

    # Trigger screening for new candidates
    scores = {}
    for a in added:
        jt_id = a.get("jt_id", "")
        if jt_id:
            try:
                result = await inhire.manual_screening(jt_id)
                if result:
                    score = result.get("score", result.get("screening", {}).get("score"))
                    if score is not None:
                        scores[jt_id] = score
            except Exception:
                pass
            if jt_id not in scores:
                try:
                    result = await inhire.analyze_resume(jt_id)
                    if result and result.get("analysis", {}).get("result"):
                        analysis = result["analysis"]["result"]
                        total_score = sum(r.get("score", 0) * r.get("weight", 1) for r in analysis)
                        total_weight = sum(r.get("weight", 1) for r in analysis)
                        if total_weight > 0:
                            scores[jt_id] = round(total_score / total_weight, 1)
                except Exception:
                    pass

    # Build ranked message
    all_results = []
    for a in added:
        all_results.append({**a, "score": scores.get(a.get("jt_id", ""), None), "status": "novo"})
    for a in already_linked:
        all_results.append({**a, "score": None, "status": "ja_vinculado"})

    # Sort: scored first (desc), then unscored
    all_results.sort(key=lambda x: (x["score"] is not None, x["score"] or 0), reverse=True)

    msg = f"🎯 *Smart Match — {job_name}*\n\n"
    msg += f"Busquei no banco de talentos. *{len(added)} novos* vinculados, *{len(already_linked)} já estavam*.\n\n"

    for i, r in enumerate(all_results[:15], 1):
        emoji = "🏆" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"*{i}.*"
        name = r.get("name", "Sem nome")
        headline = r.get("headline", "")
        location = r.get("location", "")
        linkedin = r.get("linkedin", "")
        score = r.get("score")
        status = r.get("status")

        score_str = f" — Score {score}/4.0" if score is not None else ""
        status_str = " _(já vinculado)_" if status == "ja_vinculado" else ""

        msg += f"{emoji} *{name}*{score_str}{status_str}\n"
        parts = []
        if headline:
            parts.append(headline[:80])
        if location:
            parts.append(f"📍 {location}")
        if linkedin:
            parts.append(f"🔗 linkedin.com/in/{linkedin}")
        if parts:
            msg += "   " + " | ".join(parts) + "\n"
        msg += "\n"

    if failed:
        msg += f"⚠️ {len(failed)} não consegui adicionar.\n"

    msg += "Quer que eu analise algum em detalhe ou gere uma abordagem?"
    await _send(conv, slack, channel_id, msg)
```

- [ ] **Step 3: Verificar sintaxe**

Run: `cd /c/Users/maico/OneDrive/Desktop/GitHub/agente\ inhire && python -c "from routers.handlers.hunting import _smart_match; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/routers/handlers/hunting.py
git commit -m "feat: add _smart_match handler for AI-powered talent search"
```

---

### Task 4: Handler `_process_linkedin_profiles` no hunting.py

**Files:**
- Modify: `app/routers/handlers/hunting.py` (append ao final do arquivo)

- [ ] **Step 1: Adicionar handler `_process_linkedin_profiles`**

Append ao final do arquivo:

```python
def _extract_linkedin_username(url_or_username: str) -> str | None:
    """Extract LinkedIn username from URL or raw username."""
    text = url_or_username.strip().strip("<>")
    # Full URL: linkedin.com/in/username or linkedin.com/in/username/
    match = re.search(r"linkedin\.com/in/([a-zA-Z0-9_-]+)", text)
    if match:
        return match.group(1).lower()
    # Already a username (no slashes, no dots except in names)
    if re.match(r"^[a-zA-Z0-9_-]+$", text) and len(text) >= 3:
        return text.lower()
    return None


async def _process_linkedin_profiles(conv, app, channel_id: str, tool_input: dict):
    """Process LinkedIn profile URLs: dedup, add to InHire, trigger BrightData extraction, screen."""
    slack = app.state.slack
    inhire = app.state.inhire

    job_id = conv.get_context("current_job_id")
    job_name = conv.get_context("current_job_name", "")

    if not job_id:
        await _send(conv, slack, channel_id, "Preciso saber a vaga pra vincular os perfis. Me diz qual vaga ou crie uma primeiro.")
        return

    raw_urls = tool_input.get("urls", [])
    if not raw_urls:
        await _send(conv, slack, channel_id, "Não encontrei URLs do LinkedIn na mensagem. Cola os links que eu processo.")
        return

    if len(raw_urls) > 10:
        await _send(conv, slack, channel_id, f"Muitos perfis de uma vez ({len(raw_urls)}). Máximo é 10 por mensagem. Manda em partes?")
        return

    # Extract usernames
    usernames = []
    invalid = []
    for raw in raw_urls:
        username = _extract_linkedin_username(raw)
        if username:
            usernames.append(username)
        else:
            invalid.append(raw)

    if not usernames:
        await _send(conv, slack, channel_id, "Não consegui extrair nenhum perfil LinkedIn dessas URLs. Confere e manda de novo?")
        return

    await _send(conv, slack, channel_id, f"Processando {len(usernames)} perfil(is) do LinkedIn... ⏳")

    # Load existing candidates to check duplicates
    existing_talents = await inhire.list_job_talents(job_id)
    existing_talent_ids = {c.get("talentId", "") for c in existing_talents}

    # Process each username concurrently (max 5)
    import asyncio

    semaphore = asyncio.Semaphore(5)
    results = []

    async def process_one(username: str) -> dict:
        async with semaphore:
            result = {"username": username, "status": "error", "name": username}
            try:
                # Dedup by LinkedIn username
                talent = await inhire.get_talent_by_linkedin(username)

                if talent:
                    talent_id = talent.get("id", "")
                    result["name"] = talent.get("name", username)
                    result["talent_id"] = talent_id

                    if talent_id in existing_talent_ids:
                        result["status"] = "ja_vinculado"
                        return result

                    # Existing talent, just link to job
                    resp = await inhire.add_existing_talent_to_job(job_id, talent_id, source="linkedin-hunting")
                    result["jt_id"] = resp.get("id", f"{job_id}*{talent_id}")
                    result["status"] = "existente_vinculado"
                else:
                    # Create new talent with LinkedIn username
                    new_talent = await inhire.create_talent({
                        "name": username,
                        "linkedinUsername": username,
                    })
                    talent_id = new_talent.get("id", "")
                    result["talent_id"] = talent_id

                    # Add to job — triggers EventBridge → BrightData extraction
                    resp = await inhire.add_existing_talent_to_job(job_id, talent_id, source="linkedin-hunting")
                    result["jt_id"] = resp.get("id", f"{job_id}*{talent_id}")
                    result["status"] = "novo"

            except Exception as e:
                logger.warning("Error processing LinkedIn %s: %s", username, e)
                result["status"] = "error"
                result["error"] = str(e)[:100]

            return result

    results = await asyncio.gather(*[process_one(u) for u in usernames])

    # Tag new/linked candidates
    new_jt_ids = [r["jt_id"] for r in results if r.get("jt_id") and r["status"] in ("novo", "existente_vinculado")]
    if new_jt_ids:
        try:
            await inhire.add_tags_batch(new_jt_ids, ["hunting-linkedin"])
        except Exception as e:
            logger.warning("Failed to tag hunting-linkedin candidates: %s", e)

    # Wait for BrightData to process new profiles
    new_profiles = [r for r in results if r["status"] == "novo"]
    if new_profiles:
        await asyncio.sleep(10)

    # Trigger screening and collect scores
    for r in results:
        jt_id = r.get("jt_id", "")
        if not jt_id or r["status"] == "ja_vinculado":
            continue
        try:
            screening = await inhire.manual_screening(jt_id)
            if screening:
                score = screening.get("score", screening.get("screening", {}).get("score"))
                if score is not None:
                    r["score"] = score
                    continue
        except Exception:
            pass
        try:
            analysis = await inhire.analyze_resume(jt_id)
            if analysis and analysis.get("analysis", {}).get("result"):
                items = analysis["analysis"]["result"]
                total = sum(i.get("score", 0) * i.get("weight", 1) for i in items)
                weight = sum(i.get("weight", 1) for i in items)
                if weight > 0:
                    r["score"] = round(total / weight, 1)
        except Exception:
            pass

    # Build response message
    msg = f"🔗 *Perfis LinkedIn processados — {job_name}*\n\n"

    for r in results:
        username = r["username"]
        name = r.get("name", username)
        status = r["status"]
        score = r.get("score")

        if status == "novo":
            score_str = f"Score: {score}/4.0 | " if score is not None else ""
            msg += f"✅ *{name}* (@{username}) — adicionado, perfil em extração\n"
            if score_str:
                msg += f"   {score_str}\n"
        elif status == "existente_vinculado":
            score_str = f"Score: {score}/4.0 | " if score is not None else ""
            msg += f"⚠️ *{name}* (@{username}) — já estava no banco, vinculei à vaga\n"
            if score_str:
                msg += f"   {score_str}\n"
        elif status == "ja_vinculado":
            msg += f"🔄 *{name}* (@{username}) — já vinculado à vaga\n"
        else:
            msg += f"❌ *{username}* — erro ao processar\n"
        msg += "\n"

    if invalid:
        msg += f"⚠️ {len(invalid)} URL(s) não reconhecida(s): {', '.join(invalid[:3])}\n\n"

    novos = len([r for r in results if r["status"] == "novo"])
    vinculados = len([r for r in results if r["status"] == "existente_vinculado"])
    if novos > 0:
        msg += f"Perfis novos ({novos}) serão enriquecidos automaticamente pelo InHire.\n"
    if novos + vinculados > 0:
        msg += "Quer que eu analise algum em detalhe?"

    await _send(conv, slack, channel_id, msg)
```

- [ ] **Step 2: Verificar sintaxe**

Run: `cd /c/Users/maico/OneDrive/Desktop/GitHub/agente\ inhire && python -c "from routers.handlers.hunting import _process_linkedin_profiles; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/routers/handlers/hunting.py
git commit -m "feat: add _process_linkedin_profiles handler for LinkedIn URL processing"
```

---

### Task 5: Registrar no slack.py

**Files:**
- Modify: `app/routers/slack.py:30` (import line)
- Modify: `app/routers/slack.py:~908` (elif chain, after comparar_vagas)

- [ ] **Step 1: Atualizar import do hunting.py**

Na linha 30, alterar:

```python
from routers.handlers.hunting import _analyze_profile, _compare_jobs, _generate_linkedin_search, _job_status_report, _search_talents
```

Para:

```python
from routers.handlers.hunting import _analyze_profile, _compare_jobs, _generate_linkedin_search, _job_status_report, _process_linkedin_profiles, _search_talents, _smart_match
```

- [ ] **Step 2: Adicionar entradas no elif chain**

Apos o bloco `elif tool == "comparar_vagas":` (por volta da linha 908), adicionar:

```python
    elif tool == "smart_match":
        await _smart_match(conv, app, channel_id, tool_input)

    elif tool == "processar_linkedin":
        await _process_linkedin_profiles(conv, app, channel_id, tool_input)
```

- [ ] **Step 3: Verificar sintaxe**

Run: `cd /c/Users/maico/OneDrive/Desktop/GitHub/agente\ inhire && python -c "from routers.slack import router; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/routers/slack.py
git commit -m "feat: register smart_match and processar_linkedin handlers in slack router"
```

---

### Task 6: Testar endpoint gen_filter_job_talents no tenant demo

**Files:** Nenhum (investigacao)

- [ ] **Step 1: Testar endpoint via script**

Criar script temporario e executar no servidor:

```python
import asyncio
from config import get_settings
from services.inhire_auth import InHireAuth
from services.inhire_client import InHireClient

async def test():
    settings = get_settings()
    auth = InHireAuth(settings.inhire_email, settings.inhire_password)
    client = InHireClient(auth)

    # List jobs to get a valid job_id
    jobs = await client._request("POST", "/jobs/paginated/lean", json={"limit": 1})
    job_id = jobs["results"][0]["id"]
    print(f"Testing with job: {jobs['results'][0]['name']} ({job_id})")

    # Test AI search
    result = await client.gen_filter_job_talents(job_id, "python senior são paulo")
    print(f"Result: {result}")

asyncio.run(test())
```

- [ ] **Step 2: Avaliar resultado**

Se retornou `None` (403/404): o fallback direto pro Typesense ja esta implementado no handler.
Se retornou filtros: o fluxo principal funciona.

Documentar resultado no commit.

- [ ] **Step 3: Commit resultado da investigacao**

```bash
git commit --allow-empty -m "chore: test gen_filter_job_talents endpoint — [RESULTADO]"
```

---

### Task 7: Teste end-to-end via Slack

**Files:** Nenhum (teste manual)

- [ ] **Step 1: Deploy no servidor**

```bash
ssh -i ~/.ssh/n8n_rescue_key root@65.109.160.97
cd /var/www/agente-inhire
git pull
systemctl restart agente-inhire
journalctl -u agente-inhire -f
```

- [ ] **Step 2: Testar Smart Match**

No Slack DM com Eli:
1. Selecionar uma vaga: "minhas vagas"
2. Pedir: "acha gente boa pra essa vaga no banco"
3. Verificar: retorna ranking com candidatos, tags aplicadas, scores quando disponíveis
4. Testar sem vaga: "acha candidatos" → deve pedir pra selecionar vaga
5. Testar rate limit: fazer 6 buscas em sequência → na 6a deve bloquear

- [ ] **Step 3: Testar Processar LinkedIn**

No Slack DM com Eli:
1. Com vaga ativa, colar: "olha esses perfis: linkedin.com/in/teste1 linkedin.com/in/teste2"
2. Verificar: processa, adiciona, mostra resultado
3. Testar com URL invalida: "processa linkedin.com/in/teste1 e xpto123"
4. Testar >10 URLs: deve avisar o limite
5. Testar sem vaga: deve pedir pra selecionar

- [ ] **Step 4: Commit final**

```bash
git add -A
git commit -m "docs: update CLAUDE.md and DIARIO with session 42 — smart match + processar linkedin"
```
