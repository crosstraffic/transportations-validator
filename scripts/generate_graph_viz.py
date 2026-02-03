"""Generate interactive network visualization of the Knowledge Graph using PyVis."""

import asyncio
from pathlib import Path

from pyvis.network import Network

from transportations_validator.db.neo4j.connection import get_neo4j_driver
from transportations_validator.db.postgres import async_session_maker
from transportations_validator.db.postgres.repositories import (
    ParameterRepository,
    RuleRepository,
)

# Output directory for generated HTML
OUTPUT_DIR = Path(__file__).parent.parent / "static"


async def fetch_graph_data_from_postgres():
    """Fetch graph data from PostgreSQL."""
    async with async_session_maker() as session:
        param_repo = ParameterRepository(session)
        rule_repo = RuleRepository(session)

        # Get all parameters
        parameters = await param_repo.get_all()

        # Get all rules
        rules = await rule_repo.get_all()

        return parameters, rules


async def fetch_graph_data_from_neo4j():
    """Fetch graph data from Neo4j."""
    driver = get_neo4j_driver()

    async with driver.session() as session:
        # Get all nodes and relationships
        query = """
        MATCH (n)
        WHERE n:Parameter OR n:DesignRule
        OPTIONAL MATCH (n)-[r]->(m)
        WHERE m:Parameter OR m:DesignRule
        RETURN n, r, m
        """
        result = await session.run(query)
        records = await result.data()

        return records


def create_pyvis_network(
    parameters: list,
    rules: list,
    height: str = "800px",
    width: str = "100%",
    title: str = "CrossTraffic Knowledge Graph",
) -> Network:
    """Create a PyVis network visualization."""
    # Create network with physics enabled for better layout
    # Disable select_menu and filter_menu to avoid TomSelect dependency issues
    net = Network(
        height=height,
        width=width,
        bgcolor="#1a1a2e",
        font_color="#ffffff",
        directed=True,
        select_menu=False,
        filter_menu=False,
        cdn_resources="remote",  # Use CDN for vis.js resources
    )

    # Configure physics for better layout
    net.barnes_hut(
        gravity=-8000,
        central_gravity=0.3,
        spring_length=200,
        spring_strength=0.05,
        damping=0.09,
    )

    # Color scheme
    colors = {
        "Parameter": "#4ecdc4",  # Teal
        "DesignRule": "#ff6b6b",  # Coral
        "SourceDoc": "#ffe66d",  # Yellow
        "FacilityType": "#95e1d3",  # Mint
    }

    # Group parameters by facility type
    facility_groups = {}
    for param in parameters:
        facility = param.facility_type.value if param.facility_type else "Unknown"
        if facility not in facility_groups:
            facility_groups[facility] = []
        facility_groups[facility].append(param)

    # Track parameter IDs for edge validation
    param_ids = set()

    # Add parameter nodes
    for param in parameters:
        facility = param.facility_type.value if param.facility_type else "Unknown"
        node_id = f"param_{param.id}"
        param_ids.add(param.id)

        # Build tooltip
        tooltip = f"""
        <b>{param.name}</b><br>
        Field: {param.rust_field}<br>
        Facility: {facility}<br>
        Unit: {param.unit or "N/A"}<br>
        Range: {param.typical_min or "?"} - {param.typical_max or "?"}
        """

        net.add_node(
            node_id,
            label=param.rust_field,
            title=tooltip,
            color=colors["Parameter"],
            shape="dot",
            size=25,
            group=facility,
        )

    # Add rule nodes and edges to parameters
    for rule in rules:
        node_id = f"rule_{rule.id}"

        # Determine color based on severity
        if rule.severity:
            severity_colors = {
                "error": "#ff4757",
                "warning": "#ffa502",
                "info": "#2ed573",
            }
            rule_color = severity_colors.get(rule.severity.value, colors["DesignRule"])
        else:
            rule_color = colors["DesignRule"]

        # Build tooltip
        tooltip = f"""
        <b>{rule.name}</b><br>
        Type: {rule.rule_type.value if rule.rule_type else "N/A"}<br>
        Severity: {rule.severity.value if rule.severity else "N/A"}<br>
        Min: {rule.min_value or "N/A"}<br>
        Max: {rule.max_value or "N/A"}
        """

        net.add_node(
            node_id,
            label=rule.name[:20] + "..." if len(rule.name) > 20 else rule.name,
            title=tooltip,
            color=rule_color,
            shape="diamond",
            size=15,
        )

        # Add edge from rule to parameter (VALIDATES relationship)
        if rule.parameter_id and rule.parameter_id in param_ids:
            param_node_id = f"param_{rule.parameter_id}"
            net.add_edge(
                node_id,
                param_node_id,
                title="VALIDATES",
                color="#666666",
                arrows="to",
            )

    return net


