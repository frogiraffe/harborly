from __future__ import annotations

import pytest

pytest.importorskip("textual", reason="tests the optional 'tui' extra")

from test_ports import alias_frame, registry_frame  # noqa: E402
from textual.widgets import DataTable, Static  # noqa: E402

from sea_mile import PortRegistry  # noqa: E402
from sea_mile.tui import SeaMileTUI  # noqa: E402


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _detail_text(app: SeaMileTUI) -> str | None:
    return getattr(app.query_one("#detail", Static), "_Static__content", None)


async def _type(pilot, text: str) -> None:
    await pilot.click("#query")
    for character in text:
        await pilot.press(character)
    # The search is debounced (150ms) and then runs in a worker thread.
    await pilot.pause(0.25)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.anyio
async def test_typing_populates_results_and_detail() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")

        table = app.query_one("#results", DataTable)
        assert table.row_count == 1
        assert _detail_text(app) is not None
        assert "Mersin" in _detail_text(app)


@pytest.mark.anyio
async def test_bare_unlocode_groups_the_matching_sources() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "TRMER")

        table = app.query_one("#results", DataTable)
        assert table.row_count == 1
        assert app._results[0].match_method == "exact_unlocode"
        sources_cell = str(table.get_cell_at((0, 3)))
        assert "WPI" in sources_cell
        assert "LOCODE" in sources_cell


@pytest.mark.anyio
async def test_arrow_down_changes_the_detail_pane() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Piraeus")

        before = _detail_text(app)
        await pilot.press("down")
        await pilot.pause()
        after = _detail_text(app)

        assert before != after


@pytest.mark.anyio
async def test_clearing_the_query_resets_results() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")
        table = app.query_one("#results", DataTable)
        assert table.row_count == 1

        input_widget = app.query_one("#query")
        input_widget.value = ""
        await pilot.pause()

        assert table.row_count == 0
        assert _detail_text(app) == "Type to search."


@pytest.mark.anyio
async def test_clearing_the_query_mid_search_keeps_results_empty() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await pilot.click("#query")
        for character in "Mersin":
            await pilot.press(character)
        # Clear right after the debounce fires, while a search worker for
        # the old query may still be in flight. Its late results must not
        # repopulate the cleared table.
        await pilot.pause(0.16)
        app.query_one("#query").value = ""
        await pilot.pause(0.4)

        table = app.query_one("#results", DataTable)
        assert table.row_count == 0
        assert _detail_text(app) == "Type to search."
