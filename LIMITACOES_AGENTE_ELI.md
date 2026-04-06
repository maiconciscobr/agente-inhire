# Agente Eli — Mapa completo de limitações

> Comparação entre tudo que o InHire oferece vs o que o Agente Eli cobre hoje.
> Baseado na pesquisa do Help Center do InHire (abril/2026).

---

## 1. Criação e configuração de vagas

### O que o Eli FAZ
- Extrai dados do briefing (cargo, salário, modelo, requisitos, senioridade)
- Gera job description completa
- Cria a vaga no InHire via API (`POST /jobs`)

### O que o Eli NÃO preenche na criação
| Campo/Config | Por que não faz | Solução |
|---|---|---|
| **Campos personalizados** (custom fields por empresa) | API não expõe quais custom fields existem | Precisaria de `GET /custom-fields` ou similar |
| **Scorecard da vaga** (critérios de avaliação por entrevista) | API sem endpoint para criar scorecard | Recrutador configura no InHire |
| **Pipeline customizado** (etapas diferentes do padrão) | Eli usa o pipeline padrão; não configura etapas | Recrutador ajusta no InHire se necessário |
| **Formulário de inscrição** (perguntas personalizadas, campos obrigatórios) | Sem endpoint para configurar formulário | Recrutador configura no InHire |
| **Critérios de triagem IA** (Essencial/Importante/Diferencial + faixa salarial) | Sem endpoint para configurar agente de triagem | Recrutador configura no InHire |
| **Fluxo de aprovação de requisição** (lista de aprovadores internos) | Eli cria vaga direto, não cria requisição com aprovação | Poderia ser implementado se API tiver endpoint |
| **Múltiplas posições com motivos diferentes** | Eli cria posições com motivo genérico "expansion" | Poderia pedir ao recrutador o motivo de cada posição |
| **SLA / prazo da vaga** | Campo não é preenchido na criação | Poderia extrair do briefing se mencionado |
| **Gestor técnico / hiring manager** | Extraído mas não enviado na API | API pode não ter campo para isso |
| **Tags / labels da vaga** | Não implementado | Verificar se API aceita |

---

## 2. Divulgação de vagas

### O que o Eli NÃO faz (nada desta área)
| Funcionalidade | Descrição |
|---|---|
| **Publicar em portais** | LinkedIn, Indeed, Netvagas, Glassdoor — configurável no InHire |
| **Integração com job boards** | Pacote de job boards integrado |
| **Configurar visibilidade** | Pública, restrita, interna |
| **Página de vagas (careers page)** | EMPRESA.inhire.app/vagas — personalização visual |
| **Link de compartilhamento** | Gerar links específicos por canal |
| **Programa de indicação** | Links gamificados, dashboard de indicações, gestão de colaboradores que indicam |

**Motivo:** Sem endpoints de API para divulgação. O Eli apenas orienta o recrutador com passo a passo.

---

## 3. Comunicação com candidatos

### O que o Eli NÃO faz (nada desta área)
| Funcionalidade | Descrição |
|---|---|
| **Enviar emails aos candidatos** | Templates, agendamento, personalização — requer conectar email do recrutador |
| **Templates de email** | Abordagem, rejeição, engajamento, formulário personalizado |
| **WhatsApp / InTerview** | Entrevista e comunicação via WhatsApp dentro do InHire |
| **Devolutiva direta ao candidato** | O Eli gera o texto mas não envia ao candidato |

**Motivo:** 
- Email: requer integração Google/Outlook do usuário, não da service account
- WhatsApp: InTerview sem API pública
- O Eli gera devolutivas mas a entrega ao candidato é manual

---

## 4. Testes e avaliações

### O que o Eli NÃO faz (nada desta área)
| Funcionalidade | Descrição |
|---|---|
| **Teste DISC** | Avaliação comportamental — envio automático, análise de perfil |
| **Testes Mindsight** | Testes de personalidade e competências — envio, análise, resultados |
| **Testes personalizados** | Testes técnicos customizados pela empresa |
| **Automação de envio de testes** | InHire envia automaticamente quando candidato chega em determinada etapa |

**Motivo:** Sem endpoints de API para gerenciar testes. Os testes são um módulo separado do InHire.

---

## 5. Entrevistas

