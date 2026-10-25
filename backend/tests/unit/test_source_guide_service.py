"""Source guides summarize stored text and reuse the cached result."""
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Document
from app.services.source_digest import extractive_source_guide
from app.services.source_guide import SourceGuideService


SOURCE_TEXT = (
    "天文台每晚先檢查望遠鏡與相機，確認電池和儲存空間充足。"
    "觀測人員會記錄天候、曝光時間和目標星體。"
    "結束後，原始影像會備份到研究室伺服器。"
)


def source():
    return SimpleNamespace(
        id="source-1",
        title="天文台手冊",
        content=SOURCE_TEXT,
        chunks=[
            SimpleNamespace(heading_path="天文台手冊/設備檢查", text="設備檢查"),
            SimpleNamespace(heading_path="天文台手冊/觀測流程", text="觀測流程"),
            SimpleNamespace(heading_path="天文台手冊/影像備份", text="影像備份"),
        ],
        meta_json={"keep": "metadata"},
    )


class ScriptedLLM:
    def __init__(self, reply, model="test-model"):
        self.reply = reply
        self.model = model
        self.prompts = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return {"text": self.reply, "model": self.model, "usage": {}}


@pytest.fixture
def database():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    document = Document(
        id="source-1",
        user_id=None,
        title="天文台手冊",
        source_type="text",
        content=SOURCE_TEXT,
        status="ready",
        meta_json={"keep": "metadata"},
    )
    db.add(document)
    db.commit()
    try:
        yield db, document
    finally:
        db.close()
        engine.dispose()


def test_extractive_guide_uses_source_sentences_and_heading_topics():
    guide = extractive_source_guide(source())

    assert guide["summary"].replace(" ", "") == SOURCE_TEXT
    assert guide["topics"] == ["設備檢查", "觀測流程", "影像備份"]
    assert 2 <= len(re.findall(r"[。！？.!?]", guide["summary"])) <= 4


def test_extractive_guide_uses_chinese_phrases_when_headings_are_missing():
    document = source()
    document.content = (
        "天文台每晚檢查望遠鏡與相機，確認電池和儲存空間。"
        "觀測人員記錄天候、曝光時間和目標星體。"
        "結束後，原始影像會備份到研究室伺服器。"
    )
    document.chunks = []

    guide = extractive_source_guide(document)

    assert 3 <= len(guide["topics"]) <= 6
    assert all(topic in document.content or topic in document.title for topic in guide["topics"])


def test_extractive_guide_caps_topics_when_headings_fill_limit():
    document = source()
    document.content = (
        "Astronomy equipment observations camera telescope archive records."
    )
    document.chunks = [
        SimpleNamespace(heading_path="Manual/Section %s" % index, text="")
        for index in range(6)
    ]

    guide = extractive_source_guide(document)

    assert len(guide["topics"]) == 6


def test_generated_guide_is_cached_and_preserves_other_metadata(database):
    db, document = database
    reply = {
        "summary": "The observatory checks its equipment nightly. Staff record the conditions.",
        "topics": ["Equipment", "Observations", "Image backups"],
    }
    llm = ScriptedLLM(json.dumps(reply))
    service = SourceGuideService(llm_service=llm)

    assert service.guide(db, document) == reply
    assert service.guide(db, document) == reply

    assert len(llm.prompts) == 1
    assert "天文台手冊" in llm.prompts[0]
    assert document.meta_json["keep"] == "metadata"
    assert document.meta_json["guide"]["title"] == document.title
    assert document.meta_json["guide"]["summary"] == reply["summary"]
    assert document.meta_json["guide"]["topics"] == reply["topics"]


def test_unconfigured_model_uses_the_extractive_guide(database):
    db, document = database
    expected = extractive_source_guide(document)
    service = SourceGuideService(
        llm_service=ScriptedLLM("not JSON", model="fallback"),
    )

    assert service.guide(db, document) == expected


def test_unusable_model_reply_uses_the_extractive_guide(database):
    db, document = database
    expected = extractive_source_guide(document)
    service = SourceGuideService(llm_service=ScriptedLLM(
        json.dumps({"summary": "One sentence.", "topics": ["Only one"]}),
    ))

    assert service.guide(db, document) == expected
