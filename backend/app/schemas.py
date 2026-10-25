"""Pydantic schemas for API models."""
from datetime import datetime
from typing import Annotated, Optional, List, Dict, Any, Literal
from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

from app.utils.time import as_utc

# Every datetime this API emits has to carry a UTC designator: a designator-less
# value such as "2026-08-13T09:00:00" is read as *local* time by ECMAScript, so a
# browser in UTC+8 renders a record created seconds ago as hours old and files it
# under the wrong date-group header.
#
# Stored datetimes already arrive labelled, via app.db.types.UTCDateTime. This
# alias closes the boundary for anything else a route might hand a response
# model, labelling a naive value as the UTC it is meant to be rather than letting
# it serialise bare.
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]

PROJECT_COVER_EMOJIS = ("📚", "🧠", "🔬", "🌿", "🚀", "🎨", "💡", "🌊")
PROJECT_COVER_COLORS = ("blue", "violet", "rose", "amber", "emerald", "teal", "slate")


# Authentication schemas
# email-validator is not installed, so the address is checked with a pattern
# rather than pydantic's EmailStr.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# Source ids fan out into ownership and retrieval queries; a fixed ceiling
# prevents one request from building an unbounded SQL `IN` clause.
MAX_DOCUMENT_SELECTION = 500


class UserRegister(BaseModel):
    """Schema for registering an account."""
    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., max_length=255, pattern=EMAIL_PATTERN)
    # bcrypt reads at most 72 bytes, so longer passwords are refused here
    # rather than being silently truncated.
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, password: str) -> str:
        """Reject Unicode passwords whose UTF-8 form exceeds bcrypt's cap.

        Args:
            password: Validated password string.

        Returns:
            The password unchanged when its encoded size is safe.

        Raises:
            ValueError: If UTF-8 encoding exceeds bcrypt's 72-byte boundary.
        """
        if len(password.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return password


class UserResponse(BaseModel):
    """Schema for account response. Never carries password material."""
    id: str
    username: str
    email: str
    created_at: UtcDatetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Schema for a successful sign-in."""
    access_token: str
    token_type: str = "bearer"


class DemoAccountResponse(BaseModel):
    """Schema for the demo credentials the sign-in page may offer.

    Deliberately unauthenticated: a deployment that publishes a demo account
    has to be able to tell anyone standing at the sign-in page what it is.
    `enabled` is false whenever there is nothing safe or true to publish.
    """
    enabled: bool
    username: Optional[str] = None
    password: Optional[str] = None


# Project schemas
class ProjectBase(BaseModel):
    """Base project schema."""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    meta_json: Optional[Dict[str, Any]] = {}


class ProjectCreate(ProjectBase):
    """Schema for creating a project.

    The name may be left out; the project then gets a placeholder that the
    generated overview replaces with a title.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=200)


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    meta_json: Optional[Dict[str, Any]] = None
    cover_emoji: Optional[str] = None
    cover_color: Optional[str] = None

    @field_validator("cover_emoji")
    @classmethod
    def validate_cover_emoji(cls, value: Optional[str]) -> Optional[str]:
        """Restrict covers to the supported single-grapheme emoji set.

        Args:
            value: Emoji submitted by the caller.

        Returns:
            The supported emoji, or None to clear the cover.

        Raises:
            ValueError: If the emoji is not supported.
        """
        if value is not None and value not in PROJECT_COVER_EMOJIS:
            raise ValueError("Unsupported project cover emoji")
        return value

    @field_validator("cover_color")
    @classmethod
    def validate_cover_color(cls, value: Optional[str]) -> Optional[str]:
        """Restrict covers to the supported palette.

        Args:
            value: Palette name submitted by the caller.

        Returns:
            The supported color, or None for the neutral cover.

        Raises:
            ValueError: If the color is not supported.
        """
        if value is not None and value not in PROJECT_COVER_COLORS:
            raise ValueError("Unsupported project cover color")
        return value


class ProjectResponse(ProjectBase):
    """Schema for project response."""
    id: str
    name: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    document_count: int = 0
    conversation_count: int = 0
    role: Literal["owner", "editor", "viewer"] = "owner"
    cover_emoji: Optional[str] = None
    cover_color: Optional[str] = None
    
    class Config:
        from_attributes = True


