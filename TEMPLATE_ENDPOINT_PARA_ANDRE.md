# Template — Especificacao de Endpoint para o Agente Eli

> Preencha um bloco desse para cada endpoint. So preciso desses campos pra implementar.

---

## Endpoint: [nome descritivo]

**Rota:** `[METHOD] /path/do/endpoint`

**Descricao:** [o que esse endpoint faz em 1 frase]

### Request

**Headers obrigatorios:** (alem do Authorization: Bearer)
```
[ex: X-Tenant: demo]
```

**Path params:**
| Param | Tipo | Descricao |
|---|---|---|
| `jobId` | string (UUID) | ID da vaga |

**Query params:** (se houver)
| Param | Tipo | Obrigatorio | Descricao |
|---|---|---|---|
| | | | |

**Body:**
```json
{
  "campo1": "tipo — descricao",
  "campo2": "tipo — descricao"
}
```

**Campos obrigatorios:** `campo1`, `campo2`

**Campos opcionais:** `campo3`

### Response

**Status:** `200` / `201` / `204`

**Body:**
```json
{
  "exemplo": "de resposta real"
}
```

### Erros

| Status | Quando | Body (se relevante) |
|---|---|---|
| `400` | [quando retorna 400] | |
| `404` | [quando retorna 404] | |
| `409` | [quando retorna 409] | |
| `422` | [quando retorna 422] | |

### Side effects (se houver)

- [ex: "configurar screening-config dispara triagem nos candidatos existentes?"]
- [ex: "publicar vaga envia notificacao automatica?"]

---

# Endpoints P1 — preencher abaixo

Copie o template acima para cada endpoint.

---

## 1. Formulario de inscricao

**Rota:** `GET /jobs/{jobId}/application-form`

**Descricao:** Retorna a configuracao atual do formulario de inscricao da vaga

### Request
**Path params:** `jobId` (UUID)

### Response
**Status:** `200`
```json
{

}
```

---

**Rota:** `PUT /jobs/{jobId}/application-form`

**Descricao:** Configura os campos e perguntas do formulario de inscricao

### Request
```json
{

}
```

### Response
**Status:**
```json
{

}
```

### Erros
| Status | Quando |
|---|---|
| | |

### Side effects
- Candidatos que ja se inscreveram sao afetados?
- Formulario fica visivel imediatamente na pagina de vagas?

---

## 2. Configurar triagem IA

**Rota:** `POST /jobs/{jobId}/screening-config`

**Descricao:** Configura os criterios que o agente de triagem usa pra pontuar candidatos

### Request
```json
{

}
```

### Response
**Status:**
```json
{

}
```

### Erros
| Status | Quando |
|---|---|
| | |

### Side effects
- Configurar dispara triagem nos candidatos que ja estao na vaga?
- Ou so roda pra candidatos novos?

---

**Rota:** `GET /jobs/{jobId}/screening-config`

**Descricao:** Retorna configuracao atual dos criterios de triagem

### Response
```json
{

}
```

---

## 3. Divulgacao em portais

**Rota:** `GET /jobs/{jobId}/publish/channels`

**Descricao:** Lista canais de divulgacao disponiveis e quais estao conectados

### Response
```json
{

}
```

---

**Rota:** `POST /jobs/{jobId}/publish`

**Descricao:** Publica a vaga nos canais selecionados

### Request
```json
{

}
```

### Response
```json
{

}
```

### Erros
| Status | Quando |
|---|---|
| | |

### Side effects
- Publicar em LinkedIn cria um post ou so lista na pagina?
- Pode despublicar depois? Qual endpoint?

---

## 4. Historico de movimentacao

**Rota:** `GET /job-talents/{jobTalentId}/history`

**Descricao:** Retorna log de todos os eventos de um candidato na vaga (inscricao, mudancas de etapa, rejeicao, contratacao)

### Response
```json
{

}
```

### Observacao
Se esse endpoint nao existir, uma alternativa minima seria adicionar o campo `stageChangedAt` (timestamp da ultima movimentacao) no response de `GET /job-talents/{jobId}/talents`. Isso ja nos permitiria calcular tempo por etapa.

---

## 5. Scorecards (feedback de entrevistadores)

### 5a. Liberar permissao

**Rota:** `GET /scorecards`

**Status atual:** 403 (service account sem permissao)

**Acao necessaria:** Liberar permissao de leitura para o service account (role: Teste ADM Math2)

---

### 5b. Criar scorecard

**Rota:** `POST /scorecards`

**Descricao:** Registra avaliacao de um entrevistador sobre um candidato

### Request
```json
{

}
```

### Response
```json
{

}
```

### Erros
| Status | Quando |
|---|---|
| | |

---

# Notas para o Andre

- **Tenant de teste:** `demo`
- **Service account:** role "Teste ADM Math2"
- **Auth:** Bearer JWT via `POST https://auth.inhire.app/login`
- **Prioridade:** Esses 5 endpoints desbloqueiam os fluxos mais criticos do agente
- **Depois disso:** Temos mais 17 endpoints em P2/P3 listados no `MAPA_COBERTURA_ELI.md`
