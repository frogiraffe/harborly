"""Interactive terminal port search over a local registry, built on Textual."""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static

from sea_mile.ports import Port, PortGroup, PortRegistry, source_short_label

_RESULT_COLUMNS = ("Name", "Country", "UN/LOCODE", "Sources", "Coord")
_SEARCH_DEBOUNCE_SECONDS = 0.15
_SEARCH_RESULT_LIMIT = 60


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
    # Provider text is escaped because it can contain Rich markup characters.
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
    """Live fuzzy port search with a detail pane, over a local registry."""

    # No custom commands are registered, so the command palette adds nothing.
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #body {
        height: 1fr;
    }
    #results {
        width: 68%;
        height: 100%;
    }
    #detail {
        width: 32%;
        height: 100%;
        border: solid $accent;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    # The input keeps focus, so arrow keys are bound at the app level and
    # forwarded to the results table.
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
            yield Static(id="detail", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results", DataTable)
        table.add_columns(*_RESULT_COLUMNS)
        self._base_sub_title = (
            f"{len(self._port_registry)} ports, "
            f"{len(self._port_registry.providers)} providers"
        )
        self.sub_title = self._base_sub_title
        self.query_one("#detail", Static).update("Type to search.")
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        # Debounced and run off the main thread so a full-registry search does
        # not block key handling.
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
        query = event.value.strip()
        if not query:
            # Cancel in-flight workers so a late result cannot refill the table.
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
        # A cancelled worker can still call in, so apply only current results.
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
                ", ".join(source_short_label(source) for source in group.sources),
                coordinate,
            )
        if results:
            table.move_cursor(row=0)
            self._show_detail(0)
        else:
            self.query_one("#detail", Static).update(
                "No matches." if query else "Type to search."
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None:
            self._show_detail(event.cursor_row)

    def action_browse_down(self) -> None:
        if self._results:
            self.query_one("#results", DataTable).action_cursor_down()

    def action_browse_up(self) -> None:
        if self._results:
            self.query_one("#results", DataTable).action_cursor_up()

    def _show_detail(self, index: int) -> None:
        if not 0 <= index < len(self._results):
            return
        group = self._results[index]
        self.query_one("#detail", Static).update("\n".join(_detail_lines(group)))


def run(registry: PortRegistry) -> None:
    SeaMileTUI(registry).run()
