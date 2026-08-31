# 🚀 Kelostats - Local Running & Setup Guide

This guide provides step-by-step instructions to set up, configure, run, and test the **Kelostats Multi-Agent Text-to-SQL Backend** on your local machine.

---

## 📋 Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Project Structure](#2-project-structure)
3. [Virtual Environment & Installation](#3-virtual-environment--installation)
4. [Environment Configuration (`.env`)](#4-environment-configuration-env)
5. [Database Initialization](#5-database-initialization)
6. [Starting the Application](#6-starting-the-application)
7. [API Endpoints & Testing](#7-api-endpoints--testing)
8. [Generated Artifacts & Output Locations](#8-generated-artifacts--output-locations)
9. [Troubleshooting & FAQs](#9-troubleshooting--faqs)

---

## 1. Prerequisites

Before running the application, ensure you have the following installed:

* **Python 3.10+** (Recommended: Python 3.11 or 3.12)
* **PostgreSQL / MySQL / Oracle** database instance (local or remote)
* **LLM Provider API Key**:
  * [Groq](https://console.groq.com/) (Default: `llama-3.3-70b-versatile`, `qwen/qwen3.6-27b`, or `openai/gpt-oss-120b`)
  * Or any OpenAI-compatible API endpoint

---

## 2. Project Structure

```text
Kelostats/
├── ARCHITECTURE.md                 # Mermaid architecture workflow diagram
├── LOCAL_RUNNING_GUIDE.md          # Local setup and running documentation
├── backend/
│   ├── .env                        # LLM API keys & DB configuration
│   ├── main.py                     # FastAPI entry point
│   ├── requirements.txt            # Python dependencies
│   ├── init_db.py                  # Metadata database initializer
│   ├── Agents/                     # Autonomous AI Agents
│   │   ├── query_verification_agent.py   # Node 2: Triage & Verification Agent
│   │   ├── retrival_agent.py             # Node 3B: Entity Value Search & Guardrail
│   │   ├── sql_writer_agent.py           # Node 3A: SQL Writer & Guardrail
│   │   ├── sql_repair_agent.py           # Node 4: Self-Healing SQL Repair Agent
│   │   └── prompts/                      # Agent instruction prompt templates
│   ├── databases/                  # Database management & tools
│   │   ├── schema_extraction/      # Node 1: Schema extraction & stats analyzer
│   │   └── tools/                  # DB Execution tools (Postgres, MySQL, Oracle)
│   ├── workflow/
│   │   └── orchestrator.py         # LangGraph state machine & router
│   ├── logs/
│   │   ├── llm_logger.py           # Context-bound LLM interaction & token logger
│   │   └── llm_logs/               # Detailed workflow execution log files
│   └── data/                       # Retrieved tabular JSON rows for PPT generation
└── frontend/                       # (Reserved for Web UI)
```

---

## 3. Virtual Environment & Installation

### Step 1: Clone or Navigate to the Directory
Open your terminal (PowerShell / Command Prompt / Bash):
```bash
cd c:/Kelostats/backend
```

### Step 2: Create & Activate Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Required Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. Environment Configuration (`.env`)

Create or update the `.env` file in the `backend/` directory (`c:\Kelostats\backend\.env`):

```env
# ==========================================
# Application Metadata Database (PostgreSQL)
# ==========================================
DATABASE_URL=postgresql://postgres:password@localhost:5432/kelostats

# ==========================================
# LLM Provider Configuration (Groq / OpenAI)
# ==========================================
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=gsk_your_groq_api_key_here
```

> [!TIP]
> * **Special Characters in Passwords**: If your database password contains special characters like `@`, URL-encode them (e.g. `@` becomes `%40`, so `Pass@12` becomes `Pass%4012`).
> * **LLM Models**: You can change `LLM_MODEL` to any supported model (e.g. `llama-3.3-70b-versatile`, `openai/gpt-oss-120b`, or `qwen/qwen3.6-27b`).
> * **Metadata Database**: The `DATABASE_URL` connects to the metadata database which stores registered user database connection configs in the `user_databases` table.

---

## 5. Database Initialization

To create the metadata table (`user_databases`) where database connection profiles are stored, run:

```bash
python init_db.py
```

Expected output:
```text
[+] Connected to metadata database successfully.
[+] Table 'user_databases' created or verified successfully.
```

---

## 6. Starting the Application

Start the FastAPI server with live reload:

```bash
python main.py
```

*Or via Uvicorn directly:*
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

When started, you will see:
```text
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

Interactive API documentation (Swagger UI) is available at:
👉 **[http://localhost:8000/docs](http://localhost:8000/docs)**

---

## 7. API Endpoints & Testing

### 1. Register / Connect a Target Database
**Endpoint:** `POST /api/databases/connect`

**Request Payload:**
```json
{
  "database_type": "postgres",
  "host": "localhost",
  "port": 5432,
  "username": "postgres",
  "password": "your_password",
  "database_name": "store_db",
  "schema_name": "store",
  "ssl_mode": "prefer"
}
```

**Response:**
```json
{
  "status": "success",
  "database_id": "db_4edfa948-8f02-4508-a3fc-7605da52caf1",
  "message": "Database connected and registered successfully."
}
```

---

### 2. Run Multi-Agent Text-to-SQL Workflow
**Endpoint:** `POST /api/workflow/query`

> [!NOTE]
> When you invoke `/api/workflow/query`, **Node 1 (Schema Extraction)** automatically fetches the registered database schema, formats it with statistics, and caches it to `databases/schema_extraction/output/{db_id}.txt` before running the verification and SQL agents.

**Request Payload:**
```json
{
  "user_query": "show top 3 sales by city",
  "database_id": "db_4edfa948-8f02-4508-a3fc-7605da52caf1"
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:8000/api/workflow/query" \
     -H "Content-Type: application/json" \
     -d '{
       "user_query": "show top 3 sales by city",
       "database_id": "db_4edfa948-8f02-4508-a3fc-7605da52caf1"
     }'
```

**Sample Response:**
```json
{
  "status": "SUCCESS_SQL_GENERATED",
  "user_query": "show top 3 sales by city",
  "database_id": "db_4edfa948-8f02-4508-a3fc-7605da52caf1",
  "final_output": "SELECT city, SUM(sales) AS total_sales\nFROM store.global_superstore\nGROUP BY city\nORDER BY total_sales DESC\nLIMIT 3;",
  "verification_status": "SCHEMA_MATCH"
}
```

---

## 8. Generated Artifacts & Output Locations

Every API request produces structured outputs:

| Output Type | File Location | Purpose |
| :--- | :--- | :--- |
| **Schema Text Cache** | `backend/databases/schema_extraction/output/{db_id}.txt` | Compact schema with column statistics and sample categories for LLM context. |
| **Tabular Data JSON** | `backend/data/{timestamp}.json` | Clean `{ "columns": [...], "rows": [...] }` tabular dataset saved from master SQL execution for PPT slide generation. |
| **LLM Interaction Logs** | `backend/logs/llm_logs/workflow Log {timestamp}.txt` | Full log of every agent's input prompt, output response, individual token counts, and cumulative **TOTAL TOKENS** summary. |

---

## 9. Troubleshooting & FAQs

### Q: `LLM API Error (429): Rate limit exceeded`
* **Reason:** Free-tier Groq accounts have an 8,000 Tokens-Per-Minute (TPM) limit on larger models.
* **Fix:** Use `llama-3.3-70b-versatile` (70,000 TPM limit) or allow a few seconds between heavy back-to-back queries.

### Q: `Query Verification Failed: Unrelated`
* **Reason:** The question asks for data not present in the target database schema.
* **Fix:** Check `databases/schema_extraction/output/{db_id}.txt` to inspect available tables and columns.

### Q: `the {word} not found in your database`
* **Reason:** Entity retrieval search executed cleanly, but the requested category/item does not exist in the database table.
* **Fix:** Verify the spelling or try querying broader terms.

### Q: Database Connection Failed
* Ensure your target database is running and credentials (`host`, `port`, `user`, `password`, `database_name`) are accurate in the connection request.
