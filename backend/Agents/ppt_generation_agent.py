import io
import json
import os
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import boto3
from botocore.config import Config
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "ppt_theme_prompt.txt"
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def get_s3_client():
    """
    Returns an authenticated boto3 S3 client for Supabase Storage.
    """
    endpoint = os.getenv("SUPABASE_S3_ENDPOINT")
    access_key = os.getenv("SUPABASE_S3_ACCESS_KEY_ID")
    secret_key = os.getenv("SUPABASE_S3_SECRET_ACCESS_KEY")
    region = os.getenv("SUPABASE_S3_REGION") or "us-east-1"

    if not endpoint or not access_key or not secret_key:
        return None

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def get_user_id_for_project(project_id: str) -> Optional[str]:
    """
    Looks up user_id for a given project_id from the PostgreSQL workspace table.
    Falls back to inspecting Supabase S3 workspace/ prefix if DB is inaccessible.
    """
    if not project_id:
        return None

    # 1. Database lookup
    try:
        from workspace.manage_workspace import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT user_id FROM workspace WHERE project_id = :pid LIMIT 1;"),
                {"pid": project_id}
            ).fetchone()
            if row and row[0]:
                return str(row[0])
    except Exception as db_err:
        print(f"[!] DB user_id lookup notice for project '{project_id}': {db_err}")

    # 2. S3 prefix search fallback
    s3_client = get_s3_client()
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    if s3_client:
        try:
            resp = s3_client.list_objects_v2(Bucket=bucket_name, Prefix="workspace/", Delimiter="/")
            for common_prefix in resp.get("CommonPrefixes", []):
                uid_candidate = common_prefix.get("Prefix", "").replace("workspace/", "").strip("/")
                if uid_candidate:
                    # Check if project_id exists under this uid
                    sub_check = s3_client.list_objects_v2(
                        Bucket=bucket_name,
                        Prefix=f"workspace/{uid_candidate}/{project_id}/",
                        MaxKeys=1
                    )
                    if sub_check.get("KeyCount", 0) > 0 or sub_check.get("Contents"):
                        return uid_candidate
        except Exception as s3_err:
            print(f"[!] S3 user_id prefix search notice for project '{project_id}': {s3_err}")

    return None


def is_empty_slide(html_code: str) -> bool:
    """
    Determines if the provided slide HTML represents an empty or blank slide.
    Checks for empty canvas container or blank slide keywords.
    """
    if not html_code or not html_code.strip():
        return True

    lower_html = html_code.lower()

    # 1. Check if .slide-canvas contains zero or only whitespace/comment content
    canvas_match = re.search(
        r'<div[^>]*class=["\'][^"\']*slide-canvas[^"\']*["\'][^>]*>(.*?)</div>',
        html_code,
        re.DOTALL | re.IGNORECASE
    )
    if canvas_match:
        inner_content = canvas_match.group(1).strip()
        inner_no_comments = re.sub(r"<!--[\s\S]*?-->", "", inner_content).strip()
        # If no HTML tags or visible text exist inside canvas, it is empty
        if not inner_no_comments or not re.search(r"<[a-z1-6]+", inner_no_comments, re.IGNORECASE):
            return True
        return False

    # 2. Check title / keywords
    if "blank slide" in lower_html or "pure blank white slide" in lower_html:
        return True

    # 3. Check body content
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html_code, re.DOTALL | re.IGNORECASE)
    if body_match:
        body_content = re.sub(r"<!--[\s\S]*?-->", "", body_match.group(1)).strip()
        if not body_content or not re.search(r"<[a-z1-6]+", body_content, re.IGNORECASE):
            return True

    return False


