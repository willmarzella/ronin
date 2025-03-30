#!/usr/bin/env python
"""
Script to deploy Prefect flows to a Prefect API server.
"""

import os
import sys
import subprocess
from pathlib import Path
import argparse

# Add the parent directory to the Python path
sys.path.append(str(Path(__file__).parent.parent))

from prefect.deployments import Deployment
from prefect.filesystems import LocalFileSystem
from prefect.infrastructure import Process

# Import the flows
from flows.job_search_flow import job_search_flow
from flows.job_application_flow import job_application_flow
from flows.job_outreach_flow import job_outreach_flow
from flows.blog_generator_flow import blog_generator_flow


def deploy_flow(
    flow,
    name,
    work_pool_name,
    schedule=None,
    parameters=None,
    tags=None,
    description=None,
):
    """Deploy a flow to the Prefect API."""
    # Get the local file system storage
    local_fs = LocalFileSystem(basepath=str(Path(__file__).parent.parent))

    # Create the deployment
    deployment = Deployment.build_from_flow(
        flow=flow,
        name=name,
        work_pool_name=work_pool_name,
        storage=local_fs,
        schedule=schedule,
        parameters=parameters or {},
        tags=tags or [],
        description=description or f"Deployment for {name}",
        infrastructure=Process(env={"PYTHONPATH": "."}),
    )

    # Apply the deployment
    deployment_id = deployment.apply()
    print(f"Deployment created with ID: {deployment_id}")
    return deployment_id


def deploy_all_flows(work_pool_name="default-agent-pool", apply=False):
    """Deploy all flows to the Prefect API."""
    print(f"Deploying all flows to work pool: {work_pool_name}")

    # Check if the work pool exists, if not create it
    result = subprocess.run(
        ["prefect", "work-pool", "ls"], capture_output=True, text=True
    )

    if work_pool_name not in result.stdout:
        print(f"Creating work pool: {work_pool_name}")
        subprocess.run(
            ["prefect", "work-pool", "create", work_pool_name, "--type", "process"],
            check=True,
        )

    if apply:
        # Use prefect deploy command for all flows
        print("Applying all deployments from prefect.yaml")
        subprocess.run(["prefect", "deploy"], check=True)
    else:
        # Deploy each flow individually
        deployments = []

        # Job Search Flow
        deployments.append(
            deploy_flow(
                flow=job_search_flow,
                name="job-search",
                work_pool_name=work_pool_name,
                schedule={"cron": "0 9 * * *", "timezone": "UTC"},
                parameters={"platforms": ["linkedin", "indeed", "glassdoor"]},
                tags=["job-search", "automation"],
                description="Job search pipeline that scrapes job listings, analyzes them, and stores results",
            )
        )

        # Job Application Flow
        deployments.append(
            deploy_flow(
                flow=job_application_flow,
                name="job-application",
                work_pool_name=work_pool_name,
                schedule={"cron": "0 12 * * *", "timezone": "UTC"},
                parameters={"application_limit": 5},
                tags=["job-application", "automation"],
                description="Job application pipeline that prepares and submits applications",
            )
        )

        # Job Outreach Flow
        deployments.append(
            deploy_flow(
                flow=job_outreach_flow,
                name="job-outreach",
                work_pool_name=work_pool_name,
                schedule={"cron": "0 15 * * *", "timezone": "UTC"},
                parameters={"outreach_limit": 10},
                tags=["job-outreach", "automation"],
                description="Job outreach pipeline that manages follow-ups and networking",
            )
        )

        # Blog Generator Flow
        deployments.append(
            deploy_flow(
                flow=blog_generator_flow,
                name="blog-generator",
                work_pool_name=work_pool_name,
                schedule={
                    "cron": "0 18 * * 2",
                    "timezone": "UTC",
                },  # Every Tuesday at 6 PM
                parameters={"num_topics": 3, "auto_publish": False},
                tags=["blog", "content-generation"],
                description="Blog post generator pipeline",
            )
        )

        print(f"Successfully deployed {len(deployments)} flows")


def main():
    """Main function to handle command line arguments and deploy flows."""
    parser = argparse.ArgumentParser(description="Deploy Prefect flows")
    parser.add_argument(
        "--work-pool",
        default="default-agent-pool",
        help="Name of the work pool to deploy to",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Use prefect deploy command instead of building deployments individually",
    )
    args = parser.parse_args()

    deploy_all_flows(work_pool_name=args.work_pool, apply=args.apply)


if __name__ == "__main__":
    main()
