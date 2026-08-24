#!/usr/bin/env python3
"""CDK app entry point."""
import aws_cdk as cdk
from stack import BeeContextQueryStack

app = cdk.App()
BeeContextQueryStack(app, "BeeContextQueryStack")
app.synth()
