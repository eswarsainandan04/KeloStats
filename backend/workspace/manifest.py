import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

import boto3
from botocore.config import Config
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_s3_client():
    """Returns an authenticated boto3 S3 client for Supabase Storage."""
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


def get_manifest_s3_key(user_id: str, project_id: str) -> str:
    """Returns the S3 object key for manifest.json."""
    return f"workspace/{user_id}/{project_id}/manifest.json"


def save_manifest(
    user_id: str,
    project_id: str,
    manifest_data: List[Dict[str, Any]],
    s3_client=None
) -> bool:
    """
    Saves manifest.json to Supabase S3 at:
    workspace/{user_id}/{project_id}/manifest.json

    Re-indexes all items so counts are strictly sequential 1..N:
    [
        {"filename": "UUID.html", "count": 1},
        {"filename": "UUID.html", "count": 2}
    ]
    """
    if not user_id or not project_id:
        return False

    client = s3_client or get_s3_client()
    if not client:
        print("[!] S3 client unavailable; cannot save manifest.json")
        return False

    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    manifest_key = get_manifest_s3_key(user_id, project_id)

    # Normalize and re-index counts strictly 1..N
    normalized_manifest = []
    for idx, item in enumerate(manifest_data, start=1):
        filename = item.get("filename", "").strip()
        if not filename:
            continue
        normalized_manifest.append({
            "filename": filename,
            "count": idx
        })

    try:
        manifest_bytes = json.dumps(normalized_manifest, indent=2).encode("utf-8")
        client.put_object(
            Bucket=bucket_name,
            Key=manifest_key,
            Body=manifest_bytes,
            ContentType="application/json"
        )
        print(f"[+] [Manifest] Successfully saved manifest.json ({len(normalized_manifest)} slides) to S3: {manifest_key}")
        return True
    except Exception as err:
        print(f"[-] [Manifest] Failed to save manifest.json: {err}")
        return False


def load_manifest(
    user_id: str,
    project_id: str,
    s3_client=None
) -> List[Dict[str, Any]]:
    """
    Loads manifest.json from S3 under workspace/{user_id}/{project_id}/manifest.json.

    AUTO-MIGRATION:
    If manifest.json does not exist yet for this project, automatically:
    1. Scans existing slide files in workspace/{user_id}/{project_id}/slides/
    2. Converts any numeric filenames (slide_01.html) to UUID filenames (<uuid>.html)
    3. Generates the initial manifest.json
    4. Persists it to S3 and returns the ordered list.
    """
    if not user_id or not project_id:
        return []

    client = s3_client or get_s3_client()
    if not client:
        return []

    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    manifest_key = get_manifest_s3_key(user_id, project_id)

    # 1. Try reading existing manifest.json
    try:
        resp = client.get_object(Bucket=bucket_name, Key=manifest_key)
        raw_text = resp["Body"].read().decode("utf-8")
        parsed = json.loads(raw_text)

        # Handle list format or { "slides": [...] } format
        items = parsed if isinstance(parsed, list) else parsed.get("slides", [])
        if items:
            # Sort by count
            items.sort(key=lambda x: int(x.get("count", 0)))
            return items
    except Exception:
        # manifest.json not found or corrupted; proceed to auto-migration
        pass

    # 2. Auto-migration: Discover existing HTML files in project folder
    slides_prefix = f"workspace/{user_id}/{project_id}/slides/"
    found_keys: List[str] = []

    try:
        list_resp = client.list_objects_v2(Bucket=bucket_name, Prefix=slides_prefix)
        for obj in list_resp.get("Contents", []):
            k = obj["Key"]
            if k.endswith(".html") and not k.endswith("/"):
                found_keys.append(k)
    except Exception as list_err:
        print(f"[-] [Manifest Migration] S3 listing error: {list_err}")

    if not found_keys:
        return []

    print(f"[*] [Manifest Migration] Migrating {len(found_keys)} slide files for project '{project_id}' to UUID + manifest.json...")

    # Parse and sort files
    # Check if files already have UUIDs or legacy slide_XX.html numbers
    uuid_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.html$", re.IGNORECASE)
    
    legacy_items = []
    already_uuid_items = []

    for k in found_keys:
        filename = k[len(slides_prefix):]
        if uuid_pattern.match(filename):
            already_uuid_items.append(filename)
        else:
            # Extract number from slide_01.html
            num_match = re.search(r"slide_0*(\d+)\.html", filename, re.IGNORECASE)
            s_num = int(num_match.group(1)) if num_match else 999
            legacy_items.append((s_num, k, filename))

    # Sort legacy by numeric slide number
    legacy_items.sort(key=lambda x: x[0])

    manifest_entries: List[Dict[str, Any]] = []

    # Migrate legacy slide_XX.html -> UUID.html
    for idx, (old_num, old_key, old_filename) in enumerate(legacy_items, start=1):
        new_uuid_name = f"{uuid.uuid4()}.html"
        new_s3_key = f"{slides_prefix}{new_uuid_name}"

        try:
            # Copy object to new UUID key
            client.copy_object(
                Bucket=bucket_name,
                CopySource=f"{bucket_name}/{old_key}",
                Key=new_s3_key
            )
            # Delete old object
            client.delete_object(Bucket=bucket_name, Key=old_key)
            print(f"[+] [Manifest Migration] Renamed S3 slide: {old_filename} -> {new_uuid_name}")
            manifest_entries.append({
                "filename": new_uuid_name,
                "count": idx
            })
        except Exception as mig_err:
            print(f"[-] [Manifest Migration] Error copying {old_key} to {new_s3_key}: {mig_err}")
            # Keep old filename as fallback if copy failed
            manifest_entries.append({
                "filename": old_filename,
                "count": idx
            })

    # Add any files that were already UUIDs
    start_count = len(manifest_entries) + 1
    for i, u_file in enumerate(already_uuid_items, start=start_count):
        manifest_entries.append({
            "filename": u_file,
            "count": i
        })

    # Save initial manifest.json
    if manifest_entries:
        save_manifest(user_id=user_id, project_id=project_id, manifest_data=manifest_entries, s3_client=client)

    return manifest_entries


