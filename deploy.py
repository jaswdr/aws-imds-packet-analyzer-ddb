#!/usr/bin/env python3
import argparse
import boto3
import subprocess
import sys
import os


def get_instances(target, region):
    """
    Resolve the target (ASG Name or Instance ID) to a list of instance dictionaries.
    """
    session = boto3.Session(region_name=region)
    ec2 = session.client("ec2")
    asg = session.client("autoscaling")

    instances = []

    # 1. Try as Auto Scaling Group
    try:
        response = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[target])
        if response["AutoScalingGroups"]:
            asg_name = response["AutoScalingGroups"][0]["AutoScalingGroupName"]
            print(f"[INFO] Found Auto Scaling Group: {asg_name}")
            instance_ids = [
                i["InstanceId"] for i in response["AutoScalingGroups"][0]["Instances"]
            ]

            if not instance_ids:
                print("[WARN] ASG has no instances.")
                return []

            # Get details for these instances to find IPs
            resp = ec2.describe_instances(InstanceIds=instance_ids)
            for r in resp["Reservations"]:
                for i in r["Instances"]:
                    instances.append(i)
            return instances
    except Exception as e:
        # Not an ASG or permission error, continue to check as Instance ID
        print(f"[DEBUG] ASG Lookup Error: {e}")
        pass

    # 2. Try as Instance ID
    try:
        # Check if it looks like an instance ID to avoid unnecessary API calls
        if target.startswith("i-"):
            response = ec2.describe_instances(InstanceIds=[target])
            if response["Reservations"]:
                print(f"[INFO] Found Instance: {target}")
                for r in response["Reservations"]:
                    for i in r["Instances"]:
                        instances.append(i)
                return instances
    except Exception as e:
        print(f"[DEBUG] Instance Lookup Error: {e}")
        pass

    print(f"[ERROR] Could not find ASG or Instance with ID/Name: {target}")
    return []


def get_instance_ip(instance, use_private_ip):
    if use_private_ip:
        return instance.get("PrivateIpAddress")
    else:
        return instance.get("PublicIpAddress") or instance.get("PrivateIpAddress")


def deploy(
    target,
    user,
    key_file,
    source_path,
    dest_path,
    region,
    use_private_ip,
    start_service,
    ddb_table,
    ddb_retention,
    ddb_region,
):
    instances = get_instances(target, region)

    if not instances:
        print("[ERROR] No instances found to deploy to.")
        sys.exit(1)

    print(f"[INFO] Found {len(instances)} instance(s). Starting deployment...")

    # Ensure source path ends with /
    if not source_path.endswith("/"):
        source_path += "/"

    success_count = 0

    for instance in instances:
        instance_id = instance["InstanceId"]
        ip_address = get_instance_ip(instance, use_private_ip)

        if not ip_address:
            print(
                f"[WARN] Instance {instance_id} has no IP address (State: {instance['State']['Name']}). Skipping."
            )
            continue

        print(f"\n[INFO] Deploying to {instance_id} ({ip_address})...")

        ssh_opts = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
        if key_file:
            ssh_opts.extend(["-i", key_file])

        ssh_base = ["ssh"] + ssh_opts + [f"{user}@{ip_address}"]

        # 1. Rsync files
        print(f"  -> Syncing files to {dest_path}...")
        # Create remote directory first
        try:
            subprocess.check_call(ssh_base + [f"mkdir -p {dest_path}"])
        except subprocess.CalledProcessError:
            print(f"  [ERROR] Failed to create directory on {ip_address}")
            continue

        rsync_cmd = [
            "rsync",
            "-avz",
            "--exclude",
            ".git",
            "--exclude",
            "venv",
            "--exclude",
            "__pycache__",
            "--exclude",
            "*.pyc",
            source_path,
            f"{user}@{ip_address}:{dest_path}",
        ]

        # Configure rsync to use the ssh command with key
        rsh_cmd = "ssh " + " ".join(ssh_opts)
        rsync_cmd.extend(["-e", rsh_cmd])

        try:
            subprocess.check_call(rsync_cmd, stdout=subprocess.DEVNULL)
            print("  -> Sync complete.")
        except subprocess.CalledProcessError as e:
            print(f"  [ERROR] Rsync failed: {e}")
            continue

        # 2. Install Dependencies
        print("  -> Installing dependencies (this may take a while)...")
        install_cmd = f"cd {dest_path} && sudo ./install-deps.sh"
        try:
            subprocess.check_call(ssh_base + [install_cmd])
            print("  -> Dependencies installed.")
        except subprocess.CalledProcessError as e:
            print(f"  [ERROR] Dependency installation failed: {e}")
            continue

        # 3. Start Service (Optional)
        if start_service:
            print("  -> Activating service...")
            activate_cmd = f"cd {dest_path} && sudo ./activate-tracer-service.sh"
            if ddb_table:
                # Pass the specific DDB region if provided, else the instance region (which might be None), else empty string
                target_region = ddb_region if ddb_region else (region if region else "")
                activate_cmd += f" {ddb_table} {target_region}"
                if ddb_retention:
                    activate_cmd += f" {ddb_retention}"

            try:
                subprocess.check_call(ssh_base + [activate_cmd])
                print("  -> Service activated.")
            except subprocess.CalledProcessError as e:
                print(f"  [ERROR] Service activation failed: {e}")
                continue

        print(f"  [SUCCESS] Deployment to {instance_id} finished.")
        success_count += 1

    print(
        f"\n[SUMMARY] Deployment completed. Success: {success_count}/{len(instances)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Deploy IMDS Packet Analyzer to ASG or Instance"
    )
    parser.add_argument("target", help="Auto Scaling Group Name or EC2 Instance ID")
    parser.add_argument("--user", help="SSH Username", default="ec2-user")
    parser.add_argument("--key-file", help="Path to SSH Private Key")
    parser.add_argument("--region", help="AWS Region for Instance Lookup")
    parser.add_argument(
        "--dest",
        help="Destination path on remote",
        default="~/aws-imds-packet-analyzer",
    )
    parser.add_argument(
        "--private-ip", help="Use Private IP for connection", action="store_true"
    )
    parser.add_argument(
        "--no-start",
        help="Do not start the service after deployment",
        action="store_true",
    )
    parser.add_argument("--ddb-table", help="DynamoDB table name for logging")
    parser.add_argument(
        "--ddb-retention", help="DynamoDB retention period in days", default=30
    )
    parser.add_argument(
        "--ddb-region",
        help="AWS Region for DynamoDB (if different from instance region)",
    )

    args = parser.parse_args()

    # Default source is current directory
    source = os.getcwd()

    deploy(
        args.target,
        args.user,
        args.key_file,
        source,
        args.dest,
        args.region,
        args.private_ip,
        not args.no_start,
        args.ddb_table,
        args.ddb_retention,
        args.ddb_region,
    )
