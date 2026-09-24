# 🔐 Integrating Supabase Auth into KeloStats: Complete Architectural Guide

This document explains how to integrate **Supabase Authentication** into the existing KeloStats project, transitioning from basic custom table authentication (bcrypt + localStorage) to an enterprise-grade, token-based authentication system with **JWT validation**, **Row Level Security (RLS)**, and **secure cloud storage isolation**.

---

## 1. End-to-End System Architecture

```mermaid
sequenceDiagram
    autonumber
    actor User as 👤 User / Browser
    participant FE as 🖥️ Next.js Frontend (Client & Middleware)
    participant Auth as ⚡ Supabase Auth Service (GoTrue)
    participant DB as 🗄️ Supabase PostgreSQL (auth & public)
    participant BE as 🚀 FastAPI Backend
    participant S3 as ☁️ Supabase S3 Storage (workspace)

    %% Registration / Login Flow
    rect rgb(240, 245, 255)
    Note over User, Auth: Phase 1: Authentication & Token Issuance
    User->>FE: Enters email + password / Google OAuth
    FE->>Auth: supabase.auth.signInWithPassword({ email, password })
    Auth->>DB: Verify credentials against auth.users
    DB-->>Auth: Verified (user_id: UUID, role: authenticated)
    Auth-->>FE: Returns Session (Access Token JWT + Refresh Token)
    FE->>FE: Stores session in Secure HTTP-Only Cookie / Local Storage
    end

    %% Database Sync via PostgreSQL Trigger
    rect rgb(245, 255, 245)
    Note over Auth, DB: Phase 2: Automatic User Profile Synchronization
    Auth->>DB: Trigger: on_auth_user_created()
    DB->>DB: INSERT into public.users (user_id, email, full_name)
    Note right of DB: Existing KeloStats foreign keys<br/>(user_databases, workspace) stay intact!
    end

    %% Authenticated API Calls to Backend
    rect rgb(255, 250, 240)
    Note over FE, BE: Phase 3: Protected Backend Operations
    User->>FE: Ask question / Generate presentation
    FE->>BE: POST /api/workflow/query<br/>Header: "Authorization: Bearer <Supabase_JWT>"
    BE->>BE: Decode & verify JWT using SUPABASE_JWT_SECRET
    BE->>BE: Extract validated user_id (UUID)
    BE->>DB: Fetch user databases / chat history for this user_id
    DB-->>BE: Return user's private data
    BE->>BE: Execute LangGraph multi-agent pipeline
    BE->>S3: Upload slide to workspace/{user_id}/{project_id}/slides/
    BE-->>FE: Return AI Copilot response & slide manifest
    end
```

---

## 2. High-Level Component Flow Diagram

```mermaid
graph TD
    subgraph ClientLayer["🖥️ Frontend: Next.js (Client & SSR)"]
        A[User Interface / Login & Signup] --> B["@supabase/ssr Client"]
        B --> C[Session Storage: Cookies / LocalStorage]
        C --> D[Next.js Middleware: Route Protection]
        D -->|Valid Session| E[Dashboard / Workspace]
        D -->|No Session| F[Redirect to /login]
    end

    subgraph SupabaseAuth["⚡ Supabase Identity & Auth Engine"]
        G[Email / Password Auth]
        H[Third-Party OAuth: Google / GitHub]
        I[JWT Token Generator: Access & Refresh Tokens]
        G --> I
        H --> I
    end

    subgraph DatabaseLayer["🗄️ PostgreSQL Database Engine"]
        J["auth.users (System Schema)"]
        K["Database Trigger: on_auth_user_created"]
        L["public.users (Application Profile)"]
        M["public.user_databases"]
        N["public.workspace"]
        O["public.chat_messages"]
        
        J -->|Trigger Event| K
        K -->|Auto Insert/Update| L
        L -->|Foreign Key| M
        L -->|Foreign Key| N
        L -->|Foreign Key| O
    end

    subgraph BackendLayer["🚀 FastAPI Backend Server"]
        P[API Endpoints: /api/workflow/query]
        Q["Security Dependency: get_current_user()"]
        R["Verify JWT Token Cryptographically"]
        S[LangGraph Agent Orchestrator]
        
        P --> Q
        Q --> R
        R -->|Valid user_id| S
    end

    subgraph StorageLayer["☁️ Cloud S3 Storage (Supabase Buckets)"]
        T["Bucket: workspace"]
        U["Path: workspace/{user_id}/{project_id}/*"]
        T --> U
    end

    %% Inter-layer connections
    B <-->|1. Sign in / Refresh| SupabaseAuth
    I -.->|2. JWT Token Payload| C
    E -->|3. API Request with Bearer JWT| P
    S -->|4. Query User Data| DatabaseLayer
    S -->|5. Save Slides| StorageLayer
```

---

## 3. Why Switch from Current Auth to Supabase Auth?