# Custom instructions ride along with every question, so an unbounded block would
# eat into the prompt budget the retrieved passages need.
CHAT_INSTRUCTIONS_MAX_LENGTH = 2000


class ChatSettings(BaseModel):
    """How a project's chat answers: the role it plays and how long it runs."""
    role: Literal["default", "learning_guide", "custom"] = "default"
    instructions: str = Field("", max_length=CHAT_INSTRUCTIONS_MAX_LENGTH)
    answer_length: Literal["default", "longer", "shorter"] = "default"


class ProjectListResponse(BaseModel):
    """Schema for project list response."""
    projects: List[ProjectResponse]
    total: int
    page: int
    per_page: int


class ProjectMemberCreate(BaseModel):
    """Add an existing account to a project by its username or email."""
    username: Optional[str] = Field(None, min_length=3, max_length=64)
    email: Optional[str] = Field(None, max_length=255, pattern=EMAIL_PATTERN)
    role: Literal["viewer", "editor"]

    @model_validator(mode="after")
    def require_one_identity(self):
        """Require exactly one account identifier.

        Args:
            self: Validated member request.

        Returns:
            This request when one identifier is present.
        """
        if bool(self.username) == bool(self.email):
            raise ValueError("Provide either username or email")
        return self


class ProjectMemberUpdate(BaseModel):
    """Change a member's project role."""
    role: Literal["viewer", "editor"]


class ProjectMemberResponse(BaseModel):
    """Account and effective role shown in the project member list."""
    user_id: str
    username: str
    email: str
    role: Literal["owner", "editor", "viewer"]
    created_at: UtcDatetime


# Document schemas
class DocumentBase(BaseModel):
    """Base document schema."""
    title: str
    source_type: str  # pdf, file extension, url, youtube, or pasted text
    source_url: Optional[str] = None
    meta_json: Optional[Dict[str, Any]] = {}


class DocumentCreate(DocumentBase):
    """Schema for creating a document."""
    project_id: str


class DocumentResponse(DocumentBase):
    """Schema for document response."""
    id: str
    status: str
    error_message: Optional[str] = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    chunk_count: int = 0
    is_owned_by_caller: bool = False
    
    class Config:
        from_attributes = True


class DocumentContentResponse(BaseModel):
    """Extracted source text returned only when a preview requests it."""
    content: str


class SourceGuideResponse(BaseModel):
    """Short summary and topics extracted from one source."""
    summary: str
    topics: List[str]


class DocumentStatusResponse(BaseModel):
    """Schema for document status response."""
    id: str
    status: str  # queued, processing, transcribing, ready, error
    meta: Optional[Dict[str, Any]] = {}
    error_message: Optional[str] = None
    progress: Optional[float] = None


# Upload schemas
class UploadConfigResponse(BaseModel):
    """Runtime file constraints advertised to the source upload form."""
    allowed_file_types: List[str]
    max_file_size_mb: int
    max_text_characters: int


class FileUploadResponse(BaseModel):
    """Schema for file upload response."""
    doc_id: str
    status: str
    message: str


class URLUploadRequest(BaseModel):
    """Schema for URL upload request."""
    url: str = Field(..., min_length=1)
    title: Optional[str] = None


class YouTubeUploadRequest(BaseModel):
    """Schema for YouTube upload request."""
    youtube_url: str = Field(..., min_length=1)
    title: Optional[str] = None


def _not_blank(value: str) -> str:
    """Strip a required string and refuse one that is only whitespace.

    Args:
        value: Submitted string.

    Returns:
        The stripped string.
    """
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class TextUploadRequest(BaseModel):
    """Schema for adding pasted text as a source."""
    title: Annotated[str, AfterValidator(_not_blank)] = Field(..., max_length=200)
    text: Annotated[str, AfterValidator(_not_blank)]


class DocumentUpdateRequest(BaseModel):
    """Schema for renaming a source."""
    title: Annotated[str, AfterValidator(_not_blank)] = Field(..., max_length=200)


