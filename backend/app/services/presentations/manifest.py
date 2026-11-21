import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.core.config import settings
from app.core.storage import get_storage


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely converts a value to integer with fallback."""
    try:
        if val is None:
            return default
        return int(val)
    except (ValueError, TypeError):
        return default


def get_manifest_storage_key(user_id: str, project_id: str) -> str:
    """Returns the storage key for manifest.json."""
    return f"workspace/{user_id}/{project_id}/manifest.json"


def save_manifest(
    user_id: str,
    project_id: str,
    manifest_data: List[Dict[str, Any]],
    s3_client=None
) -> bool:
    """
    Saves manifest.json to storage at:
    workspace/{user_id}/{project_id}/manifest.json

    Re-indexes all items so counts are strictly sequential 1..N:
    [
        {"filename": "UUID.svg", "count": 1},
        {"filename": "UUID.svg", "count": 2}
    ]
    """
    if not user_id or not project_id:
        return False

    # Re-index all items so counts are strictly sequential 1..N and ensure is_blank_slide is set
    for idx, item in enumerate(manifest_data, start=1):
        item["count"] = idx
        if "is_blank_slide" not in item:
            item["is_blank_slide"] = False

    storage_key = get_manifest_storage_key(user_id, project_id)
    try:
        storage = get_storage()
        json_bytes = json.dumps(manifest_data, indent=2).encode("utf-8")
        storage.create(key=storage_key, data=json_bytes, content_type="application/json")
        print(f"[+] [Manifest] Successfully saved manifest.json with {len(manifest_data)} items at: {storage_key}")
        return True
    except Exception as exc:
        print(f"[-] [Manifest] Error saving manifest.json: {exc}")
        return False


def load_manifest(
    user_id: str,
    project_id: str,
    s3_client=None
) -> List[Dict[str, Any]]:
    """
    Loads manifest.json from storage under workspace/{user_id}/{project_id}/manifest.json.

    AUTO-MIGRATION:
    If manifest.json does not exist yet for this project, automatically:
    1. Scans existing slide files in workspace/{user_id}/{project_id}/slides/
    2. Converts any numeric filenames (slide_01.svg) to UUID filenames (<uuid>.svg)
    3. Generates the initial manifest.json
    4. Persists it to storage and returns the ordered list.
    """
    if not user_id or not project_id:
        return []

    storage = get_storage()
    manifest_key = get_manifest_storage_key(user_id, project_id)

    # 1. Try reading existing manifest.json
    if storage.exists(manifest_key):
        try:
            raw_text = storage.read_text(manifest_key)
            parsed = json.loads(raw_text)
            items = parsed if isinstance(parsed, list) else parsed.get("slides", [])
            if items:
                items.sort(key=lambda x: _safe_int(x.get("count"), 0))
                for item in items:
                    if "is_blank_slide" not in item:
                        item["is_blank_slide"] = False
                return items
        except Exception as read_err:
            print(f"[!] [Manifest] Error reading existing manifest.json ({read_err}); checking slides...")

    # 2. Auto-migration: Discover existing slide files in project folder
    slides_prefix = f"workspace/{user_id}/{project_id}/slides/"
    try:
        found_keys = storage.list_files(prefix=slides_prefix)
    except Exception as list_err:
        print(f"[-] [Manifest] Error listing slides: {list_err}")
        found_keys = []

    slide_svg_files = [
        Path(k).name for k in found_keys
        if k.endswith(".svg") and not k.endswith("/")
    ]
    slide_other_files = [
        Path(k).name for k in found_keys
        if not k.endswith(".svg") and not k.endswith("/")
    ]

    # Prioritize SVG files if available
    preferred_ext = ".svg"
    slide_files = slide_svg_files if slide_svg_files else slide_other_files

    if not slide_files:
        print(f"[!] [Manifest] No slide files found in storage for {project_id}.")
        return []

    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[a-z0-9]+$",
        re.IGNORECASE
    )

    numeric_files: List[Tuple[int, str]] = []
    already_uuid_items: List[str] = []

    for fname in slide_files:
        if uuid_pattern.match(fname):
            already_uuid_items.append(fname)
        else:
            num_match = re.search(r"slide_0*(\d+)\.[a-z0-9]+", fname, re.IGNORECASE)
            if num_match:
                numeric_files.append((int(num_match.group(1)), fname))
            else:
                already_uuid_items.append(fname)

    # Sort numeric files by original slide number (1, 2, 3...)
    numeric_files.sort(key=lambda x: x[0])

    manifest_entries: List[Dict[str, Any]] = []

    # Rename numeric slide files to UUID filenames in storage
    for orig_num, old_filename in numeric_files:
        file_ext = ".svg" if old_filename.endswith(".svg") else preferred_ext
        new_uuid_name = f"{uuid.uuid4()}{file_ext}"
        old_key = f"{slides_prefix}{old_filename}"
        new_key = f"{slides_prefix}{new_uuid_name}"
        content_type = "image/svg+xml; charset=utf-8"

        try:
            old_data = storage.read(old_key)
            storage.create(key=new_key, data=old_data, content_type=content_type)
            storage.delete(old_key)
            print(f"[+] [Manifest Migration] Converted: {old_filename} -> {new_uuid_name}")
            manifest_entries.append({
                "filename": new_uuid_name,
                "is_blank_slide": False,
                "count": len(manifest_entries) + 1
            })
        except Exception as copy_err:
            print(f"[-] [Manifest Migration Error] Could not convert {old_filename}: {copy_err}")
            manifest_entries.append({
                "filename": old_filename,
                "is_blank_slide": False,
                "count": len(manifest_entries) + 1
            })

    # Add any files that were already UUIDs
    start_count = len(manifest_entries) + 1
    for i, u_file in enumerate(already_uuid_items, start=start_count):
        manifest_entries.append({
            "filename": u_file,
            "is_blank_slide": False,
            "count": i
        })

    # Save initial manifest.json
    if manifest_entries:
        save_manifest(user_id=user_id, project_id=project_id, manifest_data=manifest_entries)

    return manifest_entries


def add_slide_to_manifest(
    user_id: str,
    project_id: str,
    after_count: Optional[Union[int, str]] = None,
    new_filename: Optional[str] = None,
    is_blank_slide: bool = False,
    s3_client=None
) -> Tuple[str, int, List[Dict[str, Any]]]:
    """
    Inserts a new slide into the manifest without renaming any existing files in storage:
    - after_count: If provided (e.g. 4), places the new slide after slide 4 (at position 5).
    - If after_count is None: appends to the end of the presentation.
    - is_blank_slide: True only when user creates a pure blank slide.

    :return: (new_filename, assigned_count, updated_manifest)
    """
    manifest = load_manifest(user_id, project_id)
    slide_filename = new_filename or f"{uuid.uuid4()}.svg"

    new_item = {
        "filename": slide_filename,
        "is_blank_slide": bool(is_blank_slide),
        "count": 0
    }

    clean_after: Optional[int] = None
    if after_count is not None:
        try:
            clean_after = int(after_count)
        except (ValueError, TypeError):
            clean_after = None

    if clean_after is None or clean_after >= len(manifest):
        manifest.append(new_item)
    elif clean_after < 1:
        manifest.insert(0, new_item)
    else:
        manifest.insert(clean_after, new_item)

    # Re-index all counts sequentially 1..N
    assigned_count = 1
    for idx, item in enumerate(manifest, start=1):
        item["count"] = idx
        if item["filename"] == slide_filename:
            assigned_count = idx

    save_manifest(user_id, project_id, manifest)
    return slide_filename, assigned_count, manifest


def delete_slide_from_manifest(
    user_id: str,
    project_id: str,
    slide_identifier: Union[int, str],
    s3_client=None
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Deletes a slide from storage and updates manifest.json without renaming any remaining files:
    - slide_identifier: Can be integer slide count (e.g. 3), string count ("3"), or string filename ("UUID.svg").
    - Deletes only workspace/{user_id}/{project_id}/slides/{target_filename} from storage.
    - Re-indexes remaining slides count: 1..N in manifest.json.

    :return: (deleted_filename, updated_manifest)
    """
    manifest = load_manifest(user_id, project_id)

    target_idx = -1
    target_filename = None
    ident_str = str(slide_identifier).strip()

    for idx, item in enumerate(manifest):
        item_count_str = str(item.get("count", "")).strip()
        item_fname = str(item.get("filename", "")).strip()

        # Match by slide count number (e.g. 3 or "3")
        if ident_str.isdigit() and item_count_str == ident_str:
            target_idx = idx
            target_filename = item_fname
            break

        # Match by filename (exact or without extension)
        if (
            item_fname.lower() == ident_str.lower()
            or item_fname.lower() == f"{ident_str.lower()}.svg"
            or Path(item_fname).stem.lower() == ident_str.lower()
        ):
            target_idx = idx
            target_filename = item_fname
            break

    if target_idx == -1 or not target_filename:
        print(f"[!] Slide '{slide_identifier}' not found in manifest for project '{project_id}'.")
        return None, manifest

    # 1. Delete target file from storage
    storage = get_storage()
    slide_storage_key = f"workspace/{user_id}/{project_id}/slides/{target_filename}"
    try:
        storage.delete(slide_storage_key)
        print(f"[+] [Manifest] Deleted slide file from storage: {slide_storage_key}")
    except Exception as d_err:
        print(f"[-] [Manifest] Warning deleting slide file {slide_storage_key}: {d_err}")

    # 2. Remove from manifest and re-index
    manifest.pop(target_idx)
    for idx, item in enumerate(manifest, start=1):
        item["count"] = idx

    save_manifest(user_id, project_id, manifest)
    return target_filename, manifest


