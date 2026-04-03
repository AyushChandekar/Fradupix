"""
Vectorless RAG Service (SRS FR-800)
Structural document retrieval without vector embeddings.
Parses multi-page documents into a Page Index, auto-generates a Table of Contents,
and resolves cross-reference queries by targeting exact pages/sections.

FR-801: Parse structural hierarchy and store Page Index in PostgreSQL
FR-802: Auto-generate Table of Contents for documents exceeding 3 pages
FR-803: Resolve cross-reference queries via Page Index lookup
FR-804: Log every retrieval operation with full audit context
FR-806: Structured document queries returning exact page/section locations
"""
import io
import re
import uuid
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image
import pytesseract
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.database import SessionLocal
from app.models import PageIndex, DocumentTOC, RAGRetrievalLog, Invoice

logger = logging.getLogger(__name__)

# pdf2image import (optional -- single-page image fallback when unavailable)
try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not available - PDF multi-page extraction disabled")


# ---------------------------------------------------------------------------
# Heading detection heuristics
# ---------------------------------------------------------------------------

# Regex patterns ranked by heading level.
# Level 1: document/section titles (ALL CAPS, or common top-level labels)
# Level 2: sub-section labels
# Level 3: minor headings / labelled paragraphs
_HEADING_PATTERNS: List[Tuple[re.Pattern, int]] = [
    # ALL-CAPS lines that look like titles (>= 3 words or a known label)
    (re.compile(r"^([A-Z][A-Z0-9 /&\-]{4,})$", re.MULTILINE), 1),
    # Numbered sections like "1. Introduction", "2.1 Scope"
    (re.compile(
        r"^(\d+(?:\.\d+)*)\s+([A-Z][A-Za-z0-9 ,\-/&]+)$", re.MULTILINE
    ), 2),
    # Common invoice/document headings
    (re.compile(
        r"^(INVOICE|BILL TO|SHIP TO|PAYMENT TERMS|TERMS AND CONDITIONS"
        r"|DESCRIPTION|ITEM|QTY|QUANTITY|UNIT PRICE|AMOUNT|SUBTOTAL"
        r"|TOTAL|TAX|NOTES|REMITTANCE|PURCHASE ORDER"
        r"|SUMMARY|APPENDIX|ANNEX|SCHEDULE|EXHIBIT)\b.*$",
        re.MULTILINE | re.IGNORECASE,
    ), 2),
    # Title-case lines of moderate length (likely sub-headings)
    (re.compile(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,6})\s*$", re.MULTILINE), 3),
]

# Content-type classifiers applied to each text block
_TABLE_INDICATOR = re.compile(
    r"(\|.*\|)|(\+[-+]+\+)|(\t.*\t.*\t)", re.MULTILINE
)
_NUMERIC_LINE = re.compile(r"^\s*[\d,]+\.?\d*\s*$", re.MULTILINE)

# Fields useful for cross-reference comparisons
_CROSS_REF_FIELDS = [
    "invoice_number", "vendor_name", "total_amount",
    "invoice_date", "buyer_name", "subtotal", "tax_amount",
]

# Maximum characters stored in content_preview
_PREVIEW_LIMIT = 500


