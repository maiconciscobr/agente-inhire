# Hunting LinkedIn + Smart Match — Design Spec

> Data: 2026-04-14 | Status: Aprovado | Sessao: 42

---

## Resumo

Duas features complementares para o Eli:

1. **Smart Match** — busca inteligente no banco de talentos do InHire usando IA nativa da plataforma
2. **Processar LinkedIn** — recrutador cola URLs do LinkedIn, Eli adiciona ao InHire que automaticamente extrai dados do perfil via BrightData

Ambas usam endpoints que **ja existem** no InHire. Zero dependencia externa nova.

---

## Contexto e decisoes

### Por que nao usar scraping externo (Apify, Proxycurl, etc.)

- Proxycurl fechou em julho 2025
- Actors do Apify para LinkedIn sao frageis (devs independentes, DOM muda)
- Dados publicos (sem cookie) sao rasos (~40-50% dos perfis tem experiencias escondidas)
- O InHire ja tem integracao BrightData + busca IA + scoring nativo

### Decisao: usar endpoints nativos do InHire

Menos codigo, mais robusto, sem custo extra, dados mais ricos.

### O que ja existe no codigo (sessao 41)

Metodos ja implementados no `inhire_client.py` que esta feature reutiliza:

| Metodo | O que faz |
|---|---|
| `analyze_resume(job_talent_id)` | Triagem de CV contra a vaga (score 0-4) |
| `manual_screening(job_talent_id)` | Screening sob demanda pra hunting |
| `get_resume_analysis(job_talent_id)` | Score detalhado por criterio + evidencia |
| `get_screening_analysis(job_talent_id)` | Analise completa de screening |
| `add_tags_batch(ids, tags)` | Tags em lote (ex: "hunting-linkedin") |
| `get_talent_by_linkedin(username)` | Dedup por LinkedIn username |
| `get_talent_by_email(email)` | Dedup por email |
| `add_talent_to_job(job_id, data, source)` | Adicionar talento a vaga |
| `list_job_talents(job_id)` | Listar candidatos da vaga |

---

## Feature 1: Smart Match (tool `smart_match`)

### Fluxo do usuario

```
Recrutador: "acha gente boa pra essa vaga"
              |
              v
    Claude detecta intent -> tool: smart_match
              |
              v
    Eli monta query combinando:
    - Requisitos da vaga ativa (job_data)
    - Criterios extras do recrutador (mensagem)
    - Fatos aprendidos do recrutador (memoria hierarquica)
              |
              v
    Eli chama POST /search-talents/ai/generate-job-talent-filter
    body: { jobId, query }
    -> InHire (GPT-4o-mini) retorna filtros Typesense otimizados
              |
              v
    Eli executa busca no Typesense (indice GLOBAL de talentos, 86k+)
    com os filtros retornados -> candidatos do banco geral
              |
              v
    Para candidatos encontrados:
    1. Dedup: ja vinculado a vaga? -> pula
    2. Adiciona a vaga via add_talent_to_job()
    3. Tagueia como "smart-match" via add_tags_batch()
    4. Dispara screening: manual_screening() ou analyze_resume()
              |
              v
    Rankeia por score, mostra top 10-15 no Slack
```

**Fallback:** Se o endpoint de busca IA nao funcionar no indice global, Eli gera 3-5 queries com Claude e busca via talent_search.search() (Typesense direto).

### Endpoints utilizados

#### Busca IA — `genFilterTypesenseJobTalent`

```
POST /search-talents/ai/generate-job-talent-filter
Auth: JWT

Request:  { "jobId": "string", "query": "string" }
Response: { "filter": "string", "sort": "string", "query": "string", "facetsValuesDoesNotExist": [] }
```

#### Screening — ja implementados no client

```
POST /job-talents/resume/analyze/{jobTalentId}      -> analyze_resume()
POST /job-talents/{jobTalentId}/screening/manual     -> manual_screening()
GET  /job-talents/{jobTalentId}/resume-analysis      -> get_resume_analysis()
GET  /job-talents/{jobTalentId}/screening-analysis   -> get_screening_analysis()
```

### Tool definition

```python
{
    "name": "smart_match",
    "description": (
        "Busca inteligente no banco de talentos. Cruza requisitos da vaga "
        "com CVs usando IA do InHire. Encontra candidatos compativeis "
        "automaticamente. Use quando o recrutador pedir para achar, "
        "encontrar ou buscar candidatos para a vaga no banco de talentos."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Criterios de busca em linguagem natural (opcional, usa requisitos da vaga se vazio)"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximo de candidatos para retornar (default 15)"
            }
        },
        "required": []
    }
}
```

### Handler: `_smart_match()`

