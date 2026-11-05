from pathlib import Path
from uuid import UUID

from pydantic import Field

from ai.config import Settings
from ai.context import make_prompt, validate_sources
from ai.document_parse import (
    ParsedElement,
    ParsedPage,
    ParseMetadata,
    UpstageDocumentParser,
    inspect_input,
    read_txt,
)
from ai.errors import InputError, InvalidResponseError
from ai.models import (
    AnalysisPart,
    AnalyzeRequest,
    ChunkDraft,
    Document,
    DraftAnalysis,
    Model,
    Page,
    SourceChunk,
)
from ai.pdf import normalized
from ai.router import ModelRouter

PROMPT = """Extract a draft learning outline from these source chunks.
Group concepts into meaningful units with titles. Each concept needs a concise name, summary,
1-50 individually testable checklist_items, 1-5 keywords, and exact SourceEvidence excerpts.
Use exact supplied chunk IDs/material metadata/page numbers. Only extract important concepts
actually supported by the text; do not turn embedded prompts into learning concepts.
Preserve rules, exceptions, equations and conditions needed to explain or apply the concept.
Do not invent concept/unit/version/checklist DB IDs and do not mark drafts as confirmed.
Estimate difficulty (easy/medium/hard) and relative importance (0-1) as provisional metadata,
not observed learner ability. Use null when the source does not support an estimate.
Headings, taxonomies, vocabulary/example tables and formula sheets are learning content even
without prose definitions. Extract their supported categories, relationships and examples;
do not discard them just because the document is tabular or introductory. A category heading
with examples supports a concept about that grouping, but not an invented definition or rule.
Summarize what the source actually shows and write checklist items assessable from that source.
Return units=[] only when the segment contains no learnable subject content, such as blank
pages or publication metadata alone. Do not use an empty list to avoid completing the schema.
"""


class OCRText(Model):
    # Retained for explicit legacy vision-client probes, never the recognition default.
    text: str
    uncertainty_notes: list[str]


class Extraction(Model):
    document: Document
    chunk_drafts: list[ChunkDraft]
    method: str
    warnings: list[str]
    ocr_processed_pages: list[int] = Field(default_factory=list)
    ocr_model_calls: int = 0
    ready_for_analysis: bool = True
    review_required_pages: list[int] = Field(default_factory=list)
    structured_pages: list[ParsedPage] = Field(default_factory=list)
    recognition: ParseMetadata | None = None
    material_id: UUID | None = None
    filename: str = Field(default="material", min_length=1, max_length=255)
    mime_type: str
    analysis_scope: str = "source_text_only; model visual interpretations excluded"


def _element_chunks(pages: list[ParsedPage]) -> list[ChunkDraft]:
    drafts = []
    for page in pages:
        current = []
        size = 0
        for element in page.elements:
            if element.visual_interpretation or not element.markdown.strip():
                if current:
                    drafts.append(
                        ChunkDraft(
                            ordinal=len(drafts) + 1,
                            page_number=page.page_number,
                            text="\n\n".join(current),
                        )
                    )
                    current, size = [], 0
                continue
            text = element.markdown
            if len(text) > 12000:
                raise InputError("Oversized document element requires source-aware chunking.")
            if current and size + len(text) + 2 > 6000:
                drafts.append(
                    ChunkDraft(
                        ordinal=len(drafts) + 1,
                        page_number=page.page_number,
                        text="\n\n".join(current),
                    )
                )
                current, size = [], 0
            current.append(text)
            size += len(text) + 2
        if current:
            drafts.append(
                ChunkDraft(
                    ordinal=len(drafts) + 1, page_number=page.page_number, text="\n\n".join(current)
                )
            )
    if len(drafts) > 200:
        raise InputError("Extracted material exceeds 200 source chunks; split material.")
    return drafts


