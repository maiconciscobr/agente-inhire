# Otimizacao de Custo da API Claude — Agente InHire

**Data:** 2026-04-13
**Status:** Aprovado para implementacao
**Modelo atual:** claude-sonnet-4-20250514 (todas as chamadas)
**Custo observado:** ~$5 em testes leves (1 usuario + demo do time)

---

## Contexto

O agente Eli usa Claude Sonnet 4 para TODAS as chamadas de IA — desde classificacao trivial de 1 palavra ate geracao de job descriptions. Com 1 usuario ativo, o cache de 5 min raramente acerta, e o padrao "detect_intent + acao" gera 2+ chamadas Claude por mensagem.

### Pricing de referencia (Sonnet 4 / Haiku 4.5)

| Tipo | Sonnet 4 | Haiku 4.5 | Fator |
|---|---|---|---|
| Input | $3.00/MTok | $1.00/MTok | 3x |
| Output | $15.00/MTok | $5.00/MTok | 3x |
| Cache write | $3.75/MTok | $1.25/MTok | 3x |
| Cache read | $0.30/MTok | $0.10/MTok | 3x |
| **Min tokens p/ cache** | **1.024** | **4.096** | Critico |

### Token counts do sistema

| Componente | Tokens estimados |
|---|---|
| SYSTEM_PROMPT_STATIC | ~850 |
| ELI_TOOLS (15 tools) | ~2.000-2.500 |
| Prefixo cacheavel (system + tools) | ~2.850 |
| Conversa media (10 msgs) | ~700 |
| Conversa cheia (50 msgs) | ~3.500 |

---

## Diagnostico: pontos de desperdicio identificados

### D1. Double-call no conversa_livre

`detect_intent()` usa `tool_choice: "any"` — forca tool call. Quando o intent e conversa livre, o sistema:
1. Chama `detect_intent()` (1024 max_tokens) — resposta descartada
2. Chama `chat(conv.messages)` (4096 max_tokens) — resposta usada

**Impacto:** ~30-50% das mensagens sao conversa livre. Cada uma paga 2 chamadas quando 1 bastaria.

### D2. Sonnet para tarefas triviais

- `classify_briefing_reply()`: retorna 1 palavra ("proceed"/"more_info"/"cancel")
- `parse_routine_request()`: retorna JSON simples com 9 campos

Ambas nao precisam de Sonnet. Haiku acerta >95% nessas tarefas.

### D3. Tool definitions verbosas

8 de 15 tools tem descricoes redundantes (o nome ja e auto-explicativo):
- `listar_vagas`, `criar_vaga`, `mover_candidatos`, `reprovar_candidatos`
- `agendar_entrevista`, `carta_oferta`, `ver_memorias`, `conversa_livre`

7 tools PRECISAM de descricoes detalhadas (distincao sutil):
- `ver_candidatos`, `gerar_shortlist`, `status_vaga` (trio ambiguo)
- `buscar_talentos`, `analisar_perfil`, `guia_inhire`, `gerenciar_rotina`

### D4. Sem instrumentacao de custo

Nenhuma chamada Claude loga `resp.usage`. Impossivel medir custo real ou validar otimizacoes.

---

## O que NAO fazer (validado por 3 analises independentes)

| Proposta | Por que nao |
|---|---|
| Haiku para `detect_intent` (routing) | 10-20% de erro em tools ambiguas em PT-BR. Economia de so 5-8%, nao compensa a degradacao de UX. |
| Remover `cache_control` | Recrutador manda msgs em burst (3-5 seguidas) — cache acerta nesses momentos. Pode piorar o custo. |
| Historico 50 -> 10 msgs | Perde contexto do briefing e decisoes. Muito agressivo. |

---

## Plano de implementacao

### Fase 1 — Instrumentacao (pre-requisito, ~3-5 dias uteis de coleta antes da Fase 2)

**Arquivo:** `app/services/claude_client.py`

Criar helper `_log_usage()` chamado apos TODA chamada `messages.create`. Campos:

```json
{
  "method": "detect_intent",
  "model": "claude-sonnet-4-20250514",
  "input_tokens": 3200,
  "output_tokens": 80,
  "cache_creation_input_tokens": 2850,
  "cache_read_input_tokens": 0,
  "stop_reason": "tool_use",
  "latency_ms": 1230,
  "estimated_cost_usd": 0.014
}
```

