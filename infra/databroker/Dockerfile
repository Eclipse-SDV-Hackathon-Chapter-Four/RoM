# Made with Claude (Claude Code, Anthropic)
# KUKSA Databroker with the RoM VSS overlay (4 battery cells, heartbeats) baked in: no bind mount needed (Ankaios).
# Build from the repo root:  docker build -f infra/databroker/Dockerfile -t localhost/rom/databroker:dev .
ARG KUKSA_VERSION=latest
FROM ghcr.io/eclipse-kuksa/kuksa-databroker:${KUKSA_VERSION}
COPY infra/vss/rom_overlay.json /vss/rom_overlay.json
CMD ["--insecure", "--vss", "vss_release_6.0.json,/vss/rom_overlay.json"]
