#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

set -e # Exit immediately if a command exits with a non-zero status

BPF_TRACE_SERVICE="imds_tracer_tool.service"
BPF_TRACE_PATH=$(pwd)
BPF_TRACE_SYSTEMD_PATH="/etc/systemd/system/$BPF_TRACE_SERVICE"

# Check if script is running as root
if [[ $EUID -ne 0 ]]; then
  echo "[ERROR] Please run as root (sudo)" >&2
  exit 1
fi

DDB_TABLE_NAME=$1
AWS_REGION=$2
RETENTION_DAYS=${3:-30}

# Function to create service file
create_service_file() {
  local exec_start_cmd="$(command -v python3) -u $BPF_TRACE_PATH/src/imds_snoop.py"

  if [ -n "$DDB_TABLE_NAME" ]; then
    exec_start_cmd="$exec_start_cmd --ddb-table $DDB_TABLE_NAME"
    if [ -n "$AWS_REGION" ]; then
      exec_start_cmd="$exec_start_cmd --aws-region $AWS_REGION"
    fi
    exec_start_cmd="$exec_start_cmd --ddb-retention-days $RETENTION_DAYS"
  fi

  cat <<EOF >"$BPF_TRACE_SYSTEMD_PATH"
[Unit]
Description=ImdsPacketAnalyzer IMDS detection tooling from AWS
Before=network-online.target

[Service]
Type=simple
Restart=always
WorkingDirectory=$BPF_TRACE_PATH
ExecStart=$exec_start_cmd

[Install]
WantedBy=multi-user.target
EOF
}

# Main script execution
echo "--- Removing old service file"
rm -f "$BPF_TRACE_SYSTEMD_PATH"

echo "--- Creating new service file"
create_service_file

echo "--- Service details:"
cat "$BPF_TRACE_SYSTEMD_PATH"

echo
echo "--- Reloading daemon and enabling the $BPF_TRACE_SERVICE service"
systemctl daemon-reload
systemctl enable "$BPF_TRACE_SERVICE"

echo "--- Starting the $BPF_TRACE_SERVICE service"
systemctl start "$BPF_TRACE_SERVICE"

echo "--- Done"

