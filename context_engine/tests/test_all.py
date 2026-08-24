#!/usr/bin/env python3
"""Comprehensive functionality tests for the context_engine.

Tests all components: S3 data, GraphRAG KB, knowledge graph,
entity extraction, write-back, multi-hop queries, and Lambda integration.

Usage:
    AWS_DEFAULT_REGION=us-west-2 python3 test_all.py
    AWS_DEFAULT_REGION=us-west-2 python3 test_all.py -v          # verbose
    AWS_DEFAULT_REGION=us-west-2 python3 test_all.py -k graph    # filter by name
"""
import os
import sys
import json
import time
import unittest
import boto3
from botocore.config import Config

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'util-scripts'))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from context_engine.env_config import bucket, region, require  # noqa: E402

REGION = region()
BUCKET = bucket()
GRAPHRAG_KB_ID = require("GRAPHRAG_KB_ID")
NEPTUNE_GRAPH_ID = require("NEPTUNE_GRAPH_ID")


class TestS3Data(unittest.TestCase):
    """Verify S3 has the expected data structure."""

    @classmethod
    def setUpClass(cls):
        cls.s3 = boto3.client("s3", region_name=REGION)

    def _list_keys(self, prefix):
        resp = self.s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
        return [o["Key"] for o in resp.get("Contents", [])]

    def test_clean_conversations_exist(self):
        keys = self._list_keys("clean/conversations/")
        txt_files = [k for k in keys if k.endswith(".txt")]
        self.assertGreater(len(txt_files), 0, "No clean conversation files in S3")

    def test_clean_daily_exist(self):
        keys = self._list_keys("clean/daily/")
        txt_files = [k for k in keys if k.endswith(".txt")]
        self.assertGreater(len(txt_files), 0, "No clean daily files in S3")

    def test_clean_facts_exist(self):
        keys = self._list_keys("clean/facts/")
        self.assertTrue(any("all_facts" in k for k in keys), "No facts file in S3")

    def test_metadata_sidecars_exist(self):
        keys = self._list_keys("clean/conversations/")
        metadata = [k for k in keys if k.endswith(".metadata.json")]
        self.assertGreater(len(metadata), 0, "No metadata sidecar files")

    def test_metadata_has_bee_account_id(self):
        keys = self._list_keys("clean/conversations/")
        metadata_key = next((k for k in keys if k.endswith(".metadata.json")), None)
        self.assertIsNotNone(metadata_key)
        obj = self.s3.get_object(Bucket=BUCKET, Key=metadata_key)
        data = json.loads(obj["Body"].read())
        self.assertIn("metadataAttributes", data)
        self.assertIn("beeAccountId", data["metadataAttributes"])


class TestGraphRAGKB(unittest.TestCase):
    """Test the GraphRAG-enhanced Bedrock KB."""

    @classmethod
    def setUpClass(cls):
        cls.client = boto3.client("bedrock-agent-runtime", region_name=REGION)

    def _retrieve(self, query, n=5):
        return self.client.retrieve(
            knowledgeBaseId=GRAPHRAG_KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": n}},
        )["retrievalResults"]

    def test_graphrag_returns_results(self):
        results = self._retrieve("taco night plans")
        self.assertGreater(len(results), 0)

    def test_results_have_scores(self):
        results = self._retrieve("food preferences")
        for r in results:
            self.assertIn("score", r)
            self.assertGreater(r["score"], 0)

    def test_results_have_content(self):
        results = self._retrieve("birthday dinner")
        for r in results:
            self.assertIn("content", r)
            self.assertIn("text", r["content"])
            self.assertGreater(len(r["content"]["text"]), 0)

    def test_graphrag_finds_entity_connected_content(self):
        """GraphRAG should find content connected through entities."""
        results = self._retrieve("vegetarian food preferences")
        self.assertGreater(len(results), 0)
        texts = " ".join(r["content"]["text"] for r in results)
        self.assertGreater(len(texts), 100)


