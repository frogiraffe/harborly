# Terminal UI

The optional terminal UI combines registry search, result inspection, and a
braille world map that works without network tiles.

## Install and start

```bash
uv tool install --force 'sea-mile[tui]'
sea-mile tui
```

Add `routing`, `map`, or `api` to the same quoted requirement if the tool
installation must retain those capabilities.

## Interaction modes

The application starts in insert mode. Type in the search field and use the
arrow keys to select a result.

Press `Esc` for browse mode:

| Key | Action |
| --- | --- |
| `+` / `-` | Zoom in or out |
| `h` / `j` / `k` / `l` | Pan left, down, up, or right |
| `g` | Center on the selected port |
| `0` | Reset the map |
| `i` | Return to insert mode |

The map uses bundled coastline geometry and places ports by validated
longitude/latitude. It is a search visualization, not a navigation chart.

## Troubleshooting

If `sea-mile tui` reports that the extra is missing, reinstall the isolated uv
tool with every required extra in one command. A bare `sea-mile` command may
refer to a tool installation rather than the source checkout; use
`uv run sea-mile tui` while developing locally.