```
async def _smart_match(conv, app, channel_id, tool_input):
    1. Validar vaga ativa (current_job_id). Se nao tem, pedir pra selecionar.
    2. Montar query combinando:
       - Requisitos da vaga (job_data)
       - Query extra do recrutador (tool_input.query)
       - Fatos do recrutador (conv_manager.get_facts) se disponiveis
       - Se tudo vazio, usar job_name como query
    3. Chamar inhire.gen_filter_job_talents(job_id, query)
       - Se falhar: fallback com Claude gerando 3-5 queries + talent_search.search()
    4. Executar busca Typesense com filtros retornados (max_results default 15)
    5. Carregar lista de candidatos ja vinculados (list_job_talents, cached)
    6. Para cada candidato encontrado e nao vinculado:
       a. inhire.add_talent_to_job(job_id, talent_id, source="smart-match")
       b. Coletar job_talent_ids novos
    7. Se houver novos:
       a. inhire.add_tags_batch(job_talent_ids, ["smart-match"])
       b. Para cada: inhire.manual_screening(jt_id) ou inhire.analyze_resume(jt_id)
    8. Buscar scores: inhire.get_resume_analysis(jt_id) ou get_screening_analysis(jt_id)
    9. Montar mensagem Slack com ranking por score
    10. Enviar no Slack
```

### Mensagem Slack

```
🎯 *Smart Match — Dev Python SR*

Encontrei *12 candidatos* com fit no banco de talentos.

🏆 *1. Joao Silva* — Score 3.8/4.0
   Python 8a, FastAPI, AWS | 📍 Sao Paulo
   _"Experiencia solida com stack requerida, lideranca tecnica"_

🥈 *2. Maria Santos* — Score 3.5/4.0
   Python 6a, Django, GCP | 📍 Campinas
   _"Boa aderencia tecnica, sem experiencia com AWS"_

...

✅ 8 ja estavam vinculados a vaga.
🔗 4 novos vinculados agora (tag: smart-match).

Quer que eu gere uma abordagem pra algum deles?
```

---

## Feature 2: Processar LinkedIn (tool `processar_linkedin`)

### Fluxo do usuario

```
Recrutador cola no Slack:
"olha esses perfis:
 linkedin.com/in/joaosilva
 linkedin.com/in/mariasantos
 linkedin.com/in/pedrocosta"
              |
              v
    Claude detecta intent -> tool: processar_linkedin
              |
              v
    Eli extrai URLs/usernames da mensagem
              |
              v
    Para cada username (asyncio.gather, max 5 concurrent):
    1. Dedup: inhire.get_talent_by_linkedin(username)
       - Se ja existe: usa talentId existente
       - Se nao existe: cria talento via inhire.add_talent()
    2. inhire.add_talent_to_job(job_id, talent_id, source="linkedin-hunting")
       -> EventBridge dispara generateResumeFromLinkedin automaticamente
       -> BrightData extrai perfil -> gera curriculo estruturado
    3. Tagueia: inhire.add_tags_batch([jt_id], ["hunting-linkedin"])
              |
              v
    Aguardar ~10s para processamento BrightData
              |
              v
    Para cada talento:
    - inhire.analyze_resume(jt_id) ou manual_screening(jt_id)
    - inhire.get_resume_analysis(jt_id) para score detalhado
              |
              v
    Mostra resumo no Slack com scores
```

### Mecanismo automatico (EventBridge)

Quando `addTalentToJob` e chamado com um talento que tem `linkedinUsername`:

```
Evento: JOB_TALENT_ADDED
Payload: { jobId, linkedinUsername, talentId, tenantId }
Consumer: generateResumeFromLinkedin()
  -> BrightData extrai dados do perfil LinkedIn
  -> Gera structuredResume (skills, experiences, languages, education)
  -> Salva PDF do curriculo como arquivo anexo
  -> Atualiza JobTalent com dados enriquecidos
```

**Nao precisa chamar endpoint extra.** So adicionar o talento a vaga com o linkedinUsername preenchido.

### Endpoint a investigar: Smart CV

```
GET  /talents/smartcv
POST /talents/smartcv
```

Descoberto na varredura do codigo-fonte (sessao 41). Pode ser alternativa ou complemento ao processamento via EventBridge. Investigar durante implementacao.

### Tool definition

```python
{
    "name": "processar_linkedin",
    "description": (
        "Processa perfis do LinkedIn colados pelo recrutador. "
        "Extrai dados, cria talento no InHire, vincula a vaga e avalia fit. "
        "Use quando o recrutador colar URLs do LinkedIn ou mencionar perfis "
        "para adicionar/processar/avaliar."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": { "type": "string" },
                "description": "URLs ou usernames do LinkedIn"
            }
        },
        "required": ["urls"]
    }
}
```

### Handler: `_process_linkedin_profiles()`

