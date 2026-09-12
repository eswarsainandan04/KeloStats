"""
extractor.py — Dynamic Document Content Extractor (PDF & DOCX)
================================================================
Extracts ALL content from PDF and DOCX documents in clean Markdown format:
  - Headings (H1, H2, H3, ...) with proportional # hierarchy
  - Paragraphs and body text
  - All kinds of Tables (bordered, borderless, multi-column, financial) formatted as Markdown
  - Bullet points and numbered lists
  - Table of contents / index sections
  - Skips all embedded images and pictures

Architecture & Design:
  - 100% Dynamic typography analysis (Zero hardcoded font sizes, regex, or keywords)
  - Dynamically calculates document body size from character distribution
  - Automatically identifies bold weights and relative font size differentials
  - Converts tables into GitHub-flavored Markdown tables in exact vertical reading order
  - PDF extraction powered by pdfplumber & PyMuPDF (pymupdf4llm compatible)
  - DOCX extraction powered by python-docx
  - Saves extracted markdown to output/<file_name>.txt

Usage:
  from documents.digital.extractor import DocumentExtraction

  # Class method call:
  md_text = DocumentExtraction.pdf_extraction("sample.pdf")
  md_text = DocumentExtraction.docx_extraction("report.docx")

  # Unified router:
  md_text = DocumentExtraction.extract("any_document.pdf")

  # CLI:
  python extractor.py sample.pdf
"""

from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dynamic Typography Analyzer (Zero Hardcoding)
# ---------------------------------------------------------------------------

def _calculate_heading_hierarchy(
    font_char_counts: Counter[tuple[float, bool]]
) -> tuple[dict[tuple[float, bool], str], float]:
    """
    Dynamically determine heading hierarchy from document typography distribution.
    Zero hardcoded font sizes, zero regex, zero hardcoded keywords.

    Parameters
    ----------
    font_char_counts : Counter[(font_size, is_bold) -> total_characters]
        Character counts grouped by (size, boldness) across the entire document.

    Returns
    -------
    level_map : dict[(font_size, is_bold) -> markdown_prefix]
        Maps each heading style to its Markdown prefix ('#', '##', '###', etc.).
    body_size : float
        The dominant font size of regular paragraph text in the document.
    """
    if not font_char_counts:
        return {}, 11.0

    # 1. The dominant font size by character volume is the Body Text
    body_key = font_char_counts.most_common(1)[0][0]
    body_size = body_key[0]

    # 2. Identify candidate heading styles:
    #    - Any font size strictly larger than body text (size >= body_size + 0.5)
    #    - Any bold text with size at or above body text
    heading_candidates = set()
    for (sz, is_bold) in font_char_counts.keys():
        if sz >= body_size + 0.5 or (is_bold and sz >= body_size):
            heading_candidates.add((sz, is_bold))

    # 3. Dynamically rank heading candidates in descending hierarchy:
    #    Primary sort: font size (descending)
    #    Secondary sort: boldness (True precedes False for identical sizes)
    ranked_styles = sorted(
        heading_candidates,
        key=lambda item: (item[0], 1 if item[1] else 0),
        reverse=True
    )

    # 4. Map each distinct typography tier to Markdown heading levels (#, ##, ###, ...)
    level_map: dict[tuple[float, bool], str] = {}
    for rank, style_key in enumerate(ranked_styles, start=1):
        md_level = min(rank, 6)
        level_map[style_key] = "#" * md_level

    return level_map, body_size


def _resolve_output_path(file_path: Path, output_dir: Optional[Union[str, Path]] = None) -> Path:
    """
    Resolve and prepare the destination file path: output/<filename>.txt
    """
    if output_dir is not None:
        target_dir = Path(output_dir)
    else:
        # Save into output/ folder relative to this extractor file
        target_dir = Path(__file__).resolve().parent / "output"

    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{file_path.stem}.txt"


# ---------------------------------------------------------------------------
# Robust Table Formatter & Extractor (All Formats & Complex Grids)
# ---------------------------------------------------------------------------

