import json
import os
import time
from datetime import datetime, timezone, timedelta

import boto3

ec2 = boto3.client("ec2")

INSTANCE_ID = os.environ["INSTANCE_ID"]
EIP_ALLOCATION_ID = os.environ["EIP_ALLOCATION_ID"]
SNAPSHOT_RETENTION_DAYS = int(os.environ.get("SNAPSHOT_RETENTION_DAYS", 30))


def handler(event, context):
    action = event.get("action", "")

    if action == "start":
        return handle_start()
    elif action == "stop":
        return handle_stop()
    else:
        return {"status": "error", "message": f"Unknown action: {action}"}


def handle_start():
    # Start EC2
    ec2.start_instances(InstanceIds=[INSTANCE_ID])
    print(f"Starting {INSTANCE_ID}...")

    # Wait for running
    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[INSTANCE_ID])
    print(f"{INSTANCE_ID} is running")

    # Re-associate Elastic IP
    try:
        ec2.associate_address(InstanceId=INSTANCE_ID, AllocationId=EIP_ALLOCATION_ID)
        print(f"EIP {EIP_ALLOCATION_ID} associated")
    except Exception as e:
        print(f"EIP association skipped: {e}")

    return {"status": "ok", "action": "start", "instance": INSTANCE_ID}


def handle_stop():
    # Create EBS snapshot
    resp = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
    instance = resp["Reservations"][0]["Instances"][0]
    volume_id = instance["BlockDeviceMappings"][0]["Ebs"]["VolumeId"]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap = ec2.create_snapshot(
        VolumeId=volume_id,
        Description=f"StockAI DevServer snapshot {today}",
        TagSpecifications=[{
            "ResourceType": "snapshot",
            "Tags": [
                {"Key": "Purpose", "Value": "stockai-devserver"},
                {"Key": "InstanceId", "Value": INSTANCE_ID},
                {"Key": "CreatedDate", "Value": today},
                {"Key": "Name", "Value": f"stockai-devserver-{today}"},
            ],
        }],
    )
    print(f"Snapshot {snap['SnapshotId']} created")

    # Stop EC2
    ec2.stop_instances(InstanceIds=[INSTANCE_ID])
    print(f"Stopping {INSTANCE_ID}")

    # Prune old snapshots
    prune_old_snapshots()

    return {"status": "ok", "action": "stop", "snapshot": snap["SnapshotId"]}


def prune_old_snapshots():
    cutoff = datetime.now(timezone.utc) - timedelta(days=SNAPSHOT_RETENTION_DAYS)
    snapshots = ec2.describe_snapshots(
        OwnerIds=["self"],
        Filters=[{"Name": "tag:Purpose", "Values": ["stockai-devserver"]}],
    )["Snapshots"]

    for snap in snapshots:
        start_time = snap["StartTime"]
        if start_time < cutoff:
            ec2.delete_snapshot(SnapshotId=snap["SnapshotId"])
            print(f"Pruned old snapshot {snap['SnapshotId']} ({start_time.date()})")