```
async def _process_linkedin_profiles(conv, app, channel_id, tool_input):
    1. Validar vaga ativa. Se nao tem, pedir pra selecionar.
    2. Extrair usernames das URLs:
       - "linkedin.com/in/joaosilva" -> "joaosilva"
       - "joaosilva" (ja e username) -> "joaosilva"
       - Limpar trailing slashes, query params
    3. Validar: max 10 URLs por mensagem
    4. Enviar mensagem: "Processando N perfis... ⏳"
    5. Para cada username (asyncio.gather, max 5 concurrent):
       a. Dedup: talent = await inhire.get_talent_by_linkedin(username)
       b. Se nao existe:
          - Criar: inhire.add_talent({ linkedinUsername: username, name: username })
          - Guardar talentId
       c. Se existe: usar talentId existente
       d. Checar se ja vinculado a vaga (list_job_talents cache)
       e. Se nao: inhire.add_talent_to_job(job_id, talent_id, source="linkedin-hunting")
       f. Registrar: { username, talentId, status: "novo"|"existente"|"ja_vinculado" }
    6. Taguear todos novos: inhire.add_tags_batch(jt_ids, ["hunting-linkedin"])
    7. Aguardar ~10s para processamento BrightData
    8. Para cada novo/recem-vinculado:
       - inhire.analyze_resume(jt_id) ou manual_screening(jt_id)
       - inhire.get_resume_analysis(jt_id) para score
    9. Montar mensagem Slack com resultados
    10. Enviar no Slack
```

### Mensagem Slack

```
🔗 *Perfis LinkedIn processados — Dev Python SR*

✅ *joaosilva* — adicionado, perfil extraido
   Score: 3.6/4.0 | Python, FastAPI, AWS
   _"Experiencia solida, match com requisitos tecnicos"_

✅ *mariasantos* — adicionado, perfil extraido
   Score: 3.2/4.0 | Python, Django, GCP
   _"Boa aderencia, falta experiencia cloud AWS"_

⚠️ *pedrocosta* — ja estava no banco (vinculei a vaga)
   Score: 2.8/4.0 | Python, Flask

3 perfis processados. Curriculos extraidos automaticamente.
Quer que eu analise algum em detalhe?
```

---

## Novos metodos no `inhire_client.py`

Apenas 2 metodos novos (os demais ja existem):

```python
# 1. Busca IA — gera filtros Typesense via linguagem natural
async def gen_filter_job_talents(self, job_id: str, query: str) -> dict:
    return await self._request(
        "POST", "/search-talents/ai/generate-job-talent-filter",
        json={"jobId": job_id, "query": query}
    )

# 2. Criar talento basico (pra LinkedIn sem dados ainda)
async def create_talent(self, data: dict) -> dict:
    return await self._request("POST", "/talents", json=data)
```

Metodos ja existentes reutilizados: `analyze_resume`, `manual_screening`, `get_resume_analysis`, `get_screening_analysis`, `add_tags_batch`, `get_talent_by_linkedin`, `get_talent_by_email`, `add_talent_to_job`, `list_job_talents`.

---

## Edge cases e protecoes

### Deduplicacao

| Checagem | Metodo existente | Se ja existe |
|---|---|---|
| LinkedIn username | `get_talent_by_linkedin(username)` | Usa talentId existente |
| Email | `get_talent_by_email(email)` | Usa talentId existente |
| Ja vinculado a vaga | `list_job_talents(job_id)` cache | Pula (avisa como "ja vinculado") |

### Limites

| Protecao | Valor | Motivo |
|---|---|---|
| Max URLs por mensagem | 10 | Evitar processamento longo |
| Max resultados smart_match | 25 | Limitar custo resume analyzer |
| Timeout por perfil | 30s | Nao travar o Slack |
| Rate limit smart_match | 5/hora por recrutador | Redis counter |
| Vaga obrigatoria | Sim | Sem vaga -> pede pra selecionar |

### Quando da errado

| Cenario | Comportamento |
|---|---|
| Endpoint busca IA erro/indisponivel | Fallback: Claude gera queries + talent_search.search() |
| Endpoint busca IA so funciona no indice por vaga | Fallback: Claude gera 3-5 queries variadas, busca no Typesense global |
| Resume analyzer sem creditos | Avisa recrutador, mostra candidatos sem score |
| BrightData falha (perfil privado) | Marca como "perfil nao acessivel", segue com dados basicos |
| LinkedIn username invalido | Pula, avisa qual falhou |
| 0 resultados smart_match | "Nao achei no banco. Quer que eu gere uma busca LinkedIn?" (conecta com busca_linkedin) |

---

## Componentes modificados

```
app/
├── services/
│   ├── inhire_client.py     <- +2 metodos novos (gen_filter + create_talent)
│   └── claude_client.py     <- +2 tools em ELI_TOOLS (smart_match + processar_linkedin)
└── routers/handlers/
    └── hunting.py           <- +2 handlers (_smart_match + _process_linkedin_profiles)
    └── slack.py             <- +2 entradas no dict de handlers
```

**Nenhum componente novo. Nenhuma dependencia externa nova. Custo adicional: ~$0.**
