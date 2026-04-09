# Rotinas Dinamicas do Eli — Design Spec

## Problema

O Eli tem 3 rotinas fixas hardcoded (briefing diario, monitor 1h, consolidacao semanal). Recrutadores nao conseguem pedir rotinas personalizadas como "todo dia as 8h me manda os candidatos novos da vaga X".

## Solucao

Permitir que recrutadores criem rotinas personalizadas via linguagem natural no Slack. O Claude interpreta o pedido, extrai tipo + horario, e o sistema agenda automaticamente.

## Escopo

Somente leitura — rotinas nunca modificam dados (mover, reprovar, criar). Respeitam horario comercial e config por recrutador.

---

## Arquitetura

### Componentes

```
Recrutador msg
  -> detect_intent() -> tool "gerenciar_rotina"
  -> _handle_routine() no slack.py
  -> claude.parse_routine_request() extrai acao + schedule + tipo
  -> RoutineService.create/list/cancel()
  -> Redis persist + APScheduler add/remove job
  -> Resposta no Slack
```

### Novo servico: `services/routines.py`

Classe `RoutineService` com dependencias:
- `redis` (persistencia)
- `scheduler` (APScheduler, recebido no init)
- `slack` (envio de mensagens)
- `inhire` (consultas API)
- `claude` (formatacao de resumos)

Metodos:
- `create(user_id, channel_id, routine_data) -> Routine` — valida, salva Redis, registra job
- `list(user_id) -> list[Routine]` — lista rotinas ativas do recrutador
- `cancel(user_id, routine_id) -> bool` — remove Redis + scheduler
- `load_all()` — chamado no startup, carrega todas rotinas do Redis e registra no scheduler
- `execute(routine)` — chamado pelo scheduler, roda a action e envia resultado via Slack

### Modelo de dados (Routine)

```python
@dataclass
class Routine:
    id: str              # UUID
    user_id: str         # Slack user ID
    channel_id: str      # Slack DM channel
    routine_type: str    # novos_candidatos | status_vagas | shortlist_update | resumo_semanal
    description: str     # Descricao original do recrutador
    job_id: str | None   # UUID da vaga (se aplicavel)
    job_name: str | None # Nome da vaga (pra exibicao)
    hour: int            # Hora UTC
    minute: int          # Minuto
    days: str            # "mon-fri" | "mon,wed,fri" | "fri" | "*" (todo dia)
    created_at: str      # ISO datetime
```

### Persistencia Redis

- Chave: `eli:routines:{user_id}` -> JSON com lista de rotinas
- Sem TTL (persiste ate ser cancelada)
- Indice global: `eli:routines:all_users` -> SET de user_ids que tem rotinas (pra load_all no startup)

### Tipos de rotina suportados

| Tipo | O que faz | Precisa de vaga? |
|------|-----------|-----------------|
| `novos_candidatos` | Lista candidatos que entraram desde ultima execucao | Sim |
| `status_vagas` | Resumo de todas as vagas ativas (pipeline, SLA) | Nao |
| `shortlist_update` | Atualizacao do shortlist/ranking | Sim |
| `resumo_semanal` | Consolidado da semana (novas candidaturas, movimentacoes) | Nao |

### Execucao

Cada rotina vira um job no APScheduler com CronTrigger:
- Job ID: `routine:{routine.id}`
- Trigger: `CronTrigger(hour=routine.hour, minute=routine.minute, day_of_week=routine.days)`
- Funcao: `routine_service.execute(routine)`

A execucao:
1. Verifica horario comercial do recrutador (respeita config)
2. Roda a query correspondente ao tipo
3. Formata resultado em mensagem Slack
4. Envia via `slack.send_message(channel_id, msg)`
5. Registra timestamp da ultima execucao em `routine.last_run`

### Nova tool no ELI_TOOLS

```python
{
    "name": "gerenciar_rotina",
    "description": (
        "Cria, lista ou cancela rotinas automaticas do recrutador. "
        "Use quando o recrutador pedir algo recorrente "
        "(todo dia, toda semana, me avisa quando, etc.) "
        "ou quiser ver/cancelar suas rotinas ativas."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "O pedido completo do recrutador sobre rotinas",
            },
        },
        "required": ["request"],
    },
}
```

### Novo metodo no claude_client

`parse_routine_request(text, available_jobs)` — retorna JSON:

```json
{
    "action": "create",
    "routine_type": "novos_candidatos",
    "job_id": "uuid-da-vaga",
    "job_name": "Backend Pleno",
    "hour_brt": 8,
    "minute": 0,
    "frequency": "weekdays",
    "description": "candidatos novos da vaga de Backend"
}
```

O prompt inclui a lista de vagas ativas pra que o Claude resolva "vaga de Backend" -> UUID correto.

### Handler no slack.py

Nova funcao `_handle_routine(conv, app, channel_id, tool_input)`:
- Chama `claude.parse_routine_request()`
- Despacha pra `routine_service.create/list/cancel` conforme `action`
- Formata resposta amigavel

---

## Limites e validacoes

- Maximo 5 rotinas ativas por recrutador
- Intervalo minimo: diario (sem "a cada 30 min")
- Horario: somente horario comercial (8h-19h BRT, seg-sex por padrao)
- Tipos: apenas os 4 listados (somente leitura)
- Se a vaga for fechada/cancelada, a rotina e automaticamente desativada na proxima execucao

---

## Integracao no startup (main.py)

```python
app.state.routines = RoutineService(
    redis=conversations._redis,
    scheduler=scheduler,
    slack=app.state.slack,
    inhire=app.state.inhire,
    claude=app.state.claude,
)
await app.state.routines.load_all()
```

Chamado DEPOIS de `scheduler.start()` pra que os jobs sejam registrados no scheduler ja ativo.

---

## Arquivos a criar/modificar

| Arquivo | Acao |
|---------|------|
| `services/routines.py` | **NOVO** — RoutineService + Routine dataclass |
| `services/claude_client.py` | Adicionar `parse_routine_request()` + tool `gerenciar_rotina` no ELI_TOOLS |
| `routers/slack.py` | Adicionar handler `_handle_routine()` + dispatch no `_handle_idle` |
| `main.py` | Inicializar RoutineService + `load_all()` no lifespan |

---

## Exemplos de uso

**Criar:**
> "Todo dia as 8h me manda os candidatos novos da vaga de Backend"
> -> Rotina `novos_candidatos`, 8h BRT seg-sex, vaga Backend Pleno

**Listar:**
> "Quais rotinas eu tenho?"
> -> Lista formatada com numero, descricao, horario, status

**Cancelar:**
> "Cancela a rotina 1" / "Para de me mandar o resumo semanal"
> -> Remove rotina + confirma

**Erro:**
> "Me manda candidatos toda hora"
> -> "O minimo e uma vez por dia. Quer que eu crie uma rotina diaria?"