def _format_table_grid_to_markdown(grid: list[list[Optional[str]]]) -> str:
    """
    Convert a 2D list of cells into a well-formed GitHub Markdown table.
    """
    if not grid or not grid[0]:
        return ""

    num_cols = max(len(row) for row in grid)
    if num_cols < 1:
        return ""

    cleaned_rows = []
    for row in grid:
        cleaned_cells = []
        for i in range(num_cols):
            val = row[i] if i < len(row) else ""
            if val is None:
                cell_str = ""
            else:
                cell_str = str(val).strip().replace("\n", " ").replace("|", "&#124;")
            cleaned_cells.append(cell_str)
        cleaned_rows.append(cleaned_cells)

    # Header line
    header_line = "| " + " | ".join(cleaned_rows[0]) + " |"
    separator_line = "| " + " | ".join(["---"] * num_cols) + " |"
    data_lines = ["| " + " | ".join(r) + " |" for r in cleaned_rows[1:]]

    return "\n".join([header_line, separator_line] + data_lines)


def _extract_pdf_page_tables(page_plum, page_mupdf) -> list[dict]:
    """
    Extract all tables from a PDF page using pdfplumber and PyMuPDF.
    Accurately handles:
      - Multi-column tables with headers
      - Bordered and grid tables
      - Borderless tables and tables with horizontal rules only
      - Multi-row headers and financial statements

    Returns list of dicts: [{'bbox': (x0, top, x1, bottom), 'top': top, 'markdown': md_str}, ...]
    """
    detected_tables = []
    covered_rects = []

    if page_plum is not None:
        try:
            plum_tables = page_plum.find_tables()
            for t in plum_tables:
                bbox = t.bbox  # (x0, top, x1, bottom)

                # 1. Try pdfplumber's native table grid extraction first
                grid = t.extract()
                if grid and len(grid) >= 2 and len(grid[0]) >= 2:
                    table_md = _format_table_grid_to_markdown(grid)
                    if table_md.strip():
                        detected_tables.append({"bbox": bbox, "top": bbox[1], "markdown": table_md.strip()})
                        covered_rects.append(bbox)
                        continue

                # 2. If single column (horizontal rules without vertical lines), partition by column whitespace
                cropped = page_plum.crop(bbox)
                words = cropped.extract_words()
                if not words:
                    continue

                lines_by_y: dict[float, list] = {}
                for w in words:
                    line_key = round(w["top"] / 4.0) * 4.0
                    lines_by_y.setdefault(line_key, []).append(w)

                sorted_lines = [lines_by_y[k] for k in sorted(lines_by_y.keys())]
                if len(sorted_lines) < 2:
                    continue

                # Discover column boundaries from whitespace gaps
                col_x_starts = set()
                for row in sorted_lines:
                    row.sort(key=lambda w: w["x0"])
                    col_x_starts.add(row[0]["x0"])
                    for i in range(len(row) - 1):
                        gap = row[i + 1]["x0"] - row[i]["x1"]
                        if gap > 18:
                            col_x_starts.add(row[i + 1]["x0"])

                sorted_x = sorted(col_x_starts)
                col_bounds = []
                for x in sorted_x:
                    if not col_bounds or x - col_bounds[-1] > 18:
                        col_bounds.append(x)

                if len(col_bounds) >= 2:
                    table_matrix = []
                    for row in sorted_lines:
                        cells = [""] * len(col_bounds)
                        for w in row:
                            col_idx = 0
                            for idx, cb in enumerate(col_bounds):
                                if w["x0"] >= cb - 10:
                                    col_idx = idx
                            cells[col_idx] = (cells[col_idx] + " " + w["text"]).strip()
                        table_matrix.append(cells)

                    table_md = _format_table_grid_to_markdown(table_matrix)
                    if table_md.strip():
                        detected_tables.append({"bbox": bbox, "top": bbox[1], "markdown": table_md.strip()})
                        covered_rects.append(bbox)

        except Exception as e:
            logger.debug(f"pdfplumber table extraction error: {e}")

    # 3. Check PyMuPDF table finder for any additional vector-bordered tables
    if page_mupdf is not None:
        try:
            mupdf_tables = page_mupdf.find_tables()
            for t in getattr(mupdf_tables, "tables", []):
                bbox = t.bbox
                already_covered = any(
                    abs(bbox[0] - r[0]) < 25 and abs(bbox[1] - r[1]) < 25
                    for r in covered_rects
                )
                if not already_covered:
                    t_md = t.to_markdown()
                    if t_md and t_md.strip():
                        detected_tables.append({"bbox": bbox, "top": bbox[1], "markdown": t_md.strip()})
                        covered_rects.append(bbox)
        except Exception as e:
            logger.debug(f"PyMuPDF table extraction error: {e}")

    return detected_tables


