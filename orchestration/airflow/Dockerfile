ARG AIRFLOW_IMAGE=apache/airflow:3.3.1-python3.12@sha256:b01a795dfbd113bbbfdf3ee169b8f27e9a0090ccef105f1a452b3594a11ed316
FROM ${AIRFLOW_IMAGE}

USER root
RUN mkdir -p /opt/claimsflow /opt/airflow/db \
    && chown -R airflow:0 /opt/claimsflow /opt/airflow/db

COPY --chown=airflow:0 orchestration/airflow/policy /opt/claimsflow/airflow_policy

USER airflow
