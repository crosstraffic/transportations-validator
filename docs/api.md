# API Reference

Base URL: `http://localhost:8000/api/v1`

Interactive docs: http://localhost:8000/docs

## Validation Endpoints

### Validate Structured Data

Validate JSON data against design rules.

```
POST /validate/
```

**Request:**
```json
{
  "data": {
    "bffs": 65.0,
    "lw": 12.0,
    "lc_r": 6,
    "lc_l": 4,
    "phf": 0.92
  },
  "context": {
    "facility_type": "BasicFreeway",
    "terrain_type": "Level"
  },
  "strict": false
}
```

**Response:**
```json
{
  "success": true,
  "source_type": "json",
  "facility_type": "BasicFreeway",
  "result": {
    "is_valid": true,
    "error_count": 0,
    "warning_count": 0,
    "parameters": [
      {
        "parameter_name": "Lane Width",
        "rust_field": "lw",
        "value": 12.0,
        "is_valid": true,
        "violations": [],
        "warnings": []
      }
    ]
  },
  "extracted_context": {...},
  "message": "Validation completed successfully"
}
```

### Validate LLM Text Response

Extract and validate parameters from natural language text.

```
POST /validate/text
```

**Request:**
```json
{
  "text": "For this basic freeway, I recommend a lane width of 12 feet with a PHF of 0.92.",
  "context": {
    "facility_type": "BasicFreeway"
  }
}
```

**Response:**
```json
{
  "success": true,
  "source_type": "llm_response",
  "facility_type": "BasicFreeway",
  "result": {
    "is_valid": true,
    "parameters": [
      {
        "parameter_name": "Lane Width",
        "rust_field": "lane_width",
        "value": 12.0,
        "is_valid": true
      }
    ]
  }
}
```

### Get Validatable Parameters

Get list of parameters for a facility type.

```
GET /validate/parameters/{facility_type}
```

**Example:**
```bash
curl http://localhost:8000/api/v1/validate/parameters/BasicFreeway
```

**Response:**
```json
{
  "facility_type": "BasicFreeway",
  "parameters": [
    {
      "id": 1,
      "name": "Lane Width",
      "rust_field": "lw",
      "unit": "ft",
      "data_type": "float",
      "typical_min": 10.0,
      "typical_max": 12.0,
      "aliases": ["lane_width", "lane width"]
    }
  ]
}
```

## Parameter Endpoints

### List Parameters

```
GET /parameters/
```

**Query Parameters:**
- `facility_type` (optional): Filter by facility type
- `skip` (default: 0): Pagination offset
- `limit` (default: 100): Max results

**Example:**
```bash
curl "http://localhost:8000/api/v1/parameters/?facility_type=BasicFreeway&limit=10"
```

### Get Parameter by ID

```
GET /parameters/{id}
```

### Create Parameter

```
POST /parameters/
```

**Request:**
```json
{
  "name": "New Parameter",
  "rust_field": "new_param",
  "facility_type": "BasicFreeway",
  "unit": "ft",
  "data_type": "float",
  "description": "Description here",
  "typical_min": 0.0,
  "typical_max": 100.0
}
```

### Add Parameter Alias

```
POST /parameters/{param_id}/aliases?alias=new_alias&source=manual&confidence=1.0
```

## Sync Endpoints

### Trigger Neo4j Sync

Sync PostgreSQL data to Neo4j for graph queries.

```
POST /sync/trigger
```

**Response:**
```json
{
  "success": true,
  "message": "Sync completed successfully",
  "nodes_synced": 45,
  "relationships_synced": 120
}
```

## Facility Types

Valid facility types:
- `BasicFreeway`
- `TwoLaneHighway`
- `MultilaneHighway`
- `UrbanStreet`

## Common Parameter Fields (Rust)

### BasicFreeway
| Field | Description | Unit |
|-------|-------------|------|
| `bffs` | Base Free Flow Speed | mph |
| `lw` | Lane Width | ft |
| `lc_r` | Right Lateral Clearance | ft |
| `lc_l` | Left Lateral Clearance | ft |
| `nlanes` | Number of Lanes | - |
| `phf` | Peak Hour Factor | - |
| `ramp_density` | Ramp Density | ramps/mi |

### TwoLaneHighway
| Field | Description | Unit |
|-------|-------------|------|
| `lane_width` | Lane Width | ft |
| `shoulder_width` | Shoulder Width | ft |
| `length` | Segment Length | mi |
| `grade` | Percent Grade | % |
| `spl` | Speed Limit | mph |
| `volume` | Traffic Volume | veh/hr |
| `phv` | Heavy Vehicle % | % |
| `phf` | Peak Hour Factor | - |
| `passing_type` | Passing Type | 0/1/2 |

## Error Responses

**400 Bad Request:**
```json
{
  "detail": "Invalid facility type: Unknown. Valid types: ['BasicFreeway', 'TwoLaneHighway', ...]"
}
```

**404 Not Found:**
```json
{
  "detail": "Parameter not found"
}
```

**500 Internal Server Error:**
```json
{
  "detail": "Error message here"
}
```
