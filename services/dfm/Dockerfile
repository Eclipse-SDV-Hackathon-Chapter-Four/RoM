# Made with Claude (Claude Code, Anthropic)
# Diagnostic Fault Manager: fault-lib dfm_bin + rom-dfm bridge (guardian uProtocol fault events -> fault-lib Reporter).
# Self-contained: no bind mounts, configured only via env, logs to stdout.
# Build from the repo root:  docker build -f services/dfm/Dockerfile -t localhost/rom/dfm:dev .
FROM docker.io/library/rust:1-bookworm AS build
ARG FAULT_LIB_REV=12dac502616701734f90a61edca1326ae2ac6506
RUN apt-get update && apt-get install -y --no-install-recommends clang libclang-dev && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/eclipse-opensovd/fault-lib.git /fault-lib \
 && git -C /fault-lib checkout $FAULT_LIB_REV
WORKDIR /fault-lib
# rom-dfm joins the fault-lib workspace: same Cargo.lock and toolchain as dfm_bin
COPY services/dfm/Cargo.toml src/rom_dfm/Cargo.toml
COPY services/dfm/src src/rom_dfm/src
RUN sed -i 's|members = \[|members = [\n  "src/rom_dfm",|' Cargo.toml \
 && cargo test -p rom_dfm \
 && cargo build --release -p dfm_bin -p rom_dfm

FROM docker.io/library/debian:bookworm-slim
COPY --from=build /fault-lib/target/release/dfm_bin /fault-lib/target/release/rom-dfm /usr/local/bin/
COPY services/dfm/catalog /etc/rom/catalog
COPY services/dfm/fixtures /etc/rom/fixtures
ENV CATALOG=/etc/rom/catalog/battery_guardian.json
# ponytail: runs as root like services/opensovd, because iceoryx2 files are owner-only and both sides must be the
# same user; give both images the same non-root uid to drop this.
RUN mkdir -p /var/lib/rom-dfm /tmp/iceoryx2
# Two processes in one container (iceoryx2 shared memory): if either exits (or on SIGTERM), stop both and exit 1,
# so the orchestrator (compose restart policy / Ankaios) sees it. dfm_bin ignores SIGTERM (iceoryx2 handler) -> -9.
CMD ["bash", "-c", "dfm_bin --catalog-dir /etc/rom/catalog --storage-dir /var/lib/rom-dfm & a=$!; rom-dfm report & b=$!; trap 'kill $a $b' TERM INT; wait -n; kill $a $b 2>/dev/null; sleep 1; kill -9 $a $b 2>/dev/null; exit 1"]
