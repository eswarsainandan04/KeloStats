# 📊 KeloStats — Enterprise Multi-Agent AI Analytics & Presentation Engine

<div align="center">

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14.0+-black.svg?style=flat&logo=next.js&logoColor=white)](https://nextjs.org/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-blueviolet.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Supabase](https://img.shields.io/badge/Supabase-Auth%20%26%20S3-3ECF8E.svg?style=flat&logo=supabase&logoColor=white)](https://supabase.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg?style=flat)]()

**Transforming natural language queries into verified SQL, real-time data visualizations, conversational analytics, and dynamic boardroom-grade 16:9 slide decks.**

</div>

---

## 🎯 1. Project Agenda & Problem Solving

### The Problem
In modern enterprises, data is trapped in relational databases (PostgreSQL, MySQL, Oracle) and unstructured documents. Extracting insights requires technical SQL expertise, while communicating those findings to executives demands hours of manual slide building in PowerPoint. 

Common bottlenecks include:
- **SQL Complexity & Hallucination:** Standard LLMs frequently hallucinate column names, misunderstand dialect nuances, or fail on specific categorical filters.
- **Data-to-Presentation Disconnect:** Manually copying data tables, crafting charts, and formatting corporate presentations is tedious and error-prone.
- **Lack of Verification & Safety:** Direct Text-to-SQL without strict read-only guardrails poses database corruption risks.

### The Agenda & Solution
**KeloStats** is an autonomous, multi-agent AI system orchestrated with **LangGraph** that bridges the gap between raw enterprise data and executive storytelling:

1. **Self-Healing Text-to-SQL:** Automatically extracts database schemas, resolves ambiguous entities via targeted retrieval, writes dialect-compliant queries, and self-repairs failed SQL up to 3 iterative cycles.
2. **Strict Guardrails:** Enforces read-only database execution to guarantee enterprise database integrity.
3. **Decoupled Planner-Compiler Presentation Engine:** Translates raw database records and document insights into spatial slide layout plans (1920×1080 canvas), compiling them into pure 16:9 vector SVG slides stored in Supabase S3 / local storage.
4. **Context-Aware Slide Adaptation:** Intelligently inherits visual themes from previous slides for blank canvases (Case 1) or refines active components on content slides (Case 2).
5. **Hybrid Document & Knowledge RAG:** Combines pgvector semantic search (powered by Gemini embeddings) and BM25 hybrid ranking over unstructured documents with structured relational database analytics.

---

## 📸 2. Screenshots Showcase

<table width="100%">
  <tr>
    <td width="50%" align="center" valign="top">
      <h4>1. Database Integration & Management</h4>
      <img src="screenshots/database.png" alt="Database Management" width="460" />
      <p><i>Connect PostgreSQL, MySQL, and Oracle instances with real-time schema extraction and telemetry.</i></p>
    </td>
    <td width="50%" align="center" valign="top">
      <h4>2. Multi-Source Database Selector</h4>
      <img src="screenshots/select_databases.png" alt="Select Database" width="460" />
      <p><i>Easily switch between connected databases to contextualize queries and presentations.</i></p>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center" valign="top">
      <h4>3. Boardroom Presentation Templates</h4>
      <img src="screenshots/templates.png" alt="Presentation Templates" width="460" />
      <p><i>Curated 16:9 executive templates ready to be populated with live analytical data.</i></p>
    </td>
    <td width="50%" align="center" valign="top">
      <h4>4. Conversational AI Copilot</h4>
      <img src="screenshots/copilot.png" alt="AI Copilot" width="460" />
      <p><i>Interact in natural language to query metrics, request slide redesigns, and get instant answers.</i></p>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center" valign="top">
      <h4>5. Dynamic 16:9 Slide Canvas & Editor</h4>
      <img src="screenshots/editor.png" alt="Slide Editor" width="720" />
      <p><i>Real-time editable canvas rendering responsive 16:9 vector SVG visualizations and typography.</i></p>
    </td>
  </tr>
</table>

---

## 🏛️ 3. Architecture

KeloStats operates on a stateful, multi-agent orchestration architecture powered by **LangGraph**. The workflow decouples query classification, schema verification, entity retrieval, SQL generation, self-healing repair, conversational synthesis, and spatial presentation compilation.

### End-to-End Multi-Agent Workflow Diagram

```mermaid
flowchart TD
    %% Styling Classes
    classDef startNode fill:#1E293B,stroke:#38BDF8,stroke-width:2px,color:#F8FAFC;
    classDef agentNode fill:#0F172A,stroke:#6366F1,stroke-width:2px,color:#F8FAFC;
    classDef decisionNode fill:#312E81,stroke:#A855F7,stroke-width:2px,color:#F8FAFC;
    classDef toolNode fill:#14532D,stroke:#22C55E,stroke-width:2px,color:#F8FAFC;
    classDef guardNode fill:#701A75,stroke:#EC4899,stroke-width:2px,color:#F8FAFC;
    classDef repairNode fill:#B45309,stroke:#F59E0B,stroke-width:2px,color:#F8FAFC;
    classDef errorNode fill:#7F1D1D,stroke:#EF4444,stroke-width:2px,color:#F8FAFC;
    classDef storageNode fill:#1E3A8A,stroke:#3B82F6,stroke-width:2px,color:#F8FAFC;
    classDef endNode fill:#064E3B,stroke:#10B981,stroke-width:2px,color:#F8FAFC;

    %% Entry & Ingestion Layer
    API["🚀 <b>POST /api/workflow/query</b><br>User Query + DB ID / Collection ID + Project ID + Slide Num"]:::startNode --> LOGGER_INIT["📝 <b>Initialize LLM Logger Session</b><br>start_workflow_logger()"]:::storageNode
    LOGGER_INIT --> SAVE_USER_MSG["💬 <b>Save User Message Node</b><br>Persists query to public.chat_messages (role: 'User')"]:::storageNode
    SAVE_USER_MSG --> NODE_REFORM

    %% Layer 0: Conversational Memory & Preprocessing
    subgraph S0_PRE["Layer 0: Conversational Memory & Preprocessing"]
        NODE_REFORM["🔄 <b>Node 0: Query Reformulate Agent</b><br>Detects ambiguous pronouns ('it', 'that', 'this')<br>Reconstructs standalone query from chat history"]:::agentNode
    end

    NODE_REFORM --> NODE_0A

    %% Layer 0A: Intent Classification
    subgraph S0A["Layer 0A: Intent Classification"]
        NODE_0A["🎯 <b>Node 0A: Query Classification Agent</b><br>Classifies intent: greet | out_of_scope | in_scope"]:::agentNode
        DECIDE_INTENT{"Intent?"}:::decisionNode
        NODE_0A --> DECIDE_INTENT
    end

    DECIDE_INTENT -->|greet| GREET_HANDLER["👋 <b>Handle Greet Node</b><br>Dynamic welcoming greeting via LLM"]:::agentNode
    DECIDE_INTENT -->|out_of_scope| OOS_HANDLER["🛑 <b>Handle Out-of-Scope Node</b><br>Explains domain & enterprise data boundaries"]:::errorNode
    DECIDE_INTENT -->|in_scope| NODE_0B

    GREET_HANDLER --> SAVE_AI_MSG
    OOS_HANDLER --> SAVE_AI_MSG

    %% Layer 0B: Task Decision & Source Routing
    subgraph S0B["Layer 0B: Task & Source Decision Routing"]
        NODE_0B["🧠 <b>Node 0B: Query Decision Agent</b><br>Determines: decision ('normal_qa' vs 'agent')<br>source ('database' vs 'documents')<br>Flags: sql_required | rag_required"]:::agentNode
        DECIDE_ROUTER{"Routing Path?"}:::decisionNode
        NODE_0B --> DECIDE_ROUTER
    end

    %% Routing Branches from Node 0B
    DECIDE_ROUTER -->|"source == 'documents' & normal_qa"| NODE_KNOW_QA
    DECIDE_ROUTER -->|"source == 'documents' & agent"| NODE_PLAN
    DECIDE_ROUTER -->|"source == 'database' & sql_required=True"| NODE1
    DECIDE_ROUTER -->|"agent & sql_required=False (Direct Slide Edit)"| NODE_PLAN

    %% Layer RAG: Unstructured Knowledge / Document Pipeline
    subgraph S_RAG["Layer RAG: Unstructured Document Intelligence (pgvector)"]
        NODE_KNOW_QA["📚 <b>Knowledge Answer Node</b><br>1. generate_query_embeddings()<br>2. hybrid_search() on pgvector chunks<br>3. KnowledgeAnswerAgent synthesizes direct factual answer"]:::agentNode
    end

    NODE_KNOW_QA --> SAVE_AI_MSG

    %% Layer 1 & 2: Structured SQL Pipeline - Schema Context & Verification
    subgraph S1_2["Layers 1 & 2: Schema Context & Verification"]
        NODE1["🔍 <b>Node 1: Schema Input Node</b><br>Extracts cached schema JSON from<br>databases/schema_extraction/output/{db_id}.json"]:::agentNode
        NODE1 --> SCHEMA_FORMAT["📄 <b>Format Schema for LLM</b><br>Tables, columns, types, sample values, min/max statistics"]:::storageNode
        SCHEMA_FORMAT --> NODE2["🛡️ <b>Node 2: Verification Agent</b><br>Validates query feasibility against schema context"]:::agentNode
        
        DECIDE_VERIFY{"Verification Decision?"}:::decisionNode
        NODE2 --> DECIDE_VERIFY
    end

    DECIDE_VERIFY -->|SCHEMA_MATCH| NODE3A
    DECIDE_VERIFY -->|RETRIEVAL_REQUIRED| NODE3B

    %% Layer 3B: Entity Value Retrieval & Search
    subgraph S3B["Layer 3B: Entity Value Retrieval & Guardrail"]
        NODE3B["🔎 <b>Node 3B: Retrieval Agent</b><br>Extracts entity keywords & generates search SQL (ILIKE / LIKE)"]:::agentNode
        
        NODE3B --> GUARDRAIL_RETRIEVE{"🛡️ <b>Retrieval Guardrail</b><br>Blocks mutating keywords (DROP, DELETE, etc.)"}:::guardNode
        GUARDRAIL_RETRIEVE -->|Passed| DB_TOOL_SEARCH["⚡ <b>Execute Search Query on Target DB</b><br>PostgreSQL / MySQL / Oracle"]:::toolNode
        
        DB_TOOL_SEARCH --> CHECK_RETRIEVAL_OUT{"Execution Result?"}:::decisionNode
        CHECK_RETRIEVAL_OUT -->|Database Error| RETRIEVAL_ERR_STATE["⚠️ Status: <b>RETRIEVAL_REPAIR_REQUIRED</b>"]:::errorNode
        CHECK_RETRIEVAL_OUT -->|0 Rows Returned| NOT_FOUND_NODE["⚠️ <b>Status: NOT_FOUND</b><br>'the {word} not found in your database'"]:::errorNode
        CHECK_RETRIEVAL_OUT -->|>0 Rows Returned| MD_TABLE["📊 <b>Format Markdown Table</b><br>Exact values found for SQL WHERE clause"]:::storageNode
    end

    NOT_FOUND_NODE --> SAVE_AI_MSG
    MD_TABLE --> NODE3A
    RETRIEVAL_ERR_STATE --> NODE4

    %% Layer 3A: Master SQL Writer Agent & Execution
    subgraph S3A["Layer 3A: Master SQL Generation & Execution"]
        NODE3A["✍️ <b>Node 3A: SQL Writer Node</b><br>Generates dialect-aware analytical SQL<br>using schema + retrieved entity table"]:::agentNode
        
        NODE3A --> GUARDRAIL_WRITER{"🛡️ <b>SQL Writer Guardrail</b><br>Enforces SELECT-only; blocks mutations"}:::guardNode
        GUARDRAIL_WRITER -->|Passed| DB_EXEC["⚡ <b>Execute Master SQL on Target DB</b><br>PostgreSQL / MySQL / Oracle"]:::toolNode
        
        DB_EXEC --> CHECK_WRITER_OUT{"Execution Result?"}:::decisionNode
        CHECK_WRITER_OUT -->|Execution Error| WRITER_ERR_STATE["⚠️ Status: <b>REPAIR_REQUIRED</b>"]:::errorNode
        CHECK_WRITER_OUT -->|Execution Succeeded| SAVE_DATA[("💾 <b>Save Query Data Payload</b><br>backend/data/{timestamp}.json<br>columns, rows, data types")]:::storageNode
    end

    WRITER_ERR_STATE --> NODE4

    %% Layer 4: Centralized Self-Healing SQL Repair
    subgraph S4_REPAIR["Layer 4: Centralized Self-Healing SQL Repair"]
        NODE4["🛠️ <b>Node 4: SQL Repair Node</b><br>SQLRepairAgent: Error + Schema + DB Dialect<br>Performs up to 3 iterative repair attempts"]:::repairNode
        
        NODE4 --> ROUTE_AFTER_REPAIR{"Source of Repair?"}:::decisionNode
        
        ROUTE_AFTER_REPAIR -->|Retrieval Search Query| RE_EXEC_RETRIEVAL["⚡ <b>Re-execute Search Query</b>"]:::toolNode
        RE_EXEC_RETRIEVAL --> CHECK_REPAIRED_ROWS{"Rows Found?"}:::decisionNode
        CHECK_REPAIRED_ROWS -->|0 Rows| NOT_FOUND_NODE
        CHECK_REPAIRED_ROWS -->|>0 Rows| MD_TABLE
        
        ROUTE_AFTER_REPAIR -->|Master Analytical SQL| RE_EXEC_MASTER["⚡ <b>Re-execute Master SQL & Save Data</b><br>Writes to backend/data/{timestamp}.json"]:::toolNode
        RE_EXEC_MASTER --> DECIDE_DOWNSTREAM
    end

    SAVE_DATA --> DECIDE_DOWNSTREAM{"Downstream Task?"}:::decisionNode

    %% Downstream Routing
    DECIDE_DOWNSTREAM -->|decision == 'normal_qa'| NODE5
    DECIDE_DOWNSTREAM -->|decision == 'agent'| NODE_PLAN

    %% Layer 5: Conversational QA Synthesis
    subgraph S5_QA["Layer 5: Conversational QA Synthesis"]
        NODE5["💬 <b>Node 5: Answer Generator Node</b><br>Synthesizes direct conversational answer & metrics<br>grounded strictly in executed SQL data"]:::agentNode
    end
    NODE5 --> SAVE_AI_MSG

    %% Layer 6: Dynamic Presentation Engine (Unified Planner-Compiler)
    subgraph S6_PPT["Layer 6: Dynamic Presentation Engine (Unified Planner-Compiler)"]
        NODE_PLAN["📐 <b>Unified Slide Planning Node</b><br><b>SlidePlanningAgent:</b><br>1. Resolves template SVG via GetSVGCode & is_empty_slide<br>2. Sets slide_type ('current' | 'previous') & slide_info<br>3. Evaluates source:<br>   • 'database': Ingests raw SQL retrieved_data<br>   • 'documents': Generates embeddings & hybrid_search<br>4. Calculates non-overlapping 1920x1080 bounding boxes"]:::agentNode
        
        CHECK_PLAN_FALLBACK{"Fallback Detected?"}:::decisionNode
        NODE_PLAN --> CHECK_PLAN_FALLBACK
        CHECK_PLAN_FALLBACK -->|Yes: Info not found in docs| SAVE_AI_MSG
        CHECK_PLAN_FALLBACK -->|No: Valid slide plan| NODE_GEN["🎨 <b>Node 6: PPT Generation Node</b><br><b>PPTGenerationAgent:</b><br>1. Receives slide_plan + template_svg + slide_type + slide_info<br>2. Compiles layout into pure 16:9 vector SVG<br>3. Saves SVG directly to workspace storage via manifest.json<br>4. Returns friendly confirmation message"]:::agentNode
    end

    NODE_GEN --> SAVE_AI_MSG

    %% Layer 7: Persistence & Observability
    subgraph S_FINAL["Layer 7: Response Persistence & Observability"]
        SAVE_AI_MSG["💾 <b>Save AI Response Node</b><br>Persists Copilot answer / confirmation to<br>public.chat_messages (role: 'AI')"]:::storageNode
        
        SAVE_AI_MSG --> WORKFLOW_END["🏁 <b>LangGraph Final State (END)</b>"]:::endNode
        WORKFLOW_END --> FINALIZE_LOG[("📜 <b>Save Final LLM Log Session</b><br>logs/llm_logs/workflow Log {timestamp}.txt<br>prompts, completions & token telemetry")]:::storageNode
    end
```

### Architectural Highlights
- **Layer 0 (Conversational Memory & Reformulation):** `QueryReformulateAgent` scans the input for ambiguous referential pronouns (*"it"*, *"that"*, *"compare these"*), reconstructing a clear standalone prompt from multi-turn chat history.
- **Layer 0A & 0B (Intent Classification & Task Triaging):** Distinguishes greetings, out-of-scope requests, factual data questions (`normal_qa`), and slide directives (`agent`). Fast-paths direct visual styling updates without SQL execution.
- **Layer 1 & 2 (Schema Context & Verification):** Ingests rich table statistics and sample values; verifies attribute availability and routes to entity search (`retrieval_agent`) when specific categories or values must be resolved.
- **Layer 3 & 4 (Retrieval, SQL Writing & Self-Healing Repair):** Generates dialect-aware SQL with strict read-only regex guardrails. If execution errors occur, `SQLRepairAgent` performs up to 3 iterative self-repair cycles.
- **Layer 5 (Conversational QA):** `AnswerGeneratorAgent` synthesizes concise executive summaries grounded directly in the retrieved SQL dataset.
- **Layer 6 (Unified Planner-Compiler for Presentations):**
  - **SlidePlanningAgent:** Computes non-overlapping spatial bounding boxes on a `1920×1080` canvas for both SQL and document RAG sources without CSS/markup distractions. Adapts dynamically via `slide_type` (Case 1: theme inheritance from previous slide vs. Case 2: content modification).
  - **PPTGenerationAgent:** Compiles structured JSON layout plans and template SVGs into pure 16:9 vector SVG markup (`viewBox="0 0 1920 1080"`).
  - **Fallback Handling:** Gracefully handles missing document knowledge without breaking the generation pipeline.
- **Layer 7 (Storage & Persistence):** Slides are uniquely keyed via UUIDs in Supabase S3 / local storage under `workspace/{user_id}/{project_id}/slides/{uuid}.svg` and synchronized dynamically through `manifest.json`.

---

## 🛠️ 4. Tech Stack

| Category | Technology | Purpose |
|---|---|---|
| **Frontend** | **Next.js 14 (App Router)** | Modern full-stack React framework with SSR and responsive UI |
| | **TypeScript** | Type-safe enterprise frontend code |
| | **Tailwind CSS** | Modern styling, theme gradients, and responsive layout |
| | **Lucide React** | Clean, accessible UI icons |
| **Backend & API** | **FastAPI** | High-performance asynchronous Python REST API |
| | **Uvicorn** | ASGI web server implementation |
| | **Pydantic v2** | Data validation and settings management |
| **Multi-Agent Engine** | **LangGraph** | Stateful cyclical graph orchestration with branching decision logic |
| | **LangChain Core** | Agent abstraction, prompt management, and tool integration |
| **AI & Inference** | **Groq Cloud / OpenRouter** | Ultra-low latency inference (`llama-3.3-70b-versatile`, `gpt-oss-120b`, `glm-5.3-flash`) |
| | **Google Gemini API** | Cloud dense vector embeddings (`gemini-embedding-2`) for hybrid RAG |
| **Databases** | **PostgreSQL + pgvector** | Metadata, chat history, and semantic vector similarity search |
| | **MySQL & Oracle DB** | Supported connected enterprise customer databases |
| | **SQLAlchemy** | Unified connection pooling and multi-dialect query execution |
| **Auth & Cloud Storage** | **Supabase Auth (GoTrue)** | JWT-based authentication and secure session tokens |
| | **Supabase Storage (S3)** | S3-compatible cloud storage for presentations, SVG slides, & documents |
| **Visuals & Slides** | **Pure 16:9 Vector SVG** | Standard widescreen presentations (`viewBox="0 0 1920 1080"`) with zero CSS collisions |
| **DevOps & Containers**| **Docker & Docker Compose** | Containerized deployment with hot reloading and cloud service binding |

---

## 💡 5. Conclusion

**KeloStats** redefines how organizations interact with enterprise databases and unstructured knowledge repositories. By eliminating the manual pipeline of data extraction, SQL debugging, chart crafting, and slide formatting, KeloStats turns hours of tedious work into a seamless conversational interaction.

With its **self-healing multi-agent architecture**, **strict read-only safety guardrails**, and **unified planner-compiler presentation engine**, KeloStats delivers reliable, boardroom-ready intelligence directly from raw enterprise data—fast, accurate, and secure.