def create_parameters_only_network(
    parameters: list,
    rules: list,
    height: str = "800px",
    width: str = "100%",
) -> Network:
    """Create a simplified network showing only parameters and their relationships."""
    net = Network(
        height=height,
        width=width,
        bgcolor="#1a1a2e",
        font_color="#ffffff",
        directed=False,
        select_menu=False,
        filter_menu=False,
        cdn_resources="remote",
    )

    net.barnes_hut(
        gravity=-5000,
        central_gravity=0.3,
        spring_length=150,
        spring_strength=0.04,
        damping=0.09,
    )

    # Color by facility type
    facility_colors = {
        "BasicFreeway": "#4ecdc4",
        "MultilaneHighway": "#ff6b6b",
        "TwoLaneHighway": "#ffe66d",
        "UrbanStreet": "#95e1d3",
        "Unknown": "#888888",
    }

    # Add parameter nodes
    for param in parameters:
        facility = param.facility_type.value if param.facility_type else "Unknown"
        node_id = f"param_{param.id}"

        tooltip = f"""
        <b>{param.name}</b><br>
        Field: {param.rust_field}<br>
        Facility: {facility}<br>
        Unit: {param.unit or "N/A"}
        """

        net.add_node(
            node_id,
            label=param.rust_field,
            title=tooltip,
            color=facility_colors.get(facility, "#888888"),
            shape="dot",
            size=20,
            group=facility,
        )

    # Find parameters that share rules (implicit relationships)
    param_rules: dict[int, set[int]] = {}
    for rule in rules:
        if rule.parameter_id:
            if rule.parameter_id not in param_rules:
                param_rules[rule.parameter_id] = set()
            param_rules[rule.parameter_id].add(rule.id)

    # Add edges between parameters that have related rules
    # (This is a simplified approach - in a real KG, you'd have explicit AFFECTS relationships)
    params_list = list(parameters)
    for i, p1 in enumerate(params_list):
        for p2 in params_list[i + 1 :]:
            # Connect parameters of the same facility type
            if p1.facility_type == p2.facility_type:
                # Check if they share similar rule types
                rules1 = param_rules.get(p1.id, set())
                rules2 = param_rules.get(p2.id, set())
                if rules1 and rules2:
                    net.add_edge(
                        f"param_{p1.id}",
                        f"param_{p2.id}",
                        color="#333333",
                        width=1,
                    )

    return net


async def generate_visualization(
    output_path: Path | None = None,
    include_rules: bool = True,
    show_browser: bool = False,
) -> str:
    """Generate the knowledge graph visualization."""
    print("Fetching data from PostgreSQL...")
    parameters, rules = await fetch_graph_data_from_postgres()

    print(f"Found {len(parameters)} parameters and {len(rules)} rules")

    if include_rules:
        print("Creating full network with rules...")
        net = create_pyvis_network(parameters, rules)
        filename = "knowledge_graph.html"
    else:
        print("Creating parameters-only network...")
        net = create_parameters_only_network(parameters, rules)
        filename = "parameters_graph.html"

    # Determine output path
    if output_path is None:
        output_path = OUTPUT_DIR / filename
    else:
        output_path = Path(output_path)

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Add custom HTML header
    html_header = f"""
    <h2 style="color: #fff; font-family: sans-serif; text-align: center; margin: 10px;">
        CrossTraffic Knowledge Graph
    </h2>
    <p style="color: #888; font-family: sans-serif; text-align: center; margin: 5px;">
        {len(parameters)} Parameters | {len(rules) if include_rules else 0} Rules
    </p>
    """

    # Generate HTML
    print(f"Saving visualization to {output_path}...")
    net.save_graph(str(output_path))

    # Inject custom header
    with open(output_path) as f:
        html_content = f.read()

    html_content = html_content.replace(
        "<body>",
        f"<body>{html_header}",
    )

    with open(output_path, "w") as f:
        f.write(html_content)

    print(f"Visualization saved to: {output_path}")

    if show_browser:
        import webbrowser

        webbrowser.open(f"file://{output_path.absolute()}")

    return str(output_path)


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate Knowledge Graph visualization")
    parser.add_argument("--output", "-o", type=str, help="Output HTML file path", default=None)
    parser.add_argument(
        "--no-rules",
        action="store_true",
        help="Generate parameters-only visualization",
    )
    parser.add_argument("--open", action="store_true", help="Open in browser after generating")

    args = parser.parse_args()

    await generate_visualization(
        output_path=args.output,
        include_rules=not args.no_rules,
        show_browser=args.open,
    )


if __name__ == "__main__":
    asyncio.run(main())
