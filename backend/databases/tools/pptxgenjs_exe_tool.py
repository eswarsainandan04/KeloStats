import os
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv
import boto3
from botocore.config import Config

# Locate and load .env file
current_dir = Path(__file__).resolve().parent
backend_root = current_dir.parent.parent
if (backend_root / ".env").exists():
    load_dotenv(dotenv_path=backend_root / ".env")
else:
    load_dotenv()


def get_s3_client():
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
        config=Config(signature_version="s3v4")
    )


def execute_pptxgenjs_tool(user_id: str, project_id: str) -> Dict[str, Any]:
    """
    Executes presentation.js from workspace/{user_id}/{project_id}/ in Supabase S3:
    1. Downloads workspace files from Supabase S3 into a temporary directory.
    2. Runs 'node presentation.js' with pptxgenjs.
    3. Uploads generated presentation.pptx back to workspace/{user_id}/{project_id}/ in Supabase S3.
    4. Automatically purges all temporary files upon completion.
    """
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_client = get_s3_client()

    if not s3_client:
        return {
            "status": "error",
            "message": "Supabase S3 credentials not configured."
        }

    prefix = f"workspace/{user_id}/{project_id}/"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 1. Download project files from S3 to temp directory
        try:
            resp = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
            contents = resp.get("Contents", [])

            if not contents:
                return {
                    "status": "error",
                    "message": f"No workspace files found in Supabase S3 for {prefix}"
                }

            for item in contents:
                key = item["Key"]
                rel_path = key[len(prefix):]
                if not rel_path or rel_path.endswith("/"):
                    continue

                dest_file = tmp_path / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)

                obj_data = s3_client.get_object(Bucket=bucket_name, Key=key)["Body"].read()
                dest_file.write_bytes(obj_data)
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Failed to fetch workspace files from S3: {str(exc)}"
            }

        script_path = tmp_path / "presentation.js"
        if not script_path.exists():
            return {
                "status": "error",
                "message": "presentation.js not found in project files."
            }

        # 2. Run 'node presentation.js'
        env = os.environ.copy()
        node_modules_path = (backend_root / "node_modules").resolve()
        env["NODE_PATH"] = str(node_modules_path)

        try:
            proc = subprocess.run(
                ["node", "presentation.js"],
                cwd=str(tmp_path),
                env=env,
                capture_output=True,
                text=True,
                check=False
            )

            pptx_file = tmp_path / "presentation.pptx"
            pptx_exists = pptx_file.exists()

            # 3. Upload generated presentation.pptx back to Supabase S3
            s3_pptx_key = None
            if pptx_exists:
                s3_pptx_key = f"workspace/{user_id}/{project_id}/presentation.pptx"
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=s3_pptx_key,
                    Body=pptx_file.read_bytes(),
                    ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation"
                )
                print(f"[+] Successfully uploaded generated presentation.pptx to S3: {s3_pptx_key}")

            return {
                "status": "success" if proc.returncode == 0 and pptx_exists else "error",
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "pptx_exists": pptx_exists,
                "s3_key": s3_pptx_key
            }
        except Exception as run_err:
            return {
                "status": "error",
                "message": f"Execution error: {str(run_err)}"
            }