Campos obrigatorios:
- `resp.usage.input_tokens`, `output_tokens`
- `resp.usage.cache_creation_input_tokens`, `cache_read_input_tokens`
- `resp.model` (essencial quando tiver multi-modelo na Fase 2)
- `resp.stop_reason` (detecta truncamento por max_tokens)
- Latencia: `time.monotonic()` antes/depois da chamada

Formato: JSON em uma linha no logger, nivel INFO. Permite query com `jq` ou ingestao futura.

**Meta:** 3-5 dias uteis de coleta para estabelecer baseline antes da Fase 2. 1-2 semanas completas antes de avaliar Fase 3.

### Fase 2 — Quick wins seguros

#### 2.1 Eliminar double-call do conversa_livre

**Arquivo:** `app/services/claude_client.py` (detect_intent) + `app/routers/slack.py` (_handle_idle)

**Mudanca:**
- `detect_intent()`: trocar `tool_choice={"type": "any"}` por `tool_choice={"type": "auto"}`
- Aumentar `max_tokens` de 1024 para 2048 no `detect_intent` (para acomodar respostas de texto direto)
- **Reescrever o loop de parsing do response** em `detect_intent()` para lidar com responses mistos (text + tool_use). O response com `auto` pode conter ambos — o codigo atual descarta o texto silenciosamente:

```python
async def detect_intent(self, messages, dynamic_context=None):
    resp = await self.client.messages.create(
        model=self.model,
        max_tokens=2048,
        system=self._build_system(SYSTEM_PROMPT_STATIC, dynamic_context),
        tools=ELI_TOOLS,
        tool_choice={"type": "auto"},
        messages=messages,
    )
    # Logging (Fase 1)
    self._log_usage("detect_intent", resp, latency_ms)

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

- `_handle_idle()`: se `detect_intent` retornar texto (sem tool), usar esse texto como resposta final
- Bloco `conversa_livre` no `_handle_idle`: usar `result.get("text")` se disponivel em vez de chamar `chat()` novamente. Manter `chat()` como fallback so se `text` estiver vazio.

**Protocolo de teste:**
- Executar 50 mensagens de teste antes do deploy, registrando: mensagem enviada, tool esperada, tool chamada, resultado OK/NOK
- Incluir: "como ta?", "valeu", "beleza", "e ai?", "me mostra as vagas", "quero ver candidatos", "abre uma vaga", "shortlist da vaga X", etc.
- Criterio de rollback: se mais de 10% (5 de 50) forem respondidas como texto quando deveriam ter chamado uma tool, reverter para `"any"` (mudanca de 1 linha)
- O fallback `conversa_livre` continua existindo como tool — Claude pode chamar se quiser

**Economia estimada:** 15-25% do custo total + reducao de latencia perceptivel.

#### 2.2 Haiku para classificacao e parsing

**Arquivo:** `app/config.py` + `app/services/claude_client.py`

**Mudanca:**
- Adicionar `claude_model_fast: str = "claude-haiku-4-5-20251001"` ao Settings
- `classify_briefing_reply()`: usar `self.fast_model` em vez de `self.model`
- `parse_routine_request()`: usar `self.fast_model` em vez de `self.model`

**Nota:** O cache minimo do Haiku e 4.096 tokens. Os system prompts dessas funcoes tem ~300-500 tokens, entao o cache NAO vai ativar. Remover `cache_control` dessas chamadas (e inofensivo se mantido, mas gera confusao). Na verdade, esses prompts tambem estao abaixo do minimo de 1.024 do Sonnet — o cache NUNCA ativou nessas chamadas.

**Seguranca:** `parse_routine_request()` nao tem try/except para JSON malformado. Haiku pode retornar JSON invalido em ~5-8% dos casos. Adicionar try/except com fallback que retorna `{"action": "list"}` (acao segura).

**Economia estimada:** 1-3% (valor simbolico, mas valida o padrao multi-modelo).

#### 2.3 Comprimir tool definitions (8 de 15)

**Arquivo:** `app/services/claude_client.py` (ELI_TOOLS)

**Tools a encurtar:**
- `listar_vagas`: remover "Use quando o recrutador perguntar sobre suas vagas, quiser ver vagas ativas, ou pedir uma lista."
- `criar_vaga`: remover triggers redundantes
- `mover_candidatos`: remover "Use quando o recrutador quiser mover, avancar, ou aprovar candidatos para proxima fase."
- `reprovar_candidatos`: remover triggers redundantes
- `agendar_entrevista`: remover "Use quando o recrutador quiser agendar, marcar entrevista, ou scheduling."
- `carta_oferta`: remover triggers redundantes
- `ver_memorias`: remover lista de exemplos de trigger
- `conversa_livre`: manter so "Fallback para perguntas gerais."

**Tools a NAO tocar (distincao sutil):**
- `ver_candidatos` (vs gerar_shortlist vs status_vaga)
- `gerar_shortlist` (vs ver_candidatos)
- `status_vaga` (vs ver_candidatos)
- `buscar_talentos` (vs ver_candidatos — banco geral vs vaga especifica)
- `analisar_perfil` (vs ver_candidatos — texto colado vs dados existentes)
- `guia_inhire` (precisa dos exemplos de topico)
- `gerenciar_rotina` (precisa dos triggers de linguagem natural)

**Economia estimada:** 3-5% (~600-900 tokens por chamada a detect_intent).

#### 2.4 max_tokens dedicados por tarefa (nice-to-have)

**Arquivo:** `app/services/claude_client.py`

**Implementacao:** Adicionar `max_tokens: int = 4096` como parametro opcional ao `chat()`. Zero impacto nos chamadores existentes (default mantem comportamento atual). So mudar onde necessario:

```python
async def chat(self, messages, system=None, dynamic_context=None, max_tokens: int = 4096) -> str:
```

| Tarefa | max_tokens atual | max_tokens proposto |
|---|---|---|
| `extract_job_data` | 4096 | 1024 |
| `generate_job_description` | 4096 | 2048 |
| `summarize_candidates` | 4096 | 2048 |
| `generate_rejection_message` | 4096 | **512** |
| `summarize_conversation` | 4096 | **512** |
| CV extraction (inline) | 4096 | 512 |
| CV fit analysis (inline) | 4096 | 512 |
| Weekly consolidation | 4096 | 256 |
| Interview/offer parsing (interviews.py) | 4096 | 512 |
| Profile analysis (hunting.py) | 4096 | 1024 |
| LinkedIn search (hunting.py) | 4096 | 1024 |

**Nota:** `max_tokens` nao gera custo direto (so paga tokens gerados). Mas previne output runaway e sinaliza intencao. Prioridade baixa — implementar so se houver tempo.

### Fase 3 — Reducao de historico (apos dados da Fase 1)

**Condicao:** Implementar so apos ter 1-2 semanas de dados de logging mostrando quantos tokens de historico estao sendo enviados por chamada.

**Opcao conservadora:** Reduzir de 50 para 25 mensagens max.

**Opcao avancada (futura):** Smart truncation — manter ultimas 10 + mensagens marcadas como "importantes" (briefings, decisoes, aprovacoes).

---

## Metricas de sucesso

| Metrica | Como medir | Meta |
|---|---|---|
| Custo por interacao | Logging de tokens + pricing | Reducao de 20-35% |
| Latencia do conversa_livre | Timestamp antes/depois | Reducao de ~50% (1 chamada vs 2) |
| Taxa de routing correto | Log de tool chamada vs correcao do usuario | >= 95% (sem degradacao) |
| Custo mensal estimado (1 user) | Dashboard de tokens | < $7/mes (vs ~$10 atual) |

---

## Riscos e mitigacoes

| Risco | Probabilidade | Mitigacao |
|---|---|---|
| `tool_choice: auto` reduz taxa de tool calling | Media | Protocolo de 50 msgs de teste com registro formal. Rollback = 1 linha. |
| Response misto (text + tool_use) com `auto` | Media | Loop reescrito para capturar ambos. Tool tem prioridade, texto e preservado. |
| Haiku erra classify_briefing em PT-BR | Baixa (<5%) | Fallback heuristico ja existe (linhas 452-453 do claude_client.py). |
| Haiku retorna JSON malformado em parse_routine | Baixa (~5-8%) | Adicionar try/except com fallback seguro `{"action": "list"}`. |
| Descricoes curtas confundem routing | Baixa | So encurtar tools obvias. Manter as 7 ambiguas intactas. |
| max_tokens baixo trunca output | Baixa | Valores revisados com margem (256->512 em rejection e summarize). Monitorar `stop_reason` via Fase 1. |