def add_slide_to_manifest(
    user_id: str,
    project_id: str,
    after_count: Optional[int] = None,
    new_filename: Optional[str] = None,
    s3_client=None
) -> Tuple[str, int, List[Dict[str, Any]]]:
    """
    Inserts a new slide into the manifest without renaming any existing files in S3:
    - after_count: If provided (e.g. 4), places the new slide after slide 4 (at position 5).
      Slide 4 stays 4, new slide becomes 5, former 5 becomes 6.
    - If after_count is None: appends to the end of the presentation.

    :return: (new_filename, assigned_count, updated_manifest)
    """
    manifest = load_manifest(user_id, project_id, s3_client=s3_client)
    slide_filename = new_filename or f"{uuid.uuid4()}.html"

    new_item = {
        "filename": slide_filename,
        "count": 0
    }

    if after_count is None or after_count >= len(manifest):
        # Append to the end
        manifest.append(new_item)
    elif after_count < 1:
        # Insert at the very beginning
        manifest.insert(0, new_item)
    else:
        # Insert after slide with count == after_count (index = after_count)
        insert_idx = after_count
        manifest.insert(insert_idx, new_item)

    # Re-index all counts sequentially 1..N
    assigned_count = 1
    for idx, item in enumerate(manifest, start=1):
        item["count"] = idx
        if item["filename"] == slide_filename:
            assigned_count = idx

    save_manifest(user_id, project_id, manifest, s3_client=s3_client)
    return slide_filename, assigned_count, manifest


def delete_slide_from_manifest(
    user_id: str,
    project_id: str,
    slide_identifier: Union[int, str],
    s3_client=None
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Deletes a slide from S3 and updates manifest.json without renaming any remaining files:
    - slide_identifier: Can be integer slide count (e.g. 3) or string filename ("UUID.html").
    - Deletes only workspace/{user_id}/{project_id}/slides/{target_filename} from S3.
    - Re-indexes remaining slides count: 1..N in manifest.json.

    :return: (deleted_filename, updated_manifest)
    """
    client = s3_client or get_s3_client()
    manifest = load_manifest(user_id, project_id, s3_client=client)

    target_idx = -1
    target_filename = None

    for idx, item in enumerate(manifest):
        if isinstance(slide_identifier, int) and item.get("count") == slide_identifier:
            target_idx = idx
            target_filename = item.get("filename")
            break
        elif str(item.get("filename")) == str(slide_identifier):
            target_idx = idx
            target_filename = item.get("filename")
            break

    if target_idx == -1 or not target_filename:
        print(f"[!] Slide '{slide_identifier}' not found in manifest for project '{project_id}'.")
        return None, manifest

    # 1. Delete target file from S3
    bucket_name = os.getenv("SUPABASE_BUCKET_NAME", "storage")
    s3_key = f"workspace/{user_id}/{project_id}/slides/{target_filename}"
    if client:
        try:
            client.delete_object(Bucket=bucket_name, Key=s3_key)
            print(f"[+] [Manifest] Deleted slide file from S3: {s3_key}")
        except Exception as d_err:
            print(f"[-] [Manifest] Warning deleting slide file {s3_key}: {d_err}")

    # 2. Remove from manifest and re-index
    manifest.pop(target_idx)
    for idx, item in enumerate(manifest, start=1):
        item["count"] = idx

    save_manifest(user_id, project_id, manifest, s3_client=client)
    return target_filename, manifest


def get_slide_filename_by_count(
    user_id: str,
    project_id: str,
    count: int,
    s3_client=None
) -> Optional[str]:
    """Resolves slide number count to its physical UUID.html filename in S3."""
    manifest = load_manifest(user_id, project_id, s3_client=s3_client)
    for item in manifest:
        if item.get("count") == count:
            return item.get("filename")
    return None
