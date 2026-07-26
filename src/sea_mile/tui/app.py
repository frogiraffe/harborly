"""Interactive split-screen port search TUI built on Textual.

Layout::

    Header
    Input (#query)              search bar
    Horizontal (#body):
      DataTable (#results, 40%)   port list
      BrailleMap (#map, 60%)      braille world map
    Footer
"""

from __future__ import annotations

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.events import Resize
from textual.message import Message
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static

from sea_mile.ports import Port, PortGroup, PortRegistry, source_short_label
from sea_mile.tui.map_canvas import BrailleWorldMap

_RESULT_COLUMNS = ("Name", "Country", "UN/LOCODE", "Sources", "Coord")
_SEARCH_DEBOUNCE_SECONDS = 0.15
_SEARCH_RESULT_LIMIT = 60


class BrailleMap(Static):
    """Widget wrapper that fires a message on terminal resize."""

    class Resized(Message):
        pass

    def on_resize(self, event: Resize) -> None:
        self.post_message(self.Resized())


def _member_lines(port: Port) -> list[str]:
    coordinate = (
        f"{port.latitude:.4f}, {port.longitude:.4f}"
        if port.has_coordinates
        else "none on file"
    )
    return [
        f"- [b]{escape(port.provider)}[/b] {escape(port.provider_id)}",
        f"  id: {escape(port.registry_id)}",
        f"  coordinates: {coordinate}",
        f"  function_code: {escape(port.function_code or '-')}",
    ]


def _detail_lines(group: PortGroup) -> list[str]:
    lines = [
        f"[b]{escape(group.name)}[/b]",
        f"country: {escape(group.country_code)}",
        f"unlocode: {escape(group.unlocode or '-')}",
        f"sources: {escape(', '.join(group.sources))}",
    ]
    if group.coordinate_conflict:
        lines.append("[red]coordinate conflict across sources[/red]")
    elif group.has_coordinates:
        lines.append(f"coordinates: {group.latitude:.4f}, {group.longitude:.4f}")
    else:
        lines.append("coordinates: none on file")
    lines.append("")
    lines.append(f"[b]records ({len(group.members)})[/b]")
    for port in group.members:
        lines.extend(_member_lines(port))
    return lines


class SeaMileTUI(App[None]):
    """Live fuzzy port search with a braille world map, over a local registry."""

    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #body {
        height: 1fr;
    }
    #results {
        width: 40%;
        height: 100%;
    }
    #map {
        width: 60%;
        height: 100%;
        border: solid $accent;
        overflow: hidden;
    }
    """

    BINDINGS = [
        ("down", "browse_down", "Next result"),
        ("up", "browse_up", "Previous result"),
    ]
    TITLE = "sea-mile"

    def __init__(self, registry: PortRegistry) -> None:
        super().__init__()
        self._port_registry = registry
        self._results: list[PortGroup] = []
        self._debounce_timer: Timer | None = None
        self._base_sub_title = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search a port name or UN/LOCODE code...", id="query")
        with Horizontal(id="body"):
            yield DataTable(id="results", cursor_type="row")
            yield BrailleMap(id="map", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.add_columns(*_RESULT_COLUMNS)
        self._base_sub_title = (
            f"{len(self._port_registry)} ports, "
            f"{len(self._port_registry.providers)} providers"
        )
        self.sub_title = self._base_sub_title
        self.query_one("#map", Static).update(
            "[dim]Search to display ports on the world map.[/dim]"
        )
        self.query_one(Input).focus()

    # ── search pipeline ──────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
        query = event.value.strip()
        if not query:
            self._debounce_timer = None
            self.workers.cancel_group(self, "search")
            self._apply_results(query, [])
            return
        self._debounce_timer = self.set_timer(
            _SEARCH_DEBOUNCE_SECONDS, lambda: self._search(query)
        )

    @work(thread=True, exclusive=True, group="search")
    def _search(self, query: str) -> None:
        groups = self._port_registry.search_grouped(query, limit=_SEARCH_RESULT_LIMIT)
        self.call_from_thread(self._apply_results, query, groups)

    def _apply_results(self, query: str, results: list[PortGroup]) -> None:
        if query != self.query_one(Input).value.strip():
            return
        self._results = results
        if not query:
            self.sub_title = self._base_sub_title
        elif len(results) >= _SEARCH_RESULT_LIMIT:
            self.sub_title = f"{len(results)}+ ports"
        else:
            self.sub_title = f"{len(results)} ports"

        table = self.query_one("#results", DataTable)
        table.clear()
        for group in results:
            if group.coordinate_conflict:
                coordinate = "conflict"
            elif group.has_coordinates:
                coordinate = f"{group.latitude:.3f}, {group.longitude:.3f}"
            else:
                coordinate = "-"
            table.add_row(
                group.name,
                group.country_code,
                group.unlocode or "-",
                ", ".join(source_short_label(s) for s in group.sources),
                coordinate,
            )
        if results:
            table.move_cursor(row=0)
            self._show_map(0)
        else:
            self.query_one("#map", Static).update(
                "[dim]No matching ports.[/dim]"
                if query
                else "[dim]Search to display ports on the world map.[/dim]"
            )

    # ── selection sync ───────────────────────────────────────────────

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None:
            self._show_map(event.cursor_row)

    def on_braille_map_resized(self, event: BrailleMap.Resized) -> None:  # type: ignore[name-defined]
        if not self._results:
            return
        table = self.query_one("#results", DataTable)
        if table.cursor_row is not None:
            self._show_map(table.cursor_row)

    def action_browse_down(self) -> None:
        if self._results:
            self.query_one("#results", DataTable).action_cursor_down()

    def action_browse_up(self) -> None:
        if self._results:
            self.query_one("#results", DataTable).action_cursor_up()

    # ── rendering ────────────────────────────────────────────────────

    def _show_map(self, index: int) -> None:
        widget = self.query_one("#map", Static)
        char_w = widget.size.width
        char_h = widget.size.height
        if char_w < 10 or char_h < 3:
            widget.update("[dim]Terminal too small for map.[/dim]")
            return
        world_map = BrailleWorldMap(char_w, char_h)
        rendered = world_map.render(self._results, selected=index)
        widget.update(Text.from_ansi(rendered))


def run(registry: PortRegistry) -> None:
    """Launch the interactive TUI."""
    SeaMileTUI(registry).run()
