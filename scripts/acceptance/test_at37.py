"""AT-37 checks, with the three cloud calls replaced by plain values."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import at37_lineage_and_docs as at  # noqa: E402

P = "proj"
WH = at.fqn(P, "wh_dev", "fct_alert")
BUILD = at.fqn(P, "build_dev", "fct_alert")
STG = at.fqn(P, "build_dev", "stg_g2__alert_incidents")
RAW = at.fqn(P, "raw_g2", "alert_incidents")

FULL_CHAIN = {WH: [BUILD], BUILD: [STG], STG: [RAW]}


def links(graph):
    return lambda name: graph.get(name, [])


GOOD_PAGE = b"x" * 20_000
GOOD_MANIFEST = {"nodes": {
    "model.p.fct_alert": {"resource_type": "model", "name": "fct_alert", "description": "One row per alert."},
    "test.p.not_null": {"resource_type": "test", "name": "not_null", "description": ""},  # tests need none
}}


def run(graph=FULL_CHAIN, enabled=True, docs=(GOOD_PAGE, GOOD_MANIFEST)):
    return at.run(P, "dev", "us-central1", links(graph), enabled, docs)


# ---------------------------------------------------------------------------------- lineage
def test_the_full_chain_passes():
    assert run() == []


def test_the_chain_may_pass_through_intermediate_models():
    deep = {WH: [BUILD], BUILD: [at.fqn(P, "build_dev", "int_a")], at.fqn(P, "build_dev", "int_a"): [STG], STG: [RAW]}
    assert at.lineage_problems(links(deep), P, "dev") == []


def test_no_lineage_at_all_fails_on_both_ends():
    problems = run(graph={})
    assert any("build_dev" in p for p in problems) and any("raw_g2" in p for p in problems)


def test_lineage_that_stops_at_build_fails_on_raw_g2():
    problems = at.lineage_problems(links({WH: [BUILD]}), P, "dev")
    assert problems == ["no lineage from raw_g2 upstream of wh_dev.fct_alert"]


def test_lineage_from_raw_that_skips_build_fails_on_build():
    problems = at.lineage_problems(links({WH: [RAW]}), P, "dev")
    assert problems == ["no lineage from build_dev into wh_dev.fct_alert"]


def test_a_cycle_in_the_links_does_not_loop_forever():
    assert at.upstream(links({WH: [BUILD], BUILD: [WH]}), WH) == {WH, BUILD}


# ------------------------------------------------------------------------------------- docs
def test_a_missing_page_fails():
    assert any("no docs page" in f for f in run(docs=(None, GOOD_MANIFEST)))


def test_a_tiny_page_fails():
    assert any("empty or broken" in f for f in run(docs=(b"<html></html>", GOOD_MANIFEST)))


def test_a_missing_manifest_fails():
    assert any("no manifest.json" in f for f in run(docs=(GOOD_PAGE, None)))


def test_a_model_without_a_description_fails_and_is_named():
    manifest = {"nodes": {
        "model.p.a": {"resource_type": "model", "name": "dim_store", "description": "A store."},
        "model.p.b": {"resource_type": "model", "name": "fct_alert", "description": "   "},
        "model.p.c": {"resource_type": "model", "name": "mv_store_health"},
    }}
    failures = run(docs=(GOOD_PAGE, manifest))
    assert failures == ["2 of 3 models have no description: fct_alert, mv_store_health"]


def test_only_models_need_a_description():
    count, missing = at.models_without_description(GOOD_MANIFEST)
    assert (count, missing) == (1, [])


def test_a_manifest_without_models_fails():
    assert any("no models" in f for f in run(docs=(GOOD_PAGE, {"nodes": {}})))


def test_a_disabled_api_fails():
    assert any("not enabled" in f for f in run(enabled=False))


def test_every_failure_is_reported_not_just_the_first():
    failures = run(graph={}, enabled=False, docs=(None, None))
    assert len(failures) >= 5