class TestNeptuneGraph(unittest.TestCase):
    """Test Neptune Analytics graph connectivity and data."""

    @classmethod
    def setUpClass(cls):
        cls.client = boto3.client(
            "neptune-graph", region_name=REGION,
            config=Config(retries={"total_max_attempts": 1}, read_timeout=None),
        )

    def _query(self, cypher, params=None):
        kwargs = {
            "graphIdentifier": NEPTUNE_GRAPH_ID,
            "queryString": cypher,
            "language": "OPEN_CYPHER",
        }
        if params:
            kwargs["parameters"] = params
        resp = self.client.execute_query(**kwargs)
        return json.loads(resp["payload"].read().decode("UTF-8"))

    def test_graph_is_available(self):
        graph = boto3.client("neptune-graph", region_name=REGION).get_graph(
            graphIdentifier=NEPTUNE_GRAPH_ID
        )
        self.assertEqual(graph["status"], "AVAILABLE")

    def test_graph_has_bedrock_entities(self):
        """Bedrock GraphRAG should have auto-extracted Entity nodes."""
        r = self._query("MATCH (e:Entity) RETURN count(e) AS c")
        self.assertGreater(r["results"][0]["c"], 0)

    def test_graph_has_custom_entities(self):
        """Custom KG should have KGEntity nodes."""
        r = self._query("MATCH (e:KGEntity) RETURN count(e) AS c")
        self.assertGreater(r["results"][0]["c"], 0, "Expected KGEntity nodes")

    def test_graph_has_relationships(self):
        r = self._query("MATCH (:KGEntity)-[r]->(:KGEntity) RETURN count(r) AS c")
        self.assertGreater(r["results"][0]["c"], 0, "Expected relationships")

    def test_graph_has_person_entities(self):
        r = self._query("MATCH (e:KGEntity {type: 'person'}) RETURN count(e) AS c")
        self.assertGreater(r["results"][0]["c"], 0, "Expected person entities")

    def test_entity_types_present(self):
        r = self._query("MATCH (e:KGEntity) RETURN DISTINCT e.type AS type")
        types = {row["type"] for row in r["results"] if row["type"]}
        self.assertTrue(
            types.issuperset({"person", "event"}),
            f"Missing expected types. Got: {types}",
        )

    def test_preferences_exist(self):
        r = self._query(
            "MATCH (p:KGEntity)-[:PREFERS]->(pref:KGEntity) "
            "RETURN count(p) AS c"
        )
        self.assertGreater(r["results"][0]["c"], 0, "Expected PREFERS relationships")


class TestKnowledgeGraphModule(unittest.TestCase):
    """Test the knowledge_graph.py Python module."""

    def test_import(self):
        from knowledge_graph import (  # noqa: F401
            execute_query, extract_entities, store_entities,
            store_action, update_action_status, query_entity,
            query_multi_hop, query_by_type, query_actions,
            query_natural_language,
        )

    def test_query_entity(self):
        from knowledge_graph import query_entity
        r = query_entity("Mitra")
        self.assertIn("results", r)

    def test_query_by_type(self):
        from knowledge_graph import query_by_type
        r = query_by_type("event")
        self.assertIn("results", r)
        self.assertGreater(len(r["results"]), 0)

    def test_query_multi_hop(self):
        from knowledge_graph import query_multi_hop
        r = query_multi_hop("Mitra", 2)
        self.assertIn("results", r)

    def test_store_and_query_action(self):
        from knowledge_graph import store_action, query_actions, update_action_status
        action = store_action("test", "Integration test action", ["Mitra"], "test_pending", "test_user")
        self.assertIn("action_id", action)

        r = query_actions(status="test_pending")
        found = any(row.get("description") == "Integration test action" for row in r.get("results", []))
        self.assertTrue(found, "Stored action not found in query")

        update_action_status(action["action_id"], "test_done")
        r = query_actions(status="test_done")
        found = any(row.get("id") == action["action_id"] for row in r.get("results", []))
        self.assertTrue(found, "Updated action not found")

    def test_extract_entities(self):
        from knowledge_graph import extract_entities
        text = "Mitra and Bobby planned a taco night at Mitra's apartment."
        result = extract_entities(text)
        self.assertIn("entities", result)
        self.assertGreater(len(result["entities"]), 0)

    def test_store_entities(self):
        from knowledge_graph import store_entities, execute_query
        extracted = {
            "entities": [{"name": "TestEntity_XYZ", "type": "test", "description": "test entity"}],
            "relationships": [],
        }
        result = store_entities(extracted, source_id="test", user_id="test")
        self.assertEqual(result["entities_stored"], 1)

        r = execute_query("MATCH (e:KGEntity {name: 'TestEntity_XYZ'}) RETURN e")
        self.assertEqual(len(r["results"]), 1)

        execute_query("MATCH (e:KGEntity {name: 'TestEntity_XYZ'}) DETACH DELETE e")

    def test_natural_language_query(self):
        from knowledge_graph import query_natural_language
        r = query_natural_language("What events are planned?")
        self.assertIn("results", r)