def get_slide_filename_by_count(
    user_id: str,
    project_id: str,
    count: Union[int, str],
    s3_client=None
) -> Optional[str]:
    """Resolves slide number count to its physical UUID filename in storage."""
    manifest = load_manifest(user_id, project_id)
    target_count = str(count).strip()
    for item in manifest:
        if str(item.get("count", "")).strip() == target_count:
            return item.get("filename")
    return None


def set_slide_blank_status(
    user_id: str,
    project_id: str,
    slide_number: Union[int, str],
    is_blank_slide: bool = False,
    s3_client=None
) -> bool:
    """
    Updates the 'is_blank_slide' status flag for a given slide number in manifest.json.
    Sets to False whenever modified by LLM or user edit.
    """
    manifest = load_manifest(user_id, project_id, s3_client=s3_client)
    target_count = str(slide_number).strip()
    updated = False
    for item in manifest:
        if str(item.get("count", "")).strip() == target_count:
            item["is_blank_slide"] = bool(is_blank_slide)
            updated = True
            break
    if updated:
        save_manifest(user_id, project_id, manifest, s3_client=s3_client)
    return updated


def is_slide_blank(
    user_id: str,
    project_id: str,
    slide_number: Union[int, str],
    s3_client=None
) -> bool:
    """
    Checks if a slide is marked as a blank slide in manifest.json.
    Returns False by default.
    """
    manifest = load_manifest(user_id, project_id, s3_client=s3_client)
    target_count = str(slide_number).strip()
    for item in manifest:
        if str(item.get("count", "")).strip() == target_count:
            return bool(item.get("is_blank_slide", False))
    return False
