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


def _map_text(app: SeaMileTUI) -> str:
    return str(getattr(app.query_one("#map", Static), "_Static__content", ""))


async def _type(pilot, text: str) -> None:
    await pilot.click("#query")
    for character in text:
        await pilot.press(character)
    await pilot.pause(0.25)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def _enter_browse(app: SeaMileTUI) -> None:
    app.action_enter_browse()


@pytest.mark.anyio
async def test_typing_populates_results_and_map() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")

        table = app.query_one("#results", DataTable)
        assert table.row_count == 1
        map_content = _map_text(app)
        assert "Search to display" not in map_content


@pytest.mark.anyio
async def test_map_rerenders_after_resize(monkeypatch) -> None:
    render_calls: list[tuple[int, int]] = []

    try:
        from sea_mile.tui import map_canvas as mc

        original_render = mc.BrailleWorldMap.render

        def tracking_render(self, groups, *, selected=None):
            render_calls.append((self.char_width, self.char_height))
            return original_render(self, groups, selected=selected)

        monkeypatch.setattr(mc.BrailleWorldMap, "render", tracking_render)
    except ImportError:
        pytest.skip("tui extra not installed")

    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test(size=(80, 24)) as pilot:
        await _type(pilot, "Mersin")

        assert len(render_calls) >= 1
        before = render_calls[-1]

        await pilot.resize_terminal(120, 40)
        await pilot.pause()

        assert render_calls[-1] != before


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
async def test_arrow_down_updates_map() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")

        table = app.query_one("#results", DataTable)
        if table.row_count < 2:
            pytest.skip("Need at least 2 results for comparison")

        app._zoom = 8.0
        app._center_lat = 36.8
        app._center_lon = 34.6

        before = _map_text(app)
        app.action_browse_down()
        await pilot.pause()
        after = _map_text(app)

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
        assert "Search to display" in _map_text(app)


@pytest.mark.anyio
async def test_clearing_the_query_mid_search_keeps_results_empty() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await pilot.click("#query")
        for character in "Mersin":
            await pilot.press(character)
        await pilot.pause(0.16)
        app.query_one("#query").value = ""
        await pilot.pause(0.4)

        table = app.query_one("#results", DataTable)
        assert table.row_count == 0
        assert "Search to display" in _map_text(app)


@pytest.mark.anyio
async def test_zoom_in_increases_zoom_level() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")
        await _enter_browse(app)
        assert app._zoom == 1.0

        app.action_zoom_in()
        await pilot.pause()
        assert app._zoom > 1.0


@pytest.mark.anyio
async def test_zoom_out_decreases_zoom_level() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")
        await _enter_browse(app)
        app._zoom = 4.0

        app.action_zoom_out()
        await pilot.pause()
        assert app._zoom < 4.0


@pytest.mark.anyio
async def test_zoom_reset_restores_default() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")
        await _enter_browse(app)
        app._zoom = 8.0
        app._center_lat = 40.0
        app._center_lon = 30.0

        app.action_zoom_reset()
        await pilot.pause()
        assert app._zoom == 1.0
        assert app._center_lat == 0.0
        assert app._center_lon == 0.0


@pytest.mark.anyio
async def test_go_to_port_centers_on_selected() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")
        await _enter_browse(app)

        app.action_go_to_port()
        await pilot.pause()

        group = app._results[0]
        assert app._center_lat == group.latitude
        assert app._center_lon == group.longitude
        assert app._zoom >= 4.0


@pytest.mark.anyio
async def test_escape_enters_browse_mode() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")
        assert not app._browse_mode

        await pilot.press("escape")
        await pilot.pause()
        assert app._browse_mode


@pytest.mark.anyio
async def test_i_enters_insert_mode() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")
        await _enter_browse(app)
        assert app._browse_mode

        await pilot.press("i")
        await pilot.pause()
        assert not app._browse_mode


@pytest.mark.anyio
async def test_browse_mode_pan_and_zoom_via_keys() -> None:
    registry = PortRegistry(registry_frame(), alias_frame())
    app = SeaMileTUI(registry)
    async with app.run_test() as pilot:
        await _type(pilot, "Mersin")
        await _enter_browse(app)

        orig_lon = app._center_lon
        await pilot.press("l")
        await pilot.pause()
        assert app._center_lon != orig_lon

        orig_zoom = app._zoom
        await pilot.press("plus")
        await pilot.pause()
        assert app._zoom > orig_zoom
