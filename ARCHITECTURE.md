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

    %% Entry Point
    API["🚀 POST /api/workflow/query<br><b>User Query + Database ID</b>"]:::startNode --> LOGGER_INIT["📝 Initialize LLM Logger Session<br><b>start_workflow_logger()</b>"]:::storageNode
    LOGGER_INIT --> NODE1

    %% Node 1: Schema Extraction
    subgraph S1["Node 1: Schema Input Layer"]
        NODE1["🔍 <b>Node 1: Schema Extraction</b><br>Extracts rich schema, types, min/max ranges,<br>distinct counts & sample categories"]:::agentNode
        NODE1 --> SCHEMA_CACHE[("💾 Save schema text to<br>databases/schema_extraction/output/db_id.txt")]:::storageNode
    end

    SCHEMA_CACHE --> NODE2

    %% Node 2: Verification Agent
    subgraph S2["Node 2: Triage & Verification Layer"]
        NODE2["🛡️ <b>Node 2: Query Verification Agent</b><br>Analyzes query vs schema & classifies intent"]:::agentNode
        DECIDE_VERIFY{"Verification Decision?"}:::decisionNode
        NODE2 --> DECIDE_VERIFY
    end

    %% Verification Routing
    DECIDE_VERIFY -->|UNRELATED| UNRELATED_NODE["❌ <b>Node 3C: Rejection Fallback</b><br>Returns friendly out-of-scope message"]:::errorNode
    UNRELATED_NODE --> WORKFLOW_END

    DECIDE_VERIFY -->|RETRIEVAL_REQUIRED| NODE3B
    DECIDE_VERIFY -->|SCHEMA_MATCH| NODE3A

    %% Node 3B: Retrieval Agent & Guardrail
    subgraph S3B["Node 3B: Entity Value Retrieval Layer"]
        NODE3B["🔎 <b>Node 3B: Retrieval Agent</b><br>Splits multi-word keywords & generates search SQL<br><i>(ILIKE / LIKE / LOWER)</i>"]:::agentNode
        
        NODE3B --> GUARDRAIL_RETRIEVE{"🛡️ <b>Retrieval Guardrail</b><br>Must start with SELECT & blocks mutating keywords"}:::guardNode
        GUARDRAIL_RETRIEVE -->|Violation Detected| RETRY_RETRIEVAL["🔁 <b>Re-attempt RetrievalAgent</b><br>Appends corrective penalty warning (up to 3x)"]:::guardNode
        RETRY_RETRIEVAL --> NODE3B

        GUARDRAIL_RETRIEVE -->|Check Passed| DB_TOOL_SEARCH["⚡ <b>Execute Search Query on Target DB</b><br>PostgreSQL / MySQL / Oracle"]:::toolNode
        
        DB_TOOL_SEARCH --> CHECK_RETRIEVAL_OUT{"Execution Result?"}:::decisionNode
        
        CHECK_RETRIEVAL_OUT -->|Database Error| RETRIEVAL_ERR_STATE["⚠️ Status: <b>RETRIEVAL_REPAIR_REQUIRED</b>"]:::errorNode
        CHECK_RETRIEVAL_OUT -->|0 Rows Returned: True Not Found| NOT_FOUND_NODE["⚠️ <b>Status: NOT_FOUND</b><br>'the {word} not found in your database'"]:::errorNode
        CHECK_RETRIEVAL_OUT -->|>0 Rows Returned: Match Found| MD_TABLE["📊 <b>Format Markdown Table</b><br>Verified entity values for WHERE clause"]:::storageNode
    end

    NOT_FOUND_NODE --> WORKFLOW_END
    MD_TABLE --> NODE3A
    RETRIEVAL_ERR_STATE --> NODE4

    %% Node 3A: SQL Writer Agent & Guardrail
    subgraph S3A["Node 3A: Master SQL Generation Layer"]
        NODE3A["✍️ <b>Node 3A: SQL Writer Node</b><br>Generates dialect-aware master SQL<br>using schema + prompt + retrieved table"]:::agentNode
        
        NODE3A --> GUARDRAIL_WRITER{"🛡️ <b>SQL Writer Guardrail</b><br>Blocks DELETE, DROP, ALTER, INSERT, UPDATE..."}:::guardNode
        GUARDRAIL_WRITER -->|Violation Detected| RETRY_WRITER["🔁 <b>Re-attempt SQLWriterAgent</b><br>Appends corrective penalty warning (up to 3x)"]:::guardNode
        RETRY_WRITER --> NODE3A
        
        GUARDRAIL_WRITER -->|Check Passed| DB_EXEC["⚡ <b>Execute Master SQL on Target DB</b><br>PostgreSQL / MySQL / Oracle"]:::toolNode
        
        DB_EXEC --> CHECK_WRITER_OUT{"Execution Result?"}:::decisionNode
        CHECK_WRITER_OUT -->|Execution Error| WRITER_ERR_STATE["⚠️ Status: <b>REPAIR_REQUIRED</b>"]:::errorNode
        CHECK_WRITER_OUT -->|Execution Succeeded| SAVE_DATA[("💾 <b>Save Data Rows for PPT</b><br>Writes columns & rows to<br><b>backend/data/{timestamp}.json</b>")]:::storageNode
    end

    WRITER_ERR_STATE --> NODE4
    SAVE_DATA --> WORKFLOW_END

    %% Node 4: LangGraph Level SQL Repair Agent
    subgraph S4_REPAIR["Node 4: Centralized Self-Healing Repair Layer (LangGraph Node)"]
        NODE4["🛠️ <b>Node 4: SQL Repair Node</b><br>Calls <b>SQLRepairAgent</b> with Error + Schema + DB<br>Attempts up to 3 repair cycles"]:::repairNode
        
        NODE4 --> ROUTE_AFTER_REPAIR{"Source of Repair?"}:::decisionNode
        
        ROUTE_AFTER_REPAIR -->|Repaired Retrieval Query| RE_EXEC_RETRIEVAL["⚡ <b>Re-execute Search Query & Extract Rows</b>"]:::toolNode
        RE_EXEC_RETRIEVAL --> CHECK_REPAIRED_ROWS{"Rows Found?"}:::decisionNode
        CHECK_REPAIRED_ROWS -->|0 Rows| NOT_FOUND_NODE
        CHECK_REPAIRED_ROWS -->|>0 Rows| MD_TABLE
        
        ROUTE_AFTER_REPAIR -->|Repaired Master SQL| RE_EXEC_MASTER["⚡ <b>Re-execute Master SQL & Save Rows</b><br>Writes to <b>backend/data/{timestamp}.json</b>"]:::toolNode
        RE_EXEC_MASTER --> WORKFLOW_END
    end

    %% Workflow Completion & Logging
    subgraph S5["Workflow Finalization & Logging"]
        WORKFLOW_END["🏁 <b>LangGraph Final State</b><br>Status: SUCCESS_SQL_GENERATED / NOT_FOUND<br>Output: Final SQL or Fallback Message"]:::endNode
        WORKFLOW_END --> FINALIZE_LOG[("📜 <b>Save Final LLM Log File</b><br>logs/llm_logs/workflow Log {timestamp}.txt<br>Includes Prompts, Outputs & TOTAL TOKENS")]:::storageNode
    end
