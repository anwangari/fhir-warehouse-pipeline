# AWS setup — S3 landing zone

What this project needs on AWS is deliberately small: **one S3 bucket** (the
raw landing zone) and **one identity** allowed to `PutObject` into it. This
guide covers three ways to provision that — by hand (Console/CLI) and as code
(Terraform, with the AWS-native alternatives noted) — and the trade-offs.

> Grounded in current AWS docs (2026). Two recent changes worth knowing:
> new buckets have **ACLs disabled** (Object Ownership = *bucket owner
> enforced*) and **Block Public Access on** by default, and since **April 2026**
> SSE-C is disabled by default — SSE-S3 remains the default at-rest encryption.

---

## 0. Prerequisites

- An AWS account.
- **AWS CLI v2** installed (`aws --version`).
- A globally-unique bucket name, e.g. `tony-fhir-landing-<something>`.

---

## 1. Credentials first (do this before anything else)

**This project uses IAM user access keys** — the pragmatic choice for a solo
personal account, where standing up IAM Identity Center for a single bucket is
overkill. Know the trade-off though: these are *long-lived* credentials, so the
hygiene rules below are non-negotiable.

**What this project uses — IAM user access keys:**

```bash
# 1. IAM -> Users -> your user -> Security credentials -> Create access key
# 2. attach the least-privilege policy from §2 to that user (not root!)
aws configure                 # paste Access Key ID, Secret, region (e.g. us-east-1), output=json
aws sts get-caller-identity   # confirm you're authenticated
```

`boto3` in `upload_s3.py` reads these automatically from `~/.aws/credentials`
via the default credential chain — nothing in code. Hygiene: never use root
account keys, scope the user to least privilege (§2), rotate the key
periodically, and never commit it (`~/.aws` and `.env` stay off git).

**Best practice for teams/orgs — IAM Identity Center (SSO).** AWS's 2026
recommendation is to avoid long-lived keys for human access and use Identity
Center, which hands the CLI *temporary*, auto-expiring credentials:

```bash
aws configure sso             # needs an Identity Center "start URL" (org portal)
aws sso login --profile fhir  # browser auth; refresh when it expires
export AWS_PROFILE=fhir        # PowerShell: $env:AWS_PROFILE="fhir"
```

It requires IAM Identity Center to be enabled (an org/portal), which is why it's
skipped here — but it's the right answer at team scale, and worth saying so in
an interview: *"solo project, so I used a scoped IAM access key; in a team I'd
use Identity Center for temporary credentials."*

**When the pipeline runs on AWS** (EC2/Lambda/ECS later in the arc): attach an
**IAM role** to the compute instead of any keys — the role supplies rotating
temporary credentials. Same principle as SSO, for machines.

---

## 2. The least-privilege policy (used by every approach)

