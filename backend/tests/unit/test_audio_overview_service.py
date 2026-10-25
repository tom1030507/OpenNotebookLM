"""Focused tests for dialogue generation and extractive fallback."""
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.audio_overview as audio_overview_module
from app.db.models import AudioOverview, Base, Document, Project, ProjectDocument
from app.services.audio_overview import AudioOverviewService, parse_dialogue_script


class FixedLLM:
    def __init__(self, text):
        self.text = text
        self.prompt = None

    def generate(self, prompt, **kwargs):
        self.prompt = prompt
        return {"text": self.text, "model": "test-model"}


def doc(title, content):
    return SimpleNamespace(title=title, content=content, chunks=[])


def test_parser_repairs_fences_whitespace_length_and_repeated_speakers():
    raw = '```json\n[{"speaker":"A","text":"  First   turn. "},'
    raw += '{"speaker":"A","text":"%s"}]\n```' % ("word " * 90)

    turns = parse_dialogue_script(raw)

    assert [turn["speaker"] for turn in turns] == ["A", "B"]
    assert turns[0]["text"] == "First turn."
    assert len(turns[1]["text"]) <= 300


def test_prompt_carries_options_and_only_the_supplied_source_digest():
    llm = FixedLLM(
        '[{"speaker":"A","text":"A grounded opening."},'
        '{"speaker":"B","text":"A grounded response."}]'
    )
    service = AudioOverviewService(llm_service=llm)

    turns = service.build_script(
        project_name="Climate",
        documents=[doc("Selected source", "Selected evidence. Detailed finding.")],
        options={"format": "critique", "length": "short", "focus": "methods"},
    )

    assert len(turns) == 2
    assert 'Format: critique' in llm.prompt
    assert 'Length: short' in llm.prompt
    assert 'Focus: methods' in llm.prompt
    assert "Selected evidence." in llm.prompt
    assert "Not selected" not in llm.prompt


def test_unusable_llm_reply_falls_back_to_one_voice_and_respects_short_length():
    llm = FixedLLM("not JSON")
    service = AudioOverviewService(llm_service=llm)
    documents = [
        doc("First", "First source explains a careful method. More detail."),
        doc("Second", "Second source offers supporting evidence."),
        doc("Third", "Third source adds useful context."),
        doc("Fourth", "Fourth source explains an important limit."),
        doc("Fifth", "Fifth source is outside the short overview."),
    ]

    turns = service.build_script(
        project_name="Research",
        documents=documents,
        options={"format": "deep_dive", "length": "short", "focus": None},
    )

    assert turns
    assert all(turn["speaker"] == "A" for turn in turns)
    assert len(turns) <= 4
    assert "First" in " ".join(turn["text"] for turn in turns)
    assert "Fifth" not in " ".join(turn["text"] for turn in turns)


def test_sources_without_extracted_text_are_not_sent_to_the_llm():
    llm = FixedLLM(
        '[{"speaker":"A","text":"Ungrounded opening."},'
        '{"speaker":"B","text":"Ungrounded response."}]'
    )
    service = AudioOverviewService(llm_service=llm)

    turns = service.build_script(
        project_name="Empty source",
        documents=[doc("Scanned file", "  ")],
        options={"format": "brief", "length": "short"},
    )

    assert turns == []
    assert llm.prompt is None


def test_process_fails_with_a_safe_error_when_sources_have_no_text(tmp_path):
    engine = create_engine("sqlite:///%s" % (tmp_path / "empty-source.db"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    llm = FixedLLM(
        '[{"speaker":"A","text":"Ungrounded opening."},'
        '{"speaker":"B","text":"Ungrounded response."}]'
    )
    try:
        with sessions() as db:
            db.add(Project(id="empty-audio-project", name="Empty source"))
            db.add(Document(
                id="empty-audio-document",
                title="Scanned file",
                source_type="text",
                content="  ",
            ))
            db.flush()
            db.add(ProjectDocument(
                project_id="empty-audio-project",
                document_id="empty-audio-document",
            ))
            db.add(AudioOverview(
                id="empty-audio-overview",
                project_id="empty-audio-project",
                status="running",
                options_json={"document_ids": ["empty-audio-document"]},
                script_json=[],
            ))
            db.commit()

        AudioOverviewService(llm_service=llm).process(
            sessions,
            "empty-audio-overview",
        )

        with sessions() as db:
            overview = db.get(AudioOverview, "empty-audio-overview")
            assert overview.status == "failed"
            assert overview.error == "No source text is available for an audio overview."
        assert llm.prompt is None
    finally:
        engine.dispose()


def test_worker_service_persists_script_and_ready_audio_without_loading_models(
    tmp_path,
    monkeypatch,
):
    engine = create_engine("sqlite:///%s" % (tmp_path / "overview.db"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    output_path = tmp_path / "audio" / "overview.mp3"
    monkeypatch.setattr(
        audio_overview_module,
        "resolve_audio_file",
        lambda _file_path: output_path,
    )

    class FakeTTS:
        def synthesize(self, script, path):
            assert [turn["speaker"] for turn in script] == ["A", "B"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake mp3")
            return 2.5

    try:
        with sessions() as db:
            db.add(Project(id="audio-project", name="Climate"))
            db.add(Document(
                id="audio-document",
                title="Research",
                source_type="text",
                content="Evidence from the selected source.",
            ))
            db.add(Document(
                id="other-document",
                title="Not selected",
                source_type="text",
                content="This source must stay out of the prompt.",
            ))
            db.flush()
            db.add(ProjectDocument(
                project_id="audio-project",
                document_id="audio-document",
            ))
            db.add(ProjectDocument(
                project_id="audio-project",
                document_id="other-document",
            ))
            db.add(AudioOverview(
                id="overview-1",
                project_id="audio-project",
                status="running",
                options_json={
                    "format": "brief",
                    "length": "short",
                    "document_ids": ["audio-document"],
                },
                script_json=[],
                file_path="uploads/audio_overviews/overview-1.mp3",
            ))
            db.commit()

        llm = FixedLLM(
            '[{"speaker":"A","text":"First host."},'
            '{"speaker":"B","text":"Second host."}]'
        )
        AudioOverviewService(llm_service=llm, tts=FakeTTS()).process(
            sessions,
            "overview-1",
        )

        with sessions() as db:
            overview = db.get(AudioOverview, "overview-1")
            assert overview.status == "ready"
            assert overview.script_json == [
                {"speaker": "A", "text": "First host."},
                {"speaker": "B", "text": "Second host."},
            ]
            assert overview.duration_seconds == 2.5
            assert overview.completed_at is not None
        assert output_path.read_bytes() == b"fake mp3"
        assert "Format: brief" in llm.prompt
        assert "Evidence from the selected source." in llm.prompt
        assert "Not selected" not in llm.prompt
    finally:
        engine.dispose()
