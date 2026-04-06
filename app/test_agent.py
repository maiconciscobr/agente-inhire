"""
Eli — Agente Inteligente de Testes v2
Usa Claude para avaliar semanticamente as respostas do Eli.
Cada cenário é independente (reseta antes de rodar).

Cobertura: onboarding, abertura de vaga (completa com aprovação), hunting, análise de perfil,
candidatos, mover (shortlist + aprovação), reprovar (completo), status/SLA, listagem,
conversa livre (2 temas), guia InHire (divulgação, triagem, scorecard, automações),
toggle comunicação, cancelar, lock/dedup, shortlist, agendar entrevista (completo: lista + agenda),
carta oferta (completo: lista + dados + aprovação), ver memórias (2 variações),
sem vaga (pede ID), msg ambígua, sequência rápida.

Uso: python test_agent.py
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.parse

import httpx

# ── Config ────────────────────────────────────────────────
SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "b46332f3d53c04af792a57819d377ed1")
BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "xoxb-6948566630705-10806440568629-odI7tXFAGO5Gi7P35ZtdXSS2")
USER_TOKEN = os.getenv("SLACK_USER_TOKEN", "xoxp-6948566630705-7714476166882-10822752736321-887f10bea6224184a7dad8ac20ad4c4f")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SERVER_URL = os.getenv("SERVER_URL", "https://agente.adianterecursos.com.br")
CLAUDE_MODEL = "claude-sonnet-4-20250514"

SIM_USER_ID = "U07M0E04WRY"
SIM_CHANNEL_ID = "D0APHBF5RHD"

HEADERS_BOT = {"Authorization": f"Bearer {BOT_TOKEN}", "Content-Type": "application/json"}
HEADERS_USER = {"Authorization": f"Bearer {USER_TOKEN}", "Content-Type": "application/json"}

# ── Scenarios ─────────────────────────────────────────────
SCENARIOS = [
    # ── Bloco 1: Onboarding + Abertura de vaga ──
    {
        "name": "Primeiro contato / Onboarding",
        "reset": True,
        "steps": [
            {
                "send": "Oi, tudo bem?",
                "expect": "Deve responder com saudação ou pedir email de onboarding. Qualquer resposta amigável é válida.",
                "on_onboarding": {
                    "send": "camila.teste@empresa.com",
                    "expect": "Deve confirmar o registro, cumprimentar pelo nome e listar o que sabe fazer.",
                },
            },
        ],
    },
    {
        "name": "Abertura de vaga completa",
        "reset": True,
        "steps": [
            {
                "send": (
                    "O Rafael me pediu pra abrir uma vaga de Desenvolvedor Backend Senior, "
                    "remoto, pra ontem. Stack Python, FastAPI, PostgreSQL e AWS. "
                    "Regime PJ, budget entre 15 e 22 mil. Precisa ter experiencia com "
                    "microsservicos e CI/CD. Diferencial: Kafka."
                ),
                "expect": "Deve entender que é abertura de vaga e iniciar coleta de briefing ou perguntar por mais info.",
            },
            {
                "send": "pronto",
                "expect": "Deve gerar um rascunho de job description mencionando Backend/Python ou pedir info faltante.",
                "on_missing_info": {
                    "send": "gerar",
                    "expect": "Deve gerar o rascunho mesmo com info faltante. Deve conter cargo e requisitos.",
                },
                "expect_buttons": True,
            },
            {
                "action": "approve",
                "callback": "job_draft_approval",
                "expect": "Deve criar a vaga no InHire e confirmar com ID, status e pipeline.",
            },
        ],
    },
    # ── Bloco 2: Hunting e análise ──
    {
        "name": "Busca LinkedIn",
        "reset": False,
        "steps": [
            {
                "send": "me gera uma busca pro linkedin pra essa vaga",
                "expect": "Deve gerar strings de busca booleanas com AND/OR para LinkedIn, mencionando termos técnicos da vaga.",
                "max_wait": 60,
            },
        ],
    },
    {
        "name": "Análise de perfil",
        "reset": False,
        "steps": [
            {
                "send": (
                    "O que acha desse perfil?\n\n"
                    "Lucas Mendes — Backend Developer Senior, 6 anos de experiência\n"
                    "Atualmente na Nubank como Software Engineer III\n"
                    "Stack: Python, Django, PostgreSQL, Redis, RabbitMQ, Docker, AWS\n"
                    "Formação: Eng. Computação — Unicamp\n"
                    "Local: Campinas, SP — Pretensão: 20k PJ"
                ),
                "expect": (
                    "Deve analisar o fit do candidato mencionando pontos fortes, pontos de atenção "
                    "e uma recomendação (avançar/não avançar). "
                    "É esperado que analise contra a vaga criada no cenário anterior (Backend/Python) "
                    "já que o contexto da conversa preserva a vaga ativa."
                ),
                "max_wait": 60,
            },
        ],
    },
    # ── Bloco 3: Candidatos, triagem, mover, reprovar (usa vaga existente com candidatos) ──
    {
        "name": "Selecionar vaga existente com candidatos",
        "reset": True,
        "steps": [
            {
                "send": "quero ver os candidatos da vaga f9d75e0b-6950-4cbb-b914-3b8f1891d41a",
                "expect": (
                    "Deve mostrar candidatos da vaga com distribuição de fit ou lista de candidatos. "
                    "Pode ser triagem, nomes, ou informar quantos tem."
                ),
                "max_wait": 60,
            },
        ],
    },
    {
        "name": "Mover candidatos",
        "reset": False,
        "steps": [
            {
                "send": "quero mover os candidatos dessa vaga pra próxima etapa",
                "expect": (
                    "Deve mostrar candidatos disponíveis e pedir confirmação (botões de aprovação), "
                    "OU montar shortlist para aprovação, "
                    "OU pedir mais detalhes sobre quem mover. "
                    "NÃO deve retornar mensagem de 'em breve' ou 'não disponível'."
                ),
                "max_wait": 60,
            },
        ],
    },
    {
        "name": "Reprovar candidatos",
        "reset": False,
        "steps": [
            {
                "send": "quero reprovar os candidatos da vaga f9d75e0b-6950-4cbb-b914-3b8f1891d41a",
                "expect": (
                    "Deve identificar candidatos para reprovação e pedir confirmação (botões), "
                    "OU informar quantos serão reprovados e pedir aprovação, "
                    "OU perguntar detalhes. "
                    "NÃO deve retornar mensagem de 'em breve' ou 'não disponível'."
                ),
                "max_wait": 60,
            },
        ],
    },
    # ── Bloco 4: Status, listagem, conversa livre ──
    {
        "name": "Status / SLA da vaga",
        "reset": False,
        "steps": [
            {
                "send": "me dá o status da vaga f9d75e0b-6950-4cbb-b914-3b8f1891d41a, quero ver o SLA",
                "expect": (
                    "Deve mostrar relatório com status da vaga, dias aberta, "
                    "distribuição por etapa do pipeline ou métricas gerais."
                ),
            },
        ],
    },
    {
        "name": "Listar vagas",
        "reset": False,
        "steps": [
            {
                "send": "quais vagas eu tenho abertas?",
                "expect": "Deve listar vagas com nome, status e quantidade de candidatos.",
            },
        ],
    },
    {
        "name": "Conversa livre",
        "reset": False,
        "steps": [
            {
                "send": "Qual a melhor forma de avaliar fit cultural numa entrevista técnica?",
                "expect": (
                    "Deve responder com conteúdo relevante sobre avaliação de fit cultural, "
                    "com pelo menos 2-3 frases de substância. Não deve ser uma resposta genérica vazia."
                ),
                "max_wait": 60,
            },
        ],
    },
    # ── Bloco 5: Guia InHire ──
    {
        "name": "Guia InHire — Divulgação",
        "reset": False,
        "steps": [
            {
                "send": "como faço pra divulgar essa vaga nos portais?",
                "expect": (
                    "Deve explicar como configurar a divulgação no InHire, "
                    "mencionando LinkedIn/Indeed/portais ou aba Divulgação. "
                    "Deve incluir um link de ajuda (help.inhire.app) ou passo a passo."
                ),
            },
        ],
    },
    {
        "name": "Guia InHire — Triagem IA",
        "reset": False,
        "steps": [
            {
                "send": "como configuro a triagem automática?",
                "expect": (
                    "Deve explicar como configurar o Agente de Triagem IA no InHire, "
                    "mencionando critérios (Essencial/Importante/Diferencial) ou link de ajuda. "
                    "NÃO deve dizer que não sabe."
                ),
            },
        ],
    },
    # ── Bloco 6: Utilitários ──
    {
        "name": "Toggle comunicação",
        "reset": False,
        "steps": [
            {
                "send": "desativar comunicacao com candidatos",
                "expect": "Deve confirmar que a comunicação automática foi desativada.",
            },
            {
                "send": "ativar comunicacao com candidatos",
                "expect": "Deve confirmar que a comunicação automática foi reativada.",
            },
        ],
    },
    {
        "name": "Cancelar conversa",
        "reset": False,
        "steps": [
            {
                "send": "cancelar",
                "expect": "Deve confirmar que a conversa foi resetada e perguntar como pode ajudar.",
            },
        ],
    },
    # ── Bloco 7: Resiliência (lock + dedup) ──
    {
        "name": "Mensagens rápidas em sequência (lock)",
        "reset": True,
        "steps": [
            {
                "send": "oi",
                "expect": "Deve responder normalmente com saudação ou pedido de onboarding. Qualquer resposta é válida — o teste verifica que não quebra.",
                "max_wait": 15,
            },
            {
                "send": "vagas abertas",
                "expect": "Deve listar vagas ou responder normalmente. O importante é que respondeu sem erro — testa que o lock não travou.",
                "max_wait": 30,
            },
        ],
    },
    # ── Bloco 8: Shortlist completo (com aprovação) ──
    {
        "name": "Shortlist com aprovação",
        "reset": True,
        "steps": [
            {
                "send": "shortlist da vaga f9d75e0b-6950-4cbb-b914-3b8f1891d41a",
                "expect": (
                    "Deve listar ou analisar candidatos da vaga. "
                    "Pode mostrar triagem, montar comparativo, pedir aprovação, "
                    "ou informar que está montando o shortlist (loading). "
                    "Candidatos sem score é aceitável — o importante é processar a solicitação."
                ),
                "max_wait": 120,
            },
        ],
    },
    # ── Bloco 9: Agendamento de entrevista — fluxo completo ──
    {
        "name": "Agendar entrevista — listar candidatos",
        "reset": True,
        "steps": [
            {
                "send": "quero agendar uma entrevista pra vaga f9d75e0b-6950-4cbb-b914-3b8f1891d41a",
                "expect": (
                    "Deve listar candidatos disponíveis para agendar entrevista "
                    "e pedir o número do candidato e a data/hora. "
                    "NÃO deve dizer 'em breve' ou 'não disponível'."
                ),
                "max_wait": 60,
            },
        ],
    },
    {
        "name": "Agendar entrevista — selecionar candidato e data",
        "reset": False,
        "steps": [
            {
                "send": "1 quinta-feira às 14h",
                "expect": (
                    "Deve confirmar a criação do agendamento OU pedir confirmação. "
                    "Pode mencionar 'agendada', 'registrado', 'appointment', 'entrevista', "
                    "ou mostrar dados do agendamento (candidato, data). "
                    "NÃO deve dar erro técnico ou pedir a vaga novamente."
                ),
                "max_wait": 60,
            },
        ],
    },
    # ── Bloco 10: Carta oferta — fluxo completo ──
    {
        "name": "Carta oferta — listar candidatos",
        "reset": True,
        "steps": [
            {
                "send": "quero enviar uma carta oferta pra vaga f9d75e0b-6950-4cbb-b914-3b8f1891d41a",
                "expect": (
                    "Deve listar candidatos elegíveis para carta oferta "
                    "e pedir informações (candidato, salário, aprovador). "
                    "Pode também listar templates disponíveis. "
                    "NÃO deve dizer 'em breve', 'não disponível' ou 'não habilitada'."
                ),
                "max_wait": 60,
            },
        ],
    },
    {
        "name": "Carta oferta — fornecer dados",
        "reset": False,
        "steps": [
            {
                "send": "1 salário 15000 aprovador maiconcisco@gmail.com",
                "expect": (
                    "Deve mostrar resumo da oferta com candidato, salário e aprovador, "
                    "e pedir confirmação (botões de aprovação). "
                    "Pode mostrar 'Carta Oferta', salário, aprovador. "
                    "NÃO deve dar erro técnico."
                ),
                "expect_buttons": True,
                "max_wait": 60,
            },
        ],
    },
    {
        "name": "Carta oferta — aprovar e criar",
        "reset": False,
        "steps": [
            {
                "action": "approve",
                "callback": "offer_approval",
                "expect": (
                    "Deve confirmar criação da carta oferta OU informar erro de template/dados. "
                    "Se criou: deve mostrar ID ou status. "
                    "Se erro: deve ser erro de template/dados, NÃO erro de permissão (403)."
                ),
            },
        ],
    },
    # ── Bloco 11: Ver memórias ──
    {
        "name": "Ver memórias do recrutador",
        "reset": True,
        "steps": [
            {
                "send": "o que você sabe sobre mim?",
                "expect": (
                    "Deve mostrar informações sobre o recrutador: perfil, "
                    "configurações personalizadas, padrões de decisão, "
                    "ou mencionar que ainda está aprendendo. "
                    "Deve conter 'aprendi' ou 'perfil' ou 'configurações' ou 'padrões' ou 'decisão'."
                ),
                "max_wait": 30,
            },
        ],
    },
    # ── Bloco 12: Ver memórias com variação de linguagem ──
    {
        "name": "Ver memórias — variação",
        "reset": False,
        "steps": [
            {
                "send": "suas memórias",
                "expect": (
                    "Deve mostrar informações do recrutador como na pergunta anterior. "
                    "Variações como 'suas memórias', 'o que você lembra' devem funcionar igual."
                ),
                "max_wait": 30,
            },
        ],
    },
    # ── Bloco 13: Guia InHire — scorecard ──
    {
        "name": "Guia InHire — Scorecard",
        "reset": False,
        "steps": [
            {
                "send": "como configuro o scorecard da vaga?",
                "expect": (
                    "Deve explicar como configurar o scorecard/kit de entrevista no InHire, "
                    "mencionando critérios de avaliação, roteiro de perguntas, ou link de ajuda. "
                    "NÃO deve dizer que não sabe."
                ),
            },
        ],
    },
    # ── Bloco 14: Guia InHire — automações ──
    {
        "name": "Guia InHire — Automações",
        "reset": False,
        "steps": [
            {
                "send": "como automatizo os testes da vaga?",
                "expect": (
                    "Deve explicar como configurar automações no InHire "
                    "(envio automático de testes DISC, gatilhos por etapa), "
                    "mencionando aba Automações ou link de ajuda. "
                    "NÃO deve dizer que não sabe."
                ),
            },
        ],
    },
    # ── Bloco 15: Conversa livre — assunto diferente ──
    {
        "name": "Conversa livre — employer branding",
        "reset": False,
        "steps": [
            {
                "send": "me dá dicas de como melhorar o employer branding da empresa",
                "expect": (
                    "Deve responder com dicas relevantes sobre employer branding. "
                    "Pelo menos 2-3 sugestões práticas. Não deve ser genérico/vazio."
                ),
                "max_wait": 60,
            },
        ],
    },
    # ── Bloco 16: Shortlist com mover — fluxo completo ──
    {
        "name": "Shortlist + mover — fluxo completo com aprovação",
        "reset": True,
        "steps": [
            {
                "send": "quero ver os candidatos da vaga f9d75e0b-6950-4cbb-b914-3b8f1891d41a e mover os bons pra próxima etapa",
                "expect": (
                    "Deve mostrar candidatos e/ou iniciar processo de shortlist/mover. "
                    "Pode listar triagem, montar comparativo, ou pedir qual etapa."
                ),
                "max_wait": 120,
            },
        ],
    },
    # ── Bloco 17: Status sem especificar vaga (deve pedir ID) ──
    {
        "name": "Status sem vaga — pede ID",
        "reset": True,
        "steps": [
            {
                "send": "me dá o status da vaga",
                "expect": (
                    "Deve pedir o ID da vaga ou sugerir listar as vagas abertas. "
                    "NÃO deve dar erro ou inventar dados."
                ),
            },
        ],
    },
    # ── Bloco 18: Agendar sem vaga (deve pedir ID) ──
    {
        "name": "Agendar sem vaga — pede ID",
        "reset": True,
        "steps": [
            {
                "send": "quero agendar uma entrevista",
                "expect": (
                    "Deve pedir o ID da vaga ou sugerir listar as vagas abertas. "
                    "NÃO deve dar erro técnico."
                ),
            },
        ],
    },
    # ── Bloco 19: Mensagem vaga / ambígua ──
    {
        "name": "Mensagem ambígua",
        "reset": True,
        "steps": [
            {
                "send": "tá rolando algo?",
                "expect": (
                    "Deve responder de forma amigável, perguntando como pode ajudar "
                    "ou oferecendo opções. NÃO deve dar erro."
                ),
            },
        ],
    },
    # ── Bloco 20: Dois comandos em sequência rápida ──
    {
        "name": "Sequência rápida — vagas + conversa",
        "reset": True,
        "steps": [
            {
                "send": "vagas abertas",
                "expect": "Deve listar vagas com nome, status e candidatos.",
                "max_wait": 30,
            },
            {
                "send": "o que significa SLA em recrutamento?",
                "expect": (
                    "Deve explicar SLA (Service Level Agreement) no contexto de recrutamento. "
                    "Pelo menos 2 frases de conteúdo."
                ),
                "max_wait": 30,
            },
        ],
    },
    # ── Bloco 21: Reprovar com fluxo completo ──
    {
        "name": "Reprovar candidatos — fluxo com aprovação",
        "reset": True,
        "steps": [
            {
                "send": "quero reprovar os candidatos da vaga f9d75e0b-6950-4cbb-b914-3b8f1891d41a",
                "expect": (
                    "Deve identificar candidatos para reprovação e pedir confirmação (botões), "
                    "OU informar quantos serão reprovados, "
                    "OU dizer que não tem candidatos pra reprovar. "
                    "NÃO deve dizer 'em breve' ou 'não disponível'."
                ),
                "max_wait": 60,
            },
        ],
    },
]

# ── Colors ────────────────────────────────────────────────
def green(s): return f"\033[92m{s}\033[0m"
def red(s): return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def cyan(s): return f"\033[96m{s}\033[0m"
def dim(s): return f"\033[90m{s}\033[0m"
def bold(s): return f"\033[1m{s}\033[0m"


# ── State ─────────────────────────────────────────────────
event_counter = 0
last_seen_ts = "0"
results = []


# ── Slack helpers ─────────────────────────────────────────
def make_signed_event(text: str) -> tuple[str, dict]:
    global event_counter
    event_counter += 1
    body = json.dumps({
        "token": "test",
        "team_id": "T06TWGNJJLR",
        "event_id": f"Ev_test_{event_counter}_{int(time.time())}",
        "event": {
            "type": "message",
            "channel_type": "im",
            "channel": SIM_CHANNEL_ID,
            "user": SIM_USER_ID,
            "text": text,
            "ts": str(time.time()),
        },
        "type": "event_callback",
    })
    timestamp = str(int(time.time()))
    sig_base = f"v0:{timestamp}:{body}"
    signature = "v0=" + hmac.new(
        SIGNING_SECRET.encode(), sig_base.encode(), hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
    }
    return body, headers


async def get_new_bot_messages(client: httpx.AsyncClient) -> list[dict]:
    global last_seen_ts
    resp = await client.post(
        "https://slack.com/api/conversations.history",
        headers=HEADERS_BOT,
        json={"channel": SIM_CHANNEL_ID, "limit": 15, "oldest": last_seen_ts},
    )
    data = resp.json()
    messages = data.get("messages", [])
    bot_msgs = [
        m for m in messages
        if m.get("bot_id") and float(m["ts"]) > float(last_seen_ts)
    ]
    bot_msgs.sort(key=lambda m: float(m["ts"]))
    if messages:
        max_ts = max(float(m["ts"]) for m in messages)
        if max_ts > float(last_seen_ts):
            last_seen_ts = str(max_ts)
    return bot_msgs


async def send_and_collect(client: httpx.AsyncClient, text: str, max_wait: int = 45):
    """Send message visibly as Maicon + simulated event to trigger bot processing."""
    global last_seen_ts

    # Drain pending
    await asyncio.sleep(0.5)
    await get_new_bot_messages(client)

    # Post as Maicon for visibility in Slack chat (optional — doesn't trigger bot)
    await client.post(
        "https://slack.com/api/chat.postMessage",
        headers=HEADERS_USER,
        json={"channel": SIM_CHANNEL_ID, "text": text},
    )
    await asyncio.sleep(1)
    # Drain the echo of our own message
    await get_new_bot_messages(client)

    # Send simulated event to trigger bot processing
    body, headers = make_signed_event(text)
    resp = await client.post(f"{SERVER_URL}/slack/events", content=body, headers=headers)
    if resp.status_code != 200:
        return [], False

    # Poll for responses — keep waiting if we only got a loading indicator
    LOADING_INDICATORS = ["analisando", "gerando", "processando", "montando", "deixa eu ver",
                          "verificando", "buscando", "criando", "movendo", "reprovando"]
    all_msgs = []
    for _ in range(max_wait // 3):
        await asyncio.sleep(3)
        new = await get_new_bot_messages(client)
        if new:
            all_msgs.extend(new)

            # Check if we only got loading messages — if so, keep waiting for the real response
            all_texts_so_far = " ".join(m.get("text", "") for m in all_msgs).lower()
            only_loading = all(
                any(ind in t.get("text", "").lower() for ind in LOADING_INDICATORS)
                and len(t.get("text", "")) < 100
                for t in all_msgs
            )
            if only_loading:
                # Keep polling — real response hasn't arrived yet
                continue

            # Got substantive response — wait a bit for any follow-ups
            await asyncio.sleep(5)
            more = await get_new_bot_messages(client)
            if more:
                all_msgs.extend(more)
            break

    texts = []
    has_buttons = False
    for m in all_msgs:
        t = m.get("text", "")
        # Also extract text from blocks (approval details, etc.)
        for block in m.get("blocks", []):
            if block.get("type") == "section":
                bt = block.get("text", {}).get("text", "")
                if bt and bt not in t:
                    t = f"{t}\n{bt}" if t else bt
            if block.get("type") == "actions":
                has_buttons = True
        texts.append(t)
    return texts, has_buttons


async def click_button(client: httpx.AsyncClient, action_id: str, callback_id: str):
    global last_seen_ts
    await asyncio.sleep(0.5)
    await get_new_bot_messages(client)

    payload = json.dumps({
        "type": "block_actions",
        "actions": [{"action_id": action_id, "value": callback_id}],
        "user": {"id": SIM_USER_ID},
        "channel": {"id": SIM_CHANNEL_ID},
    })
    await client.post(
        f"{SERVER_URL}/slack/interactions",
        content="payload=" + urllib.parse.quote(payload),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    all_msgs = []
    for _ in range(12):
        await asyncio.sleep(3)
        new = await get_new_bot_messages(client)
        if new:
            all_msgs.extend(new)
            await asyncio.sleep(5)
            more = await get_new_bot_messages(client)
            if more:
                all_msgs.extend(more)
            break

    return [m.get("text", "") for m in all_msgs]


# ── Claude judge ──────────────────────────────────────────
async def judge(client: httpx.AsyncClient, response_texts: list[str],
                expectation: str, scenario_name: str, step_desc: str) -> dict:
    """Ask Claude to evaluate if the response meets the expectation."""
    combined = "\n---\n".join(response_texts) if response_texts else "(sem resposta)"

    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 300,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Você é um avaliador de testes do agente Eli (assistente de recrutamento via Slack).\n\n"
                    f"**Cenário:** {scenario_name}\n"
                    f"**Mensagem enviada:** {step_desc}\n"
                    f"**Expectativa:** {expectation}\n\n"
                    f"**Resposta do Eli:**\n{combined}\n\n"
                    f"Avalie: a resposta atende a expectativa?\n"
                    f"Responda EXATAMENTE neste formato JSON (sem markdown):\n"
                    f'{{"verdict": "PASS" ou "FAIL", "reason": "justificativa em 1 linha"}}'
                ),
            }
        ],
    }

    try:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=30,
        )
        data = resp.json()
        text = data.get("content", [{}])[0].get("text", "")

        # Parse JSON
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(text)
        return result
    except Exception as e:
        return {"verdict": "ERROR", "reason": f"Falha ao avaliar: {e}"}


# ── Adaptive helpers ──────────────────────────────────────

WAITING_INDICATORS = ["esperando sua decisão", "aprovar", "ajustar", "rejeitar"]
BUTTON_CALLBACKS = {
    "job_draft_approval": "approve",
    "shortlist_approval": "approve",
    "rejection_approval": "approve",
    "offer_approval": "approve",
}


def _is_waiting_for_action(texts: list[str]) -> bool:
    """Detect if Eli is stuck waiting for a button click."""
    combined = " ".join(texts).lower()
    return any(ind in combined for ind in WAITING_INDICATORS) and len(combined) < 200


def _detect_pending_callback(texts: list[str]) -> str | None:
    """Try to guess which callback is pending from the response text."""
    combined = " ".join(texts).lower()
    if "shortlist" in combined or "mover" in combined:
        return "shortlist_approval"
    if "reprovar" in combined or "reprovação" in combined:
        return "rejection_approval"
    if "rascunho" in combined or "vaga" in combined:
        return "job_draft_approval"
    if "oferta" in combined or "carta" in combined:
        return "offer_approval"
    return None


async def _clear_pending_state(client: httpx.AsyncClient):
    """If Eli is waiting for approval, cancel to unblock."""
    print(f"    {yellow('[ADAPT]')} Estado pendente detectado — cancelando pra destravar")
    texts, _ = await send_and_collect(client, "cancelar", max_wait=10)
    if texts:
        preview = texts[-1][:100]
        print(f"    {dim(f'Eli: {preview}')}")


# ── Runner ────────────────────────────────────────────────
async def run_step(client: httpx.AsyncClient, step: dict, scenario_name: str) -> dict:
    """Execute a single step and return the result. Adapts to Eli's state."""
    if "action" in step:
        # Explicit button click
        desc = f"*clica em [{step['action'].upper()}]*"
        print(f"    {cyan('Recrutador:')} {desc}")
        texts = await click_button(client, step["action"], step["callback"])
        has_buttons = False
    else:
        # Message
        msg = step["send"]
        desc = msg[:120] + ("..." if len(msg) > 120 else "")
        print(f"    {cyan('Recrutador:')} {desc}")
        wait = step.get("max_wait", 45)
        texts, has_buttons = await send_and_collect(client, msg, max_wait=wait)

        # ── Adaptive: Eli is stuck waiting for button? ──
        if _is_waiting_for_action(texts):
            await _clear_pending_state(client)
            # Retry the original message
            print(f"    {yellow('[ADAPT]')} Reenviando mensagem original")
            texts, has_buttons = await send_and_collect(client, msg, max_wait=wait)

        # ── Adaptive: Onboarding detected ──
        if step.get("on_onboarding") and texts:
            is_onboarding = any("email" in t.lower() for t in texts)
            if is_onboarding:
                print(f"    {yellow('[ONBOARDING]')} Detectado — enviando email")
                for t in texts:
                    print(f"    {dim('Eli:')} {t[:200]}")
                ob = step["on_onboarding"]
                print(f"    {cyan('Recrutador:')} {ob['send']}")
                texts, _ = await send_and_collect(client, ob["send"])
                step = {**step, "expect": ob["expect"], "send": ob["send"]}

        # ── Adaptive: Missing info detected ──
        if step.get("on_missing_info") and texts:
            has_missing = any("faltando" in t.lower() or "falta" in t.lower() for t in texts)
            if has_missing:
                print(f"    {yellow('[MISSING INFO]')} Detectado — forçando gerar")
                for t in texts:
                    print(f"    {dim('Eli:')} {t[:200]}")
                mi = step["on_missing_info"]
                print(f"    {cyan('Recrutador:')} {mi['send']}")
                texts, has_buttons = await send_and_collect(client, mi["send"], max_wait=50)
                step = {**step, "expect": mi["expect"]}

        # Check buttons if expected
        if step.get("expect_buttons") and not has_buttons:
            print(f"    {yellow('[WARN]')} Botões esperados mas não encontrados")

    # Print response
    if not texts:
        print(f"    {red('Eli:')} (sem resposta)")
    else:
        for t in texts:
            preview = t[:300].replace("\n", "\n           ")
            print(f"    {green('Eli:')} {preview}")
            if len(t) > 300:
                print(f"           {dim(f'... (+{len(t)-300} chars)')}")

    # Judge
    verdict = await judge(client, texts, step["expect"], scenario_name, step.get("send", str(step.get("action", ""))))

    v = verdict.get("verdict", "ERROR")
    reason = verdict.get("reason", "")

    if v == "PASS":
        print(f"    {green('[PASS]')} {dim(reason)}")
    elif v == "FAIL":
        print(f"    {red('[FAIL]')} {reason}")
    else:
        print(f"    {yellow('[ERROR]')} {reason}")

    return {"verdict": v, "reason": reason, "scenario": scenario_name, "step": step.get("send", step.get("action", "")),
            "has_buttons": has_buttons if "action" not in step else False}