def GetHTMLCode(project_id: str, slide_number: int, user_id: Optional[str] = None) -> str:
    """
    Retrieves the raw HTML slide code from Supabase S3 bucket:
    workspace/{user_id}/{project_id}/slides/{UUID}.html
    resolved dynamically via workspace/{user_id}/{project_id}/manifest.json.

    Falls back gracefully to local practice slides if S3 is not available.
    """
    if not project_id or slide_number < 1:
        return ""

    uid = user_id or get_user_id_for_project(project_id)
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()

    # 1. Primary: Resolve filename via manifest.json
    if s3_client and uid:
        try:
            from workspace.manifest import get_slide_filename_by_count, load_manifest
            filename = get_slide_filename_by_count(uid, project_id, slide_number, s3_client=s3_client)
            if filename:
                target_s3_key = f"workspace/{uid}/{project_id}/slides/{filename}"
                try:
                    obj = s3_client.get_object(Bucket=bucket_name, Key=target_s3_key)
                    html_text = obj["Body"].read().decode("utf-8")
                    if html_text.strip():
                        print(f"[+] [GetHTMLCode] Loaded Slide {slide_number} ({filename}) from S3 via manifest: {target_s3_key}")
                        return html_text
                except Exception as get_err:
                    print(f"[!] Warning reading manifest slide {target_s3_key}: {get_err}")
        except Exception as m_err:
            print(f"[!] Warning checking manifest in GetHTMLCode: {m_err}")

        # Fallback check for legacy slide_{slide_number:02d}.html
        target_s3_key = f"workspace/{uid}/{project_id}/slides/slide_{slide_number:02d}.html"
        try:
            obj = s3_client.get_object(Bucket=bucket_name, Key=target_s3_key)
            html_text = obj["Body"].read().decode("utf-8")
            if html_text.strip():
                print(f"[+] [GetHTMLCode] Loaded Slide {slide_number} from S3 (legacy fallback): {target_s3_key}")
                return html_text
        except Exception:
            pass

        # Fallback check for unpadded slide_{slide_number}.html
        fallback_s3_key = f"workspace/{uid}/{project_id}/slides/slide_{slide_number}.html"
        try:
            obj = s3_client.get_object(Bucket=bucket_name, Key=fallback_s3_key)
            html_text = obj["Body"].read().decode("utf-8")
            if html_text.strip():
                print(f"[+] [GetHTMLCode] Loaded Slide {slide_number} from S3 (unpadded fallback): {fallback_s3_key}")
                return html_text
        except Exception:
            pass

    # 2. Local practice/ fallback (for development and tests)
    practice_dir = BACKEND_ROOT.parent / "practice"
    local_candidates = [
        practice_dir / f"slide_{slide_number:02d}.html",
        practice_dir / f"slide_{slide_number}.html",
        practice_dir / "slides" / f"slide_{slide_number:02d}.html",
        practice_dir / "slides" / f"slide_{slide_number}.html",
    ]

    for p in local_candidates:
        if p.exists():
            try:
                print(f"[+] [GetHTMLCode] Loaded fallback slide from local file: {p}")
                return p.read_text(encoding="utf-8")
            except Exception:
                pass

    return ""