# Conversation schemas
class ConversationCreate(BaseModel):
    """Schema for creating a conversation."""
    project_id: str
    title: Optional[str] = None


class ConversationResponse(BaseModel):
    """Schema for conversation response."""
    id: str
    project_id: str
    title: Optional[str] = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    message_count: int = 0
    
    class Config:
        from_attributes = True


# Message schemas
class MessageCreate(BaseModel):
    """Schema for creating a message."""
    conversation_id: str
    text: str
    role: str = "user"


class CitationSchema(BaseModel):
    """Schema for citation."""
    doc_id: str
    chunk_id: str
    page_num: Optional[int] = None
    url: Optional[str] = None
    ts_start: Optional[float] = None
    ts_end: Optional[float] = None
    char_span: Optional[List[int]] = None
    text_snippet: Optional[str] = None


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: str
    conversation_id: str
    role: str
    text: str
    citations: List[CitationSchema] = []
    used_mode: Optional[str] = None
    token_count: Optional[int] = None
    cost: Optional[float] = None
    processing_time: Optional[float] = None
    is_bookmarked: bool = False
    tags: List[str] = []
    created_at: UtcDatetime
    
    class Config:
        from_attributes = True


# Query schemas
class QueryRequest(BaseModel):
    """Schema for query request."""
    project_id: str
    query: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)
    rerank: bool = True
    mode: str = Field(default="auto", pattern="^(local|cloud|auto)$")


class QueryResponse(BaseModel):
    """Schema for query response."""
    answer: str
    citations: List[CitationSchema]
    used_mode: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    timings: Dict[str, float] = {}
    token_cost: Optional[Dict[str, Any]] = None


# Export schemas
class ExportRequest(BaseModel):
    """Schema for export request."""
    format: str = Field(default="markdown", pattern="^(markdown|json|html)$")
    include_citations: bool = True
    include_metadata: bool = False


# Health schemas
class HealthResponse(BaseModel):
    """Schema for health check response."""
    ok: bool
    timestamp: UtcDatetime
    version: str
    environment: str
    database: str
    system: Dict[str, Any]
    config: Dict[str, Any]


class ReadyResponse(BaseModel):
    """Schema for readiness check response."""
    ready: bool
    reason: Optional[str] = None


# Mind map schemas
class MindMapNode(BaseModel):
    """One node of a project's mind map.

    The same shape at every level — project, document, topic — so the browser can
    draw the tree with one recursive renderer instead of three.
    """
    model_config = {"extra": "forbid"}

    id: str
    label: str
    kind: str = Field(..., pattern="^(project|document|topic)$")
    # Source-grounded explanation of the concept, when one was generated.
    detail: Optional[str] = None
    # Set on a document node and on its topics, so selecting a topic can open
    # the source it came from.
    document_id: Optional[str] = None
    children: List["MindMapNode"] = []


class SourceSelection(BaseModel):
    """Optional body narrowing a Studio output to some of a project's sources."""

    # Omitted means every source. An empty list is refused rather than read as
    # "no restriction", which would quietly use everything.
    document_ids: Optional[List[str]] = Field(
        default=None,
        min_length=1,
        max_length=MAX_DOCUMENT_SELECTION,
    )

    @field_validator("document_ids", mode="before")
    @classmethod
    def deduplicate_document_ids(
        cls,
        document_ids: Any,
    ) -> Any:
        """Keep the first occurrence of every selected source id.

        Args:
            document_ids: Validated source ids, or None when no selection was
                supplied.

        Returns:
            The selection in request order with duplicates removed.
        """
        if not isinstance(document_ids, (list, tuple)):
            return document_ids
        unique_ids = []
        seen_ids = set()
        for document_id in document_ids:
            if not isinstance(document_id, str):
                unique_ids.append(document_id)
            elif document_id not in seen_ids:
                seen_ids.add(document_id)
                unique_ids.append(document_id)
        return unique_ids