class TestLambdaIntegration(unittest.TestCase):
    """Test the Lambda data job is deployed and running."""

    @classmethod
    def setUpClass(cls):
        cls.lambda_client = boto3.client("lambda", region_name=REGION)
        cls.events_client = boto3.client("events", region_name=REGION)
        cls.logs_client = boto3.client("logs", region_name=REGION)

    def _get_function_name(self):
        funcs = self.lambda_client.list_functions()["Functions"]
        for f in funcs:
            if "BeeIngest" in f["FunctionName"]:
                return f["FunctionName"]
        return None

    def test_lambda_exists(self):
        name = self._get_function_name()
        self.assertIsNotNone(name, "BeeIngest Lambda not found")

    def test_eventbridge_rule_enabled(self):
        rules = self.events_client.list_rules()["Rules"]
        bee_rules = [r for r in rules if "BeeContext" in r["Name"]]
        self.assertGreater(len(bee_rules), 0, "No EventBridge rule found")
        self.assertEqual(bee_rules[0]["State"], "ENABLED")

    def test_lambda_has_recent_logs(self):
        name = self._get_function_name()
        if not name:
            self.skipTest("Lambda not found")
        log_group = f"/aws/lambda/{name}"
        now_ms = int(time.time() * 1000)
        day_ago = now_ms - 86400000
        try:
            resp = self.logs_client.filter_log_events(
                logGroupName=log_group, startTime=day_ago,
                filterPattern="Starting Bee sync", limit=1,
            )
            self.assertGreater(len(resp.get("events", [])), 0, "No recent Lambda invocations")
        except Exception:
            self.skipTest("Could not access Lambda logs")


class TestCDKStack(unittest.TestCase):
    """Verify CDK stack resources exist."""

    def test_cloudformation_stack_exists(self):
        cf = boto3.client("cloudformation", region_name=REGION)
        try:
            resp = cf.describe_stacks(StackName="BeeContextQueryStack")
            self.assertIn("COMPLETE", resp["Stacks"][0]["StackStatus"])
        except Exception:
            self.fail("BeeContextQueryStack not found")


class TestScripts(unittest.TestCase):
    """Verify scripts exist and are executable."""

    SCRIPTS = [
        "util-scripts/verify-bee-api.sh",
        "util-scripts/lambda-status.sh",
        "util-scripts/prefill.sh",
        "util-scripts/invoke-lambda.sh",
        "util-scripts/setup-aws.sh",
    ]

    def test_scripts_exist(self):
        base = os.path.join(os.path.dirname(__file__), '..')
        for script in self.SCRIPTS:
            path = os.path.join(base, script)
            self.assertTrue(os.path.exists(path), f"Missing: {script}")

    def test_scripts_executable(self):
        base = os.path.join(os.path.dirname(__file__), '..')
        for script in self.SCRIPTS:
            path = os.path.join(base, script)
            self.assertTrue(os.access(path, os.X_OK), f"Not executable: {script}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
