"""CDK stack for Bee context ingestion pipeline."""
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrock as bedrock,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_neptunegraph as neptunegraph,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

# Foundation models used by the GraphRAG knowledge base (region-agnostic ARNs).
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
ENRICHMENT_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
RERANK_MODEL = "cohere.rerank-v3-5:0"
EMBEDDING_DIMENSION = 1024


class BeeContextQueryStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # S3 bucket for transcript storage
        bucket = s3.Bucket(
            self, "BeeContextBucket",
            bucket_name=f"bee-context-store-{self.account}-{self.region}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            lifecycle_rules=[
                s3.LifecycleRule(expiration=Duration.days(14)),
            ],
        )

        # Secrets Manager — reference existing secret
        secret = secretsmanager.Secret.from_secret_name_v2(
            self, "BeeApiToken", "bee-api-token"
        )

        # --- GraphRAG knowledge base backed by Neptune Analytics ---------------
        # The graph is the KB's vector store. A single Retrieve call does both
        # semantic vector search and graph expansion over this one graph.
        # See docs/agent-context.md.
        graph = neptunegraph.CfnGraph(
            self, "BeeKnowledgeGraph",
            graph_name="bee-knowledge-graph",
            provisioned_memory=128,
            replica_count=0,
            public_connectivity=True,
            vector_search_configuration=neptunegraph.CfnGraph.VectorSearchConfigurationProperty(
                vector_search_dimension=EMBEDDING_DIMENSION,
            ),
        )
        # These resources already exist and are adopted via `cdk import`
        # (see docs/agent-context.md). RETAIN ensures a rollback or stack delete
        # never destroys the live graph or its ingested data.
        graph.apply_removal_policy(RemovalPolicy.RETAIN)

        # Role assumed by Bedrock to run the KB, ingest data, and rerank.
        kb_role = iam.Role(
            self, "BedrockKBRole",
            role_name="BedrockKBRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:ListBucket"],
            resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"],
        ))
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL}",
                f"arn:aws:bedrock:{self.region}::foundation-model/{ENRICHMENT_MODEL}",
                f"arn:aws:bedrock:{self.region}::foundation-model/{RERANK_MODEL}",
            ],
        ))
        # Rerank endpoint is not addressed by the model ARN, so scope to "*".
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:Rerank"],
            resources=["*"],
        ))
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "neptune-graph:ReadDataViaQuery",
                "neptune-graph:WriteDataViaQuery",
                "neptune-graph:DeleteDataViaQuery",
                "neptune-graph:GetGraph",
            ],
            resources=[graph.attr_graph_arn],
        ))

        kb = bedrock.CfnKnowledgeBase(
            self, "BeeGraphRagKb",
            name="bee-graphrag-kb",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/{EMBEDDING_MODEL}",
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="NEPTUNE_ANALYTICS",
                neptune_analytics_configuration=bedrock.CfnKnowledgeBase.NeptuneAnalyticsConfigurationProperty(
                    graph_arn=graph.attr_graph_arn,
                    field_mapping=bedrock.CfnKnowledgeBase.NeptuneAnalyticsFieldMappingProperty(
                        text_field="AMAZON_BEDROCK_TEXT_CHUNK",
                        metadata_field="AMAZON_BEDROCK_METADATA",
                    ),
                ),
            ),
        )
        kb.node.add_dependency(graph)
        kb.apply_removal_policy(RemovalPolicy.RETAIN)

        # S3 data source with automatic entity extraction for graph enrichment.
        data_source = bedrock.CfnDataSource(
            self, "BeeS3DataSource",
            name="bee-s3-clean-graphrag",
            knowledge_base_id=kb.attr_knowledge_base_id,
            data_deletion_policy="DELETE",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=bucket.bucket_arn,
                    inclusion_prefixes=["clean/"],
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                context_enrichment_configuration=bedrock.CfnDataSource.ContextEnrichmentConfigurationProperty(
                    type="BEDROCK_FOUNDATION_MODEL",
                    bedrock_foundation_model_configuration=bedrock.CfnDataSource.BedrockFoundationModelContextEnrichmentConfigurationProperty(
                        model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/{ENRICHMENT_MODEL}",
                        enrichment_strategy_configuration=bedrock.CfnDataSource.EnrichmentStrategyConfigurationProperty(
                            method="CHUNK_ENTITY_EXTRACTION",
                        ),
                    ),
                ),
            ),
        )
        data_source.apply_removal_policy(RemovalPolicy.RETAIN)

        # Lambda function — deps pre-installed via setup.sh
        fn = _lambda.Function(
            self, "BeeIngestFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../lambda/package"),
            timeout=Duration.minutes(5),
            memory_size=256,
            environment={
                "BUCKET_NAME": bucket.bucket_name,
                "BEE_SECRET_ARN": secret.secret_arn,
                "BEE_API_BASE": "https://app-api-developer.ce.bee.amazon.dev",
                "KB_ID": kb.attr_knowledge_base_id,
                "KB_DATA_SOURCE_ID": data_source.attr_data_source_id,
                "EXCLUDED_DAILY_IDS": "599111",
            },
        )

        bucket.grant_read_write(fn)
        secret.grant_read(fn)
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:StartIngestionJob"],
            resources=[kb.attr_knowledge_base_arn],
        ))

        # EventBridge rule — every 1 hour
        events.Rule(
            self, "HourlySync",
            schedule=events.Schedule.rate(Duration.hours(1)),
            targets=[targets.LambdaFunction(fn)],
        )