def save_slide_to_s3(
    project_id: str,
    slide_number: int,
    html_code: str,
    user_id: Optional[str] = None
) -> bool:
    """
    Replaces the slide code with the generated HTML code in Supabase S3 under:
    workspace/{user_id}/{project_id}/slides/{UUID}.html
    and keeps manifest.json accurately synchronized.
    """
    if not project_id or not html_code:
        return False

    uid = user_id or get_user_id_for_project(project_id)
    if not uid:
        print(f"[!] Warning: Unable to resolve user_id for project '{project_id}'; skipping S3 slide persistence.")
        return False

    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()
    if not s3_client:
        print("[!] S3 client not configured; cannot upload generated slide to S3.")
        return False

    cleaned_code = _clean_html_response(html_code)

    # 1. Resolve or create UUID filename via manifest.json
    filename = None
    try:
        from workspace.manifest import get_slide_filename_by_count, add_slide_to_manifest
        filename = get_slide_filename_by_count(uid, project_id, slide_number, s3_client=s3_client)
        if not filename:
            # Add to manifest at position slide_number
            filename, _, _ = add_slide_to_manifest(
                user_id=uid,
                project_id=project_id,
                after_count=slide_number - 1,
                s3_client=s3_client
            )
    except Exception as m_err:
        print(f"[!] Notice resolving manifest filename in save_slide_to_s3: {m_err}")

    # Fallback filename if manifest resolution failed
    if not filename:
        import uuid
        filename = f"{uuid.uuid4()}.html"

    primary_s3_key = f"workspace/{uid}/{project_id}/slides/{filename}"

    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=primary_s3_key,
            Body=cleaned_code.encode("utf-8"),
            ContentType="text/html; charset=utf-8"
        )
        print(f"[+] [save_slide_to_s3] Saved Slide {slide_number} ({filename}) in S3: {primary_s3_key}")
    except Exception as upload_err:
        print(f"[-] [save_slide_to_s3] Failed to upload Slide {slide_number} to {primary_s3_key}: {upload_err}")
        return False

    # Clean up legacy numeric keys (slide_01.html, slide_1.html) so no duplicate files remain
    legacy_keys = [
        f"workspace/{uid}/{project_id}/slides/slide_{slide_number:02d}.html",
        f"workspace/{uid}/{project_id}/slides/slide_{slide_number}.html",
    ]
    for l_key in legacy_keys:
        if l_key != primary_s3_key:
            try:
                s3_client.delete_object(Bucket=bucket_name, Key=l_key)
            except Exception:
                pass

    return True


