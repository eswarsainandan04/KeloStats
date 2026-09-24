import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from dotenv import load_dotenv
import pymupdf
import pymupdf4llm

# Load .env file
backend_dir = Path(__file__).resolve().parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()


# Default Chunk Configuration
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


class ChunkList(list):
    """A list container for markdown chunks that behaves natively as List[str]

    for RAG vector embeddings, while formatting with visual separators when
    converted to string or printed.
    """

    def format(self) -> str:
        """Formats the chunks with the required separator lines."""
        parts = []
        for i, chunk in enumerate(self, 1):
            parts.append("--------------------------------")
            parts.append(f"chunk {i}:\n\n{chunk.strip()}\n")
        parts.append("--------------------------------")
        return "\n".join(parts)

    def __str__(self) -> str:
        return self.format()

    def __repr__(self) -> str:
        return self.format()


def is_title_line(line: str) -> bool:
    """Dynamically determines if a markdown line represents a title or heading.

    Matches:
    - ATX headings: # to ###### (e.g., '# Title', '###### **DBMS**')
    - Standalone bold lines: lines where the entire content consists of **bold** text
      (e.g., '**Database Management Systems**', '**UNIT-1**', '**Normalization in DBMS**')

    Ignores:
    - Ordered/unordered list items (e.g. '1. Item', '- Item')
    - Markdown table lines (e.g. '| Col 1 | Col 2 |')
    - Inline definitions where bold is followed by normal text (e.g. '**Data** : Facts, figures...')
    """
    s = line.strip()
    if not s or len(s) > 200:
        return False

    # ATX headings (# through ######)
    if re.match(r"^#{1,6}\s+", s):
        return True

    # List items are not titles
    if re.match(r"^(?:[0-9]+[.)]|[-*+])\s+", s):
        return False

    # Table rows are not titles
    if s.startswith("|") and s.endswith("|"):
        return False

    # Standalone bold line: entire line (excluding optional trailing : or .) is bold
    cleaned = re.sub(r"[:.]\s*$", "", s).strip()
    if re.fullmatch(r"(\*\*[^*]+?\*\*\s*)+", cleaned):
        return True

    return False


def is_table_delimiter(line: str) -> bool:
    """Checks if a line is a markdown table separator row (|---|---|)."""
    s = line.strip()
    return bool(re.match(r"^\|?(\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?$", s))


def parse_markdown_blocks(text: str) -> List[Tuple[str, str]]:
    """Dynamically parses raw markdown text into semantic blocks:

    - 'title': heading text (consecutive heading lines are merged into composite titles)
    - 'table': intact markdown tables
    - 'paragraph': body text paragraphs, lists, and other text units
    """
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: List[Tuple[str, str]] = []
    i = 0
    n = len(lines)
    current_text_lines: List[str] = []

    def flush_text():
        if current_text_lines:
            content = "\n".join(current_text_lines).strip()
            if content:
                # Split content into paragraphs by double newlines
                paragraphs = re.split(r"\n\s*\n", content)
                for p in paragraphs:
                    p_str = p.strip()
                    if p_str:
                        blocks.append(("paragraph", p_str))
            current_text_lines.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 1. Detect markdown table
        if stripped.startswith("|") and stripped.endswith("|"):
            tbl_lines = [lines[i]]
            j = i + 1
            while (
                j < n
                and lines[j].strip().startswith("|")
                and lines[j].strip().endswith("|")
            ):
                tbl_lines.append(lines[j])
                j += 1
            if len(tbl_lines) >= 2 and any(
                is_table_delimiter(l) for l in tbl_lines
            ):
                flush_text()
                blocks.append(("table", "\n".join(tbl_lines).strip()))
                i = j
                continue

        # 2. Detect title line (grouping consecutive title lines)
        if is_title_line(line):
            flush_text()
            title_lines = [stripped]
            j = i + 1
            while j < n:
                next_l = lines[j].strip()
                if not next_l:
                    j += 1
                    continue
                if is_title_line(next_l):
                    title_lines.append(next_l)
                    j += 1
                else:
                    break
            blocks.append(("title", "\n\n".join(title_lines)))
            i = j
            continue

        # 3. Accumulate regular body line
        current_text_lines.append(line)
        i += 1

    flush_text()
    return blocks