class ReportRequest(SourceSelection):
    """Options for one source-grounded project report."""
    model_config = {"extra": "forbid"}

    format: Literal["briefing", "study_guide", "faq", "timeline", "custom"]
    instruction: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_custom_instruction(self):
        """Require nonblank custom guidance and reject it for fixed formats.

        Returns:
            This request after its format and instruction are checked.
        """
        if self.format == "custom":
            if not self.instruction or not self.instruction.strip():
                raise ValueError("custom reports require a nonblank instruction")
        elif self.instruction is not None:
            raise ValueError("instruction is only accepted for custom reports")
        return self


class ReportCitation(BaseModel):
    """One source citation rendered alongside a report."""
    model_config = {"extra": "forbid"}

    id: int
    document_id: str
    source: str
    text: str


class ReportResponse(BaseModel):
    """Generated Markdown and its cited source passages."""
    model_config = {"extra": "forbid"}

    markdown: str
    citations: List[ReportCitation] = Field(default_factory=list)


class StudyRequest(SourceSelection):
    """Options for one temporary flashcard or quiz generation request."""

    count: int = Field(default=10, ge=5, le=30)
    focus: Optional[str] = Field(default=None, max_length=500)


class StudySource(BaseModel):
    """A source excerpt used by a generated study item."""

    model_config = {"extra": "forbid"}

    document_id: str
    title: str
    excerpt: str = Field(..., max_length=1200)


class FlashcardItem(BaseModel):
    """One validated front-and-back study card."""

    model_config = {"extra": "forbid"}

    front: str = Field(..., min_length=1, max_length=300)
    back: str = Field(..., min_length=1, max_length=1200)
    document_id: str


class QuizItem(BaseModel):
    """One validated single-answer multiple-choice question."""

    model_config = {"extra": "forbid"}

    question: str = Field(..., min_length=1, max_length=500)
    options: List[str] = Field(..., min_length=4, max_length=4)
    answer_index: int = Field(..., ge=0, le=3)
    explanation: str = Field(..., min_length=1, max_length=1200)
    document_id: str


class FlashcardsResponse(BaseModel):
    """Study cards, project metadata, and their citation sources."""

    model_config = {"protected_namespaces": (), "extra": "forbid"}

    project_id: str
    project_name: str
    generated_at: UtcDatetime
    model_used: str
    selected_ready_source_count: int = Field(..., ge=0)
    sources_considered: int = Field(..., ge=0)
    items: List[FlashcardItem]
    sources: List[StudySource]


class QuizResponse(BaseModel):
    """Quiz questions, project metadata, and their citation sources."""

    model_config = {"protected_namespaces": (), "extra": "forbid"}

    project_id: str
    project_name: str
    generated_at: UtcDatetime
    model_used: str
    selected_ready_source_count: int = Field(..., ge=0)
    sources_considered: int = Field(..., ge=0)
    items: List[QuizItem]
    sources: List[StudySource]


class AudioOverviewCreate(SourceSelection):
    """Generation style and source selection for one audio overview."""

    format: Literal["deep_dive", "brief", "critique", "debate"] = "deep_dive"
    length: Literal["short", "default"] = "default"
    focus: Optional[str] = Field(default=None, max_length=500)


class AudioOverviewTurn(BaseModel):
    """One validated host turn in the stored transcript."""

    speaker: Literal["A", "B"]
    text: str = Field(..., min_length=1, max_length=300)


class AudioOverviewResponse(BaseModel):
    """Persisted status, options, transcript, and timing for an overview."""

    id: str
    status: Literal["queued", "running", "ready", "failed"]
    options: AudioOverviewCreate
    script: List[AudioOverviewTurn] = Field(default_factory=list)
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    started_at: Optional[UtcDatetime] = None
    completed_at: Optional[UtcDatetime] = None


class AudioOverviewListResponse(BaseModel):
    """Stored overviews and the runtime synthesis capability."""

    enabled: bool
    items: List[AudioOverviewResponse] = Field(default_factory=list)


