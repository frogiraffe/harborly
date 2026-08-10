"""Minimal Harborly demo: resolve, search, route, matrix.

Run: python demos/basic.py
"""

from harborly import PortRegistry, SeaRouter


def main() -> None:
    # Load the bundled port registry (20K+ ports)
    registry = PortRegistry.bundled()

    # --- Resolve ---
    mersin = registry.resolve("TRMER")
    piraeus = registry.resolve("GRPIR")
    rotterdam = registry.resolve("NLRTM")
    print(
        f"Resolved: {mersin.name} ({mersin.registry_id}), "
        f"{piraeus.name} ({piraeus.registry_id}), "
        f"{rotterdam.name} ({rotterdam.registry_id})"
    )

    # --- Search ---
    results = registry.search("Shanghai", country_code="CN")
    print(f"Search 'Shanghai CN': {len(results)} result(s)")
    for sr in results:
        p = sr.port
        print(f"  {p.name} ({p.registry_id}) — {p.latitude}, {p.longitude}")

    # --- Nearest ---
    nearby = registry.nearest(36.8, 34.6, limit=3)
    print("Nearest to (36.8, 34.6):")
    for n in nearby:
        print(f"  {n.port.name} ({n.port.registry_id}) — {n.distance_nmi:.1f} nmi")

    # --- Route ---
    router = SeaRouter()
    route = router.route(mersin, piraeus)
    print(
        f"Route {mersin.name} → {piraeus.name}: "
        f"{route.distance_nmi:.1f} nmi, quality: {route.quality_flag}"
    )

    # --- Distance matrix ---
    ports = [mersin, piraeus, rotterdam]
    matrix = router.distance_matrix(ports)
    print(f"Distance matrix ({len(ports)} ports):")
    for i, origin in enumerate(ports):
        for j, dest in enumerate(ports):
            if i >= j:
                continue
            print(f"  {origin.name} → {dest.name}: {matrix[i][j]:.0f} nmi")


if __name__ == "__main__":
    main()