| Feature | Current Implementation (`login.py` & `signup.py`) | With Supabase Auth |
|---|---|---|
| **Password Security** | Custom bcrypt hashing in local Python code | Enterprise-grade Argon2/bcrypt handled automatically by Supabase GoTrue |
| **Session Management** | Plain user object stored in browser `localStorage` (vulnerable to XSS) | Cryptographic **JWT Access Tokens** (1 hour) + automated **Refresh Tokens** |
| **Backend Verification** | Relies on client sending unverified `user_id` strings in body | FastAPI cryptographically validates the signed JWT signature from `Authorization` header |
| **Social Login (OAuth)** | Not supported (requires building Google/GitHub OAuth flows from scratch) | 1-click toggle for Google, GitHub, Azure, etc. |
| **Data Isolation** | Manual `WHERE user_id = :user_id` filtering in every SQL query | Native **Row Level Security (RLS)** in PostgreSQL protecting tables automatically |
| **Storage Security** | S3 bucket files are public or require backend proxy | S3 Storage policies restrict access so users can only read/write their own `{user_id}/*` prefix |

---

## 4. Step-by-Step Implementation Roadmap

### Step 1: Database Synchronization (The PostgreSQL Trigger)
When users register via Supabase Auth, they are created in the internal `auth.users` table. To keep your existing `public.users`, `user_databases`, and `workspace` tables working without any broken foreign keys, run this SQL script in your **Supabase SQL Editor**:

```sql
-- 1. Create automatic sync function
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (user_id, email, full_name, created_at)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
    NOW()
  )
  ON CONFLICT (user_id) DO UPDATE
  SET email = EXCLUDED.email,
      full_name = EXCLUDED.full_name;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 2. Bind trigger to Supabase auth.users table
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();
```

---

### Step 2: Frontend Setup (Next.js)

#### 1. Install Supabase Client Libraries
```bash
cd frontend
npm install @supabase/supabase-js @supabase/ssr
```

#### 2. Configure Supabase Client Helper (`frontend/lib/supabase/client.ts`)
```typescript
import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
}
```

#### 3. Update Frontend Login (`frontend/app/login/page.tsx`)
Replace custom `fetch('/api/auth/login')` with native Supabase Auth:
```typescript
import { createClient } from "@/lib/supabase/client";

const supabase = createClient();

const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault();
  const { data, error } = await supabase.auth.signInWithPassword({
    email: email.trim(),
    password: password,
  });

  if (error) {
    setError(error.message);
    return;
  }

  // Session token is now stored securely by Supabase
  router.push("/dashboard");
};
```

#### 4. Route Protection Middleware (`frontend/middleware.ts`)
Ensures unauthenticated users cannot access `/dashboard` or `/workspace`:
```typescript
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  let response = NextResponse.next({ request: { headers: request.headers } });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() { return request.cookies.getAll(); },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const { data: { user } } = await supabase.auth.getUser();

  if (!user && request.nextUrl.pathname.startsWith("/dashboard")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  return response;
}

export const config = {
  matcher: ["/dashboard/:path*"],
};
```

---

### Step 3: FastAPI Backend Authentication (JWT Verification)

In the backend, verify the incoming Supabase JWT token so users cannot spoof another user's `user_id`.

#### 1. Install PyJWT & Cryptography in Backend
```bash
cd backend
pip install pyjwt cryptography
```

#### 2. Create JWT Verification Dependency (`backend/auth/supabase_jwt.py`)
```python
import os
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Validates Supabase Bearer JWT and extracts the authenticated user_id (sub).
    """
    token = credentials.credentials
    try:
        # Decode and verify Supabase HS256 JWT
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject (user_id)."
            )
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please log in again."
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}"
        )
```

#### 3. Protect FastAPI Endpoints (`backend/workflow/orchestrator.py`)
```python
from auth.supabase_jwt import get_current_user_id

@router.post("/api/workflow/query")
def workflow_query_endpoint(
    payload: QueryWorkflowRequest,
    authenticated_user_id: str = Depends(get_current_user_id) # Enforces valid token!
):
    # Overwrite payload user_id with the verified cryptographic identity
    target_user_id = authenticated_user_id
    
    # Run LangGraph workflow safely isolated to this user
    return run_orchestrator(
        user_query=payload.user_query,
        database_id=payload.database_id,
        project_id=payload.project_id,
        user_id=target_user_id,
        slide_number=payload.slide_number
    )
```

---

### Step 4: Storage Security (Supabase S3 Isolation)

Since KeloStats uploads generated slides to:
`workspace/{user_id}/{project_id}/slides/{uuid}.html`

You can add a **Supabase Storage Policy** in the dashboard:
```sql
-- Allow users to only read and upload within their own user_id directory
CREATE POLICY "Allow User Workspace Isolation"
ON storage.objects FOR ALL
TO authenticated
USING ( bucket_id = 'workspace' AND (storage.foldername(name))[1] = auth.uid()::text )
WITH CHECK ( bucket_id = 'workspace' AND (storage.foldername(name))[1] = auth.uid()::text );
```

---

## 5. Summary of Benefits

```mermaid
mindmap
  root((Supabase Auth in KeloStats))
    Security
      Cryptographic JWT Verification
      Protection against user_id spoofing
      Row-Level Security RLS in PostgreSQL
      Storage bucket folder isolation
    User Experience
      OAuth Social Logins (Google, GitHub)
      Email confirmations & password resets
      Automatic session persistence & silent refresh
    Developer Experience
      Zero password hashing code to maintain
      Automatic user profile sync via DB triggers
      Next.js Middleware route guarding
      Clean separation of concerns
```

By adding **Supabase Auth**, KeloStats evolves from a prototype with basic local credentials into a **secure, multi-tenant SaaS architecture** ready for enterprise deployment.
