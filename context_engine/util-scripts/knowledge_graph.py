"""Knowledge graph tools for Neptune Analytics.

Provides entity extraction from conversations and graph query/write-back
capabilities. Works alongside Bedrock KB GraphRAG (Option 1) — this module
adds custom entities, relationships, and state tracking (Option 2).

Custom nodes use the label `KGEntity` and `KGAction` to avoid colliding
with Bedrock's auto-managed `Entity`/`Chunk`/`DocumentId` nodes.
"""

import os
import json
import boto3
from botocore.config import Config
from datetime import datetime, timezone

GRAPH_ID = os.environ.get("NEPTUNE_GRAPH_ID")
REGION = os.environ.get("AWS_REGION", "us-west-2")

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            'neptune-graph',
            region_name=REGION,
            config=Config(retries={"total_max_attempts": 1, "mode": "standard"}, read_timeout=None),
        )
    return _client


def execute_query(query: str, params: dict = None) -> dict:
    """Execute an openCypher query against Neptune Analytics."""
    kwargs = {
        'graphIdentifier': GRAPH_ID,
        'queryString': query,
        'language': 'OPEN_CYPHER',
    }
    if params:
        kwargs['parameters'] = params
    resp = _get_client().execute_query(**kwargs)
    return json.loads(resp['payload'].read().decode('UTF-8'))


# --- Entity Extraction ---

EXTRACTION_PROMPT = """\
You are a knowledge graph extraction assistant. Extract entities and relationships \
from the conversation below and return structured JSON.

-Goal-
Identify concrete, named entities and the relationships between them. \
Every entity and relationship must be directly stated in the text — no inference or speculation.

-Entity types-
Use ONLY these types:
- person: named individuals (e.g. "Mitra", "Bobby")
- organization: restaurants, businesses, venues, bakeries (e.g. "Luca's", "Goldie's")
- location: geographic places, streets, neighborhoods, landmarks (e.g. "Seattle waterfront", "Mission district")
- event: gatherings, occasions, celebrations (e.g. "Taco night", "Bobby's birthday dinner")
- item: food, drink, physical objects (e.g. "black beans", "tortillas", "miso ramen")
- preference: a person's stated food/cuisine/activity preference — normalize to one canonical form \
(e.g. use "Thai cuisine" not "Thai" or "Thai food"; use "vegetarian" not "vegetarian diet")
- commitment: a specific action someone explicitly agreed or committed to do \
(e.g. "Mitra buys black beans before Wednesday")

-DO NOT extract-
- Abstract concepts or descriptions (e.g. "casual atmosphere", "conversation-friendly environment")
- Vague phrases (e.g. "restaurant options", "guest logistics", "planning process")
- Action items or tasks — these become commitment entities only if explicitly committed to by a named person
- Duplicate entities: if the same thing appears in multiple forms, use the most specific name once

-Output format-
Return valid JSON with two arrays:
- "entities": each with "name" (string), "type" (from list above), \
"description" (one sentence grounded in what the text says about this entity)
- "relationships": each with "from" (entity name), "rel" (UPPERCASE relationship type), \
"to" (entity name), "description" (one sentence explaining the relationship), \
"strength" (integer 1-10: 10=explicitly stated core fact, 5=clearly implied, 1=peripheral mention)

Relationship types (UPPERCASE): ATTENDED, DISCUSSED, PLANNED, LOCATED_AT, COMMITTED_TO, \
PREFERS, KNOWS, MENTIONED, WANTS, NEEDS, ORGANIZED_BY, SCHEDULED_FOR, HOSTED, INVITED

-Examples-
Good entity: {{"name": "Mitra", "type": "person", "description": "Main speaker planning the taco night"}}
Good entity: {{"name": "Thai cuisine", "type": "preference", "description": "Shrijani's stated favorite cuisine"}}
Good entity: {{"name": "Luca's", "type": "organization", "description": "Italian restaurant being considered for Bobby's birthday dinner"}}
Bad entity: {{"name": "casual atmosphere", "type": "None"}} — DO NOT extract this
Bad entity: {{"name": "restaurant options", "type": "None"}} — DO NOT extract this

Good relationship: {{"from": "Shrijani", "rel": "PREFERS", "to": "Thai cuisine", \
"description": "Shrijani explicitly stated Thai is her favorite cuisine", "strength": 9}}
Good relationship: {{"from": "Mitra", "rel": "COMMITTED_TO", "to": "black beans", \
"description": "Mitra said she needs to buy black beans before the dinner", "strength": 8}}

Conversation:
{text}

JSON:"""