def split_long_text(text: str, max_chars: int, overlap: int) -> List[str]:
    """Splits a lengthy text block into sub-chunks respecting sentence and word boundaries,

    with a sliding overlap window so context is preserved smoothly.
    """
    if len(text) <= max_chars:
        return [text.strip()]

    pieces: List[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            cut = -1
            # Prefer sentence punctuation
            for punct in (
                ".\n",
                ". ",
                "?\n",
                "? ",
                "!\n",
                "! ",
                ";\n",
                "; ",
                ":\n",
            ):
                pos = text.rfind(punct, start + max_chars // 2, end)
                if pos != -1:
                    cut = pos + len(punct)
                    break
            # Fallback to newline
            if cut == -1:
                nl_pos = text.rfind("\n", start + max_chars // 2, end)
                if nl_pos != -1:
                    cut = nl_pos + 1
            # Fallback to word boundary
            if cut == -1:
                sp_pos = text.rfind(" ", start + max_chars // 2, end)
                if sp_pos != -1:
                    cut = sp_pos + 1
                else:
                    cut = end
        else:
            cut = n

        piece = text[start:cut].strip()
        if piece:
            pieces.append(piece)

        if cut >= n:
            break

        # Calculate next start with sliding overlap, snapping to a word boundary
        next_start = max(start + 1, cut - overlap)
        sp_pos = text.rfind(" ", start, next_start)
        if sp_pos != -1 and sp_pos >= start:
            next_start = sp_pos + 1
        start = next_start

    return pieces


_MODEL_CACHE: Dict[str, Any] = {}


class PDFProcessor:
    """Document processing module using PyMuPDF and PyMuPDF4LLM.

    Extracts clean Markdown from PDF files (ignoring header/footer borders)
    and segments the text into semantically cohesive RAG chunks with:
    - Contextual heading preservation and overlap
    - Atomic table isolation with topic titles
    - Dynamic adaptive half-page chunk sizing
    """

    def __init__(
        self,
        file: Optional[str] = None,
        margins: Tuple[float, float, float, float] = (0, 40, 0, 40),
    ):
        self.file = file
        self.margins = margins
        self.page_count: Optional[int] = None
        self.extracted_text: Optional[str] = None
        self.chunks: Optional[ChunkList] = None

    def document_extractor(
        self,
        file: Optional[str] = None,
        margins: Optional[Tuple[float, float, float, float]] = None,
    ) -> str:
        """Extracts PDF text to markdown, ignoring borders like headers & footers
        of the PDF page layout.
        """
        # Support calling as static/class function or instance method
        if not isinstance(self, PDFProcessor):
            file_path = self
            proc = PDFProcessor(file=file_path)
            return proc.document_extractor(file=file_path, margins=margins)

        target_file = file or self.file
        if not target_file:
            raise ValueError(
                "No PDF file specified for document extraction. Please provide a file path."
            )

        active_margins = (
            margins if margins is not None else (self.margins or (0, 40, 0, 40))
        )

        input_type = "raw bytes" if isinstance(target_file, (bytes, bytearray)) else getattr(target_file, "filename", str(target_file))
        print(f"[PDFProcessor] Starting document extraction ({input_type})...")

        # Open document to track page count and layout metrics (supports filepath, bytes, UploadFile, stream)
        if isinstance(target_file, (bytes, bytearray)):
            doc = pymupdf.open(stream=target_file, filetype="pdf")
        elif hasattr(target_file, "file"):
            file_data = target_file.file.read()
            if hasattr(target_file.file, "seek"):
                target_file.file.seek(0)
            doc = pymupdf.open(stream=file_data, filetype="pdf")
        elif hasattr(target_file, "read"):
            file_data = target_file.read()
            if hasattr(target_file, "seek"):
                target_file.seek(0)
            doc = pymupdf.open(stream=file_data, filetype="pdf")
        else:
            doc = pymupdf.open(target_file)

        self.page_count = len(doc)
        print(f"[PDFProcessor] PDF opened successfully. Total pages: {self.page_count}")

        try:
            # Extract markdown with margin clipping to remove header/footer noise
            print(f"[PDFProcessor] Converting layout to Markdown (margins={active_margins})...")
            raw_markdown = pymupdf4llm.to_markdown(doc, margins=active_margins)
        finally:
            doc.close()

        # Clean extraneous trailing/leading whitespace and blank page artifacts
        cleaned_markdown = re.sub(r"\n{4,}", "\n\n\n", raw_markdown).strip()
        self.extracted_text = cleaned_markdown
        print(f"[PDFProcessor] [+] Document extraction complete: {len(cleaned_markdown)} characters extracted.")
        return cleaned_markdown

    def pdf_chunker(
        self,
        text: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> ChunkList:
        """Splits markdown text into cohesive RAG chunks adhering to:
        1. Multi-Topic Budget Packing: Small topics (title + context) are accumulated into a single chunk
           (fitting 1, 2, 3, 4 topics) as long as their combined text stays within CHUNK_SIZE.
        2. Boundary Overflow Rule: If topics fit into the current chunk but adding the next topic would
           exceed CHUNK_SIZE, the current chunk is finalized immediately and the next topic begins cleanly
           in a new chunk (even if some space remains).
        3. Large Topic Splitting: When a single topic's context is very large (exceeding CHUNK_SIZE), it is split
           into 2, 3 or more sub-chunks, with each sub-chunk retaining the topic heading prepended at the top.
        4. Atomic Table Preservation: Tables within topics remain intact and are preserved with topic headings.
        """
        # Support calling as static/class function or instance method
        if not isinstance(self, PDFProcessor):
            text_arg = self
            proc = PDFProcessor()
            return proc.pdf_chunker(text=text_arg, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        target_text = text if text is not None else self.extracted_text
        if not target_text:
            raise ValueError(
                "No text provided for chunking. Provide text or run document_extractor() first."
            )

        effective_chunk_size = chunk_size if chunk_size is not None else CHUNK_SIZE
        effective_overlap = chunk_overlap if chunk_overlap is not None else CHUNK_OVERLAP
        print(f"[PDFProcessor] Starting chunking (chunk_size={effective_chunk_size}, overlap={effective_overlap})...")

        blocks = parse_markdown_blocks(target_text)
        print(f"[PDFProcessor] Parsed text into {len(blocks)} semantic markdown block(s).")

        # 1. Group parsed blocks into logical Topic Sections (composite title + content items)
        class Section:
            def __init__(self, title: str = ""):
                self.title = title.strip()
                self.items: List[Tuple[str, str]] = []

        sections: List[Section] = []
        current_sec = Section(title="")

        for block_type, content in blocks:
            if block_type == "title":
                if current_sec.items:
                    # Finalize current section since it already has content
                    sections.append(current_sec)
                    current_sec = Section(title=content)
                elif current_sec.title:
                    # Merge hierarchical consecutive titles (e.g. Unit title + Chapter title)
                    current_sec.title = f"{current_sec.title}\n\n{content}".strip()
                else:
                    current_sec.title = content.strip()
            else:
                current_sec.items.append((block_type, content))

        if current_sec.title or current_sec.items:
            sections.append(current_sec)

        # 2. Build chunks respecting chunk budget and topic boundaries
        chunks = ChunkList()
        current_chunk_parts: List[str] = []

        def current_len() -> int:
            if not current_chunk_parts:
                return 0
            return sum(len(p) for p in current_chunk_parts) + (len(current_chunk_parts) - 1) * 2

        def flush_current_chunk():
            nonlocal current_chunk_parts
            if current_chunk_parts:
                chunk_str = "\n\n".join(current_chunk_parts).strip()
                if chunk_str:
                    chunks.append(chunk_str)
                current_chunk_parts = []

        for sec in sections:
            sec_title = sec.title
            body = "\n\n".join(content for _, content in sec.items).strip()

            if sec_title and body:
                sec_full = f"{sec_title}\n\n{body}"
            elif sec_title:
                sec_full = sec_title
            else:
                sec_full = body

            if not sec_full:
                continue

            sec_len = len(sec_full)

            # Scenario A: Topic fits within effective_chunk_size
            if sec_len <= effective_chunk_size:
                c_len = current_len()
                needed_len = c_len + (2 if c_len > 0 else 0) + sec_len

                if needed_len <= effective_chunk_size:
                    # Fits alongside previous topic(s) in current chunk
                    current_chunk_parts.append(sec_full)
                else:
                    # Adding this topic would exceed chunk size budget -> flush current chunk, start fresh in next one
                    flush_current_chunk()
                    current_chunk_parts.append(sec_full)

            # Scenario B: Topic context is very large (exceeds effective_chunk_size)
            else:
                # Flush whatever was pending in current chunk so large topic starts clean
                flush_current_chunk()

                title_prefix_len = (len(sec_title) + 2) if sec_title else 0
                available_budget = max(200, effective_chunk_size - title_prefix_len)

                sub_chunk_items: List[str] = []

                def sub_chunk_len() -> int:
                    if not sub_chunk_items:
                        return 0
                    return sum(len(x) for x in sub_chunk_items) + (len(sub_chunk_items) - 1) * 2

                def flush_sub_chunk():
                    nonlocal sub_chunk_items
                    if sub_chunk_items:
                        content_str = "\n\n".join(sub_chunk_items).strip()
                        if content_str:
                            ch = f"{sec_title}\n\n{content_str}" if sec_title else content_str
                            chunks.append(ch)
                        sub_chunk_items = []

                if not sec.items:
                    # Fallback for rare case where title itself is huge
                    sub_pieces = split_long_text(
                        sec_full,
                        max_chars=effective_chunk_size,
                        overlap=effective_overlap,
                    )
                    for piece in sub_pieces:
                        chunks.append(piece)
                else:
                    for item_type, item_content in sec.items:
                        item_len = len(item_content)

                        if item_len <= available_budget:
                            if sub_chunk_len() + (2 if sub_chunk_items else 0) + item_len <= available_budget:
                                sub_chunk_items.append(item_content)
                            else:
                                flush_sub_chunk()
                                sub_chunk_items.append(item_content)
                        else:
                            # Individual item itself exceeds available_budget
                            flush_sub_chunk()
                            if item_type == "table":
                                # Keep markdown table atomic in its own chunk with topic title
                                ch = f"{sec_title}\n\n{item_content}" if sec_title else item_content
                                chunks.append(ch)
                            else:
                                # Split large paragraph into sub-pieces, keeping topic heading on each
                                sub_pieces = split_long_text(
                                    item_content,
                                    max_chars=available_budget,
                                    overlap=effective_overlap,
                                )
                                for piece in sub_pieces:
                                    ch = f"{sec_title}\n\n{piece}" if sec_title else piece
                                    chunks.append(ch)

                    flush_sub_chunk()

        flush_current_chunk()
        self.chunks = chunks
        print(f"[PDFProcessor] [+] Chunking complete: Generated {len(chunks)} cohesive RAG chunk(s).")
        return chunks

    def generate_embeddings(
        self,
        chunks: Optional[Union[ChunkList, List[str], str]] = None,
        embedding_model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Generates embeddings for each chunk and returns a JSON-format list:
        [
            {
                "embeddings": [0.122, 0.234, 0.214, ...],
                "context": "..."
            },
            ...
        ]

        Args:
            chunks: The chunks to embed (ChunkList, list of strings, or single string).
                    If None, uses self.chunks from previous pdf_chunker() call.
            embedding_model: Optional model name (defaults to EMBEDDING_MODEL in .env or 'all-MiniLM-L6-v2').

        Returns:
            embedded_chunks: List of dicts with 'embeddings' and 'context'.
        """
        target_chunks = chunks if chunks is not None else self.chunks
        if target_chunks is None:
            raise ValueError(
                "No chunks available to embed. Provide chunks or run pdf_chunker() first."
            )

        # Normalize chunks input to a list of strings
        if isinstance(target_chunks, str):
            chunk_list = [target_chunks]
        elif isinstance(target_chunks, list):
            chunk_list = [str(c) for c in target_chunks]
        else:
            chunk_list = [str(target_chunks)]

        if not chunk_list:
            print("[PDFProcessor] [!] No chunks provided to generate embeddings.")
            return []

        # Resolve model name from argument or .env
        model_name = (
            embedding_model.strip()
            if (embedding_model and str(embedding_model).strip())
            else os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        )

        print(f"[PDFProcessor] Starting vector embeddings generation for {len(chunk_list)} chunk(s)...")

        if model_name not in _MODEL_CACHE:
            print(f"[PDFProcessor] Loading embedding model '{model_name}' into memory...")
            from sentence_transformers import SentenceTransformer
            _MODEL_CACHE[model_name] = SentenceTransformer(model_name)
            print(f"[PDFProcessor] [+] Embedding model '{model_name}' loaded successfully.")
        else:
            print(f"[PDFProcessor] Using cached embedding model '{model_name}'.")

        model = _MODEL_CACHE[model_name]

        # Generate embeddings for each chunk
        print(f"[PDFProcessor] Encoding {len(chunk_list)} chunk(s) into vector space...")
        raw_embeddings = model.encode(
            chunk_list,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        embedded_chunks: List[Dict[str, Any]] = []
        for text_chunk, emb in zip(chunk_list, raw_embeddings):
            vector_list = (
                emb.tolist() if hasattr(emb, "tolist") else [float(x) for x in emb]
            )
            embedded_chunks.append({
                "embeddings": vector_list,
                "context": text_chunk,
            })

        dim = len(embedded_chunks[0]["embeddings"]) if embedded_chunks else 0
        print(f"[PDFProcessor] [+] Generated embeddings for {len(embedded_chunks)} chunk(s) (vector dimension: {dim}).")
        return embedded_chunks