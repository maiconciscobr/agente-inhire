const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const {
  FaRobot, FaSlack, FaBrain, FaSearch, FaUsers, FaChartLine,
  FaClock, FaDatabase, FaBolt, FaCheckCircle, FaComments,
  FaLinkedin, FaEnvelope, FaCalendarAlt, FaFileContract, FaRocket
} = require("react-icons/fa");

// --- Icon helper ---
function renderIconSvg(IconComponent, color = "#000000", size = 256) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color, size: String(size) })
  );
}

async function iconToBase64Png(IconComponent, color, size = 256) {
  const svg = renderIconSvg(IconComponent, color, size);
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}

// --- Colors ---
const C = {
  navy:    "0F172A",
  blue:    "1E40AF",
  cyan:    "06B6D4",
  cyanDk:  "0891B2",
  slate50: "F8FAFC",
  slate100:"F1F5F9",
  slate200:"E2E8F0",
  slate400:"94A3B8",
  slate600:"475569",
  slate800:"1E293B",
  white:   "FFFFFF",
  green:   "10B981",
  amber:   "F59E0B",
};

const makeShadow = () => ({
  type: "outer", color: "000000", blur: 8, offset: 2, angle: 135, opacity: 0.12
});

async function buildPresentation() {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "Maicon — InHire";
  pres.title = "Eli — Agente de IA para Recrutamento";

  // Pre-render icons
  const icons = {
    robot:    await iconToBase64Png(FaRobot, "#06B6D4"),
    slack:    await iconToBase64Png(FaSlack, "#FFFFFF"),
    brain:    await iconToBase64Png(FaBrain, "#06B6D4"),
    search:   await iconToBase64Png(FaSearch, "#06B6D4"),
    users:    await iconToBase64Png(FaUsers, "#06B6D4"),
    chart:    await iconToBase64Png(FaChartLine, "#06B6D4"),
    clock:    await iconToBase64Png(FaClock, "#06B6D4"),
    database: await iconToBase64Png(FaDatabase, "#06B6D4"),
    bolt:     await iconToBase64Png(FaBolt, "#F59E0B"),
    check:    await iconToBase64Png(FaCheckCircle, "#10B981"),
    comments: await iconToBase64Png(FaComments, "#06B6D4"),
    linkedin: await iconToBase64Png(FaLinkedin, "#06B6D4"),
    email:    await iconToBase64Png(FaEnvelope, "#06B6D4"),
    calendar: await iconToBase64Png(FaCalendarAlt, "#06B6D4"),
    contract: await iconToBase64Png(FaFileContract, "#06B6D4"),
    rocket:   await iconToBase64Png(FaRocket, "#06B6D4"),
    // Dark bg versions
    robotW:   await iconToBase64Png(FaRobot, "#FFFFFF"),
    rocketW:  await iconToBase64Png(FaRocket, "#FFFFFF"),
    boltW:    await iconToBase64Png(FaBolt, "#06B6D4"),
  };

  // ============================================================
  // SLIDE 1 — CAPA
  // ============================================================
  let s1 = pres.addSlide();
  s1.background = { color: C.navy };

  // Accent bar top
  s1.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.cyan }
  });

  // Robot icon
  s1.addImage({ data: icons.robotW, x: 4.25, y: 0.7, w: 1.5, h: 1.5 });

  // Title
  s1.addText("Eli", {
    x: 0.5, y: 2.3, w: 9, h: 1.0,
    fontSize: 54, fontFace: "Calibri", bold: true,
    color: C.white, align: "center", margin: 0
  });

  // Subtitle
  s1.addText("Agente de IA para Recrutamento", {
    x: 0.5, y: 3.2, w: 9, h: 0.6,
    fontSize: 24, fontFace: "Calibri",
    color: C.cyan, align: "center", margin: 0
  });

  // Tagline
  s1.addText("Slack + InHire + Claude AI — automação inteligente de ponta a ponta", {
    x: 1.0, y: 4.1, w: 8, h: 0.5,
    fontSize: 14, fontFace: "Calibri",
    color: C.slate400, align: "center", margin: 0
  });

  // Bottom bar
  s1.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.35, w: 10, h: 0.28, fill: { color: C.slate800 }
  });
  s1.addText("InHire · Abril 2026", {
    x: 0.5, y: 5.35, w: 9, h: 0.28,
    fontSize: 10, fontFace: "Calibri",
    color: C.slate400, align: "center", valign: "middle", margin: 0
  });

  // ============================================================
  // SLIDE 2 — O PROBLEMA
  // ============================================================
  let s2 = pres.addSlide();
  s2.background = { color: C.white };

  // Section label
  s2.addText("O PROBLEMA", {
    x: 0.6, y: 0.4, w: 3, h: 0.35,
    fontSize: 11, fontFace: "Calibri", bold: true,
    color: C.cyan, charSpacing: 3, margin: 0
  });

  s2.addText("Recrutadores estão afogados em tarefas operacionais", {
    x: 0.6, y: 0.8, w: 8.5, h: 0.7,
    fontSize: 26, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0
  });

  // Pain points — 3 cards
  const painPoints = [
    { icon: icons.clock, title: "Tempo perdido", desc: "70% do tempo em triagem manual, copiar dados entre sistemas, e-mails repetitivos" },
    { icon: icons.users, title: "Candidatos esquecidos", desc: "Pipeline parado, SLA estourado, talentos perdidos para concorrência" },
    { icon: icons.comments, title: "Zero inteligência", desc: "Decisões sem dados, sem ranking, sem aprendizado sobre o que funciona" },
  ];

  painPoints.forEach((p, i) => {
    const x = 0.6 + i * 3.05;
    const y = 1.85;
    s2.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 2.8, h: 2.8,
      fill: { color: C.slate50 }, shadow: makeShadow()
    });
    // Accent top
    s2.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 2.8, h: 0.05, fill: { color: C.cyan }
    });
    s2.addImage({ data: p.icon, x: x + 0.3, y: y + 0.35, w: 0.45, h: 0.45 });
    s2.addText(p.title, {
      x: x + 0.3, y: y + 0.95, w: 2.2, h: 0.4,
      fontSize: 15, fontFace: "Calibri", bold: true, color: C.navy, margin: 0
    });
    s2.addText(p.desc, {
      x: x + 0.3, y: y + 1.35, w: 2.2, h: 1.1,
      fontSize: 12, fontFace: "Calibri", color: C.slate600, margin: 0
    });
  });

  // Bottom stat
  s2.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 4.9, w: 8.8, h: 0.05, fill: { color: C.slate200 }
  });
  s2.addText([
    { text: "Resultado: ", options: { color: C.slate600, fontSize: 12 } },
    { text: "vagas demoram mais para fechar, candidatos desistem, e a empresa perde dinheiro.", options: { color: C.navy, fontSize: 12, bold: true } }
  ], {
    x: 0.6, y: 5.05, w: 8.8, h: 0.4, fontFace: "Calibri", margin: 0
  });

  // ============================================================
  // SLIDE 3 — A SOLUÇÃO
  // ============================================================
  let s3 = pres.addSlide();
  s3.background = { color: C.white };

  s3.addText("A SOLUÇÃO", {
    x: 0.6, y: 0.4, w: 3, h: 0.35,
    fontSize: 11, fontFace: "Calibri", bold: true,
    color: C.cyan, charSpacing: 3, margin: 0
  });

  s3.addText("Eli — seu copiloto de recrutamento no Slack", {
    x: 0.6, y: 0.8, w: 8.5, h: 0.7,
    fontSize: 26, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0
  });

  // Flow: 3 columns
  const flowSteps = [
    { icon: icons.slack, bg: C.blue, label: "Slack", desc: "Recrutador conversa naturalmente no DM — sem tela nova, sem treinamento" },
    { icon: icons.brain, bg: C.navy, label: "Claude AI", desc: "Entende contexto, sugere ações, gera conteúdo, ranqueia candidatos" },
    { icon: icons.database, bg: C.cyanDk, label: "InHire ATS", desc: "Executa ações reais: cria vagas, move candidatos, agenda entrevistas" },
  ];

  flowSteps.forEach((f, i) => {
    const x = 0.6 + i * 3.2;
    const y = 1.75;

    // Icon circle
    s3.addShape(pres.shapes.OVAL, {
      x: x + 0.85, y, w: 1.0, h: 1.0, fill: { color: f.bg }
    });
    s3.addImage({ data: f.icon, x: x + 1.1, y: y + 0.25, w: 0.5, h: 0.5 });

    s3.addText(f.label, {
      x, y: y + 1.15, w: 2.7, h: 0.4,
      fontSize: 16, fontFace: "Calibri", bold: true,
      color: C.navy, align: "center", margin: 0
    });
    s3.addText(f.desc, {
      x, y: y + 1.55, w: 2.7, h: 0.9,
      fontSize: 12, fontFace: "Calibri",
      color: C.slate600, align: "center", margin: 0
    });
  });

  // Arrows between circles
  [3.6, 6.8].forEach(ax => {
    s3.addText("→", {
      x: ax, y: 1.95, w: 0.5, h: 0.6,
      fontSize: 28, fontFace: "Calibri", bold: true,
      color: C.cyan, align: "center", valign: "middle", margin: 0
    });
  });

  // Key principle box
  s3.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 4.1, w: 8.8, h: 1.0,
    fill: { color: C.slate50 }, shadow: makeShadow()
  });
  s3.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 4.1, w: 0.06, h: 1.0, fill: { color: C.cyan }
  });
  s3.addText([
    { text: "Princípio fundamental: ", options: { bold: true, color: C.navy } },
    { text: "O Eli nunca executa ações críticas sem aprovação. Publicar vaga, mover candidatos, reprovar, carta oferta — tudo passa por confirmação do recrutador via botão no Slack.", options: { color: C.slate600 } }
  ], {
    x: 1.0, y: 4.1, w: 8.1, h: 1.0,
    fontSize: 13, fontFace: "Calibri", valign: "middle", margin: 0
  });

  // ============================================================
  // SLIDE 4 — ARQUITETURA
  // ============================================================
  let s4 = pres.addSlide();
  s4.background = { color: C.white };

  s4.addText("ARQUITETURA", {
    x: 0.6, y: 0.4, w: 3, h: 0.35,
    fontSize: 11, fontFace: "Calibri", bold: true,
    color: C.cyan, charSpacing: 3, margin: 0
  });

  s4.addText("Stack moderno, assíncrono, com cache inteligente", {
    x: 0.6, y: 0.8, w: 8.5, h: 0.6,
    fontSize: 24, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0
  });

  // Architecture grid — 2x3
  const archItems = [
    { icon: icons.bolt, label: "FastAPI + asyncio", desc: "Servidor assíncrono, non-blocking, processamento paralelo de eventos" },
    { icon: icons.brain, label: "Claude Sonnet 4", desc: "Tool calling nativo, prompt caching, extração estruturada" },
    { icon: icons.database, label: "Redis", desc: "Estado de conversa (TTL 7d), dedup de eventos, locks de concorrência" },
    { icon: icons.search, label: "Typesense", desc: "Busca full-text em 86k+ talentos, scoped keys com TTL 24h" },
    { icon: icons.chart, label: "Monitor proativo", desc: "Cron jobs: briefing diário, SLA, pipeline parado, candidato excepcional" },
    { icon: icons.calendar, label: "26 melhorias", desc: "Prompt caching, dedup, locks, fila fora horário, consolidação semanal" },
  ];

  archItems.forEach((item, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const x = 0.6 + col * 3.05;
    const y = 1.65 + row * 1.75;

    s4.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 2.8, h: 1.5,
      fill: { color: C.slate50 }, shadow: makeShadow()
    });
    s4.addImage({ data: item.icon, x: x + 0.25, y: y + 0.25, w: 0.35, h: 0.35 });
    s4.addText(item.label, {
      x: x + 0.7, y: y + 0.2, w: 1.85, h: 0.4,
      fontSize: 13, fontFace: "Calibri", bold: true, color: C.navy, margin: 0
    });
    s4.addText(item.desc, {
      x: x + 0.25, y: y + 0.7, w: 2.3, h: 0.65,
      fontSize: 11, fontFace: "Calibri", color: C.slate600, margin: 0
    });
  });

  // ============================================================
  // SLIDE 5 — FUNCIONALIDADES (12 tools)
  // ============================================================
  let s5 = pres.addSlide();
  s5.background = { color: C.white };

  s5.addText("FUNCIONALIDADES", {
    x: 0.6, y: 0.4, w: 3, h: 0.35,
    fontSize: 11, fontFace: "Calibri", bold: true,
    color: C.cyan, charSpacing: 3, margin: 0
  });

  s5.addText("12 tools — tudo via linguagem natural no Slack", {
    x: 0.6, y: 0.8, w: 8.5, h: 0.6,
    fontSize: 24, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0
  });

  // Tools in 2 columns of 6
  const tools = [
    { icon: icons.check, name: "Criar vagas", desc: "Briefing guiado + JD gerada por IA" },
    { icon: icons.users, name: "Triagem inteligente", desc: "Score 1-5 com justificativa" },
    { icon: icons.chart, name: "Shortlist", desc: "Ranking comparativo dos melhores" },
    { icon: icons.search, name: "Buscar talentos", desc: "86k+ no banco via Typesense" },
    { icon: icons.linkedin, name: "Busca LinkedIn", desc: "Query booleana otimizada" },
    { icon: icons.brain, name: "Análise de perfil", desc: "Avaliação detalhada + fit" },
    { icon: icons.bolt, name: "Mover candidatos", desc: "Batch com aprovação" },
    { icon: icons.clock, name: "Status de vaga", desc: "SLA, pipeline, métricas" },
    { icon: icons.calendar, name: "Agendar entrevista", desc: "Registro direto no ATS" },
    { icon: icons.contract, name: "Carta oferta", desc: "Template + ClickSign" },
    { icon: icons.email, name: "Comunicar candidato", desc: "E-mail via Amazon SES" },
    { icon: icons.comments, name: "Conversa livre", desc: "Chat direto com a IA" },
  ];

  tools.forEach((t, i) => {
    const col = i < 6 ? 0 : 1;
    const row = i % 6;
    const x = 0.6 + col * 4.7;
    const y = 1.55 + row * 0.64;

    s5.addImage({ data: t.icon, x, y: y + 0.08, w: 0.3, h: 0.3 });
    s5.addText(t.name, {
      x: x + 0.42, y, w: 1.8, h: 0.45,
      fontSize: 12, fontFace: "Calibri", bold: true, color: C.navy, valign: "middle", margin: 0
    });
    s5.addText(t.desc, {
      x: x + 2.25, y, w: 2.1, h: 0.45,
      fontSize: 11, fontFace: "Calibri", color: C.slate600, valign: "middle", margin: 0
    });
  });

  // Separator line
  s5.addShape(pres.shapes.LINE, {
    x: 5.05, y: 1.55, w: 0, h: 3.85,
    line: { color: C.slate200, width: 1 }
  });

  // ============================================================
  // SLIDE 6 — NÚMEROS / IMPACTO
  // ============================================================
  let s6 = pres.addSlide();
  s6.background = { color: C.navy };

  s6.addText("IMPACTO", {
    x: 0.6, y: 0.4, w: 3, h: 0.35,
    fontSize: 11, fontFace: "Calibri", bold: true,
    color: C.cyan, charSpacing: 3, margin: 0
  });

  s6.addText("Números que importam", {
    x: 0.6, y: 0.8, w: 8.5, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.white, margin: 0
  });

  // Big stat cards
  const stats = [
    { number: "12", label: "tools funcionais", sub: "Todas via linguagem natural" },
    { number: "86k+", label: "talentos buscáveis", sub: "Full-text search instantâneo" },
    { number: "26", label: "melhorias de arquitetura", sub: "Cache, dedup, locks, cron" },
    { number: "5", label: "pontos de aprovação", sub: "Humano sempre no controle" },
  ];

  stats.forEach((st, i) => {
    const x = 0.6 + i * 2.35;
    const y = 1.75;

    s6.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 2.1, h: 2.4,
      fill: { color: C.slate800 }, shadow: makeShadow()
    });
    s6.addText(st.number, {
      x, y: y + 0.3, w: 2.1, h: 0.8,
      fontSize: 42, fontFace: "Calibri", bold: true,
      color: C.cyan, align: "center", margin: 0
    });
    s6.addText(st.label, {
      x, y: y + 1.1, w: 2.1, h: 0.4,
      fontSize: 14, fontFace: "Calibri", bold: true,
      color: C.white, align: "center", margin: 0
    });
    s6.addText(st.sub, {
      x, y: y + 1.55, w: 2.1, h: 0.5,
      fontSize: 11, fontFace: "Calibri",
      color: C.slate400, align: "center", margin: 0
    });
  });

  // Quote
  s6.addText([
    { text: "\"O recrutador decide. O Eli executa.\"", options: { italic: true, color: C.cyan, fontSize: 16 } }
  ], {
    x: 0.6, y: 4.6, w: 8.8, h: 0.5,
    fontFace: "Calibri", align: "center", margin: 0
  });

  // ============================================================
  // SLIDE 7 — PRÓXIMOS PASSOS + ENCERRAMENTO
  // ============================================================
  let s7 = pres.addSlide();
  s7.background = { color: C.white };

  s7.addText("PRÓXIMOS PASSOS", {
    x: 0.6, y: 0.4, w: 3, h: 0.35,
    fontSize: 11, fontFace: "Calibri", bold: true,
    color: C.cyan, charSpacing: 3, margin: 0
  });

  s7.addText("Roadmap e evolução", {
    x: 0.6, y: 0.8, w: 8.5, h: 0.6,
    fontSize: 26, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0
  });

  // Roadmap items
  const roadmap = [
    { phase: "Agora", items: "InTerview (WhatsApp) · Screening automatizado · Dashboard de métricas" },
    { phase: "Curto prazo", items: "Multi-tenant · Onboarding self-service · Integração com calendário real" },
    { phase: "Médio prazo", items: "IA preditiva (fit score) · Automações de nurturing · Marketplace de templates" },
  ];

  roadmap.forEach((r, i) => {
    const y = 1.65 + i * 1.15;

    // Phase badge
    s7.addShape(pres.shapes.RECTANGLE, {
      x: 0.6, y, w: 1.5, h: 0.35,
      fill: { color: i === 0 ? C.cyan : (i === 1 ? C.blue : C.navy) }
    });
    s7.addText(r.phase, {
      x: 0.6, y, w: 1.5, h: 0.35,
      fontSize: 11, fontFace: "Calibri", bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0
    });

    s7.addText(r.items, {
      x: 2.3, y, w: 7, h: 0.35,
      fontSize: 13, fontFace: "Calibri",
      color: C.slate600, valign: "middle", margin: 0
    });

    // Connector line
    if (i < 2) {
      s7.addShape(pres.shapes.LINE, {
        x: 1.35, y: y + 0.35, w: 0, h: 0.8,
        line: { color: C.slate200, width: 2 }
      });
    }
  });

  // CTA box
  s7.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 4.3, w: 8.8, h: 1.0,
    fill: { color: C.navy }
  });
  s7.addImage({ data: icons.rocketW, x: 1.0, y: 4.55, w: 0.45, h: 0.45 });
  s7.addText([
    { text: "Pronto para testar?", options: { bold: true, color: C.white, fontSize: 18 } },
    { text: "\n", options: { breakLine: true } },
    { text: "O Eli já está rodando no tenant demo — agende uma demonstração ao vivo.", options: { color: C.slate400, fontSize: 13 } }
  ], {
    x: 1.7, y: 4.3, w: 7.3, h: 1.0,
    fontFace: "Calibri", valign: "middle", margin: 0
  });

  // ============================================================
  // Save
  // ============================================================
  await pres.writeFile({ fileName: "Eli_Agente_InHire.pptx" });
  console.log("✅ Presentation saved: Eli_Agente_InHire.pptx");
}

buildPresentation().catch(err => { console.error(err); process.exit(1); });
