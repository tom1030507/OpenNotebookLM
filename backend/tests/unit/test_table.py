"""Validation for model-produced source comparison tables."""
import json

import pytest

from app.schemas import TableRequest
from app.services.table import (
    MAX_TABLE_CELL_CHARS,
    MAX_TABLE_ROWS,
    TableService,
    parse_table_response,
)


def test_request_trims_fields_and_deduplicates_source_ids():
    request = TableRequest(
        instruction=" Compare these papers ",
        columns=[" Title ", "Year"],
        source_ids=["doc-a", "doc-a", "doc-b"],
    )

    assert request.instruction == "Compare these papers"
    assert request.columns == ["Title", "Year"]
    assert request.source_ids == ["doc-a", "doc-b"]


@pytest.mark.parametrize("payload", [
    {"instruction": "  "},
    {"instruction": "Compare", "columns": [" "]},
    {"instruction": "Compare", "columns": ["x" * 101]},
    {"instruction": "Compare", "source_ids": []},
])
def test_request_rejects_blank_and_unbounded_fields(payload):
    with pytest.raises(ValueError):
        TableRequest(**payload)


def test_parser_maps_only_cited_selected_sources_and_blanks_invalid_cells():
    payload = {
        "columns": ["Paper", "Year"],
        "rows": [
            [
                {"value": "Paper A", "source": "[Source 1]"},
                {"value": "2025", "source": "[Source 1]"},
            ],
            [
                {"value": "invented", "source": "[Source 2]"},
                {"value": 2024, "source": "[Source 1]"},
            ],
        ],
    }
    sources = [
        {
            "id": 1,
            "document_id": "doc-a",
            "document_title": "Paper A",
            "text_preview": "A study from 2025.",
        },
        {
            "id": 2,
            "document_id": "doc-outside-selection",
            "document_title": "Other paper",
            "text_preview": "Not selected.",
        },
    ]

    result = parse_table_response(
        json.dumps(payload), sources, ["doc-a"], ["Paper", "Year"],
    )

    assert result == {
        "columns": ["Paper", "Year"],
        "rows": [
            [
                {"value": "Paper A", "document_id": "doc-a", "source_id": 1},
                {"value": "2025", "document_id": "doc-a", "source_id": 1},
            ],
            [
                {"value": "", "document_id": None, "source_id": None},
                {"value": "", "document_id": None, "source_id": None},
            ],
        ],
        "sources": [{
            "id": 1,
            "document_id": "doc-a", "title": "Paper A", "excerpt": "A study from 2025.",
        }],
    }


def test_parser_keeps_distinct_evidence_for_same_document():
    payload = {
        "columns": ["Title", "Year"],
        "rows": [[
            {"value": "Paper A", "source": "[Source 1]"},
            {"value": "2025", "source": "[Source 2]"},
        ]],
    }
    sources = [
        {"id": 1, "document_id": "doc-a", "document_title": "Paper A", "text_preview": "Title: Paper A."},
        {"id": 2, "document_id": "doc-a", "document_title": "Paper A", "text_preview": "Published in 2025."},
    ]

    result = parse_table_response(json.dumps(payload), sources, ["doc-a"], None)

    assert result["rows"] == [[
        {"value": "Paper A", "document_id": "doc-a", "source_id": 1},
        {"value": "2025", "document_id": "doc-a", "source_id": 2},
    ]]
    assert [source["excerpt"] for source in result["sources"]] == [
        "Title: Paper A.", "Published in 2025.",
    ]


def test_parser_returns_empty_rows_for_malformed_output():
    assert parse_table_response("not json", [], ["doc-a"], ["Paper"]) == {
        "columns": ["Paper"], "rows": [], "sources": [],
    }


def test_parser_blanks_an_oversized_source_reference_without_raising():
    payload = {
        "columns": ["Paper"],
        "rows": [[{
            "value": "Paper A",
            "source": "[Source %s]" % ("9" * 5_000),
        }]],
    }

    result = parse_table_response(json.dumps(payload), [], ["doc-a"], ["Paper"])

    assert result["rows"] == [[{"value": "", "document_id": None, "source_id": None}]]


def test_parser_caps_rows_and_cell_length():
    payload = {
        "columns": ["Value"],
        "rows": [
            [{"value": "x" * (MAX_TABLE_CELL_CHARS + 10), "source": "[Source 1]"}]
            for _ in range(MAX_TABLE_ROWS + 1)
        ],
    }
    sources = [{
        "id": 1, "document_id": "doc-a", "document_title": "Paper A",
        "text_preview": "Evidence.",
    }]

    result = parse_table_response(json.dumps(payload), sources, ["doc-a"], None)

    assert len(result["rows"]) == MAX_TABLE_ROWS
    assert len(result["rows"][0][0]["value"]) == MAX_TABLE_CELL_CHARS


def test_service_retrieves_using_the_instruction_and_only_selected_sources():
    class StubRAG:
        def query(self, db, **kwargs):
            self.db = db
            self.kwargs = kwargs
            return {
                "answer": json.dumps({
                    "columns": ["Paper"],
                    "rows": [[{"value": "Paper A", "source": "[Source 1]"}]],
                }),
                "sources": [{
                    "id": 1, "document_id": "doc-a", "document_title": "Paper A",
                    "text_preview": "A relevant paper.",
                }],
            }

    rag = StubRAG()
    service = TableService(rag)
    database = object()

    result = service.generate(
        database, "project-1", "one row per paper", ["Paper"], ["doc-a"],
    )

    assert result["rows"] == [[{"value": "Paper A", "document_id": "doc-a", "source_id": 1}]]
    assert rag.db is database
    assert rag.kwargs["retrieval_query"] == "one row per paper"
    assert rag.kwargs["allowed_document_ids"] == ["doc-a"]
    assert '"one row per paper"' in rag.kwargs["query"]
