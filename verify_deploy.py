#!/usr/bin/env python3
import argparse
import boto3
import subprocess
import sys
import time


def get_instances(target, region):
    """
    Resolve the target (ASG Name or Instance ID) to a list of instance dictionaries.
    (Reused from deploy.py logic)
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
        pass

    print(f"[ERROR] Could not find ASG or Instance with ID/Name: {target}")
    return []


def get_instance_ip(instance, use_private_ip):
    if use_private_ip:
        return instance.get("PrivateIpAddress")
    else:
        return instance.get("PublicIpAddress") or instance.get("PrivateIpAddress")


def check_deployment(target, user, key_file, region, use_private_ip):
    instances = get_instances(target, region)

    if not instances:
        print("[ERROR] No instances found to check.")
        sys.exit(1)

    print(f"[INFO] Found {len(instances)} instance(s). Starting status check...")

    for instance in instances:
        instance_id = instance["InstanceId"]
        ip_address = get_instance_ip(instance, use_private_ip)

        if not ip_address:
            print(f"[WARN] Instance {instance_id} has no IP address. Skipping.")
            continue

        print(f"\n[INFO] Checking status on {instance_id} ({ip_address})...")

        ssh_opts = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
        if key_file:
            ssh_opts.extend(["-i", key_file])

        ssh_base = ["ssh"] + ssh_opts + [f"{user}@{ip_address}"]

        # 1. Check systemd service status
        print("  -> Service Status:")
        try:
            # Check if active
            subprocess.check_call(
                ssh_base + ["systemctl is-active imds_tracer_tool.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("     [OK] Active (Running)")
        except subprocess.CalledProcessError:
            print("     [FAIL] Inactive / Failed")

        # 2. Print Service Status Details (for uptime, PID, etc)
        try:
            subprocess.call(
                ssh_base
                + [
                    "systemctl status imds_tracer_tool.service --no-pager | grep -E 'Active:|Main PID:|Memory:'"
                ]
            )
        except Exception:
            pass

        # 3. Fetch last 20 lines of logs
        print("\n  -> Recent Logs (journalctl):")
        try:
            subprocess.call(
                ssh_base
                + ["sudo journalctl -u imds_tracer_tool.service -n 20 --no-pager"]
            )
        except Exception as e:
            print(f"     [ERROR] Failed to fetch logs: {e}")

        # 4. Make IMDS Call
        print("\n  -> Generating IMDS traffic (curl)...")
        try:
            curl_cmd = "curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/instance-id"
            # Run curl and capture output
            result = subprocess.check_output(
                ssh_base + [curl_cmd], stderr=subprocess.STDOUT
            )
            print(
                f"     [OK] IMDS Call successful. Response: {result.decode().strip()}"
            )
        except subprocess.CalledProcessError as e:
            print(
                f"     [FAIL] IMDS Call failed: {e.output.decode().strip() if e.output else str(e)}"
            )

    print("\n[INFO] Check completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify IMDS Packet Analyzer Deployment"
    )
    parser.add_argument("target", help="Auto Scaling Group Name or EC2 Instance ID")
    parser.add_argument("--user", help="SSH Username", default="ec2-user")
    parser.add_argument("--key-file", help="Path to SSH Private Key")
    parser.add_argument("--region", help="AWS Region")
    parser.add_argument(
        "--private-ip", help="Use Private IP for connection", action="store_true"
    )

    args = parser.parse_args()

    check_deployment(
        args.target, args.user, args.key_file, args.region, args.private_ip
    )
