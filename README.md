# ObradorIA Agent

Sistema inteligente para geração automática de orçamentos de construção civil utilizando IA/LLM e busca semântica na base SINAPI.

## Funcionalidades

- Extração de informações de orçamento a partir de linguagem natural
- Busca semântica de composições SINAPI via embeddings (pgvector)
- Precificação automática por estado e data de referência
- Streaming de progresso em tempo real (SSE)
- Suporte a múltiplos providers LLM (Ollama, OpenAI, Anthropic)

## Estrutura do Projeto

```
obradoria-agent/
├── main.py                 # Entry point FastAPI
├── requirements.txt        # Dependências
└── app/
    ├── config.py           # Configurações (variáveis de ambiente)
    ├── api/
    │   ├── routes.py       # Endpoints REST
    │   └── schemas.py      # Modelos Pydantic (request/response)
    ├── core/
    │   ├── models.py       # Modelos de domínio
    │   ├── orchestrator.py # Orquestrador de geração de orçamento
    │   ├── extractor.py    # Extração de dados via LLM
    │   ├── prompts.py      # Prompts do sistema
    │   └── validators.py   # Validação e normalização
    ├── llm/
    │   ├── base.py         # Interface abstrata LLM
    │   ├── ollama.py       # Provider Ollama (local)
    │   ├── openai.py       # Provider OpenAI
    │   └── anthropic.py    # Provider Anthropic
    └── services/
        ├── spring_client.py   # Cliente API Spring Boot
        └── vector_search.py   # Busca vetorial (pgvector)
```

## Requisitos

- Python 3.11+
- PostgreSQL com extensão pgvector
- Ollama (ou chave OpenAI/Anthropic)
- API Spring Boot do Obradoria rodando

## Instalação

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuração

Variáveis de ambiente (ou arquivo `.env`):

```env
# API
API_HOST=0.0.0.0
API_PORT=8000

# Banco de dados
DB_HOST=localhost
DB_PORT=5432
DB_NAME=obradoria
DB_USER=postgres
DB_PASSWORD=postgres

# Spring API
SPRING_API_URL=http://localhost:8891/api

# LLM (escolher provider)
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# Opcional: OpenAI ou Anthropic
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

## Execução

```bash
python main.py
```

Acesse a documentação em `http://localhost:8000/docs`.

## Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/health` | Status dos componentes |
| GET | `/api/providers` | LLM providers disponíveis |
| POST | `/api/budget` | Gerar orçamento (resposta completa) |
| POST | `/api/budget/stream` | Gerar orçamento (SSE com progresso) |

## Exemplo de Uso

```bash
curl -X POST http://localhost:8000/api/budget \
  -H "Content-Type: application/json" \
  -d '{"mensagem": "Construir 2 casas residenciais padrão mínimo no Maranhão para janeiro de 2025"}'
```