### O que o Eli NÃO faz
| Funcionalidade | Descrição | Bloqueio |
|---|---|---|
| **Agendar entrevista** | Criar appointment com link de videochamada | API retorna 403 (Gap 1) |
| **Interview Kit** | Roteiro de perguntas + scorecard por entrevista | Sem endpoint |
| **Extensão Google Meet** | Preencher scorecard durante a call | Extensão Chrome, não API |
| **Permissionamento de avaliadores** | Controlar quem vê o que no kit | Sem endpoint |
| **Scorecard / avaliação pós-entrevista** | Registrar nota e feedback por critério | `GET /scorecards` retorna 403 |

---

## 6. Carta oferta

### O que o Eli NÃO faz
| Funcionalidade | Descrição | Bloqueio |
|---|---|---|
| **Criar e enviar carta oferta** | Template + variáveis + aprovação + envio | API retorna 403 (Gap 2) |
| **Fluxo de aprovação de oferta** | Aprovador interno antes de enviar ao candidato | API retorna 403 |
| **Desativar aprovação** | Enviar direto sem aprovador | API retorna 403 |
| **Templates de oferta** | Listar e usar templates configurados | API retorna 403 |

**Código já está implementado** — só precisa da API liberada no tenant.

---

## 7. Banco de talentos

### O que o Eli NÃO faz
| Funcionalidade | Descrição | Bloqueio |
|---|---|---|
| **Busca full-text** | Buscar por nome, email, skills, cargo | Sem endpoint de busca (Gap 3) |
| **Filtros avançados** | Cruzar informações (fonte, processo, etapa) | Sem endpoint |
| **Reaproveitar candidatos** | Mover talento do banco para nova vaga | Parcial — `POST /job-talents/{jobId}/talents` funciona se tiver o ID |

---

## 8. Analytics e relatórios

### O que o Eli faz parcialmente
- Relatório de status da vaga (SLA, dias aberta, candidatos por etapa)

### O que o Eli NÃO faz
| Funcionalidade | Descrição |
|---|---|
| **Analytics end-to-end** | Dashboard completo do InHire (funil, conversão, tempo por etapa) |
| **Relatórios customizados** | Exportação de dados específicos |
| **Dashboard de indicações** | Métricas do programa de referral |
| **Dashboard de diversidade** | Métricas de inclusão e acessibilidade |

**Motivo:** Sem endpoints de API para relatórios. O Eli calcula métricas básicas a partir dos dados que tem.

---

## 9. Diversidade e inclusão

### O que o Eli NÃO faz (nada desta área)
| Funcionalidade | Descrição |
|---|---|
| **Módulo de diversidade** | Vagas afirmativas, dados sensíveis, LGPD |
| **Acessibilidade** | Leitor de tela, alto contraste, Libras nos testes |

---

## 10. Smart CV

### O que o Eli NÃO faz
| Funcionalidade | Descrição |
|---|---|
| **Gerar Smart CV** | CV padronizado e editável a partir do perfil do talento |
| **Compartilhar com gestores** | Link público ou PDF para hiring manager |
| **Ocultar campos sensíveis** | Remover info antes de compartilhar (reduzir viés) |

---

## 11. Extensões Chrome

### O que o Eli NÃO faz
| Funcionalidade | Descrição |
|---|---|
| **Extensão de Hunting** | Capturar perfis do LinkedIn direto pro InHire |
| **Extensão Interview Kit** | Preencher scorecard durante Google Meet |

**Nota:** O Eli já tem endpoint `POST /extension/analyze` para análise de perfil via extensão Chrome, mas a extensão de hunting do InHire é separada.

---

## Resumo por prioridade

### Resolvível com APIs que existem (só precisam ser liberadas)
1. **Agendamento de entrevista** — endpoint existe, 403
2. **Carta oferta** — endpoint existe, 403
3. **Scorecards** — endpoint existe, 403

### Precisa de novos endpoints
4. **Busca no banco de talentos** — busca full-text
5. **Configurar formulário de inscrição** — campos e perguntas
6. **Configurar triagem IA** — critérios Essencial/Importante/Diferencial
7. **Configurar scorecard da vaga** — critérios de avaliação
8. **Custom fields** — listar campos personalizados da empresa
9. **Relatórios/analytics** — métricas de funil e conversão

### Precisa de integração externa
10. **Envio de email ao candidato** — precisa da conta do recrutador (Google/Outlook)
11. **WhatsApp / InTerview** — sem API pública
12. **Testes DISC / Mindsight** — módulo separado sem API

### Fora do escopo do agente (features visuais/UI)
13. Página de vagas (careers page)
14. Extensões Chrome (hunting, interview kit)
15. Dashboard visual de analytics
16. Módulo de diversidade
17. Smart CV (edição visual)
18. Programa de indicação (gamificação, dashboard)
