#!/usr/bin/env python3
import argparse
import boto3
import json
import sys
import time
from botocore.exceptions import ClientError


def get_instance_role_name(instance_id, region):
    session = boto3.Session(region_name=region)
    ec2 = session.client("ec2")
    iam = session.client("iam")

    print(f"[INFO] Finding IAM role for instance {instance_id}...")
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        reservations = response.get("Reservations", [])
        if not reservations:
            print(f"[ERROR] Instance {instance_id} not found.")
            sys.exit(1)

        instance = reservations[0]["Instances"][0]
        iam_profile = instance.get("IamInstanceProfile")

        if not iam_profile:
            print(
                "[ERROR] Instance has no IAM Instance Profile attached. Cannot attach policy."
            )
            sys.exit(1)

        profile_name = iam_profile["Arn"].split("/")[-1]

        # Get role from profile
        profile_resp = iam.get_instance_profile(InstanceProfileName=profile_name)
        roles = profile_resp["InstanceProfile"]["Roles"]

        if not roles:
            print("[ERROR] Instance Profile has no roles attached.")
            sys.exit(1)

        return roles[0]["RoleName"]

    except ClientError as e:
        print(f"[ERROR] AWS Error: {e}")
        sys.exit(1)


def grant_ddb_write(instance_id, table_name, region):
    session = boto3.Session(region_name=region)
    iam = session.client("iam")
    sts = session.client("sts")

    account_id = sts.get_caller_identity()["Account"]
    role_name = get_instance_role_name(instance_id, region)

    # Construct the ARN for the table
    # Assuming standard partition, but could be aws-cn or aws-us-gov
    partition = "aws"
    if region and (region.startswith("cn-") or region.startswith("us-gov-")):
        # Simple heuristic, strict check might be needed for edge cases
        partition = "aws-cn" if region.startswith("cn-") else "aws-us-gov"

    # Handle region being None for global endpoints (though DDB is regional)
    # If region is not passed, boto3 session default is used.
    target_region = region or session.region_name

    table_arn = (
        f"arn:{partition}:dynamodb:{target_region}:{account_id}:table/{table_name}"
    )

    policy_name = f"IMDS_Packet_Analyzer_DDB_Write_{table_name}"

    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowDDBWrite",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:BatchWriteItem",
                ],
                "Resource": table_arn,
            }
        ],
    }

    print(f"[INFO] Attaching inline policy '{policy_name}' to role '{role_name}'...")
    print(f"       Target Table: {table_arn}")

    try:
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_doc),
        )
        print(
            f"[SUCCESS] Policy '{policy_name}' successfully attached to role '{role_name}'."
        )
        print("          Changes may take a few moments to propagate.")
    except ClientError as e:
        print(f"[ERROR] Failed to attach policy: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Grant DynamoDB Write Permissions to an EC2 Instance"
    )
    parser.add_argument("instance_id", help="EC2 Instance ID")
    parser.add_argument("--table-name", help="DynamoDB Table Name", required=True)
    parser.add_argument("--region", help="AWS Region", required=False)

    args = parser.parse_args()

    grant_ddb_write(args.instance_id, args.table_name, args.region)
