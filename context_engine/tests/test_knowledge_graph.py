#!/usr/bin/env python3
"""Test the knowledge graph: entity queries, multi-hop traversal, write-back, and natural language queries.

Usage:
    AWS_DEFAULT_REGION=us-west-2 python3 test_knowledge_graph.py
    AWS_DEFAULT_REGION=us-west-2 python3 test_knowledge_graph.py --query "Who attended the Easter dinner?"
    AWS_DEFAULT_REGION=us-west-2 python3 test_knowledge_graph.py --entity Bobby
    AWS_DEFAULT_REGION=us-west-2 python3 test_knowledge_graph.py --type event
    AWS_DEFAULT_REGION=us-west-2 python3 test_knowledge_graph.py --actions
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'util-scripts'))
from knowledge_graph import (query_entity, query_multi_hop, query_by_type,
                              query_actions, query_natural_language, execute_query,
                              store_action, update_action_status)


def show_stats():
    print("=== Knowledge Graph Stats ===")
    r = execute_query("MATCH (n:KGEntity) RETURN n.type AS type, count(n) AS count ORDER BY count DESC")
    total = 0
    for row in r['results']:
        print(f"  {(row.get('type') or '?'):15s} | {row['count']}")
        total += row['count']
    print(f"  {'TOTAL':15s} | {total}")
    r = execute_query("MATCH (:KGEntity)-[r]->(:KGEntity) RETURN count(r) AS c")
    print(f"  Relationships   | {r['results'][0]['c']}")
    r = execute_query("MATCH (a:KGAction) RETURN count(a) AS c")
    print(f"  Agent actions   | {r['results'][0]['c']}")


def show_entity(name):
    print(f"\n=== Entity: {name} ===")
    r = query_entity(name)
    if not r.get('results'):
        print("  Not found.")
        return
    for row in r['results']:
        to = row.get('connected_to') or '?'
        rel = row.get('rel') or '?'
        print(f"  --[{rel}]--> {to}")

    print(f"\n=== 2-hop neighborhood ===")
    r = query_multi_hop(name, 2)
    for row in r.get('results', [])[:20]:
        n = row.get('entity') or '?'
        t = row.get('type') or '?'
        h = row.get('hops', '?')
        print(f"  {n:35s} | {t:15s} | hops: {h}")


def show_type(entity_type):
    print(f"\n=== Entities of type: {entity_type} ===")
    r = query_by_type(entity_type)
    for row in r.get('results', []):
        conns = [c['to'] for c in row.get('connections', []) if c.get('to')]
        name = row.get('entity') or '?'
        print(f"  {name:35s} | connections: {conns[:5]}")


def show_actions():
    print("\n=== Agent Actions ===")
    r = query_actions()
    if not r.get('results'):
        print("  No actions recorded.")
        return
    for row in r['results']:
        status = row.get('status') or '?'
        atype = row.get('type') or '?'
        desc = (row.get('description') or '?')[:80]
        ents = row.get('related_entities', [])
        print(f"  [{status}] {atype}: {desc}")
        if ents:
            print(f"    Related: {ents}")


def nl_query(question):
    print(f"\n=== Natural Language: {question} ===")
    try:
        r = query_natural_language(question)
        print(json.dumps(r, indent=2, default=str)[:1000])
    except Exception as e:
        print(f"  Error: {e}")


def main():
    p = argparse.ArgumentParser(description="Test the ContextIQ knowledge graph")
    p.add_argument("--query", help="Natural language query")
    p.add_argument("--entity", help="Look up an entity by name")
    p.add_argument("--type", help="List entities by type (person, event, location, etc.)")
    p.add_argument("--actions", action="store_true", help="Show agent actions")
    p.add_argument("--all", action="store_true", help="Run all demo queries")
    args = p.parse_args()

    show_stats()

    if args.entity:
        show_entity(args.entity)
    elif args.type:
        show_type(args.type)
    elif args.actions:
        show_actions()
    elif args.query:
        nl_query(args.query)
    elif args.all:
        show_entity("Bobby")
        show_type("event")
        show_type("person")
        show_actions()
        nl_query("What events did Bobby attend?")
        nl_query("Who knows Bobby and what do they discuss?")
    else:
        # Default: show a quick demo
        show_entity("Bobby")
        show_actions()


if __name__ == "__main__":
    main()
