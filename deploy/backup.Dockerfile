# The backup container: the database's own client tools plus the AWS CLI,
# openssl to seal the dumps, and bash for backup.sh (our-stories pattern).
FROM postgres:16-alpine

RUN apk add --no-cache aws-cli bash openssl