def extract_entities(text: str, model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0") -> dict:
    """Use an LLM to extract entities and relationships from text."""
    bedrock = boto3.client('bedrock-runtime', region_name=REGION)
    resp = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": EXTRACTION_PROMPT.format(text=text[:8000])}],
        }),
    )
    body = json.loads(resp['body'].read())
    content = body['content'][0]['text']
    # Extract JSON from response (handle markdown code blocks)
    if '```json' in content:
        content = content.split('```json')[1].split('```')[0]
    elif '```' in content:
        content = content.split('```')[1].split('```')[0]
    return json.loads(content.strip())


def store_entities(extracted: dict, source_id: str = None, user_id: str = None) -> dict:
    """Store extracted entities and relationships in Neptune."""
    now = datetime.now(timezone.utc).isoformat()
    entities_stored = 0
    rels_stored = 0

    for e in extracted.get('entities', []):
        name = e.get('name', '').strip()
        etype = e.get('type') or 'unknown'
        etype = etype.strip().lower()
        desc = e.get('description', '').strip()
        if not name or etype == 'none':
            continue
        execute_query(
            "MERGE (n:KGEntity {name: $name}) "
            "SET n.type = $type, n.description = $desc, "
            "n.updated_at = $now, n.user_id = $uid RETURN n",
            {"name": name, "type": etype, "desc": desc, "now": now, "uid": user_id or "default"}
        )
        entities_stored += 1

    for r in extracted.get('relationships', []):
        from_name = r.get('from', '').strip()
        to_name = r.get('to', '').strip()
        rel_type = r.get('rel', 'RELATED_TO').strip().upper().replace(' ', '_')
        rel_desc = r.get('description', '').strip()
        strength = int(r.get('strength', 5))
        if not from_name or not to_name:
            continue
        execute_query(
            f"MERGE (a:KGEntity {{name: $from_name}}) "
            f"MERGE (b:KGEntity {{name: $to_name}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"SET r.description = $desc, r.strength = $strength, "
            f"r.created_at = $now, r.source = $src RETURN r",
            {"from_name": from_name, "to_name": to_name, "desc": rel_desc,
             "strength": strength, "now": now, "src": source_id or "unknown"}
        )
        rels_stored += 1

    return {"entities_stored": entities_stored, "relationships_stored": rels_stored}


# --- Agent Write-Back ---

def store_action(action_type: str, description: str, related_entities: list = None,
                 status: str = "completed", user_id: str = None) -> dict:
    """Store an agent action in the graph for state tracking."""
    now = datetime.now(timezone.utc).isoformat()
    action_id = f"action_{now.replace(':', '').replace('-', '').replace('.', '')}"

    execute_query(
        "CREATE (a:KGAction {id: $id, type: $type, description: $desc, status: $status, "
        "created_at: $now, user_id: $uid}) RETURN a",
        {"id": action_id, "type": action_type, "desc": description,
         "status": status, "now": now, "uid": user_id or "default"}
    )

    if related_entities:
        for entity_name in related_entities:
            execute_query(
                "MATCH (a:KGAction {id: $aid}) "
                "MERGE (e:KGEntity {name: $ename}) "
                "MERGE (a)-[:RELATED_TO]->(e) RETURN a, e",
                {"aid": action_id, "ename": entity_name}
            )

    return {"action_id": action_id, "status": status}