async def run_scenario(client: httpx.AsyncClient, scenario: dict):
    """Run all steps in a scenario. Adapts to Eli's state between steps."""
    name = scenario["name"]
    print(f"\n  {bold('━'*50)}")
    print(f"  {bold(name)}")

    if scenario.get("reset", False):
        print(f"    {dim('(resetando conversa)')}")
        await send_and_collect(client, "cancelar", max_wait=10)
    else:
        # Drain any leftover messages from previous scenario
        await asyncio.sleep(3)
        await get_new_bot_messages(client)

    step_results = []
    for step in scenario["steps"]:
        result = await run_step(client, step, name)
        step_results.append(result)

    return step_results


async def main():
    global last_seen_ts

    print(f"\n{bold('='*60)}")
    print(f"{bold('  Eli — Agente de Testes Inteligente v1')}")
    print(f"{bold('='*60)}")

    if not ANTHROPIC_KEY:
        print(f"\n  {red('ERRO:')} ANTHROPIC_API_KEY não configurada.")
        print(f"  Defina a variável de ambiente ou edite o script.")
        return

    async with httpx.AsyncClient(timeout=60) as client:
        # Health check
        try:
            resp = await client.get(f"{SERVER_URL}/health")
            if resp.status_code == 200:
                print(f"\n  {green('[OK]')} Servidor online: {SERVER_URL}")
            else:
                print(f"\n  {red('[ERRO]')} Servidor retornou {resp.status_code}")
                return
        except Exception as e:
            print(f"\n  {red('[ERRO]')} Servidor inacessível: {e}")
            return

        # Set baseline
        hist = await client.post(
            "https://slack.com/api/conversations.history",
            headers=HEADERS_BOT,
            json={"channel": SIM_CHANNEL_ID, "limit": 1},
        )
        hist_data = hist.json()
        if hist_data.get("messages"):
            last_seen_ts = hist_data["messages"][0]["ts"]

        # Run scenarios
        all_results = []
        for scenario in SCENARIOS:
            step_results = await run_scenario(client, scenario)
            all_results.extend(step_results)

    # ── Report ────────────────────────────────────────────
    passed = sum(1 for r in all_results if r["verdict"] == "PASS")
    failed = sum(1 for r in all_results if r["verdict"] == "FAIL")
    errors = sum(1 for r in all_results if r["verdict"] == "ERROR")
    total = len(all_results)

    print(f"\n{bold('='*60)}")
    print(f"{bold('  RESULTADO')}")
    print(f"{bold('='*60)}")
    print(f"\n  {green(f'{passed} PASS')}  {red(f'{failed} FAIL') if failed else ''}  {yellow(f'{errors} ERROR') if errors else ''}  (total: {total})")

    if failed or errors:
        print(f"\n  {bold('Detalhes:')}")
        for r in all_results:
            if r["verdict"] != "PASS":
                icon = red("[FAIL]") if r["verdict"] == "FAIL" else yellow("[ERROR]")
                step_preview = str(r["step"])[:60]
                print(f"    {icon} {r['scenario']} → {step_preview}")
                print(f"          {dim(r['reason'])}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
