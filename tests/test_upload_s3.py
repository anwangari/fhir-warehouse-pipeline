"""Tests for the S3 raw-landing uploader, using moto to mock S3."""

import json

import boto3
import pytest
from moto import mock_aws

import upload_s3 as up


def _make_bundles(tmp_path, n=3):
    for i in range(n):
        (tmp_path / f"bundle_{i}.json").write_text(json.dumps({"resourceType": "Bundle", "id": i}))
    return tmp_path


@mock_aws
def test_uploads_under_dated_prefix(tmp_path):
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="landing-test")
    _make_bundles(tmp_path, 3)

    keys = up.upload_bundles(client, "landing-test", fhir_dir=tmp_path,
                             ingest_date="2026-07-08")

    assert len(keys) == 3
    assert all(k.startswith("landing/fhir/ingest_date=2026-07-08/") for k in keys)
    listed = client.list_objects_v2(Bucket="landing-test")["Contents"]
    assert len(listed) == 3


@mock_aws
def test_rerun_is_idempotent(tmp_path):
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="landing-test")
    _make_bundles(tmp_path, 3)

    up.upload_bundles(client, "landing-test", fhir_dir=tmp_path, ingest_date="2026-07-08")
    up.upload_bundles(client, "landing-test", fhir_dir=tmp_path, ingest_date="2026-07-08")

    listed = client.list_objects_v2(Bucket="landing-test")["Contents"]
    assert len(listed) == 3          # same keys overwritten, not duplicated


@mock_aws
def test_empty_dir_uploads_nothing(tmp_path):
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="landing-test")
    assert up.upload_bundles(client, "landing-test", fhir_dir=tmp_path) == []
