#!/usr/bin/env python3
import argparse
import boto3
import botocore.exceptions
import sys


def create_log_table(table_name, region=None):
    if region:
        dynamodb = boto3.resource("dynamodb", region_name=region)
        client = boto3.client("dynamodb", region_name=region)
    else:
        dynamodb = boto3.resource("dynamodb")
        client = boto3.client("dynamodb")

    print(f"Checking if table '{table_name}' exists...")

    try:
        table = dynamodb.Table(table_name)
        table.load()
        print(f"Table '{table_name}' already exists. Skipping creation.")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Table '{table_name}' does not exist. Creating...")
            try:
                table = dynamodb.create_table(
                    TableName=table_name,
                    KeySchema=[
                        {"AttributeName": "PK", "KeyType": "HASH"},  # Partition key
                        {"AttributeName": "SK", "KeyType": "RANGE"},  # Sort key
                    ],
                    AttributeDefinitions=[
                        {"AttributeName": "PK", "AttributeType": "S"},
                        {"AttributeName": "SK", "AttributeType": "S"},
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )
                print("Waiting for table to be active...")
                table.wait_until_exists()
                print(f"Table '{table_name}' created successfully.")
            except Exception as create_error:
                print(f"Error creating table: {create_error}")
                sys.exit(1)
        else:
            print(f"Error checking table existence: {e}")
            sys.exit(1)

    # Enable TTL
    print("Configuring TTL...")
    try:
        client.update_time_to_live(
            TableName=table_name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expire_at"},
        )
        print("TTL enabled on attribute 'expire_at'.")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"][
            "Code"
        ] == "ValidationException" and "Time to live is already enabled" in str(e):
            print("TTL is already enabled.")
        else:
            print(f"Error enabling TTL: {e}")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create DynamoDB table for IMDS logging"
    )
    parser.add_argument(
        "--table-name", help="Name of the DynamoDB table", required=True
    )
    parser.add_argument("--region", help="AWS region", required=False)
    args = parser.parse_args()

    create_log_table(args.table_name, args.region)
