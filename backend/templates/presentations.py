import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import create_engine, text

# Locate and load .env file
current_dir = Path(__file__).resolve().parent
if (current_dir.parent / ".env").exists():
    load_dotenv(dotenv_path=current_dir.parent / ".env")
elif (current_dir / ".env").exists():
    load_dotenv(dotenv_path=current_dir / ".env")
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:Nithin%4012@localhost:5432/kelostats")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

router = APIRouter(tags=["Presentation Templates"])


@router.get("/api/get/templates", summary="Get PPT templates from public.templates")
def get_templates():
    """
    Executes:
    SELECT * FROM public.templates
    ORDER BY template_id ASC

    Returns all presentation templates.
    """
    try:
        with engine.connect() as conn:
            query = text("SELECT * FROM public.templates ORDER BY template_id ASC;")
            result = conn.execute(query).fetchall()

            templates_list = []
            for row in result:
                mapping = row._mapping if hasattr(row, "_mapping") else dict(row)
                templates_list.append({
                    "template_id": str(mapping.get("template_id", "")),
                    "template_name": str(mapping.get("template_name", "")),
                    "category": str(mapping.get("category", "") or "")
                })

            return {
                "status": "success",
                "count": len(templates_list),
                "templates": templates_list
            }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch templates: {str(exc)}"
        )
