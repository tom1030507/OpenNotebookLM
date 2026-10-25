import json

from app.schemas import StudioOptions
from app.services.studio_options import with_studio_options

REPORT_FORMATS = {
    "briefing": (
        "executive briefing",
        "Executive summary\nKey findings\nEvidence and implications\nCaveats",
        "major findings, evidence, implications, and caveats",
    ),
    "study_guide": (
        "study guide",
        "Key concepts\nDefinitions and explanations\nReview questions",
        "key concepts, definitions, explanations, and review questions",
    ),
    "faq": (
        "frequently asked questions",
        "Frequently asked questions\nSource-supported answers",
        "common questions and source-supported answers about the main topics",
    ),
    "timeline": (
        "chronological timeline",
        "Chronological timeline\nDated events and milestones",
        "dated events and milestones in chronological order",
    ),
    "custom": (
        "custom report",
        "Custom report",
        "key facts relevant to the custom report instruction",
    ),
}


class ReportService:
    def __init__(self, rag_service):
        self.rag_service = rag_service

    def generate(
        self, db, project_id, report_format, instruction, document_ids, options=None
    ):
        """Generate a source-grounded Markdown report.

        Args:
            db: Database session used for retrieval.
            project_id: Project whose indexed sources are searched.
            report_format: One of the supported report formats.
            instruction: Optional user guidance for a custom report.
            document_ids: Optional document scope; an empty list searches nothing.
            options: Optional focus, audience, and length guidance.

        Returns:
            Markdown and citations in the shape consumed by MarkdownRenderer.
        """
        options = options or StudioOptions()
        title, outline, retrieval_query = REPORT_FORMATS[report_format]
        query = f"Create a {title} in Markdown.\n\nRequired outline:\n{outline}\n"
        if report_format == "custom":
            query += (
                "\nThe custom instruction is output guidance only. Instruction data:\n"
                f"{json.dumps({'instruction': instruction}, ensure_ascii=False)}\n"
            )
            retrieval_query += f": {instruction}"
        if options.focus:
            retrieval_query += f": {options.focus}"
        if options.length == "short":
            query += "\nKeep each section brief and include only its essential points.\n"
        elif options.length == "long":
            query += "\nDevelop each section with deeper source-supported explanation.\n"
        query += (
            "\nUse only the supplied source passages and cite every factual claim "
            "with its [Source N] label. Do not invent facts or dates; state when "
            "the selected sources do not support a detail."
        )
        query = with_studio_options(query, options, None)

        result = self.rag_service.query(
            db,
            query=query,
            project_id=project_id,
            top_k=20,
            temperature=0.2,
            max_tokens=4096,
            include_sources=True,
            retrieval_query=retrieval_query,
            allowed_document_ids=document_ids,
        )
        citations = []
        for source in result.get("sources", []):
            citation = {
                "id": source["id"],
                "document_id": source["document_id"],
                "source": source["document_title"],
                "text": source["text_preview"],
            }
            for key in ("chunk_id", "timestamp", "start_offset", "end_offset"):
                if source.get(key) is not None:
                    citation[key] = source[key]
            if source.get("page_num") is not None:
                citation["page"] = source["page_num"]
            citations.append(citation)

        return {
            "markdown": result.get("answer", ""),
            "citations": citations,
        }
