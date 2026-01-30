"""Graph query API endpoints for Neo4j knowledge graph."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from transportations_validator.db.neo4j.connection import get_neo4j_session

router = APIRouter(prefix="/graph", tags=["graph"])


class RelatedParameter(BaseModel):
    """A parameter related through the knowledge graph."""

    rust_field: str
    name: str
    facility_type: str
    relationship_type: str
    description: str | None = None


class ParameterNode(BaseModel):
    """A parameter node in the graph."""

    id: str
    rust_field: str
    name: str
    facility_type: str
    type: str = "Parameter"


class RuleNode(BaseModel):
    """A rule node in the graph."""

    id: str
    name: str
    rule_type: str
    severity: str
    type: str = "DesignRule"


class GraphEdge(BaseModel):
    """An edge in the graph."""

    source: str
    target: str
    relationship: str
    properties: dict[str, Any] | None = None


class GraphVisualization(BaseModel):
    """D3-compatible graph visualization data."""

    nodes: list[dict[str, Any]]
    edges: list[GraphEdge]


class ConflictingRulePair(BaseModel):
    """A pair of rules that may conflict."""

    rule1_id: int
    rule1_name: str
    rule2_id: int
    rule2_name: str
    parameter: str
    reason: str


class ImpactAnalysis(BaseModel):
    """Impact analysis for a parameter."""

    parameter: str
    affected_rules: list[dict[str, Any]]
    related_parameters: list[str]
    citations: list[dict[str, Any]]


@router.get("/parameters/{rust_field}/related", response_model=list[RelatedParameter])
async def get_related_parameters(
    rust_field: str,
    depth: int = Query(default=2, ge=1, le=5, description="Maximum relationship depth"),
    neo4j=Depends(get_neo4j_session),
) -> list[RelatedParameter]:
    """Get parameters related to the specified parameter through AFFECTS or RELATED_TO relationships."""
    # Neo4j doesn't allow parameters in relationship depth, so we construct it safely
    # depth is already validated as int between 1-5 by FastAPI
    query = f"""
    MATCH (p:Parameter {{rust_field: $rust_field}})
          -[r:AFFECTS|RELATED_TO*1..{depth}]-(related:Parameter)
    WHERE p <> related
    WITH related, r
    UNWIND r as rel
    RETURN DISTINCT
        related.rust_field as rust_field,
        related.name as name,
        related.facility_type as facility_type,
        type(rel) as relationship_type,
        rel.description as description
    """
    result = await neo4j.run(query, rust_field=rust_field)
    records = await result.data()

    return [RelatedParameter(**record) for record in records]


@router.get("/rules/{rule_id}/citations")
async def get_rule_citations(
    rule_id: int,
    neo4j=Depends(get_neo4j_session),
) -> dict[str, Any]:
    """Get full citation information for a rule."""
    query = """
    MATCH (r:DesignRule {id: $rule_id})
    OPTIONAL MATCH (r)-[:VALIDATES]->(p:Parameter)
    OPTIONAL MATCH (r)-[c:CITED_IN]->(ref:SourceRef)-[:IN_DOCUMENT]->(doc:SourceDoc)
    RETURN
        r.id as rule_id,
        r.name as rule_name,
        r.rule_type as rule_type,
        r.severity as severity,
        p.name as parameter_name,
        p.rust_field as parameter_field,
        collect(DISTINCT {
            chapter: ref.chapter,
            section: ref.section,
            exhibit: ref.exhibit,
            document: doc.title,
            abbreviation: doc.abbreviation,
            is_primary: c.is_primary
        }) as citations
    """
    result = await neo4j.run(query, rule_id=rule_id)
    record = await result.single()

    if not record:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")

    data = dict(record)
    # Filter out empty citation entries
    data["citations"] = [c for c in data["citations"] if c.get("chapter")]
    return data


@router.get("/conflicts", response_model=list[ConflictingRulePair])
async def find_conflicting_rules(
    facility_type: str | None = Query(default=None, description="Filter by facility type"),
    neo4j=Depends(get_neo4j_session),
) -> list[ConflictingRulePair]:
    """Find rules that may conflict (overlapping ranges for same parameter)."""
    query = """
    MATCH (r1:DesignRule)-[:VALIDATES]->(p:Parameter)<-[:VALIDATES]-(r2:DesignRule)
    WHERE r1.id < r2.id
      AND r1.rule_type = 'range'
      AND r2.rule_type = 'range'
      AND (
        (r1.max_value IS NOT NULL AND r2.min_value IS NOT NULL AND r1.max_value < r2.min_value)
        OR (r2.max_value IS NOT NULL AND r1.min_value IS NOT NULL AND r2.max_value < r1.min_value)
        OR (r1.min_value IS NOT NULL AND r2.min_value IS NOT NULL AND r1.min_value > r2.max_value)
      )
    """
    if facility_type:
        query += " AND p.facility_type = $facility_type"

    query += """
    RETURN
        r1.id as rule1_id,
        r1.name as rule1_name,
        r2.id as rule2_id,
        r2.name as rule2_name,
        p.rust_field as parameter,
        'Non-overlapping ranges' as reason
    """

    result = await neo4j.run(query, facility_type=facility_type)
    records = await result.data()

    return [ConflictingRulePair(**record) for record in records]


@router.get("/impact", response_model=ImpactAnalysis)
async def analyze_parameter_impact(
    parameter: str = Query(..., description="Parameter rust_field to analyze"),
    neo4j=Depends(get_neo4j_session),
) -> ImpactAnalysis:
    """Analyze the impact of changes to a parameter - what rules and other parameters would be affected."""
    # Get rules that validate this parameter
    rules_query = """
    MATCH (p:Parameter {rust_field: $parameter})
          <-[:VALIDATES]-(r:DesignRule)
    OPTIONAL MATCH (r)-[:CITED_IN]->(ref:SourceRef)
    RETURN
        r.id as id,
        r.name as name,
        r.rule_type as rule_type,
        r.severity as severity,
        count(ref) as citation_count
    ORDER BY citation_count DESC
    """

    # Get related parameters
    related_query = """
    MATCH (p:Parameter {rust_field: $parameter})
          -[:AFFECTS|RELATED_TO*1..2]-(related:Parameter)
    WHERE p <> related
    RETURN DISTINCT related.rust_field as rust_field
    """

    # Get citations
    citations_query = """
    MATCH (p:Parameter {rust_field: $parameter})
          <-[:VALIDATES]-(r:DesignRule)
          -[:CITED_IN]->(ref:SourceRef)
          -[:IN_DOCUMENT]->(doc:SourceDoc)
    RETURN DISTINCT
        doc.title as document,
        doc.abbreviation as abbreviation,
        ref.chapter as chapter,
        ref.section as section
    """

    rules_result = await neo4j.run(rules_query, parameter=parameter)
    rules_data = await rules_result.data()

    related_result = await neo4j.run(related_query, parameter=parameter)
    related_data = await related_result.data()

    citations_result = await neo4j.run(citations_query, parameter=parameter)
    citations_data = await citations_result.data()

    return ImpactAnalysis(
        parameter=parameter,
        affected_rules=rules_data,
        related_parameters=[r["rust_field"] for r in related_data],
        citations=citations_data,
    )


@router.get("/visualize", response_model=GraphVisualization)
async def visualize_graph(
    center: str = Query(..., description="Center node rust_field"),
    depth: int = Query(default=2, ge=1, le=4, description="Traversal depth"),
    neo4j=Depends(get_neo4j_session),
) -> GraphVisualization:
    """Get D3-compatible graph visualization data centered on a parameter."""
    # Neo4j doesn't allow parameters in relationship depth, so we construct it safely
    # depth is already validated as int between 1-4 by FastAPI
    query = f"""
    MATCH path = (p:Parameter {{rust_field: $center}})-[*1..{depth}]-(connected)
    WHERE connected:Parameter OR connected:DesignRule
    WITH nodes(path) as ns, relationships(path) as rs
    UNWIND ns as n
    WITH collect(DISTINCT n) as nodes, rs
    UNWIND rs as r
    WITH nodes, collect(DISTINCT r) as rels
    RETURN nodes, rels
    """

    result = await neo4j.run(query, center=center)
    record = await result.single()

    if not record:
        # Return just the center node if no connections
        return GraphVisualization(
            nodes=[{"id": center, "type": "Parameter", "label": center}],
            edges=[],
        )

    nodes = []
    node_ids = set()

    for node in record["nodes"]:
        labels = list(node.labels)
        node_type = labels[0] if labels else "Unknown"

        if node_type == "Parameter":
            node_id = f"param_{node.get('id', node.get('rust_field'))}"
            if node_id not in node_ids:
                nodes.append(
                    {
                        "id": node_id,
                        "type": "Parameter",
                        "label": node.get("name", node.get("rust_field")),
                        "rust_field": node.get("rust_field"),
                        "facility_type": node.get("facility_type"),
                    }
                )
                node_ids.add(node_id)

        elif node_type == "DesignRule":
            node_id = f"rule_{node.get('id')}"
            if node_id not in node_ids:
                nodes.append(
                    {
                        "id": node_id,
                        "type": "DesignRule",
                        "label": node.get("name"),
                        "rule_type": node.get("rule_type"),
                        "severity": node.get("severity"),
                    }
                )
                node_ids.add(node_id)

    edges = []
    for rel in record["rels"]:
        start_node = rel.start_node
        end_node = rel.end_node

        # Determine node IDs based on type
        start_labels = list(start_node.labels)
        end_labels = list(end_node.labels)

        if "Parameter" in start_labels:
            source = f"param_{start_node.get('id', start_node.get('rust_field'))}"
        else:
            source = f"rule_{start_node.get('id')}"

        if "Parameter" in end_labels:
            target = f"param_{end_node.get('id', end_node.get('rust_field'))}"
        else:
            target = f"rule_{end_node.get('id')}"

        edges.append(
            GraphEdge(
                source=source,
                target=target,
                relationship=rel.type,
                properties=dict(rel) if rel else None,
            )
        )

    return GraphVisualization(nodes=nodes, edges=edges)


class SuggestedParameter(BaseModel):
    """A suggested parameter to check."""

    rust_field: str
    name: str


class SuggestResponse(BaseModel):
    """Response for suggest endpoint."""

    checked_parameters: list[str]
    suggestions: list[SuggestedParameter]


@router.get("/suggest", response_model=SuggestResponse)
async def suggest_related_checks(
    params: str = Query(..., description="Comma-separated parameter rust_fields"),
    neo4j=Depends(get_neo4j_session),
) -> SuggestResponse:
    """Given validated parameters, suggest other parameters that should also be checked."""
    param_list = [p.strip() for p in params.split(",")]

    query = """
    MATCH (p:Parameter)-[:AFFECTS|RELATED_TO]-(related:Parameter)
    WHERE p.rust_field IN $param_names
      AND NOT related.rust_field IN $param_names
    RETURN DISTINCT related.rust_field as suggestion, related.name as name
    LIMIT 10
    """

    result = await neo4j.run(query, param_names=param_list)
    records = await result.data()

    return SuggestResponse(
        checked_parameters=param_list,
        suggestions=[
            SuggestedParameter(rust_field=r["suggestion"], name=r["name"]) for r in records
        ],
    )
