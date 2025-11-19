#!/usr/bin/env python3
import argparse
import boto3
import subprocess
import time
import sys
from botocore.exceptions import ClientError


def verify_and_wait(instance_id, user, key_file, table_name, region):
    print(f"[INFO] Starting verification loop for {instance_id}...")
    print(f"       Target Table: {table_name} ({region})")

    session = boto3.Session(region_name=region)
    dynamodb = session.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # Get the hostname of the instance (needed for DDB PK)
    print("[INFO] Resolving instance hostname...")
    ssh_opts = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
    if key_file:
        ssh_opts.extend(["-i", key_file])

    # We need the IP to ssh
    ec2 = session.client("ec2")
    try:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        inst = resp["Reservations"][0]["Instances"][0]
        ip_addr = inst.get("PublicIpAddress") or inst.get("PrivateIpAddress")
        if not ip_addr:
            print("[ERROR] Could not resolve IP address for instance.")
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to describe instance: {e}")
        sys.exit(1)

    ssh_base = ["ssh"] + ssh_opts + [f"{user}@{ip_addr}"]

    try:
        # Fetch hostname directly from the machine to match what the python script uses
        hostname = (
            subprocess.check_output(ssh_base + ["hostname"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
        print(f"       Hostname: {hostname}")
    except subprocess.CalledProcessError:
        print("[ERROR] Failed to SSH into instance to get hostname.")
        sys.exit(1)

    print("\n[INFO] Polling DynamoDB for new records...")

    start_time = time.time()
    max_duration = 300  # 5 minutes timeout

    while (time.time() - start_time) < max_duration:
        # 1. Trigger Traffic
        print("  -> Triggering IMDS traffic on remote node...")
        try:
            subprocess.check_call(
                ssh_base
                + ["curl -s -m 1 http://169.254.169.254/latest/meta-data/instance-id"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            print("     [WARN] Curl failed (network issue?)")

        # 2. Check DDB
        print("  -> Querying DynamoDB...")
        try:
            # Query for items with PK = hostname and SK > recent timestamp
            # For simplicity, just scan/query the last few items or check count
            # Using Query is efficient: PK = hostname
            response = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq(hostname),
                ScanIndexForward=False,  # Descending order (newest first)
                Limit=5,
            )

            items = response.get("Items", [])
            if items:
                print(f"\n[SUCCESS] Found {len(items)} log entries for {hostname}!")
                print("Last entry:")
                print(f"  Timestamp: {items[0]['SK']}")
                print(f"  Message:   {items[0]['message']}")
                return
            else:
                print("     [PENDING] No records found yet. Waiting 10s...")

        except ClientError as e:
            print(f"     [ERROR] DynamoDB Query failed: {e}")

        time.sleep(10)

    print("\n[FAIL] Timed out waiting for logs after 5 minutes.")
    sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Loop and wait for DynamoDB logs")
    parser.add_argument("instance_id", help="EC2 Instance ID")
    parser.add_argument("--user", help="SSH Username", default="ec2-user")
    parser.add_argument("--key-file", help="Path to SSH Private Key")
    parser.add_argument("--table-name", help="DynamoDB Table Name", required=True)
    parser.add_argument("--region", help="AWS Region", default="us-east-1")

    args = parser.parse_args()

    verify_and_wait(
        args.instance_id, args.user, args.key_file, args.table_name, args.region
    )
