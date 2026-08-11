#!/usr/bin/env bash
# One-time EC2 bootstrap: IAM note + S3 bucket + Secrets Manager secret shells.
# Run on a machine with AWS credentials that can create resources in us-east-1.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text --region "${REGION}")"
BUCKET="${S3_BANK_PDF_BUCKET:-kalke-bank-pdfs-${ACCOUNT_ID}}"

echo "==> Creating private S3 bucket ${BUCKET}"
if ! aws s3api head-bucket --bucket "${BUCKET}" --region "${REGION}" 2>/dev/null; then
  if [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}"
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration LocationConstraint="${REGION}"
  fi
fi
aws s3api put-public-access-block --bucket "${BUCKET}" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "${BUCKET}" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

echo "==> Ensuring CloudWatch log groups"
for g in /kalke/e-bank-api /kalke/auth /kalke/pde; do
  aws logs create-log-group --log-group-name "${g}" --region "${REGION}" 2>/dev/null || true
done

echo "==> Placeholder secrets (update values via CI or console)"
for name in kalke/e-bank-api/prod kalke/kalke-auth/prod kalke/pde/prod; do
  aws secretsmanager describe-secret --secret-id "${name}" --region "${REGION}" >/dev/null 2>&1 \
    || aws secretsmanager create-secret --name "${name}" --region "${REGION}" \
         --secret-string '{"PLACEHOLDER":"replace-me"}'
done

cat <<EOF
Done.
- S3_BANK_PDF_BUCKET=${BUCKET}
- Attach an instance profile with secretsmanager:GetSecretValue on kalke/* and
  s3:GetObject/PutObject on ${BUCKET}, plus logs:CreateLogStream/PutLogEvents.
- Set GitHub secret S3_BANK_PDF_BUCKET=${BUCKET}
EOF
