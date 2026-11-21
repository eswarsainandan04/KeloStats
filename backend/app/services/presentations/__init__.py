from .downloads import (
    compile_and_save_pptx,
    compile_slides_to_pptx,
)
from .manager import (
    GetSVGCode,
    is_empty_slide,
    copy_template_files,
    create_workspace,
    create_workspace_folder,
    delete_workspace,
    delete_workspace_storage,
    fetch_workspace_history_from_storage,
    get_workspace,
    list_user_workspaces,
    update_workspace_source,
)
from .manifest import (
    add_slide_to_manifest,
    delete_slide_from_manifest,
    get_slide_filename_by_count,
    is_slide_blank,
    load_manifest,
    save_manifest,
    set_slide_blank_status,
)
from .render import (
    create_blank_slide,
    delete_slide,
    load_slides_from_storage,
    upload_slide_content,
)
from .layouts import (
    get_all_templates,
    get_template_preview_image,
    get_template_slides_data,
)

__all__ = [
    # Manager
    "GetSVGCode",
    "is_empty_slide",
    "create_workspace",
    "create_workspace_folder",
    "copy_template_files",
    "fetch_workspace_history_from_storage",
    "delete_workspace_storage",
    "get_workspace",
    "update_workspace_source",
    "list_user_workspaces",
    "delete_workspace",
    # Manifest
    "load_manifest",
    "save_manifest",
    "add_slide_to_manifest",
    "delete_slide_from_manifest",
    "get_slide_filename_by_count",
    "is_slide_blank",
    "set_slide_blank_status",
    # Render
    "load_slides_from_storage",
    "create_blank_slide",
    "delete_slide",
    "upload_slide_content",
    # Templates
    "get_all_templates",
    "get_template_preview_image",
    "get_template_slides_data",
    # Downloads
    "compile_slides_to_pptx",
    "compile_and_save_pptx",
]
