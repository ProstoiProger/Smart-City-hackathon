import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "extract_review_signals",
    Path(__file__).resolve().parents[1] / "scripts" / "extract_review_signals.py",
)
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

BATCH = [
    {"review_id": "1", "text": "Уютно, но розеток нет.\nЗато Wi-Fi  быстрый!"},
    {"review_id": "2", "text": "Отличная игровая зона для детей"},
]


def claim(rid, attr, pol, quote):
    return {"review_id": rid, "attribute": attr, "polarity": pol, "quote": quote}


def test_only_verbatim_quotes_from_the_batch_survive():
    kept, dropped = ex.validate_claims(
        [
            claim("1", "power_outlets", "negative", "розеток нет"),
            claim("1", "wifi", "positive", "Wi-Fi быстрый"),  # whitespace-normalized match
            claim("1", "quiet", "positive", "очень тихо"),  # not in the review
            claim("3", "kids", "positive", "игровая зона"),  # review outside the batch
            claim("2", "kids", "great", "игровая зона"),  # unknown polarity
            claim("2", "smell", "positive", "игровая зона"),  # unknown attribute
            claim("2", "kids", "positive", "игровая зона"),
            claim("2", "kids", "positive", "для детей"),  # duplicate review/attribute
        ],
        BATCH,
    )
    assert [(c["review_id"], c["attribute"], c["polarity"]) for c in kept] == [
        ("1", "power_outlets", "negative"),
        ("1", "wifi", "positive"),
        ("2", "kids", "positive"),
    ]
    assert dropped == 5


def test_malformed_model_output_is_dropped():
    assert ex.validate_claims(None, BATCH) == ([], 0)
    assert ex.validate_claims([{"review_id": "1"}], BATCH) == ([], 1)


def test_status_needs_repeated_agreement():
    assert ex.status_of(1, 0, 0) == "single_mention"
    assert ex.status_of(4, 0, 0) == "supported"
    assert ex.status_of(3, 1, 0) == "supported"
    assert ex.status_of(2, 1, 0) == "mixed"
    assert ex.status_of(1, 2, 0) == "contradicted"
    assert ex.status_of(0, 1, 0) == "contradicted"


def test_prefilter_catches_negations_and_kazakh_free_text_is_ignored_safely():
    assert "power_outlets" in ex.prefilter({"text": "Розеток нет совсем"})
    assert ex.prefilter({"text": "Вкусный кофе"}) == []
