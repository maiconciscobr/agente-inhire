#!/usr/bin/env python3
"""
Agente InHire — Automated Test Suite
Executes each test case by sending messages via Slack and validating bot responses.
Usage: python3 run_tests.py
"""
import asyncio
import json
import os
import sys
import time

import httpx
from slack_sdk.web.async_client import AsyncWebClient

# === Config ===
BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "xoxb-6948566630705-10806440568629-odI7tXFAGO5Gi7P35ZtdXSS2")
USER_TOKEN = os.getenv("SLACK_USER_TOKEN", "xoxp-6948566630705-7714476166882-10822752736321-887f10bea6224184a7dad8ac20ad4c4f")
BOT_USER_ID = "U0APQCYGQJH"
TEST_USER_ID = "U07M0E04WRY"  # Maicon
AGENT_URL = "https://agente.adianterecursos.com.br"

# Test data
TEST_EMAIL = "maicon.cisco@byintera.com"
TEST_BRIEFING = "Preciso abrir uma vaga de Analista de Dados Sênior, remoto, CLT, salário de 12 a 18 mil. Requisitos: SQL, Python, Power BI. Urgência alta."
TEST_PROFILE = """João Silva
Engenheiro de Software Sênior com 8 anos de experiência.
Atualmente na empresa XYZ como Tech Lead.
Experiência com Python, FastAPI, PostgreSQL, AWS, Docker, Kubernetes.
Formação: Ciência da Computação - USP
Localização: São Paulo, SP
LinkedIn: joaosilva"""


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = ""
        self.bot_response = ""
        self.duration = 0.0

    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        s = f"{status} | {self.name} ({self.duration:.1f}s)"
        if not self.passed and self.error:
            s += f"\n         Error: {self.error}"
        if self.bot_response:
            s += f"\n         Bot: {self.bot_response[:150]}..."
        return s


