# Architecture Overview

## System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Applications                       │
│              (Rust Libraries, LLMs, Web Apps, etc.)             │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI Server                           │
│                      (transportations-api)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Validation  │  │ Parameters  │  │     Sync Service        │  │
│  │   Router    │  │   Router    │  │  (PostgreSQL → Neo4j)   │  │
│  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘  │
│         │                │                      │                │
│         ▼                ▼                      ▼                │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Validation Engine                         ││
│  │  ┌───────────┐  ┌────────────┐  ┌─────────────────────────┐ ││
│  │  │Extractors │  │ Resolvers  │  │     Rule Checker        │ ││
│  │  │- JSON     │  │- Condition │  │  - Range/Min/Max/Enum   │ ││
│  │  │- Rust Lib │  │- Jurisdict │  │  - Formula (planned)    │ ││
│  │  │- LLM Text │  │            │  │                         │ ││
│  │  └───────────┘  └────────────┘  └─────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
┌─────────────────────────────┐   ┌─────────────────────────────┐
│        PostgreSQL           │   │          Neo4j              │
│   (Primary Data Store)      │   │    (Graph Queries)          │
│                             │   │                             │
│  - Parameters               │   │  - Rule relationships       │
│  - Design Rules             │   │  - Parameter dependencies   │
│  - Conditions               │   │  - Citation graph           │
│  - Source Documents         │   │                             │
└─────────────────────────────┘   └─────────────────────────────┘
```

## Directory Structure

```
transportations-validator/
├── src/transportations_validator/
│   ├── main.py                 # FastAPI app entry point
│   ├── api/
│   │   └── v1/
│   │       ├── validation.py   # /validate endpoints
│   │       ├── parameters.py   # /parameters endpoints
│   │       └── rules.py        # /rules endpoints
│   ├── db/
│   │   ├── postgres/
│   │   │   ├── connection.py   # Async session factory
│   │   │   └── repositories/   # Data access layer
│   │   └── neo4j/
│   │       ├── connection.py   # Neo4j driver
│   │       └── sync.py         # PostgreSQL → Neo4j sync
│   ├── extractors/
│   │   ├── base.py             # Base extractor class
│   │   ├── json_extractor.py   # JSON/dict extraction
│   │   ├── rust_lib.py         # Rust struct extraction
│   │   └── llm_response.py     # Text extraction (regex)
│   ├── validators/
│   │   ├── engine.py           # Core validation orchestrator
│   │   └── resolvers/
│   │       ├── condition.py    # Context matching
│   │       └── jurisdiction.py # Rule prioritization
│   └── models/
│       ├── parameter.py        # Parameter, Alias models
│       ├── rule.py             # DesignRule, RuleCondition
│       ├── condition.py        # ConditionType, ConditionValue
│       ├── source.py           # SourceDoc, SourceRef
│       └── validation.py       # Pydantic request/response models
├── migrations/
│   └── versions/               # Alembic migrations
├── seed_data/
│   ├── parameters/             # Parameter definitions by facility
│   ├── conditions/             # Condition types and values
│   └── rules/                  # Design rules (HCM, AASHTO)
├── scripts/
│   └── load_seed_data.py       # Database seeding
├── tests/
├── docs/
└── docker-compose.yaml
```

## Data Flow

### 1. Validation Request

```
Client Request
    │
    ▼
┌─────────────────┐
│ Extract Source  │  Detect: JSON, Rust struct, or LLM text
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Extract Params  │  Parse data into parameter key-value pairs
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Resolve Context │  Match context (terrain, jurisdiction, etc.)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Fetch Rules     │  Get applicable rules from PostgreSQL
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Prioritize      │  Sort by jurisdiction priority
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Rules     │  Validate each parameter against rules
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Return Result   │  Violations, warnings, citations
└─────────────────┘
```

### 2. Database Schema

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  SourceDoc   │──1:N─│  SourceRef   │──N:M─│  DesignRule  │
│              │      │              │      │              │
│ - title      │      │ - chapter    │      │ - name       │
│ - abbrev     │      │ - section    │      │ - rule_type  │
│ - edition    │      │ - page_start │      │ - min_value  │
│ - priority   │      │ - exhibit    │      │ - max_value  │
└──────────────┘      └──────────────┘      └──────┬───────┘
                                                   │
                                                   │ N:1
                                                   ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│ConditionType │──1:N─│ConditionVal  │──N:M─│  Parameter   │
│              │      │              │      │              │
│ - name       │      │ - value      │      │ - name       │
│ - rust_enum  │      │ - rust_var   │      │ - rust_field │
│              │      │              │      │ - facility   │
└──────────────┘      └──────────────┘      │ - unit       │
                                            └──────┬───────┘
                                                   │ 1:N
                                                   ▼
                                            ┌──────────────┐
                                            │ ParamAlias   │
                                            │ - alias      │
                                            │ - confidence │
                                            └──────────────┘
```

## Rule Types

| Type | Description | Example |
|------|-------------|---------|
| `range` | Value must be within min-max | Lane width: 10-12 ft |
| `min` | Value must be >= minimum | PHF >= 0.70 |
| `max` | Value must be <= maximum | Grade <= 6% |
| `enum` | Value must be in allowed set | Passing type: 0, 1, 2 |
| `formula` | Complex calculated constraint | (planned) |
| `relationship` | Cross-parameter constraint | (planned) |

## Extractors

### JSON Extractor
Handles structured dict/JSON input. Maps field names to parameters using:
1. Direct `rust_field` match
2. Parameter name match
3. Alias lookup

### Rust Library Extractor
Handles output from Rust transportation libraries (e.g., HCM calculations).
Recognizes known struct patterns and field naming conventions.

### LLM Response Extractor
Parses natural language text using regex patterns.
Limited accuracy - see `docs/plans/llm-integration.md` for improvement plans.

## Condition System

Rules can have conditions that must match for the rule to apply:

```json
{
  "rule": "Lane width minimum 11 ft",
  "conditions": [
    {"type": "terrain_type", "value": "Mountainous"},
    {"type": "facility_type", "value": "TwoLaneHighway"}
  ]
}
```

The condition resolver matches request context against rule conditions.

## Jurisdiction Priority

Rules from different sources are prioritized:

| Jurisdiction | Priority | Example |
|--------------|----------|---------|
| Project | 10 | Project-specific standards |
| Local | 25 | City/county requirements |
| State | 50 | State DOT standards |
| Federal | 100 | FHWA, HCM, AASHTO |

Lower number = higher priority. Local standards override federal when applicable.
