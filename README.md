# EBANX Bank API

API simples de contas bancárias para o case técnico EBANX. Endpoints: `POST /reset`, `GET /balance`, `POST /event` (deposit, withdraw, transfer).

## Pré-requisitos

- Python 3.11+
- [ngrok](https://ngrok.com/) (para expor a API à suíte automatizada)

## Como rodar localmente

```bash
cd e-bank-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 3000
```

A API fica em `http://localhost:3000`.

## Testes

```bash
source .venv/bin/activate
pytest -v
```

Os testes validam o estado real em memória (sem mock da lógica de negócio).

## Publicar com ngrok

Com o servidor rodando na porta 3000:

```bash
ngrok http 3000
```

Use a URL HTTPS do campo **Forwarding** (ex: `https://xxxx.ngrok-free.app`) na suíte de testes da EBANX. Após o green light, envie o código-fonte.

## Estrutura do projeto

| Arquivo | Responsabilidade |
|---------|------------------|
| `app/store.py` | Persistência em memória (`dict` account_id → saldo) |
| `app/services.py` | Regras de negócio (depósito, saque, transferência, reset) |
| `app/main.py` | Rotas HTTP (camada fina) |
| `app/schemas.py` | Validação do payload com Pydantic |
| `app/errors.py` | Exceções de domínio |

## Decisões técnicas

- **Dependências (`requirements.txt`)**: neste take-home usei `requirements.txt` em vez de Poetry para manter o setup mínimo (`pip install -r requirements.txt`) e alinhar com a simplicidade pedida no case. Em um projeto maior ou de time, faria sentido Poetry (ou `uv`) com `poetry.lock` para versões reproduzíveis e separação clara de dependências de dev/prod.
- **FastAPI** apenas na borda HTTP; a lógica fica em `AccountService`.
- **Store em memória**: suficiente para o desafio; trocar persistência = alterar só `store.py`.
- **GET /balance** só lê o store, sem efeitos colaterais.
- **Transferência atômica**: valida saldo da origem, calcula novos saldos e aplica origem e destino no mesmo método.
- **Erros**: conta inexistente → `404` com body `0`; saldo insuficiente → `400` com body `0` (ajuste de status isolado em `main.py` se a suíte exigir outro código).
- **IDs de conta** são strings (`"100"`), como na especificação.

## Como estender na entrevista

- Nova regra de negócio → `app/services.py`
- Novo tipo de evento → `app/schemas.py` + branch em `app/main.py`
- Banco de dados → implementar a mesma interface de `InMemoryStore` em `app/store.py`
- Mudar formato de resposta ou status HTTP → `app/main.py`

## Endpoints (resumo)

### POST /reset

Limpa todas as contas. Resposta: `200`.

### GET /balance?account_id={id}

- Conta existe: `200`, body texto com o saldo (ex: `20`)
- Conta não existe: `404`, body `0`

### POST /event

**Deposit**

```json
{"type": "deposit", "destination": "100", "amount": 10}
```

Resposta `201`: `{"destination": {"id": "100", "balance": 10}}`

**Withdraw**

```json
{"type": "withdraw", "origin": "100", "amount": 5}
```

Resposta `201`: `{"origin": {"id": "100", "balance": 15}}`  
Conta inexistente: `404`, body `0`  
Saldo insuficiente: `400`, body `0`

**Transfer**

```json
{"type": "transfer", "origin": "100", "amount": 15, "destination": "300"}
```

Resposta `201`: `{"origin": {...}, "destination": {...}}`  
Origem inexistente: `404`, body `0`  
Saldo insuficiente: `400`, body `0`