class AgentTester:
    def __init__(self):
        self.bot_client = AsyncWebClient(token=BOT_TOKEN)
        self.user_client = AsyncWebClient(token=USER_TOKEN)
        self.channel_id = None
        self.results: list[TestResult] = []
        self.created_job_id = None

    async def setup(self):
        """Open DM channel with the bot and clean state."""
        print("🔧 Setup: abrindo DM com o bot...")
        resp = await self.user_client.conversations_open(users=BOT_USER_ID)
        self.channel_id = resp["channel"]["id"]
        print(f"   Canal: {self.channel_id}")

        # Clean Redis for fresh onboarding
        print("   Limpando Redis...")
        import redis as redis_lib
        r = redis_lib.from_url("redis://:efsQrxLQ6uLkzFsMphCT2ArX3RPzCdl1AAhz2idRohw=@localhost:6379/2", decode_responses=True)
        for key in r.scan_iter("inhire:*"):
            r.delete(key)
        r.close()
        print("   Redis limpo.")

        # Wait for any pending bot processing to finish
        await asyncio.sleep(3)

    async def send_message(self, text: str) -> str:
        """Send a message as the user and return the timestamp."""
        # Record time BEFORE sending to avoid race conditions
        before_ts = str(time.time())
        resp = await self.user_client.chat_postMessage(
            channel=self.channel_id, text=text
        )
        return before_ts

    async def wait_for_bot_reply(self, after_ts: str, timeout: int = 45, min_replies: int = 1) -> list[dict]:
        """Wait for bot replies after a given timestamp."""
        deadline = time.time() + timeout
        seen_ts = set()
        while time.time() < deadline:
            await asyncio.sleep(3)
            resp = await self.bot_client.conversations_history(
                channel=self.channel_id, oldest=after_ts, limit=15
            )
            messages = resp.get("messages", [])
            bot_msgs = [
                m for m in messages
                if m.get("bot_id") and m["ts"] not in seen_ts and float(m["ts"]) > float(after_ts)
            ]
            if len(bot_msgs) >= min_replies:
                # Sort by timestamp ascending
                bot_msgs.sort(key=lambda m: float(m["ts"]))
                return bot_msgs
        return []

    async def send_and_get_reply(self, text: str, timeout: int = 45, min_replies: int = 1) -> list[dict]:
        """Send message and wait for bot reply. Waits between send and poll."""
        ts = await self.send_message(text)
        await asyncio.sleep(2)
        return await self.wait_for_bot_reply(ts, timeout=timeout, min_replies=min_replies)

    def get_text(self, messages: list[dict]) -> str:
        """Combine all bot message texts."""
        return "\n".join(m.get("text", "") for m in messages)

    def has_blocks_with_buttons(self, messages: list[dict]) -> bool:
        """Check if any message has action buttons."""
        for m in messages:
            for block in m.get("blocks", []):
                if block.get("type") == "actions":
                    return True
        return False

    async def click_button(self, messages: list[dict], action_id: str = "approve") -> bool:
        """Simulate clicking a button by posting to the interactions endpoint."""
        for m in messages:
            for block in m.get("blocks", []):
                if block.get("type") == "actions":
                    for element in block.get("elements", []):
                        if element.get("action_id") == action_id:
                            callback_id = element.get("value", "")
                            payload = {
                                "type": "block_actions",
                                "actions": [{"action_id": action_id, "value": callback_id}],
                                "user": {"id": TEST_USER_ID},
                                "channel": {"id": self.channel_id},
                            }
                            async with httpx.AsyncClient() as client:
                                resp = await client.post(
                                    f"{AGENT_URL}/slack/interactions",
                                    data={"payload": json.dumps(payload)},
                                    timeout=10,
                                )
                                return resp.status_code == 200
        return False

    # === TEST CASES ===

    async def test_01_onboarding_ask_email(self) -> TestResult:
        """Test 1: Bot asks for email on first interaction."""
        r = TestResult("01 - Onboarding: pede email")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply("oi")
            text = self.get_text(msgs)
            r.bot_response = text
            if "e-mail" in text.lower() or "email" in text.lower():
                r.passed = True
            else:
                r.error = "Bot não pediu email"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_02_onboarding_register(self) -> TestResult:
        """Test 2: Bot registers user after email."""
        r = TestResult("02 - Onboarding: registra email")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply(TEST_EMAIL, timeout=30)
            text = self.get_text(msgs)
            r.bot_response = text
            if "tudo certo" in text.lower() or "já sei quem" in text.lower() or "como posso" in text.lower():
                r.passed = True
            else:
                r.error = "Bot não confirmou registro"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_03_job_briefing(self) -> TestResult:
        """Test 3: Bot recognizes job creation intent."""
        r = TestResult("03 - Abertura de vaga: reconhece intent")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply(TEST_BRIEFING)
            text = self.get_text(msgs)
            r.bot_response = text
            if "vaga" in text.lower() and ("pronto" in text.lower() or "briefing" in text.lower() or "informações" in text.lower()):
                r.passed = True
            else:
                r.error = "Bot não reconheceu intent de abertura de vaga"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_04_job_generate_draft(self) -> TestResult:
        """Test 4: Bot generates job draft with approval buttons."""
        r = TestResult("04 - Abertura de vaga: gera rascunho")
        start = time.time()
        try:
            # Say "pronto" and wait for both the "analyzing" message and the draft
            msgs = await self.send_and_get_reply("pronto", timeout=60, min_replies=2)
            text = self.get_text(msgs)
            r.bot_response = text
            has_buttons = self.has_blocks_with_buttons(msgs)
            if has_buttons or "aprovar" in text.lower():
                r.passed = True
            elif "faltando" in text.lower() or "missing" in text.lower():
                # Missing info — still a valid response, try generating anyway
                msgs2 = await self.send_and_get_reply("gerar", timeout=60, min_replies=2)
                text2 = self.get_text(msgs2)
                r.bot_response = text2
                if self.has_blocks_with_buttons(msgs2):
                    r.passed = True
                else:
                    r.error = "Rascunho gerado mas sem botões de aprovação"
            else:
                r.error = "Não gerou rascunho com botões"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_05_job_approve(self) -> TestResult:
        """Test 5: Approve job draft and verify creation in InHire."""
        r = TestResult("05 - Abertura de vaga: aprovar e criar")
        start = time.time()
        try:
            # Get most recent messages to find approval buttons
            resp = await self.bot_client.conversations_history(
                channel=self.channel_id, limit=5
            )
            recent = resp.get("messages", [])
            before_ts = str(time.time())

            clicked = await self.click_button(recent, "approve")
            if not clicked:
                r.error = "Não encontrou botão de aprovar"
                r.duration = time.time() - start
                return r

            # Wait for confirmation
            msgs = await self.wait_for_bot_reply(before_ts, timeout=30)
            text = self.get_text(msgs)
            r.bot_response = text

            if "criada" in text.lower() or "sucesso" in text.lower():
                r.passed = True
                # Extract job ID for later tests
                import re
                id_match = re.search(r'`([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})`', text)
                if id_match:
                    self.created_job_id = id_match.group(1)
            else:
                r.error = "Vaga não foi criada"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_06_list_jobs(self) -> TestResult:
        """Test 6: List open jobs."""
        r = TestResult("06 - Listar vagas")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply("vagas abertas")
            text = self.get_text(msgs)
            r.bot_response = text
            if "vaga" in text.lower() and ("`open`" in text or "status" in text.lower() or "ID:" in text):
                r.passed = True
            else:
                r.error = "Listagem de vagas não retornou dados esperados"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_07_job_status(self) -> TestResult:
        """Test 7: Job status report with SLA."""
        r = TestResult("07 - Relatório / SLA")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply("status da vaga")
            text = self.get_text(msgs)
            r.bot_response = text
            if "relatório" in text.lower() or "candidatos" in text.lower() or "dias" in text.lower() or "status" in text.lower():
                r.passed = True
            else:
                r.error = "Relatório não gerado"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_08_linkedin_search(self) -> TestResult:
        """Test 8: Generate LinkedIn search string."""
        r = TestResult("08 - Busca LinkedIn")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply("busca linkedin", timeout=30)
            text = self.get_text(msgs)
            r.bot_response = text
            if "and" in text.lower() or "or" in text.lower() or "busca" in text.lower() or '"' in text:
                r.passed = True
            else:
                r.error = "Não gerou string de busca"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_09_analyze_profile(self) -> TestResult:
        """Test 9: Analyze pasted profile."""
        r = TestResult("09 - Análise de perfil")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply(TEST_PROFILE, timeout=30)
            text = self.get_text(msgs)
            r.bot_response = text
            if "fit" in text.lower() or "pontos" in text.lower() or "análise" in text.lower() or "recomendação" in text.lower():
                r.passed = True
            else:
                r.error = "Não analisou o perfil"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_10_candidates(self) -> TestResult:
        """Test 10: Check candidates for current job."""
        r = TestResult("10 - Candidatos / triagem")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply("candidatos", timeout=30)
            text = self.get_text(msgs)
            r.bot_response = text
            if "candidato" in text.lower() or "triagem" in text.lower() or "nenhum" in text.lower() or "fit" in text.lower():
                r.passed = True
            else:
                r.error = "Não respondeu sobre candidatos"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_11_cancel(self) -> TestResult:
        """Test 11: Cancel/reset conversation."""
        r = TestResult("11 - Cancelar conversa")
        start = time.time()
        try:
            msgs = await self.send_and_get_reply("cancelar")
            text = self.get_text(msgs)
            r.bot_response = text
            if "reiniciad" in text.lower() or "como posso" in text.lower() or "ajudar" in text.lower():
                r.passed = True
            else:
                r.error = "Não reiniciou conversa"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def test_12_comms_toggle(self) -> TestResult:
        """Test 12: Toggle candidate communication."""
        r = TestResult("12 - Toggle comunicação")
        start = time.time()
        try:
            # Need to re-register first since we cancelled
            await self.send_and_get_reply(TEST_EMAIL, timeout=15)
            await asyncio.sleep(2)

            msgs = await self.send_and_get_reply("desativar comunicação com candidatos", timeout=15)
            text1 = self.get_text(msgs)

            msgs2 = await self.send_and_get_reply("ativar comunicação com candidatos", timeout=15)
            text2 = self.get_text(msgs2)

            r.bot_response = f"Desativar: {text1} | Ativar: {text2}"
            if "desativad" in text1.lower() and "ativad" in text2.lower():
                r.passed = True
            else:
                r.error = "Toggle não funcionou corretamente"
        except Exception as e:
            r.error = str(e)
        r.duration = time.time() - start
        return r

    async def run_all(self):
        """Run all tests in sequence."""
        print("=" * 60)
        print("🧪 AGENTE INHIRE — SUITE DE TESTES AUTOMATIZADOS")
        print("=" * 60)
        print()

        await self.setup()
        print()

        tests = [
            self.test_01_onboarding_ask_email,
            self.test_02_onboarding_register,
            self.test_03_job_briefing,
            self.test_04_job_generate_draft,
            self.test_05_job_approve,
            self.test_06_list_jobs,
            self.test_07_job_status,
            self.test_08_linkedin_search,
            self.test_09_analyze_profile,
            self.test_10_candidates,
            self.test_11_cancel,
            self.test_12_comms_toggle,
        ]

        for test_fn in tests:
            print(f"▶ Running: {test_fn.__doc__}")
            result = await test_fn()
            self.results.append(result)
            print(f"  {result}")
            print()

            # Delay between tests to avoid message collision
            await asyncio.sleep(5)

        # Summary
        print("=" * 60)
        print("📊 RESUMO DOS TESTES")
        print("=" * 60)
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        print(f"\n{'✅' if passed == total else '⚠️'} {passed}/{total} testes passaram\n")

        for r in self.results:
            print(f"  {r}")

        print()
        if passed < total:
            failed = [r for r in self.results if not r.passed]
            print(f"❌ {len(failed)} teste(s) falharam:")
            for r in failed:
                print(f"   - {r.name}: {r.error}")
        else:
            print("🎉 Todos os testes passaram!")

        return passed == total


async def main():
    tester = AgentTester()
    success = await tester.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
