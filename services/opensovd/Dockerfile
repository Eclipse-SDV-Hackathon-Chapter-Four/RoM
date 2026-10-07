# Made with Claude (Claude Code, Anthropic)
# RoM OpenSOVD server: upstream Eclipse OpenSOVD server + SOVD faults read from the DFM (iceoryx2 dfm/query).
# Build from the repo root:  docker build -f services/opensovd/Dockerfile -t localhost/rom/opensovd:dev .
# Runtime: must share IPC (/dev/shm) and /tmp/iceoryx2 with the DFM and run as the same user (iceoryx2
# files are owner-only), e.g. compose `ipc: "service:dfm"` + the `iceoryx2` volume.
FROM docker.io/library/rust:1-bookworm AS builder
RUN apt-get update && apt-get install -y --no-install-recommends clang libclang-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# Toolchain + dependencies first (cached layer), sources after.
COPY services/opensovd/rust-toolchain.toml services/opensovd/Cargo.toml services/opensovd/Cargo.lock ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs && cargo build --release --locked && rm -rf src
COPY services/opensovd/src src
RUN touch src/main.rs && cargo test --release --locked && cargo build --release --locked

FROM docker.io/library/debian:bookworm-slim
COPY --from=builder /src/target/release/rom-opensovd /usr/local/bin/rom-opensovd
ENV SOVD_URL=http://0.0.0.0:7690/sovd RUST_LOG=info
EXPOSE 7690
CMD ["rom-opensovd"]