def update_action_status(action_id: str, new_status: str) -> dict:
    """Update the status of a previously stored action."""
    now = datetime.now(timezone.utc).isoformat()
    result = execute_query(
        "MATCH (a:KGAction {id: $id}) SET a.status = $status, a.updated_at = $now RETURN a",
        {"id": action_id, "status": new_status, "now": now}
    )
    return {"updated": len(result.get('results', [])) > 0}


# --- Graph Queries ---

def query_entity(name: str) -> dict:
    """Get an entity and all its direct relationships."""
    result = execute_query(
        "MATCH (e:KGEntity {name: $name})-[r]-(other) "
        "RETURN e.name AS entity, e.type AS type, type(r) AS rel, "
        "other.name AS connected_to, labels(other) AS connected_labels "
        "ORDER BY rel",
        {"name": name}
    )
    return result


def query_multi_hop(start_entity: str, max_hops: int = 3) -> dict:
    """Find all entities within N hops of a starting entity."""
    result = execute_query(
        f"MATCH path = (start:KGEntity {{name: $name}})-[*1..{max_hops}]-(end:KGEntity) "
        "WHERE start <> end "
        "RETURN DISTINCT end.name AS entity, end.type AS type, length(path) AS hops "
        "ORDER BY hops, entity",
        {"name": start_entity}
    )
    return result


def query_by_type(entity_type: str) -> dict:
    """Get all entities of a given type."""
    result = execute_query(
        "MATCH (e:KGEntity {type: $type}) "
        "OPTIONAL MATCH (e)-[r]-(other:KGEntity) "
        "RETURN e.name AS entity, collect(DISTINCT {rel: type(r), to: other.name}) AS connections",
        {"type": entity_type}
    )
    return result


def query_actions(status: str = None, user_id: str = None) -> dict:
    """Get agent actions, optionally filtered by status."""
    where_clauses = []
    params = {}
    if status:
        where_clauses.append("a.status = $status")
        params["status"] = status
    if user_id:
        where_clauses.append("a.user_id = $uid")
        params["uid"] = user_id
    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    result = execute_query(
        f"MATCH (a:KGAction) {where} "
        "OPTIONAL MATCH (a)-[:RELATED_TO]->(e:KGEntity) "
        "RETURN a.id AS id, a.type AS type, a.description AS description, "
        "a.status AS status, a.created_at AS created_at, "
        "collect(e.name) AS related_entities "
        "ORDER BY a.created_at DESC",
        params
    )
    return result


def query_natural_language(question: str, model_id: str = "anthropic.claude-3-haiku-20240307-v1:0") -> str:
    """Convert a natural language question to a graph query and execute it."""
    bedrock = boto3.client('bedrock-runtime', region_name=REGION)

    # Get graph schema summary
    schema = execute_query(
        "MATCH (n:KGEntity) WITH DISTINCT n.type AS type, count(n) AS cnt "
        "RETURN type, cnt ORDER BY cnt DESC LIMIT 10"
    )
    rel_types = execute_query(
        "MATCH (a:KGEntity)-[r]->(b:KGEntity) "
        "RETURN DISTINCT type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC LIMIT 15"
    )

    prompt = f"""Given this knowledge graph schema:
Entity types: {json.dumps(schema.get('results', []))}
Relationship types: {json.dumps(rel_types.get('results', []))}
Node labels: KGEntity (custom entities), KGAction (agent actions)

Write an openCypher query to answer: "{question}"
Return ONLY the openCypher query, no explanation."""

    resp = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    body = json.loads(resp['body'].read())
    cypher = body['content'][0]['text'].strip()
    if '```' in cypher:
        cypher = cypher.split('```')[1].split('```')[0]
        if cypher.startswith('cypher'):
            cypher = cypher[6:]
    cypher = cypher.strip()

    return execute_query(cypher)