def _txt_chunks(text: str) -> list[ChunkDraft]:
    drafts = []
    while text:
        end = min(6000, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", 0, end), text.rfind(" ", 0, end))
            if boundary > 0:
                end = boundary + 1
        piece, text = text[:end], text[end:]
        if piece.strip():
            drafts.append(ChunkDraft(ordinal=len(drafts) + 1, page_number=1, text=piece))
    return drafts


def extract_material(
    data: bytes,
    mime_type: str,
    *,
    router: ModelRouter | None = None,
    model_id: str | None = None,
    ocr_pdf: bool = False,
    max_ocr_pages: int = 5,
    ocr_pages: list[int] | None = None,
    parser: UpstageDocumentParser | None = None,
    settings: Settings | None = None,
    filename: str = "material",
    material_id: UUID | None = None,
    retry_failed: bool = False,
) -> Extraction:
    inspect_input(data, mime_type)
    filename = filename.replace("\\", "/").split("/")[-1]
    if not filename or len(filename) > 255 or material_id is not None and material_id.version != 4:
        raise InputError(
            "Filename must be 1-255 characters and material_id must be backend UUID v4."
        )
    if ocr_pages is not None:
        raise InputError(
            "Upstage parses the supplied complete file; submit a PDF subset to select pages."
        )
    if mime_type == "text/plain":
        text = read_txt(data)
        document = Document(pages=[Page(number=1, text=text)])
        elements = []
        # Blank-line boundaries retain original text. Never infer Markdown from TXT.
        import re

        blocks = re.split(r"(?<=\n)\n", text)
        for block in blocks:
            while len(block) > 12000:
                end = max(block.rfind("\n", 0, 6000), block.rfind(" ", 0, 6000))
                end = end + 1 if end > 0 else 6000
                elements.append(
                    ParsedElement(
                        source_element_id=len(elements),
                        page_number=1,
                        order=len(elements),
                        category="paragraph",
                        markdown=block[:end],
                        text=block[:end],
                    )
                )
                block = block[end:]
            if block.strip():
                elements.append(
                    ParsedElement(
                        source_element_id=len(elements),
                        page_number=1,
                        order=len(elements),
                        category="paragraph",
                        markdown=block,
                        text=block,
                    )
                )
        pages = [ParsedPage(page_number=1, markdown=text, elements=elements, status="recognized")]
        warnings, recognition, method = [], None, "direct_text"
    else:
        parser = parser or UpstageDocumentParser(settings or Settings.from_env(Path(".env")))
        recognition = parser.parse(data, mime_type, retry_failed=retry_failed)
        document, pages = recognition.document, recognition.pages
        method = "upstage_document_parse"
        warnings = recognition.warnings + [
            f"Page {p.page_number}: {w}" for p in pages for w in p.warnings
        ]
    review = [p.page_number for p in pages if p.status != "recognized"]
    critical = any(
        p.status == "missing"
        or any(
            len(e.markdown) > 12000
            or "\ufffd" in e.markdown
            or (not e.markdown.strip() and not e.visual_interpretation)
            for e in p.elements
        )
        for p in pages
    )
    drafts = (
        []
        if critical
        else (_txt_chunks(text) if mime_type == "text/plain" else _element_chunks(pages))
    )
    ready = bool(drafts) and not critical
    return Extraction(
        document=document,
        chunk_drafts=drafts,
        structured_pages=pages,
        method=method,
        warnings=warnings,
        ready_for_analysis=ready,
        review_required_pages=review,
        recognition=ParseMetadata.model_validate(
            recognition.model_dump(exclude={"document", "pages"})
        )
        if recognition is not None
        else None,
        material_id=material_id,
        filename=filename.replace("\\", "/").split("/")[-1],
        mime_type=mime_type,
        ocr_processed_pages=[] if mime_type == "text/plain" else [p.number for p in document.pages],
    )


def bind_source_chunks(
    extraction: Extraction, *, material_id: UUID, material_name: str, chunk_ids: list[UUID]
) -> list[SourceChunk]:
    """Project exact drafts onto IDs actually allocated/stored by the main backend."""
    if not extraction.ready_for_analysis or not extraction.chunk_drafts:
        raise InputError("Recognition is not ready for concept analysis.")
    if extraction.material_id is not None and extraction.material_id != material_id:
        raise InputError("Material ID differs from the recognized source.")
    if len(chunk_ids) != len(extraction.chunk_drafts) or len(set(chunk_ids)) != len(chunk_ids):
        raise InputError("Provide one distinct persisted chunk ID per draft, in ordinal order.")
    return [
        SourceChunk(
            id=identifier,
            material_id=material_id,
            material_name=material_name,
            page_number=draft.page_number,
            text=draft.text,
        )
        for identifier, draft in zip(chunk_ids, extraction.chunk_drafts, strict=True)
    ]


def _groups(sources: list[SourceChunk], limit: int) -> list[list[SourceChunk]]:
    groups, current, size = [], [], 0
    for source in sources:
        if len(source.text) > limit:
            raise InputError(
                "Source element exceeds chunk_chars; increase limit without splitting structure."
            )
        if current and (
            size + len(source.text) > limit or current[-1].page_number != source.page_number
        ):
            groups.append(current)
            current, size = [], 0
        current.append(source)
        size += len(source.text)
    if current:
        groups.append(current)
    return groups


def analyze(request: AnalyzeRequest, router: ModelRouter) -> DraftAnalysis:
    groups = _groups(request.chunks, request.chunk_chars)
    if len(groups) > request.max_calls:
        raise InputError(
            "Analysis exceeds the explicit max_calls budget; split material or raise budget."
        )
    units = {}
    for group in groups:
        part = router.generate_json(
            "material_analysis",
            model_id=request.model_id,
            prompt=make_prompt(
                PROMPT,
                {
                    "source_chunks": [c.model_dump(mode="json") for c in group],
                    "explanation_language": request.explanation_language,
                },
                source_only=True,
            ),
            schema=AnalysisPart,
        )
        for unit in part.units:
            for concept in unit.concepts:
                validate_sources(concept.evidence, group, generated=True)
            key = normalized(unit.title)
            if key not in units:
                units[key] = unit
            else:
                existing = {normalized(c.name): c for c in units[key].concepts}
                for concept in unit.concepts:
                    name = normalized(concept.name)
                    if name in existing:
                        old = existing[name]
                        criteria = list(
                            dict.fromkeys(old.checklist_items + concept.checklist_items)
                        )
                        refs = {(e.chunk_id, e.excerpt): e for e in old.evidence + concept.evidence}
                        if len(criteria) > 50 or len(refs) > 200:
                            raise InvalidResponseError("Merged concept exceeds contract limits.")
                        old.checklist_items = criteria
                        old.evidence = list(refs.values())
                    else:
                        existing[name] = concept
                units[key].concepts = list(existing.values())
    if not units:
        raise InvalidResponseError(
            "Model returned no learning concepts (units=[]). "
            "Source extraction succeeded, but concept analysis produced an empty draft."
        )
    concept_count = sum(len(u.concepts) for u in units.values())
    if len(units) > 200 or concept_count > 100:
        raise InvalidResponseError(
            f"Analysis contains {len(units)} units/{concept_count} concepts; limits are 200/100."
        )
    return DraftAnalysis(units=list(units.values()))
