FROM nousresearch/hermes-agent:v2026.8.3@sha256:16788311e2fa3035456bdc1bafb8ec2b1777db64ebf020af9bb7eb73c3712c9e

USER root
COPY services/hermes-runtime/platform_capabilities.py /opt/hermes/gateway/platform_capabilities.py
COPY services/hermes-runtime/patch_api_server.py /tmp/patch_api_server.py
RUN /opt/hermes/.venv/bin/python /tmp/patch_api_server.py /opt/hermes/gateway/platforms/api_server.py \
    && rm /tmp/patch_api_server.py \
    && chmod 0444 /opt/hermes/gateway/platform_capabilities.py /opt/hermes/gateway/platforms/api_server.py