class MindMapResponse(BaseModel):
    """Schema for a generated mind map."""

    # `model_used` collides with pydantic's reserved `model_` prefix, and the
    # pinned pydantic 2.5.0 warns about every such field at import time. The name
    # is kept because a query answer already reports `model_used` and the browser
    # reads that key; the guard is waived rather than the field renamed.
    model_config = {"protected_namespaces": (), "extra": "forbid"}

    project_id: str
    project_name: str
    generated_at: UtcDatetime
    # Which model named the topics, or "fallback" when the document structure
    # did. Mirrors `model_used` on a query answer: the caller has to be able to
    # tell a generated map from an extracted one.
    model_used: str
    node_count: int
    # Input coverage is explicit when the model's bounded source sample is
    # smaller than the project. Optional for previously saved map responses.
    source_count: Optional[int] = Field(default=None, ge=0)
    total_source_count: Optional[int] = Field(default=None, ge=0)
    root: MindMapNode


# Video summary schemas
class VideoScene(BaseModel):
    """One scene of a project's video summary.

    The same shape for all three kinds — title card, source, closing recap — so
    the browser plays them with one renderer instead of three.
    """
    model_config = {"extra": "forbid"}

    id: str
    kind: str = Field(..., pattern="^(title|source|closing)$")
    # One clause naming what this scene is about.
    headline: str
    # The lines on the slide. Empty for a source whose text is not extracted yet.
    bullets: List[str] = []
    # Read aloud over the slide. Never empty: a silent scene is a gap in the
    # video, and the scene advances when the voice finishes.
    narration: str
    # Set on a source scene, so a listener can open the source it came from.
    document_id: Optional[str] = None
    # The source's own title, shown as the citation on the slide. Distinct from
    # `headline`, which may be a sentence a model wrote about it.
    source_label: Optional[str] = None


# Summary generation covers every project source, not only the 500-source
# selection request. Keep export bounded while supporting large projects.
# shortcut: 1,000 source slides max; raise after measuring larger deck exports.
MAX_VIDEO_SUMMARY_PPTX_SOURCE_SCENES = 1_000
MAX_VIDEO_SUMMARY_PPTX_SCENES = MAX_VIDEO_SUMMARY_PPTX_SOURCE_SCENES + 2
MAX_VIDEO_SUMMARY_PPTX_TEXT_CHARS = 500_000
MAX_VIDEO_SUMMARY_PPTX_BULLET_CHARS = 120
MAX_VIDEO_SUMMARY_PPTX_NARRATION_CHARS = 10_000


class VideoSummaryPptxScene(VideoScene):
    """A bounded video scene accepted by the PowerPoint export endpoint."""

    model_config = {"extra": "forbid"}

    id: str = Field(..., min_length=1, max_length=128)
    headline: str = Field(..., min_length=1, max_length=500)
    bullets: List[
        Annotated[str, Field(max_length=MAX_VIDEO_SUMMARY_PPTX_BULLET_CHARS)]
    ] = Field(default_factory=list, max_length=4)
    narration: str = Field(
        ..., min_length=1, max_length=MAX_VIDEO_SUMMARY_PPTX_NARRATION_CHARS,
    )
    document_id: Optional[str] = Field(None, max_length=128)
    source_label: Optional[str] = Field(None, max_length=500)


class VideoSummaryPptxRequest(BaseModel):
    """The scenes already shown in the video summary dialog."""

    model_config = {"extra": "forbid"}

    scenes: List[VideoSummaryPptxScene] = Field(
        ..., min_length=2, max_length=MAX_VIDEO_SUMMARY_PPTX_SCENES,
    )

    @field_validator("scenes")
    @classmethod
    def scenes_fit_one_summary(
        cls,
        scenes: List[VideoSummaryPptxScene],
    ) -> List[VideoSummaryPptxScene]:
        """Reject oversized or out-of-order scene lists at the export boundary.

        Args:
            scenes: Validated video summary scenes.

        Returns:
            The original scenes when they fit the generated-summary contract.
        """
        if scenes[0].kind != "title" or scenes[-1].kind != "closing":
            raise ValueError("scenes must start with a title and end with a closing scene")
        if any(scene.kind != "source" for scene in scenes[1:-1]):
            raise ValueError("only source scenes may appear between the title and closing")
        if any(not scene.document_id for scene in scenes[1:-1]):
            raise ValueError("source scenes must include a document id")

        text_chars = sum(
            len(scene.headline)
            + len(scene.narration)
            + sum(len(bullet) for bullet in scene.bullets)
            + len(scene.source_label or "")
            for scene in scenes
        )
        if text_chars > MAX_VIDEO_SUMMARY_PPTX_TEXT_CHARS:
            raise ValueError("scene text exceeds the PowerPoint export limit")

        return scenes


