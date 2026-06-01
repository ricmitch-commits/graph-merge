from dataclasses import dataclass, field


@dataclass
class GraphNode:
    id: str
    file: str
    symbol: str
    kind: str
    calls: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str
    confidence: str


@dataclass
class Change:
    type: str
    node_id: str | None = None
    file: str | None = None
    symbol: str | None = None
    kind: str | None = None
    before: dict | None = None
    after: dict | None = None
    rationale: str | None = None
    edge: "GraphEdge | None" = None


@dataclass
class SemanticDiff:
    commit_message: str
    changes: list[Change] = field(default_factory=list)


@dataclass
class SourceChange:
    node_id: str
    type: str = ""


@dataclass
class DestinationNode:
    file: str
    symbol: str


@dataclass
class Mapping:
    source_change: SourceChange
    destination_node: DestinationNode
    confidence: str
    rationale: str


@dataclass
class UnmappableChange:
    source_change: SourceChange
    reason: str


@dataclass
class MappingResult:
    mappings: list[Mapping] = field(default_factory=list)
    unmappable: list[UnmappableChange] = field(default_factory=list)
