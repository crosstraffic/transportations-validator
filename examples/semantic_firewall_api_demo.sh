#!/bin/bash
# Semantic Firewall API Demo
#
# This script demonstrates the FastAPI integration of the Semantic Firewall
# described in Paper Section 2.2 and Section 4.2.
#
# Prerequisites:
#   - FastAPI server running: uv run uvicorn transportations_validator.main:app --reload
#   - curl and jq installed

BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "CrossTraffic Semantic Firewall API Demo"
echo "═══════════════════════════════════════════════════════════════════════════════"

echo ""
echo "DEMO 1: Valid Inputs - All 5 Constraints Pass"
echo "───────────────────────────────────────────────────────────────────────────────"
curl -s -X POST "${BASE_URL}/validate/firewall" \
  -H "Content-Type: application/json" \
  -d '{
    "lane_width": 11.0,
    "shoulder_width": 6.0,
    "hor_class": 2,
    "passing_type": 1,
    "design_rad": 1000.0,
    "speed_limit": 55
  }' | jq .

echo ""
echo "DEMO 2: Invalid Lane Width (8 ft < 9 ft minimum)"
echo "───────────────────────────────────────────────────────────────────────────────"
curl -s -X POST "${BASE_URL}/validate/firewall" \
  -H "Content-Type: application/json" \
  -d '{
    "lane_width": 8.0
  }' | jq .

echo ""
echo "DEMO 3: Speed-Curvature Mismatch (R=500 ft too small for 55 mph)"
echo "───────────────────────────────────────────────────────────────────────────────"
curl -s -X POST "${BASE_URL}/validate/firewall" \
  -H "Content-Type: application/json" \
  -d '{
    "design_rad": 500.0,
    "speed_limit": 55
  }' | jq .

echo ""
echo "DEMO 4: Multiple Violations"
echo "───────────────────────────────────────────────────────────────────────────────"
curl -s -X POST "${BASE_URL}/validate/firewall" \
  -H "Content-Type: application/json" \
  -d '{
    "lane_width": 14.0,
    "shoulder_width": 12.0,
    "hor_class": 7,
    "passing_type": 3,
    "design_rad": 400.0,
    "speed_limit": 55
  }' | jq .

echo ""
echo "DEMO 5: Boundary Case - Lane Width 8.99 ft (just below 9 ft minimum)"
echo "───────────────────────────────────────────────────────────────────────────────"
curl -s -X POST "${BASE_URL}/validate/firewall" \
  -H "Content-Type: application/json" \
  -d '{
    "lane_width": 8.99
  }' | jq .

echo ""
echo "═══════════════════════════════════════════════════════════════════════════════"
echo "Demo Complete"
echo ""
echo "The Semantic Firewall provides:"
echo "  - Deterministic validation (same input → same output)"
echo "  - Traceable error messages with HCM/AASHTO citations"
echo "  - Catches edge cases that RAG/LLM might miss"
echo "═══════════════════════════════════════════════════════════════════════════════"