The uploader only ever writes objects under one prefix. Grant exactly that:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "FhirRawLandingPut",
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::<bucket>/landing/fhir/*"
    }
  ]
}
```

No `s3:*`, no bucket-wide `Resource`, no list/get/delete. If a later step
needs to *read* raw back (replay), add `s3:GetObject` on the same prefix then.

---

## 3. Manual setup

### 3a. Console (click-through)

1. **S3 → Create bucket.** Name it; pick your region. Leave **ACLs disabled**
   (default) and **Block all public access ON** (default) — don't touch these.
2. **Bucket Versioning → Enable.** (Immutable-raw safety net; lets you recover
   overwrites.)
3. **Default encryption** is already **SSE-S3** — leave it, or switch to
   **SSE-KMS** if you want key-level audit/control.
4. **Permissions → Bucket policy** — enforce HTTPS-only (deny plaintext):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Sid": "DenyInsecureTransport",
       "Effect": "Deny",
       "Principal": "*",
       "Action": "s3:*",
       "Resource": ["arn:aws:s3:::<bucket>", "arn:aws:s3:::<bucket>/*"],
       "Condition": { "Bool": { "aws:SecureTransport": "false" } }
     }]
   }
   ```
5. **IAM → Policies → Create policy**, paste §2, attach it to your SSO
   permission set / role / user.

### 3b. CLI (scriptable, repeatable)

```bash
BUCKET=tony-fhir-landing-xyz
REGION=us-east-1

# create (us-east-1 needs no LocationConstraint; other regions do)
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"

# versioning on
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

# belt-and-suspenders: explicitly assert Block Public Access (on by default)
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# HTTPS-only policy (save the JSON from 3a to tls-policy.json)
aws s3api put-bucket-policy --bucket "$BUCKET" --policy file://tls-policy.json

# least-privilege IAM policy (save §2 to put-policy.json)
aws iam create-policy --policy-name fhir-landing-put --policy-document file://put-policy.json
```

The CLI path is essentially "manual, but as a script you can re-run and commit"
— a real middle ground before full IaC.

---

## 4. Infrastructure as Code — Terraform

Terraform is the industry-standard, cloud-agnostic IaC tool. Note the AWS
provider **v4+** splits each bucket setting into its own resource (versioning,
encryption, public-access-block, ownership) rather than nesting them.

```hcl
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}
provider "aws" { region = var.region }

variable "region"      { default = "us-east-1" }
variable "bucket_name" {}

resource "aws_s3_bucket" "landing" {
  bucket = var.bucket_name
}

# disable ACLs (bucket owner enforced) — the current default, made explicit
resource "aws_s3_bucket_ownership_controls" "landing" {
  bucket = aws_s3_bucket.landing.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_public_access_block" "landing" {
  bucket                  = aws_s3_bucket.landing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "landing" {
  bucket = aws_s3_bucket.landing.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" } # SSE-S3
  }
}

# HTTPS-only
resource "aws_s3_bucket_policy" "landing" {
  bucket = aws_s3_bucket.landing.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid = "DenyInsecureTransport", Effect = "Deny", Principal = "*",
      Action = "s3:*",
      Resource = [aws_s3_bucket.landing.arn, "${aws_s3_bucket.landing.arn}/*"],
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# least-privilege put policy (attach to your role / permission set / user)
resource "aws_iam_policy" "landing_put" {
  name = "fhir-landing-put"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid = "FhirRawLandingPut", Effect = "Allow", Action = "s3:PutObject",
      Resource = "${aws_s3_bucket.landing.arn}/landing/fhir/*"
    }]
  })
}
```

Run: `terraform init`, `terraform plan`, `terraform apply`. For real work, keep
Terraform **state** in an S3 backend with DynamoDB locking (not the local
`terraform.tfstate`) so it's shareable and safe.

### AWS-native IaC alternatives
- **CloudFormation** — AWS's own YAML/JSON IaC. No extra tooling, deep AWS
  integration (StackSets, drift detection), but AWS-only and more verbose.
- **AWS CDK** — write infra in Python/TypeScript that *synthesizes*
  CloudFormation. Great if you'd rather express infra in a real language.
- *(Note: "Cloud Composer" is GCP's managed Apache Airflow — an orchestrator,
  not an IaC tool. The AWS analogues to Terraform are CloudFormation and CDK.)*

---

## 5. Trade-offs

| Approach | Best for | Pros | Cons |
|---|---|---|---|
| **Console (click)** | learning, one-off, exploring | zero setup, visual, immediate | not reproducible, undocumented, drifts, error-prone at scale |
| **CLI script** | small repeatable setups, this project | scriptable, commit-able, no new tool | imperative (you manage order/idempotency), no state/drift tracking |
| **Terraform** | anything real / multi-env / team | declarative, versioned, plan-before-apply, drift detection, cloud-agnostic | learning curve, state to manage, another tool in the chain |
| **CloudFormation / CDK** | all-in AWS shops | native, no state files to host, StackSets | AWS-only; CFN verbose, CDK adds a build step |

The through-line: **manual doesn't scale or reproduce; IaC trades upfront
effort for reproducibility, review, and drift control.** The moment infra
outlives a single afternoon or is touched by more than one person, code wins.

---

## 6. Recommendation for this project

For Project 1, the honest right-sized answer is the **CLI script** (§3b): the
footprint is one bucket + one policy, fully reproducible from a committed
script, no state backend to babysit. But **include the Terraform** (§4) in the
repo as the "how I'd do it for real" artifact — it's a strong portfolio signal
and lets you speak to IaC fluently.

Interview framing: *"I scripted the bucket for this project since it's a single
resource, but I keep a Terraform version to show how I'd provision it in a team
setting — declarative, plan-reviewed, with remote state and drift detection.
I'd reach for IaC the moment the infra is shared or multi-environment."* That
"right tool for the stage" story mirrors how the arc scopes Airflow to one
project — deliberate, not decorative.

---

## 7. Wire it into the pipeline

```bash
aws configure                 # once: access key, secret, region (already done)
aws sts get-caller-identity   # confirm creds are active
export S3_BUCKET=tony-fhir-landing-xyz   # PowerShell: $env:S3_BUCKET="..."
python src/upload_s3.py       # lands raw bundles under landing/fhir/ingest_date=.../
```

See `docs/s3_landing.md` for the key layout and the uploader's behaviour.

---

## Sources
- [Security best practices for Amazon S3 — AWS docs](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)
- [Security best practices in IAM — AWS docs](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [Amazon S3 applies two security best practices to all new buckets by default](https://aws.amazon.com/about-aws/whats-new/2023/04/amazon-s3-security-best-practices-buckets-default)
- [aws_s3_bucket — Terraform AWS provider (Registry)](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket)
- [Create IAM policies — HashiCorp Terraform tutorial](https://developer.hashicorp.com/terraform/tutorials/aws/aws-iam-policy)