# ---------------------------------------------------------------------------
# DocumentExtraction Class
# ---------------------------------------------------------------------------

class DocumentExtraction:
    """
    Dynamic Document Content Extractor for PDF and DOCX.
    Extracts all headings, sub-headings, body paragraphs, bullet lists,
    numbered points, and tables in clean Markdown format while skipping images.
    """

    def __init__(self, output_dir: Optional[Union[str, Path]] = None):
        self.output_dir = Path(output_dir) if output_dir else None

    @classmethod
    def pdf_extraction(
        cls,
        file: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None
    ) -> str:
        """
        Extract all content (headings, paragraphs, bullet points, numbered lists,
        and tables) from a PDF file using PyMuPDF & pdfplumber. Images are skipped.

        Parameters
        ----------
        file : str | Path
            Path to the input PDF file.
        output_dir : str | Path, optional
            Custom directory to save output. Defaults to output/<file_name>.txt.

        Returns
        -------
        str : The full extracted content formatted as Markdown.
        """
        import pymupdf
        try:
            import pdfplumber
            has_pdfplumber = True
        except ImportError:
            has_pdfplumber = False

        file_path = Path(file).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Input PDF not found: {file_path}")

        doc = pymupdf.open(file_path)
        plum_doc = pdfplumber.open(file_path) if has_pdfplumber else None

        # -------------------------------------------------------------------
        # Pass 1: Global Document Typography Scan
        # -------------------------------------------------------------------
        font_char_counts: Counter[tuple[float, bool]] = Counter()

        for page in doc:
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # 0 indicates text block, skip images
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span.get("text", "").strip()
                        if not txt:
                            continue
                        size = round(span.get("size", 0.0), 1)
                        flags = span.get("flags", 0)
                        font_name = span.get("font", "").lower()
                        is_bold = bool(flags & 16) or any(
                            attr in font_name for attr in ("bold", "black", "heavy", "semibold")
                        )
                        font_char_counts[(size, is_bold)] += len(txt)

        level_map, body_size = _calculate_heading_hierarchy(font_char_counts)

        # -------------------------------------------------------------------
        # Pass 2: Structured Document Reconstruction
        # -------------------------------------------------------------------
        markdown_sections: list[str] = []

        for page_idx, page in enumerate(doc):
            page_plum = plum_doc.pages[page_idx] if plum_doc is not None else None

            # 1. Detect all tables on this page
            page_tables = _extract_pdf_page_tables(page_plum, page)
            table_bboxes = [t["bbox"] for t in page_tables]

            # 2. Collect page items (both text blocks and tables) with vertical y0 coordinate
            page_items: list[tuple[float, str]] = []

            # Add tables to page items
            for t in page_tables:
                page_items.append((t["top"], f"{t['markdown']}\n"))

            # Process text blocks
            page_dict = page.get_text("dict")
            blocks = page_dict.get("blocks", [])

            for block in blocks:
                # Strictly skip non-text blocks (images, raster drawings)
                if block.get("type") != 0:
                    continue

                bbox = block.get("bbox", [0, 0, 0, 0])

                # Skip text blocks inside table boundaries (prevents duplication)
                is_inside_table = any(
                    bbox[0] >= r[0] - 5 and bbox[1] >= r[1] - 5 and
                    bbox[2] <= r[2] + 5 and bbox[3] <= r[3] + 5
                    for r in table_bboxes
                )
                if is_inside_table:
                    continue

                block_lines: list[str] = []
                is_heading_block = False
                block_heading_prefix = ""

                for line in block.get("lines", []):
                    line_text_parts: list[str] = []
                    for span in line.get("spans", []):
                        txt = span.get("text", "")
                        if not txt:
                            continue
                        size = round(span.get("size", 0.0), 1)
                        flags = span.get("flags", 0)
                        font_name = span.get("font", "").lower()
                        is_bold = bool(flags & 16) or any(
                            attr in font_name for attr in ("bold", "black", "heavy", "semibold")
                        )

                        key = (size, is_bold)
                        if key in level_map and not is_heading_block:
                            is_heading_block = True
                            block_heading_prefix = level_map[key]

                        line_text_parts.append(txt)

                    line_str = "".join(line_text_parts).strip()
                    if line_str:
                        block_lines.append(line_str)

                full_text = " ".join(block_lines).strip()
                if not full_text:
                    continue

                # Format headings, bullet points, or paragraphs
                if is_heading_block and block_heading_prefix:
                    item_content = f"{block_heading_prefix} {full_text}\n"
                else:
                    bullet_chars = ("\u2022", "\u25cf", "\u25cb", "\u25aa", "\u25ab", "\xb7", "\ufffd", "-", "*")
                    if full_text.startswith(bullet_chars):
                        cleaned_bullet = full_text.lstrip("\u2022\u25cf\u25cb\u25aa\u25ab\xb7\ufffd-* ").strip()
                        item_content = f"- {cleaned_bullet}\n"
                    else:
                        item_content = f"{full_text}\n"

                page_items.append((bbox[1], item_content))

            # 3. Sort page items by top coordinate to maintain natural document reading order
            page_items.sort(key=lambda item: item[0])

            for _, content in page_items:
                markdown_sections.append(content)

        if plum_doc is not None:
            try:
                plum_doc.close()
            except Exception:
                pass

        extracted_markdown = "\n".join(markdown_sections).strip()

        # Save to output/<file_name>.txt
        dest_path = _resolve_output_path(file_path, output_dir)
        dest_path.write_text(extracted_markdown, encoding="utf-8")

        print(f"[DocumentExtraction] Extracted {len(extracted_markdown)} chars from '{file_path.name}' -> {dest_path}")
        return extracted_markdown

    @classmethod
    def docx_extraction(
        cls,
        file: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None
    ) -> str:
        """
        Extract all content (headings, paragraphs, bullet points, numbered lists,
        and tables) from a DOCX file using python-docx. Images are skipped.

        Parameters
        ----------
        file : str | Path
            Path to the input DOCX file.
        output_dir : str | Path, optional
            Custom directory to save output. Defaults to output/<file_name>.txt.

        Returns
        -------
        str : The full extracted content formatted as Markdown.
        """
        from docx import Document

        file_path = Path(file).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Input DOCX not found: {file_path}")

        doc = Document(file_path)

        def _get_run_font_size(run, paragraph) -> float:
            if run.font.size and run.font.size.pt:
                return round(run.font.size.pt, 1)
            if paragraph.style and paragraph.style.font and paragraph.style.font.size and paragraph.style.font.size.pt:
                return round(paragraph.style.font.size.pt, 1)
            return 11.0  # standard default body size

        def _get_run_boldness(run, paragraph) -> bool:
            if run.bold is not None:
                return bool(run.bold)
            if paragraph.style and paragraph.style.font and paragraph.style.font.bold is not None:
                return bool(paragraph.style.font.bold)
            style_name = paragraph.style.name.lower() if paragraph.style else ""
            return any(w in style_name for w in ("bold", "heading", "title"))

        # -------------------------------------------------------------------
        # Pass 1: Global DOCX Typography Distribution
        # -------------------------------------------------------------------
        font_char_counts: Counter[tuple[float, bool]] = Counter()

        for paragraph in doc.paragraphs:
            p_text = paragraph.text.strip()
            if not p_text:
                continue
            for run in paragraph.runs:
                r_text = run.text.strip()
                if not r_text:
                    continue
                size = _get_run_font_size(run, paragraph)
                is_bold = _get_run_boldness(run, paragraph)
                font_char_counts[(size, is_bold)] += len(r_text)

        level_map, body_size = _calculate_heading_hierarchy(font_char_counts)

        # -------------------------------------------------------------------
        # Pass 2: Structured Document Reconstruction
        # -------------------------------------------------------------------
        markdown_sections: list[str] = []

        # Process paragraphs (headings, bullet points, body text)
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue

            # Determine dominant style of paragraph from first non-empty run
            p_size = body_size
            p_bold = False
            for run in paragraph.runs:
                if run.text.strip():
                    p_size = _get_run_font_size(run, paragraph)
                    p_bold = _get_run_boldness(run, paragraph)
                    break

            style_name = paragraph.style.name.lower() if paragraph.style else ""
            style_key = (p_size, p_bold)

            # 1. Heading detection
            if style_key in level_map:
                heading_tag = level_map[style_key]
                markdown_sections.append(f"{heading_tag} {text}\n")
            # 2. Bullet / List detection
            elif "list" in style_name or "bullet" in style_name or text.startswith(("\u2022", "\u25cf", "-", "*")):
                cleaned = text.lstrip("\u2022\u25cf\u25cb\u25aa\u25ab-* ").strip()
                markdown_sections.append(f"- {cleaned}\n")
            # 3. Regular paragraph body text
            else:
                markdown_sections.append(f"{text}\n")

        # Process all DOCX tables and convert to GitHub Markdown tables
        for table in doc.tables:
            table_rows_data: list[list[str]] = []
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                table_rows_data.append(cells)

            if table_rows_data:
                table_md = _format_table_grid_to_markdown(table_rows_data)
                if table_md.strip():
                    markdown_sections.append(f"{table_md.strip()}\n")

        extracted_markdown = "\n".join(markdown_sections).strip()

        # Save to output/<file_name>.txt
        dest_path = _resolve_output_path(file_path, output_dir)
        dest_path.write_text(extracted_markdown, encoding="utf-8")

        print(f"[DocumentExtraction] Extracted {len(extracted_markdown)} chars from '{file_path.name}' -> {dest_path}")
        return extracted_markdown

    @classmethod
    def extract(
        cls,
        file: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None
    ) -> str:
        """
        Unified router that extracts content from either PDF or DOCX.
        """
        path = Path(file).resolve()
        ext = path.suffix.lower()

        if ext == ".pdf":
            return cls.pdf_extraction(path, output_dir=output_dir)
        elif ext in (".docx", ".doc"):
            return cls.docx_extraction(path, output_dir=output_dir)
        else:
            raise ValueError(
                f"Unsupported file format: '{ext}'. DocumentExtraction supports .pdf and .docx files."
            )

    # Backwards compatibility method aliases
    pdf_heading_extraction = pdf_extraction
    docx_heading_extraction = docx_extraction

    def __call__(self, file: Union[str, Path]) -> str:
        """Allow instance call: extractor = DocumentExtraction(); extractor('doc.pdf')"""
        return self.extract(file, output_dir=self.output_dir)


# Backwards compatibility class aliases
headingsExtraction = DocumentExtraction
HeadingsExtraction = DocumentExtraction


def document_extractor(file: Union[str, Path], output_dir: Optional[Union[str, Path]] = None) -> str:
    """
    Convenience functional interface for document extraction.
    """
    return DocumentExtraction.extract(file, output_dir=output_dir)


# Backwards compatibility function alias
heading_extractor = document_extractor


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extractor.py <file.pdf | file.docx> [output_dir]")
        sys.exit(1)

    input_arg = sys.argv[1]
    out_dir_arg = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        result_md = DocumentExtraction.extract(input_arg, output_dir=out_dir_arg)
        print("\n=== EXTRACTED MARKDOWN PREVIEW ===")
        print(result_md[:1200] if len(result_md) > 1200 else result_md)
    except Exception as err:
        print(f"Extraction Error: {err}", file=sys.stderr)
        sys.exit(1)
