# Agente SDR - Sistema de Qualificação de Leads

Sistema de SDR automatizado usando IA para qualificação de leads via WhatsApp.
Conversão do workflow n8n para Python com FastAPI.

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Server                         │
├─────────────────────────────────────────────────────────────┤
│  POST /webhook/captura   → Captura de leads (formulário)   │
│  POST /webhook/whatsapp  → Mensagens do WhatsApp           │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   Message Processor                         │
│  • Filtro fromMe  • Bloqueio  • Debounce  • Transcrição    │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│               AI Agents (LangChain / Agno)                  │
│  • WelcomeAgent: Boas-vindas                               │
│  • SDRAgent: SPIN Selling + Memória Redis                  │
└─────────────────────────────────────────────────────────────┘
```

## Instalação

```bash
# Clone o projeto
cd agente_sdr

# Crie ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
.\venv\Scripts\activate  # Windows

# Instale dependências
pip install -r requirements.txt

# Configure variáveis de ambiente
cp .env.example .env
# Edite .env com suas credenciais
```

## Configuração

### 1. OpenAI
- Obtenha API Key em https://platform.openai.com
- Configure `OPENAI_API_KEY` no `.env`

### 2. Redis
- Instale Redis localmente ou use serviço cloud
- Configure `REDIS_URL` no `.env`

### 3. Evolution API (WhatsApp)
- Configure sua instância Evolution API
- Configure `EVOLUTION_API_URL`, `EVOLUTION_API_KEY` e `EVOLUTION_INSTANCE`

### 4. Google Sheets
- Crie credenciais de Service Account
- Salve como `credentials.json`
- Compartilhe a planilha com o email da Service Account
- Configure `GOOGLE_SHEETS_DOCUMENT_ID`

## Execução

```bash
# Desenvolvimento
python main.py

# ou com uvicorn diretamente
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints

### Webhooks
- `POST /webhook/captura` - Recebe leads do formulário
- `POST /webhook/whatsapp` - Recebe mensagens WhatsApp

### Admin
- `POST /admin/block/{sender}` - Bloqueia chat (intervenção humana)
- `POST /admin/unblock/{sender}` - Desbloqueia chat
- `GET /admin/lead/{sender}` - Estado do lead
- `GET /admin/summary/{sender}` - Resumo da conversação

## Comparativo: LangChain vs Agno

Configure `AGENT_FRAMEWORK=langchain` ou `AGENT_FRAMEWORK=agno` no `.env`

| Aspecto | LangChain | Agno |
|---------|-----------|------|
| **Maturidade** | Mais maduro, comunidade maior | Mais novo, em crescimento |
| **Complexidade** | Mais abstrações, curva de aprendizado | Mais simples e direto |
| **Performance** | Overhead maior | Mais leve |
| **Memória** | RedisChatMessageHistory | Memory com RedisDb |
| **Documentação** | Extensa | Boa mas menos exemplos |
| **Integração** | Muitos conectores | Focado em simplicidade |

### Recomendação

- **LangChain**: Projetos complexos, múltiplos agentes, workflows elaborados
- **Agno**: Projetos simples/médios, quando performance é prioridade

## Estrutura de Arquivos

```
agente_sdr/
├── main.py                    # FastAPI app
├── config.py                  # Configurações
├── requirements.txt
├── .env.example
│
├── agents/
│   ├── langchain/
│   │   ├── welcome_agent.py   # Boas-vindas
│   │   └── sdr_agent.py       # SDR com SPIN
│   └── agno/
│       ├── welcome_agent.py
│       └── sdr_agent.py
│
├── services/
│   ├── redis_service.py       # Cache, bloqueio, memória
│   ├── sheets_service.py      # Google Sheets
│   ├── whatsapp_service.py    # Evolution API
│   ├── openai_service.py      # Transcrição
│   └── message_processor.py   # Processamento
│
├── models/
│   ├── lead.py
│   └── message.py
│
├── prompts/
│   ├── welcome_prompt.py
│   └── sdr_prompt.py
│
└── utils/
    └── message_splitter.py
```

## Fluxo de Mensagens

### 1. Captura de Lead
```
Formulário → /webhook/captura → Google Sheets → AI (boas-vindas) → WhatsApp
```

### 2. Conversa SDR
```
WhatsApp → /webhook/whatsapp → Filtros → Debounce → AI (SPIN) → WhatsApp
```

## SPIN Selling

O agente segue a metodologia SPIN:

1. **Situação**: Entender contexto e ferramentas atuais
2. **Problema**: Identificar dores e dificuldades
3. **Implicação**: Amplificar impacto do problema
4. **Necessidade**: Direcionar para solução/vendedor

## Tags de Controle

O agente pode adicionar tags especiais na resposta:

- `[QUALIFICADO]` - Lead qualificado, pronto para vendedor
- `[NAO_QUALIFICADO]` - Lead não tem fit
- `[FOLLOW_UP_24H]` - Agendar follow-up
- `[TRANSFERIR_VENDEDOR]` - Iniciar transferência
- `[ENVIAR_AUDIO]` - Responder com áudio

## Licença

MIT
