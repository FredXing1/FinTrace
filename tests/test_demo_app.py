"""App-level regression tests for the hosted demo (streamlit AppTest).

The 2026-09-25 launch incident: Streamlit carried a slider's user-selected
value across reruns after the date range changed, crashing with
InvalidMinMaxError on the live demo. AppTest renders the real app headlessly
so that class of bug fails here first.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

DEMO_APP = str(Path(__file__).resolve().parent.parent / "demo" / "app.py")


@pytest.fixture()
def at() -> AppTest:
    app = AppTest.from_file(DEMO_APP, default_timeout=60)
    app.run()
    return app


def test_default_render_has_no_exception(at: AppTest) -> None:
    assert not at.exception
    assert at.slider[0].value is not None


def test_single_filing_range_does_not_crash(at: AppTest) -> None:
    # AMEX / AccountsPayable / 2008-12-31 has exactly ONE filing on record:
    # a single-point date range that once crashed the live app.
    at.selectbox[0].select("AMERICAN EXPRESS CO (AXP)")
    at.selectbox[1].select("AccountsPayable")
    at.selectbox[2].select("2008-12-31")
    at.run()
    assert not at.exception
    assert at.slider[0].value is not None


def test_unknown_card_before_publication(at: AppTest) -> None:
    aapl_label = next(o for o in at.selectbox[0].options if "(AAPL)" in o)
    at.selectbox[0].select(aapl_label)
    at.run()
    at.selectbox[1].select("RevenueFromContractWithCustomerExcludingAssessedTax")
    at.run()
    at.selectbox[2].select("2022-09-24")
    # slider minimum IS the period end: any cutoff before the 10-K filing
    # (2022-10-28) must render the unknown card
    at.selectbox[2].select("2022-09-24")
    at.run()
    # the slider's minimum must BE the period end, so the "unknown" zone
    # (any cutoff before the 2022-10-28 filing) is reachable by the user
    # AppTest exposes date-slider bounds as microsecond timestamps
    assert date.fromtimestamp(at.slider[0].min / 1_000_000) == date(2022, 9, 24)
    assert date.fromtimestamp(at.slider[0].max / 1_000_000) >= date(2022, 10, 28)
    at.slider[0].set_value(date(2022, 10, 27)).run()
    assert not at.exception
    assert any("unknown" in e.value.lower() for e in at.error)


def test_gated_card_after_publication(at: AppTest) -> None:
    aapl_label = next(o for o in at.selectbox[0].options if "(AAPL)" in o)
    at.selectbox[0].select(aapl_label)
    at.run()
    at.selectbox[1].select("RevenueFromContractWithCustomerExcludingAssessedTax")
    at.run()
    at.selectbox[2].select("2022-09-24")
    at.slider[0].set_value(date(2023, 1, 1)).run()
    assert not at.exception
    # the numeric answer appears somewhere in the rendered metrics
    rendered = "".join(str(el.value) for el in at.metric)
    assert "394,328,000,000" in rendered