class VectorlessRAGService:
    """
    Vectorless Retrieval-Augmented Generation service.

    Instead of embedding documents into a vector space this service builds a
    *structural index* (Page Index + TOC) that allows deterministic,
    auditable retrieval of exact pages and sections.
    """

    # ------------------------------------------------------------------
    # FR-801 / FR-802  -  Document indexing
    # ------------------------------------------------------------------

    def index_document(
        self,
        document_id: uuid.UUID,
        file_bytes: bytes,
        db: Session,
    ) -> Dict[str, Any]:
        """
        Parse a document, build Page Index entries, and auto-generate a TOC.

        Supports PDF (multi-page via pdf2image + pytesseract) and single-page
        images (PNG, JPEG, TIFF).

        Returns a summary dict with page_count, index_entries, and toc_entries.
        """
        # Determine document type
        is_pdf = file_bytes[:5] == b"%PDF-"

        if is_pdf and PDF2IMAGE_AVAILABLE:
            pages = self._extract_pages_from_pdf(file_bytes)
        else:
            # Treat as single-page image
            pages = self._extract_pages_from_image(file_bytes)

        page_count = len(pages)
        logger.info(
            "RAG index_document: document_id=%s, pages=%d, is_pdf=%s",
            document_id, page_count, is_pdf,
        )

        # Remove any stale index / TOC rows for this document
        self._purge_existing_index(document_id, db)

        # Build page index entries (FR-801)
        all_index_entries: List[PageIndex] = []
        all_headings: List[Dict[str, Any]] = []  # collected for TOC generation

        running_byte_offset = 0

        for page_num, page_text in pages:
            sections = self._segment_page(page_text)
            for section in sections:
                content_type = section["content_type"]
                heading = section.get("heading")
                text_block = section["text"]
                block_bytes = len(text_block.encode("utf-8"))

                entry = PageIndex(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    page_number=page_num,
                    section_heading=heading,
                    content_type=content_type,
                    byte_offset_start=running_byte_offset,
                    byte_offset_end=running_byte_offset + block_bytes,
                    content_preview=text_block[:_PREVIEW_LIMIT],
                )
                all_index_entries.append(entry)

                if heading:
                    all_headings.append({
                        "title": heading,
                        "page_number": page_num,
                        "level": section.get("level", 2),
                    })

                running_byte_offset += block_bytes

        db.bulk_save_objects(all_index_entries)

        # Auto-generate TOC (FR-802) - only for documents exceeding 3 pages
        toc_entries_created = 0
        if page_count > 3:
            toc_entries_created = self._build_toc(
                document_id, all_headings, db,
            )

        db.commit()

        summary = {
            "document_id": str(document_id),
            "page_count": page_count,
            "index_entries": len(all_index_entries),
            "toc_entries": toc_entries_created,
            "headings_detected": len(all_headings),
        }
        logger.info("RAG indexing complete: %s", summary)
        return summary

    # ------------------------------------------------------------------
    # FR-803 / FR-806  -  Query resolution
    # ------------------------------------------------------------------

    def query_document(
        self,
        query: str,
        document_id: uuid.UUID,
        db: Session,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        Resolve a free-text query against the Page Index for a document.

        Strategy:
        1. Normalise query tokens.
        2. Search section_heading and content_preview for keyword overlap.
        3. Rank results by relevance (heading match > preview match).
        4. Log the retrieval (FR-804).
        5. Return structured results with page/section/snippet (FR-806).
        """
        query_lower = query.lower().strip()
        tokens = self._tokenise(query_lower)

        if not tokens:
            return {"results": [], "query": query, "message": "Empty query"}

        # Fetch all page index rows for this document
        index_rows: List[PageIndex] = (
            db.query(PageIndex)
            .filter(PageIndex.document_id == document_id)
            .order_by(PageIndex.page_number, PageIndex.byte_offset_start)
            .all()
        )

        scored_results: List[Tuple[float, PageIndex]] = []

        for row in index_rows:
            score = self._score_match(tokens, row)
            if score > 0:
                scored_results.append((score, row))

        # Sort descending by relevance score
        scored_results.sort(key=lambda x: x[0], reverse=True)

        # Build response with top results (capped at 10)
        results: List[Dict[str, Any]] = []
        for rank, (score, row) in enumerate(scored_results[:10], start=1):
            results.append({
                "rank": rank,
                "page_number": row.page_number,
                "section_heading": row.section_heading,
                "content_type": row.content_type,
                "byte_offset_start": row.byte_offset_start,
                "byte_offset_end": row.byte_offset_end,
                "content_snippet": row.content_preview,
                "relevance_score": round(score, 4),
            })

        # FR-804: Log retrieval
        top_row = scored_results[0][1] if scored_results else None
        self._log_retrieval(
            db=db,
            query_text=query,
            document_id=document_id,
            page_number=top_row.page_number if top_row else None,
            section_identifier=top_row.section_heading if top_row else None,
            byte_offset=top_row.byte_offset_start if top_row else None,
            query_context=f"query_document | tokens={tokens} | hits={len(scored_results)}",
            user_id=user_id,
        )
        db.commit()

        return {
            "query": query,
            "document_id": str(document_id),
            "total_matches": len(scored_results),
            "results": results,
        }

    # ------------------------------------------------------------------
    # FR-802  -  Table of Contents retrieval
    # ------------------------------------------------------------------

    def get_toc(
        self,
        document_id: uuid.UUID,
        db: Session,
    ) -> Dict[str, Any]:
        """
        Return the auto-generated Table of Contents for a document.

        The TOC is built during index_document for documents exceeding 3 pages.
        For shorter documents, an empty list is returned.
        """
        toc_rows: List[DocumentTOC] = (
            db.query(DocumentTOC)
            .filter(DocumentTOC.document_id == document_id)
            .order_by(DocumentTOC.page_number, DocumentTOC.level)
            .all()
        )

        entries = [
            {
                "id": str(row.id),
                "entry_title": row.entry_title,
                "page_number": row.page_number,
                "level": row.level,
                "parent_entry_id": str(row.parent_entry_id) if row.parent_entry_id else None,
            }
            for row in toc_rows
        ]

        return {
            "document_id": str(document_id),
            "total_entries": len(entries),
            "entries": entries,
        }

    # ------------------------------------------------------------------
    # FR-803  -  Cross-reference resolution
    # ------------------------------------------------------------------

    def cross_reference(
        self,
        invoice_id: uuid.UUID,
        target_doc_id: uuid.UUID,
        field_type: str,
        db: Session,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        Compare a specific field between two documents by querying the Page
        Index of each for the relevant section.

        *field_type* should be one of the standard invoice fields
        (e.g. ``'total_amount'``, ``'vendor_name'``, ``'invoice_number'``).

        Returns matched sections from both documents with content snippets
        so the caller can verify field consistency.
        """
        search_terms = self._field_type_to_keywords(field_type)

        source_hits = self._search_index(invoice_id, search_terms, db)
        target_hits = self._search_index(target_doc_id, search_terms, db)

        # Also pull denormalised fields from the Invoice table for comparison
        source_invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        target_invoice = db.query(Invoice).filter(Invoice.id == target_doc_id).first()

        source_value = self._extract_invoice_field(source_invoice, field_type)
        target_value = self._extract_invoice_field(target_invoice, field_type)

        match_status = "match" if source_value and source_value == target_value else "mismatch"
        if source_value is None or target_value is None:
            match_status = "incomplete"

        # FR-804: Log the cross-reference retrieval
        self._log_retrieval(
            db=db,
            query_text=f"cross_reference:{field_type}",
            document_id=invoice_id,
            page_number=source_hits[0]["page_number"] if source_hits else None,
            section_identifier=field_type,
            byte_offset=source_hits[0]["byte_offset_start"] if source_hits else None,
            query_context=(
                f"cross_reference | source={invoice_id} | "
                f"target={target_doc_id} | field={field_type}"
            ),
            user_id=user_id,
        )
        db.commit()

        return {
            "field_type": field_type,
            "source_document_id": str(invoice_id),
            "target_document_id": str(target_doc_id),
            "source_value": str(source_value) if source_value else None,
            "target_value": str(target_value) if target_value else None,
            "match_status": match_status,
            "source_sections": source_hits[:5],
            "target_sections": target_hits[:5],
        }

    # ==================================================================
    # PRIVATE HELPERS
    # ==================================================================

    # ---- PDF / Image page extraction ---------------------------------

    def _extract_pages_from_pdf(
        self, file_bytes: bytes
    ) -> List[Tuple[int, str]]:
        """Convert each PDF page to an image and OCR it."""
        pages: List[Tuple[int, str]] = []
        try:
            images = convert_from_bytes(file_bytes, dpi=300)
            for idx, img in enumerate(images, start=1):
                text = pytesseract.image_to_string(img)
                pages.append((idx, text))
        except Exception as exc:
            logger.error("PDF page extraction failed: %s", exc)
            # Fallback: try treating the whole blob as a single image
            pages = self._extract_pages_from_image(file_bytes)
        return pages

    def _extract_pages_from_image(
        self, file_bytes: bytes
    ) -> List[Tuple[int, str]]:
        """OCR a single-page image (PNG/JPEG/TIFF)."""
        try:
            img = Image.open(io.BytesIO(file_bytes))
            text = pytesseract.image_to_string(img)
            return [(1, text)]
        except Exception as exc:
            logger.error("Image OCR failed: %s", exc)
            return [(1, "")]

    # ---- Page segmentation & heading detection -----------------------

    def _segment_page(self, page_text: str) -> List[Dict[str, Any]]:
        """
        Split a page's raw OCR text into logical sections.

        Each section has:
        - ``heading``: detected heading text (or None)
        - ``level``: heading level (1-3) if heading detected
        - ``content_type``: 'heading', 'table', or 'text'
        - ``text``: the raw text of the section
        """
        if not page_text or not page_text.strip():
            return [{
                "heading": None,
                "content_type": "text",
                "text": "",
            }]

        # Identify heading line positions
        heading_spans: List[Dict[str, Any]] = []
        for pattern, level in _HEADING_PATTERNS:
            for match in pattern.finditer(page_text):
                heading_spans.append({
                    "start": match.start(),
                    "end": match.end(),
                    "text": match.group(0).strip(),
                    "level": level,
                })

        # De-duplicate overlapping spans (keep the one with lower level = higher priority)
        heading_spans.sort(key=lambda h: (h["start"], h["level"]))
        deduped: List[Dict[str, Any]] = []
        for span in heading_spans:
            if deduped and span["start"] < deduped[-1]["end"]:
                # Overlapping -- keep the one with smaller (more important) level
                if span["level"] < deduped[-1]["level"]:
                    deduped[-1] = span
                continue
            deduped.append(span)

        if not deduped:
            # No headings detected -- return entire page as one section
            return [{
                "heading": None,
                "content_type": self._classify_content(page_text),
                "text": page_text.strip(),
            }]

        sections: List[Dict[str, Any]] = []

        # Text before the first heading
        if deduped[0]["start"] > 0:
            pre_text = page_text[: deduped[0]["start"]].strip()
            if pre_text:
                sections.append({
                    "heading": None,
                    "content_type": self._classify_content(pre_text),
                    "text": pre_text,
                })

        # Each heading + the text following it until the next heading
        for i, hspan in enumerate(deduped):
            body_start = hspan["end"]
            body_end = deduped[i + 1]["start"] if i + 1 < len(deduped) else len(page_text)
            body_text = page_text[body_start:body_end].strip()

            full_text = hspan["text"]
            if body_text:
                full_text = f"{hspan['text']}\n{body_text}"

            sections.append({
                "heading": hspan["text"],
                "level": hspan["level"],
                "content_type": self._classify_content(body_text) if body_text else "heading",
                "text": full_text,
            })

        return sections

    @staticmethod
    def _classify_content(text: str) -> str:
        """Heuristically classify a text block as 'table' or 'text'."""
        if _TABLE_INDICATOR.search(text):
            return "table"
        # If more than 40% of non-empty lines are purely numeric, treat as table
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if lines:
            numeric_count = sum(1 for ln in lines if _NUMERIC_LINE.match(ln))
            if numeric_count / len(lines) > 0.4:
                return "table"
        return "text"

    # ---- TOC generation (FR-802) -------------------------------------

    def _build_toc(
        self,
        document_id: uuid.UUID,
        headings: List[Dict[str, Any]],
        db: Session,
    ) -> int:
        """
        Build DocumentTOC rows from detected headings.

        Establishes parent-child relationships based on heading level:
        a level-2 heading becomes a child of the most recent level-1 heading.
        """
        if not headings:
            return 0

        toc_entries: List[DocumentTOC] = []
        # Stack tracks the most recent entry at each level for parenting
        level_stack: Dict[int, uuid.UUID] = {}

        for h in headings:
            entry_id = uuid.uuid4()
            level = h["level"]

            # Determine parent: closest ancestor with a lower level number
            parent_id = None
            for check_level in range(level - 1, 0, -1):
                if check_level in level_stack:
                    parent_id = level_stack[check_level]
                    break

            entry = DocumentTOC(
                id=entry_id,
                document_id=document_id,
                entry_title=h["title"][:500],
                page_number=h["page_number"],
                level=level,
                parent_entry_id=parent_id,
            )
            toc_entries.append(entry)
            level_stack[level] = entry_id

            # Clear deeper levels when a higher-level heading appears
            for deeper in list(level_stack.keys()):
                if deeper > level:
                    del level_stack[deeper]

        db.bulk_save_objects(toc_entries)
        return len(toc_entries)

    # ---- Purge stale data --------------------------------------------

    @staticmethod
    def _purge_existing_index(document_id: uuid.UUID, db: Session) -> None:
        """Remove old Page Index and TOC rows for a document before re-indexing."""
        db.query(PageIndex).filter(PageIndex.document_id == document_id).delete()
        db.query(DocumentTOC).filter(DocumentTOC.document_id == document_id).delete()

    # ---- Query scoring -----------------------------------------------

    @staticmethod
    def _tokenise(text: str) -> List[str]:
        """Split text into lowercase alpha-numeric tokens, dropping noise."""
        raw = re.findall(r"[a-z0-9]+", text.lower())
        # Filter out very short tokens that add noise
        stopwords = {
            "the", "a", "an", "is", "in", "on", "at", "to", "of",
            "and", "or", "for", "it", "by", "as", "be", "was",
        }
        return [t for t in raw if len(t) > 1 and t not in stopwords]

    @staticmethod
    def _score_match(tokens: List[str], row: PageIndex) -> float:
        """
        Score how well a Page Index row matches the query tokens.

        Heading matches are weighted 3x over preview matches.
        """
        score = 0.0
        heading_lower = (row.section_heading or "").lower()
        preview_lower = (row.content_preview or "").lower()

        for token in tokens:
            if token in heading_lower:
                score += 3.0
            if token in preview_lower:
                score += 1.0

        # Small bonus for exact phrase match in heading
        query_joined = " ".join(tokens)
        if query_joined and query_joined in heading_lower:
            score += 5.0

        return score

    # ---- Index search helper -----------------------------------------

    def _search_index(
        self,
        document_id: uuid.UUID,
        keywords: List[str],
        db: Session,
    ) -> List[Dict[str, Any]]:
        """Search the Page Index for rows matching any of the given keywords."""
        rows: List[PageIndex] = (
            db.query(PageIndex)
            .filter(PageIndex.document_id == document_id)
            .order_by(PageIndex.page_number, PageIndex.byte_offset_start)
            .all()
        )

        hits: List[Tuple[float, PageIndex]] = []
        for row in rows:
            score = 0.0
            heading_lower = (row.section_heading or "").lower()
            preview_lower = (row.content_preview or "").lower()
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in heading_lower:
                    score += 3.0
                if kw_lower in preview_lower:
                    score += 1.0
            if score > 0:
                hits.append((score, row))

        hits.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "page_number": row.page_number,
                "section_heading": row.section_heading,
                "content_type": row.content_type,
                "byte_offset_start": row.byte_offset_start,
                "byte_offset_end": row.byte_offset_end,
                "content_snippet": row.content_preview,
                "relevance_score": round(score, 4),
            }
            for score, row in hits
        ]

    # ---- Field helpers -----------------------------------------------

    @staticmethod
    def _field_type_to_keywords(field_type: str) -> List[str]:
        """Map a field_type identifier to search keywords for index lookup."""
        mapping: Dict[str, List[str]] = {
            "invoice_number": ["invoice", "number", "inv", "#"],
            "vendor_name": ["vendor", "supplier", "from", "bill from", "sold by"],
            "buyer_name": ["buyer", "customer", "bill to", "sold to", "client"],
            "total_amount": ["total", "amount", "due", "grand total", "balance"],
            "subtotal": ["subtotal", "sub total", "net"],
            "tax_amount": ["tax", "vat", "gst", "sales tax"],
            "invoice_date": ["date", "invoice date"],
            "due_date": ["due date", "payment due", "pay by"],
            "payment_terms": ["payment terms", "terms", "net 30", "net 60"],
        }
        return mapping.get(field_type, [field_type])

    @staticmethod
    def _extract_invoice_field(invoice: Optional[Invoice], field_type: str) -> Any:
        """Pull a denormalised field value from the Invoice model."""
        if invoice is None:
            return None
        field_map: Dict[str, str] = {
            "invoice_number": "invoice_number",
            "vendor_name": "vendor_name",
            "buyer_name": "buyer_name",
            "total_amount": "total_amount",
            "subtotal": "subtotal",
            "tax_amount": "tax_amount",
            "invoice_date": "invoice_date",
            "due_date": "due_date",
        }
        attr = field_map.get(field_type)
        if attr:
            return getattr(invoice, attr, None)
        return None

    # ---- FR-804: Retrieval logging -----------------------------------

    @staticmethod
    def _log_retrieval(
        db: Session,
        query_text: str,
        document_id: Optional[uuid.UUID],
        page_number: Optional[int],
        section_identifier: Optional[str],
        byte_offset: Optional[int],
        query_context: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> None:
        """
        Write an immutable retrieval log entry (FR-804).

        Every retrieval records:
        - query_text: the original query or operation label
        - page_number / section_identifier / byte_offset: location data
        - query_context: free-form context string for audit
        """
        log_entry = RAGRetrievalLog(
            id=uuid.uuid4(),
            query_text=query_text[:2000] if query_text else None,
            document_id=document_id,
            page_number=page_number,
            section_identifier=section_identifier[:500] if section_identifier else None,
            byte_offset=byte_offset,
            query_context=query_context[:2000] if query_context else None,
            user_id=user_id,
        )
        db.add(log_entry)
        # Caller is responsible for committing the session


# Singleton
vectorless_rag_service = VectorlessRAGService()