class VideoSummaryResponse(BaseModel):
    """Schema for a generated video summary script."""

    # `model_used` collides with pydantic's reserved `model_` prefix, and the
    # pinned pydantic 2.5.0 warns about every such field at import time. The name
    # is kept because a query answer and a mind map already report `model_used`
    # and the browser reads that key; the guard is waived rather than the field
    # renamed.
    model_config = {"protected_namespaces": (), "extra": "forbid"}

    project_id: str
    project_name: str
    generated_at: UtcDatetime
    # Which model wrote the source scenes, or "fallback" when the documents' own
    # structure did. Mirrors `model_used` on a query answer and a mind map: a
    # written script and an extracted one sound alike, so the caller has to be
    # able to tell them apart.
    model_used: str
    scene_count: int
    # How long the script takes to read out, so a caller knows the length without
    # counting words itself. The player derives its own timeline from the same
    # pace, because its progress bar has to agree with its scene boundaries; keep
    # `WORDS_PER_SECOND` here and in `videoSummaryTiming.ts` the same.
    estimated_seconds: int
    scenes: List[VideoScene]


# Note schemas
# A bound on what one request can store; long enough for any answer or essay.
NOTE_CONTENT_MAX_LENGTH = 100_000
NOTE_PAYLOAD_MAX_BYTES = 750_000


class NoteCreate(BaseModel):
    """Schema for creating a note.

    `source_message_id` saves an answer from stored data; `studio_kind` saves
    client-supplied report Markdown or a validated Studio JSON result.
    """
    model_config = {"extra": "forbid"}

    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(default="", max_length=NOTE_CONTENT_MAX_LENGTH)
    source_message_id: Optional[str] = None
    studio_kind: Optional[Literal["report", "mindmap", "video_summary"]] = None
    payload_json: Optional[Dict[str, Any]] = None


class NoteUpdate(BaseModel):
    """Schema for editing a note."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, max_length=NOTE_CONTENT_MAX_LENGTH)


class NoteResponse(BaseModel):
    """Schema for note response."""
    id: str
    project_id: str
    title: str
    content: str
    origin: str
    source_message_id: Optional[str] = None
    studio_kind: Optional[Literal["report", "mindmap", "video_summary"]] = None
    payload_json: Optional[Dict[str, Any]] = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    class Config:
        from_attributes = True


# Project overview schemas
class ProjectAnalyticsDay(BaseModel):
    """Question count for one UTC calendar day."""
    date: str
    question_count: int


class ProjectAnalyticsSource(BaseModel):
    """A currently linked source and its citation count."""
    document_id: str
    title: str
    citation_count: int


class ProjectAnalyticsRatings(BaseModel):
    """Counts of rated and unrated assistant answers."""
    up: int
    down: int
    unrated: int


class ProjectAnalyticsRecentQuestion(BaseModel):
    """An owner's question that received a recent down rating."""
    question: str
    answered_at: UtcDatetime


class ProjectAnalyticsUncitedSource(BaseModel):
    """A current project source with no citations in the selected window."""
    document_id: str
    title: str


class ProjectAnalyticsResponse(BaseModel):
    """Usage analytics for one project and a supported date window."""
    days: Literal[7, 30, 90]
    questions_by_day: List[ProjectAnalyticsDay]
    conversation_count: int
    top_cited_sources: List[ProjectAnalyticsSource]
    ratings: ProjectAnalyticsRatings
    recent_down_rated_questions: List[ProjectAnalyticsRecentQuestion]
    uncited_sources: List[ProjectAnalyticsUncitedSource]


class ProjectOverviewResponse(BaseModel):
    """Schema for a project's generated overview and suggested questions."""
    project_name: str
    overview: Optional[str] = None
    questions: List[str] = []


class FollowUpResponse(BaseModel):
    """Schema for questions suggested after an answer."""
    questions: List[str] = []
