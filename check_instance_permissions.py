#!/usr/bin/env python3
import argparse
import boto3
import json
import sys
from botocore.exceptions import ClientError


def get_instance_profile(instance_id, region):
    session = boto3.Session(region_name=region)
    ec2 = session.client("ec2")

    print(
        f"[INFO] Inspecting Instance: {instance_id} in {region or session.region_name}"
    )

    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        reservations = response.get("Reservations", [])
        if not reservations:
            print(f"[ERROR] Instance {instance_id} not found.")
            return None

        instance = reservations[0]["Instances"][0]
        iam_profile = instance.get("IamInstanceProfile")

        if not iam_profile:
            print("[WARN] Instance has no IAM Instance Profile attached.")
            return None

        print(f"[INFO] Found Instance Profile: {iam_profile['Arn']}")
        return iam_profile["Arn"]

    except ClientError as e:
        print(f"[ERROR] Failed to describe instance: {e}")
        sys.exit(1)


def get_role_from_profile(profile_arn, region):
    session = boto3.Session(region_name=region)
    iam = session.client("iam")

    profile_name = profile_arn.split("/")[-1]

    try:
        response = iam.get_instance_profile(InstanceProfileName=profile_name)
        roles = response["InstanceProfile"]["Roles"]

        if not roles:
            print("[WARN] Instance Profile has no roles attached.")
            return None

        # Instance profiles usually have only one role
        role_name = roles[0]["RoleName"]
        print(f"[INFO] Found IAM Role: {role_name}")
        return role_name

    except ClientError as e:
        print(f"[ERROR] Failed to get instance profile: {e}")
        return None


def get_role_permissions(role_name, region):
    session = boto3.Session(region_name=region)
    iam = session.client("iam")

    print("\n--- Managed Policies ---")
    try:
        paginator = iam.get_paginator("list_attached_role_policies")
        for page in paginator.paginate(RoleName=role_name):
            for policy in page["AttachedPolicies"]:
                print(f"- {policy['PolicyName']} ({policy['PolicyArn']})")
                # Optional: Print policy document details?
                # That might be too verbose, listing names is usually a good start.
    except ClientError as e:
        print(f"[ERROR] Failed to list attached policies: {e}")

    print("\n--- Inline Policies ---")
    try:
        paginator = iam.get_paginator("list_role_policies")
        for page in paginator.paginate(RoleName=role_name):
            for policy_name in page["PolicyNames"]:
                print(f"- {policy_name}")
                try:
                    p_resp = iam.get_role_policy(
                        RoleName=role_name, PolicyName=policy_name
                    )
                    print(json.dumps(p_resp["PolicyDocument"], indent=2))
                except ClientError as pe:
                    print(f"  [ERROR] Could not retrieve policy document: {pe}")

    except ClientError as e:
        print(f"[ERROR] Failed to list inline policies: {e}")


def check_permissions(instance_id, region):
    profile_arn = get_instance_profile(instance_id, region)
    if not profile_arn:
        return

    role_name = get_role_from_profile(profile_arn, region)
    if not role_name:
        return

    get_role_permissions(role_name, region)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check IAM Permissions for an EC2 Instance"
    )
    parser.add_argument("instance_id", help="EC2 Instance ID")
    parser.add_argument("--region", help="AWS Region", default=None)

    args = parser.parse_args()

    check_permissions(args.instance_id, args.region)
