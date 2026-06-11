"""
Tests for standalone_config_gen.py — auto-discovery rules.

Each derivation rule is tested in isolation:
  - classify_business_model: sector-code-only / keyword-only / both-agree / both-disagree
  - derive_sector_etf: known prefix / unknown prefix / missing
  - derive_comp_set: blends sector peers + 10-K + sell-side; weights and dedup
  - derive_key_metrics: per-class seeds + segment additions
  - derive_day_of_binary: revenue preference / fallback
  - generate_config: end-to-end synthesis
  - generate_config_from_disk: reads input files correctly
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import standalone_config_gen as scg


# --- classify_business_model ---

def test_classify_neither_source_returns_other():
    r = scg.classify_business_model(None, None)
    assert r["class"] == "other"
    assert r["confidence"] == 0.0


def test_classify_sector_code_only():
    """Sector code 5015 (insurers) -> health_insurer_mco with low confidence."""
    r = scg.classify_business_model("5015XYZA", None)
    assert r["class"] == "health_insurer_mco"
    assert r["confidence"] == 0.3
    assert "sector_code" in r["sources"]


def test_classify_keywords_only_subscription_dtc():
    text = (
        "The company connects subscribers to telehealth providers. "
        "Our subscription business has grown ARPU through cross-sell. "
        "Direct-to-consumer model with monthly active users."
    )
    r = scg.classify_business_model(None, text)
    assert r["class"] == "subscription_dtc"
    assert r["confidence"] > 0
    assert "keywords" in r["sources"]


def test_classify_keywords_health_insurer():
    text = (
        "The company offers Marketplace plans. Medical loss ratio (MLR) is the "
        "primary profitability driver. Premiums collected from members fund claims."
    )
    r = scg.classify_business_model(None, text)
    assert r["class"] == "health_insurer_mco"


def test_classify_both_agree():
    """Sector 5015 + insurer keywords -> both agree, single source dominates."""
    text = "Premiums and medical loss ratio drive profitability. Members covered by Medicare Advantage."
    r = scg.classify_business_model("5015XYZA", text)
    assert r["class"] == "health_insurer_mco"
    assert r["confidence"] > 0


def test_classify_keywords_win_when_disagree():
    """Sector code says manufactured_goods; keywords say subscription_dtc -> keywords win,
    sector code becomes alternative."""
    text = (
        "Subscription business with ARPU growth. Monthly active subscribers. "
        "Direct-to-consumer model with churn tracking."
    )
    r = scg.classify_business_model("4520XYZA", text)  # 4520 -> manufactured_goods
    assert r["class"] == "subscription_dtc"
    assert r["alternative"] == "manufactured_goods"


def test_classify_software_saas():
    text = (
        "Annual recurring revenue (ARR) of $1.2bn. Net retention 120%. "
        "RPO grew 30% y/y. Software platform serves enterprise customers."
    )
    r = scg.classify_business_model(None, text)
    assert r["class"] == "software_saas"


def test_classify_lifesci_tools():
    text = (
        "Sequencing instruments deployed globally. Consumables revenue grew 25%. "
        "Throughput improvements drove molecular diagnostics adoption."
    )
    r = scg.classify_business_model(None, text)
    assert r["class"] == "lifesci_tools"


# --- derive_sector_etf ---

def test_etf_known_prefix():
    etf, note = scg.derive_sector_etf("5015AB12")
    assert etf == "XLV"
    assert "5015" in note


def test_etf_unknown_prefix_defaults_xlv():
    etf, note = scg.derive_sector_etf("9999AB12")
    assert etf == "XLV"
    assert "9999" in note
    assert "override" in note.lower()


def test_etf_missing_sector_code_defaults_xlv():
    etf, note = scg.derive_sector_etf(None)
    assert etf == "XLV"
    assert "no sector" in note.lower()


def test_etf_software_to_xlk():
    etf, _ = scg.derive_sector_etf("4510ABCD")
    assert etf == "XLK"


def test_etf_industrials_to_xli():
    etf, _ = scg.derive_sector_etf("2010ABCD")
    assert etf == "XLI"


# --- derive_comp_set ---

def test_comp_set_from_sector_peers_only():
    comps = scg.derive_comp_set(
        sector_peers=["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"],
        business_text=None,
        sell_side_synth_path=None,
    )
    assert len(comps) == 5
    assert comps[0]["ticker"] == "AAA"
    assert comps[0]["role"] == "auto_derived_peer"


def test_comp_set_drops_self_ticker():
    comps = scg.derive_comp_set(
        sector_peers=["XYZ", "TDOC", "WW"],
        business_text=None, sell_side_synth_path=None,
        self_ticker="XYZ",
    )
    tickers = [c["ticker"] for c in comps]
    assert "XYZ" not in tickers
    assert "TDOC" in tickers


def test_comp_set_blends_three_sources(tmp_path):
    """Sector peers supply 3, 10-K mentions 2 (one overlapping), sell-side
    mentions parenthetical tickers. Sector-weighted entries rank higher.

    The extractor intentionally only catches parenthetical tickers in
    sell-side text — bare uppercase tokens are too ambiguous (could be
    abbreviations, acronyms, etc.)."""
    business_text = "Competitors include Teladoc Health (TDOC) and We Communities (WW)."
    synth = tmp_path / "synthesis.md"
    synth.write_text("Outliers: argument from a broker mentioning (AMWL) and (LFST).")
    comps = scg.derive_comp_set(
        sector_peers=["TDOC", "AMWL", "WW"],
        business_text=business_text,
        sell_side_synth_path=synth,
        target_count=10,
    )
    tickers = [c["ticker"] for c in comps]
    # TDOC scores 3 (sector) + 2 (10-K) = 5 — highest
    assert tickers[0] == "TDOC"
    # WW scores 3 (sector) + 2 (10-K) = 5 — tied with TDOC, alphabetic tiebreak
    assert "WW" in tickers
    # AMWL: sector (3) + sell-side (1) = 4
    assert "AMWL" in tickers
    # LFST: sell-side only (1)
    assert "LFST" in tickers


def test_comp_set_skips_common_abbreviations():
    """10-K text mentioning '(GAAP)' or '(FDA)' should not produce a comp."""
    text = "Our reporting follows GAAP. The (FDA) approved our product."
    comps = scg.derive_comp_set(
        sector_peers=None, business_text=text, sell_side_synth_path=None,
    )
    tickers = [c["ticker"] for c in comps]
    assert "GAAP" not in tickers
    assert "FDA" not in tickers


# --- derive_key_metrics ---

def test_key_metrics_subscription_dtc_seed():
    metrics, notes = scg.derive_key_metrics("subscription_dtc", None, None)
    assert "subscribers_total" in metrics
    assert "arpu" in metrics
    assert "marketing_pct_revenue" in metrics
    assert any("subscription_dtc" in n for n in notes)


def test_key_metrics_health_insurer_mco_seed():
    metrics, _ = scg.derive_key_metrics("health_insurer_mco", None, None)
    assert "medical_loss_ratio" in metrics
    assert "members" in metrics
    assert "sga_pct_revenue" in metrics


def test_key_metrics_software_saas_seed():
    metrics, _ = scg.derive_key_metrics("software_saas", None, None)
    assert "arr" in metrics
    assert "net_retention" in metrics
    assert "fcf_margin" in metrics


def test_key_metrics_unknown_class_falls_back_to_other():
    metrics, _ = scg.derive_key_metrics("not_a_real_class", None, None)
    # Should match the "other" seed
    assert "total_revenue" in metrics
    assert "eps_non_gaap" in metrics


def test_key_metrics_adds_segment_revenue():
    segments = [{"name": "Online Revenue"}, {"name": "Wholesale"}, {"name": "International"}]
    metrics, notes = scg.derive_key_metrics("subscription_dtc", segments, None)
    assert "online_revenue_revenue" in metrics
    assert "wholesale_revenue" in metrics
    assert any("segment-revenue" in n for n in notes)


def test_key_metrics_caps_segment_additions_at_3():
    segments = [{"name": f"seg{i}"} for i in range(10)]
    metrics, _ = scg.derive_key_metrics("other", segments, None)
    seg_metrics = [m for m in metrics if m.startswith("seg")]
    assert len(seg_metrics) == 3


# --- derive_day_of_binary ---

def test_day_of_binary_picks_revenue_metric():
    metric, note = scg.derive_day_of_binary(
        ["units_shipped", "asp", "total_revenue", "eps_non_gaap"]
    )
    assert metric == "total_revenue"
    assert "revenue-like" in note


def test_day_of_binary_falls_back_when_no_revenue():
    metric, note = scg.derive_day_of_binary(["asp", "units_shipped", "eps_non_gaap"])
    assert metric == "asp"
    assert "no revenue metric" in note


def test_day_of_binary_handles_empty_list():
    metric, note = scg.derive_day_of_binary([])
    assert metric == "revenue"
    assert "no key_metrics" in note


# --- generate_config (top-level) ---

def test_generate_config_full_synthesis():
    text = (
        "The company connects subscribers to telehealth providers. "
        "Subscription business. ARPU growth. Direct-to-consumer model."
    )
    config = scg.generate_config(
        ticker="XYZ", analyst="user",
        fiscal_period_in_focus="C1Q26",
        sector_code="5010ABCD",
        sector_peers=["TDOC", "WW", "AMWL"],
        business_text=text,
        segments=[{"name": "Online"}],
        sell_side_synth_path=None,
        company_name="Acme Health",
    )
    assert config["ticker"] == "XYZ"
    assert config["_auto_generated"] is True
    assert config["_analyst_reviewed"] is False
    assert config["fiscal_period_in_focus"] == "C1Q26"
    assert config["business_model_class"] == "subscription_dtc"
    assert config["sector_etf"] == "XLV"
    assert any(c["ticker"] == "TDOC" for c in config["comp_set"])
    assert "subscribers_total" in config["key_metrics"]
    assert config["company_name_aliases"] == ["Acme Health"]


def test_generate_config_marks_unreviewed_by_default():
    config = scg.generate_config(ticker="ZZZZ", analyst="user")
    assert config["_analyst_reviewed"] is False
    assert config["_auto_generated"] is True


def test_generate_config_with_no_inputs():
    """Worst case: no sector code, no business text, no segments, no peers.
    Should still produce a usable config with 'other' class and defaults."""
    config = scg.generate_config(ticker="ZZZZ", analyst="user")
    assert config["business_model_class"] == "other"
    assert config["sector_etf"] == "XLV"  # default
    assert config["comp_set"] == []
    assert "total_revenue" in config["key_metrics"]


# --- generate_config_from_disk ---

@pytest.fixture
def disk_inputs(tmp_path, monkeypatch):
    """Build a fake workspace and input files, then rebind the ticker-dir resolver."""
    repo = tmp_path / "repo"
    td = repo / "workspace" / "ZZZZ"
    filings_dir = td / "filings"
    data_dir = td / "data"
    syn_dir = td / "synthesis"
    filings_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    syn_dir.mkdir(parents=True)
    monkeypatch.setattr(scg, "_ws_ticker_dir", lambda t: repo / "workspace" / t.upper())
    return {"repo": repo, "ticker_dir": td, "filings_dir": filings_dir,
            "data_dir": data_dir, "syn_dir": syn_dir}


def test_from_disk_with_all_inputs(disk_inputs):
    di = disk_inputs
    (di["filings_dir"] / "latest_10K_business.txt").write_text(
        "We connect subscribers via subscription telehealth services. ARPU growth."
    )
    (di["syn_dir"] / "sell_side_synthesis.md").write_text("synthesis content")

    config, summary = scg.generate_config_from_disk("ZZZZ", "user")
    assert config["ticker"] == "ZZZZ"
    # Free path no longer derives a fiscal period (no paid calendar feed).
    assert config["fiscal_period_in_focus"] is None
    assert config["business_model_class"] == "subscription_dtc"
    assert "subscribers_total" in config["key_metrics"]

    assert summary["inputs_present"]["sec_business_section"] is True
    assert summary["inputs_present"]["sell_side_synthesis"] is True
    assert summary["fiscal_period_derived"] is None


def test_from_disk_reads_legacy_data_location(disk_inputs):
    """Falls back to data/sec_business_section.txt when the filings/ file is absent."""
    di = disk_inputs
    (di["data_dir"] / "sec_business_section.txt").write_text(
        "Subscription telehealth services. ARPU growth. Direct-to-consumer."
    )
    config, summary = scg.generate_config_from_disk("ZZZZ", "user")
    assert config["business_model_class"] == "subscription_dtc"
    assert summary["inputs_present"]["sec_business_section"] is True


def test_from_disk_missing_inputs_degrades_gracefully(disk_inputs):
    """No input files present — the generator still produces a usable
    skeleton with 'other' class, default ETF, empty comp set."""
    config, summary = scg.generate_config_from_disk("ZZZZ", "user")
    assert config["ticker"] == "ZZZZ"
    assert config["business_model_class"] == "other"
    assert config["fiscal_period_in_focus"] is None
    assert config["comp_set"] == []
    assert all(v is False for v in summary["inputs_present"].values())


def test_yaml_serialization_preserves_key_order():
    config = scg.generate_config(ticker="XYZ", analyst="user")
    yaml_text = scg._serialize_to_yaml(config)
    # Sanity: ticker appears before company_name_aliases (key order preserved)
    assert yaml_text.index("ticker:") < yaml_text.index("company_name_aliases:")
    # _analyst_reviewed marker is visible
    assert "_analyst_reviewed: false" in yaml_text.lower()