def _clean_html_response(raw_response: str) -> str:
    """
    Extracts pure executable HTML code from the model output.
    Strips reasoning tags, markdown fences, and conversational commentary.
    """
    text = raw_response.strip()

    # 1. Strip <think>...</think>
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()

    # 2. Extract ```html ... ``` content if present
    match = re.search(r"```(?:html)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    # 3. If standard DOCTYPE or <html> is present, isolate from <!DOCTYPE or <html to </html>
    doc_idx = text.lower().find("<!doctype html")
    if doc_idx == -1:
        doc_idx = text.lower().find("<html")

    html_end_idx = text.lower().rfind("</html>")

    if doc_idx != -1 and html_end_idx != -1 and html_end_idx > doc_idx:
        text = text[doc_idx:html_end_idx + 7].strip()

    # 4. If the response contains an unclosed <script> tag (truncated by LLM), safely strip the incomplete script
    last_script_open = text.rfind("<script")
    last_script_close = text.rfind("</script>")
    if last_script_open != -1 and last_script_open > last_script_close:
        text = text[:last_script_open].strip()
        if not text.endswith("</body>"):
            text += "\n</body>\n</html>"

    return text


def PPTGenerationAgent(
    user_query: str,
    retrived_rows: Union[Dict[str, Any], List[Any], str],
    slide_number: int = 1,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    html_code: Optional[str] = None
) -> str:
    """
    PPT Generation Agent:
    - Receives user query, retrieved database records, target slide number, and slide template HTML.
    - Instructs LLM using ppt_theme_prompt.txt to generate executable HTML code adhering to the template theme.
    - Replaces the empty slide code and saves to Supabase S3 under workspace/{user_id}/{project_id}/slides/{current_slide}.html.
    - Returns executable HTML code.

    :param user_query: The user prompt / instruction for the presentation slide
    :param retrived_rows: The data records returned from SQL execution
    :param slide_number: Target slide index (e.g. 1, 2, 3...)
    :param project_id: Optional project identifier for S3 sync and retrieval
    :param user_id: Optional user identifier for S3 path resolution
    :param html_code: Explicit template HTML string (if not provided, retrieved dynamically via GetHTMLCode)
    :return: Pure executable HTML slide markup
    """
    cleaned_query = (user_query or "").strip()

    # 1. Format retrieved_rows to clean JSON string
    if isinstance(retrived_rows, (dict, list)):
        if isinstance(retrived_rows, dict) and "rows" in retrived_rows:
            all_rows = retrived_rows.get("rows") or []
            if len(all_rows) > 50:
                truncated_payload = {
                    "columns": retrived_rows.get("columns", []),
                    "total_rows_count": len(all_rows),
                    "showing_first_50_rows": all_rows[:50]
                }
                data_str = json.dumps(truncated_payload, indent=2, default=str)
            else:
                data_str = json.dumps(retrived_rows, indent=2, default=str)
        elif isinstance(retrived_rows, list) and len(retrived_rows) > 50:
            data_str = json.dumps({
                "total_rows_count": len(retrived_rows),
                "showing_first_50_rows": retrived_rows[:50]
            }, indent=2, default=str)
        else:
            data_str = json.dumps(retrived_rows, indent=2, default=str)
    else:
        data_str = str(retrived_rows or "{}")

    # 2. Determine template HTML code if not provided
    template_html = html_code
    if not template_html and project_id:
        current_html = GetHTMLCode(project_id=project_id, slide_number=slide_number, user_id=user_id)
        if is_empty_slide(current_html):
            if slide_number > 1:
                prev_html = GetHTMLCode(project_id=project_id, slide_number=slide_number - 1, user_id=user_id)
                template_html = prev_html if (prev_html and not is_empty_slide(prev_html)) else current_html
            else:
                template_html = current_html
        else:
            template_html = current_html

    # Fallback to local slide_04.html template if still empty
    if not template_html or not template_html.strip():
        local_fallback = BACKEND_ROOT.parent / "practice" / "slide_04.html"
        if local_fallback.exists():
            template_html = local_fallback.read_text(encoding="utf-8")
        else:
            template_html = "<!-- Default Presentation Slide Canvas -->"

    # 3. Read prompt template
    if not PROMPT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"PPT generation prompt template not found at: {PROMPT_TEMPLATE_PATH}")

    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    populated_prompt = (
        prompt_template
        .replace("{{Prompt}}", cleaned_query)
        .replace("{{retrived_rows}}", data_str)
        .replace("{{html_code}}", template_html)
    )

    base_url = os.getenv("PPT_GENERATION_LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    api_key = os.getenv("PPT_GENERATION_LLM_API_KEY", "")
    model = os.getenv("PPT_GENERATION_LLM_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        raise ValueError("LLM_API_KEY is not set in environment or .env file.")

    endpoint_url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url

    request_data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": populated_prompt
            }
        ],
        "temperature": 0.2,
        "max_tokens": 8192
    }

    req = urllib.request.Request(
        endpoint_url,
        data=json.dumps(request_data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Kelostats-Agent/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_bytes = resp.read()
            resp_json = json.loads(resp_bytes.decode("utf-8"))
            raw_content = resp_json["choices"][0]["message"]["content"]
            usage = resp_json.get("usage", {})

            # Log interaction to workflow logger
            try:
                from logs.llm_logger import log_agent_call
                log_agent_call(
                    node_name="Node: PPT Generation",
                    agent_name="PPT Generation Agent",
                    llm_input=populated_prompt,
                    llm_output=raw_content,
                    usage=usage
                )
            except Exception as log_err:
                print(f"[!] Warning logging PPT generation interaction: {log_err}")

            generated_html = _clean_html_response(raw_content)

            # 4. Save generated slide to Supabase S3 replacing the empty slide code
            if project_id:
                save_slide_to_s3(
                    project_id=project_id,
                    slide_number=slide_number,
                    html_code=generated_html,
                    user_id=user_id
                )

            return generated_html

    except Exception as err:
        print(f"[!] Error in PPTGenerationAgent: {err}")
        # Return fallback HTML using template
        fallback_html = template_html
        return fallback_html
