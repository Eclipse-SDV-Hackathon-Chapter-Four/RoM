// Made with Claude (Claude Code, Anthropic)
//! rom-opensovd: Eclipse OpenSOVD server for RoM.
//!
//! Runs the upstream OpenSOVD server (opensovd-core: entities, data, version-info, auth layers) with
//! one SOVD app per DFM entity path (default `battery_guardian`), hosted on component `rom-hpc`, and
//! adds the `faults` resource on top, read live from the DFM over iceoryx2 (`dfm/query`):
//!
//!   guardian --uProtocol--> rom-dfm report --fault-lib Reporter--> dfm_bin --dfm/query--> rom-opensovd --HTTP--> client
//!
//!   curl http://localhost:7690/sovd/v1/apps/battery_guardian/faults
//!
//! Config via flags or env (see `--help`): SOVD_URL, SOVD_DFM_APPS, SOVD_COMPONENT, DFM_QUERY_TIMEOUT_MS.
mod faults;

use std::{sync::Arc, time::Duration};

use anyhow::Context;
use clap::Parser;
use dfm_lib::DfmQueryApi;
use opensovd_core::{App, Component, Topology};
use opensovd_server::Server;

#[derive(Parser, Debug)]
#[command(version, about = "Eclipse OpenSOVD server for RoM: SOVD entities + DFM faults")]
struct Cli {
    /// Server URL with the SOVD base path.
    #[arg(long, env = "SOVD_URL", default_value = "http://0.0.0.0:7690/sovd")]
    url: String,
    /// DFM entity paths (= fault catalog ids) exposed as SOVD apps, comma-separated.
    #[arg(long = "app", env = "SOVD_DFM_APPS", value_delimiter = ',', default_value = "battery_guardian")]
    apps: Vec<String>,
    /// SOVD component the apps run on (`GET /components/{id}/hosts`).
    #[arg(long, env = "SOVD_COMPONENT", default_value = "rom-hpc")]
    component: String,
    /// How long one DFM query may take before the request answers 503.
    #[arg(long, env = "DFM_QUERY_TIMEOUT_MS", default_value_t = 500)]
    dfm_timeout_ms: u64,
}

fn app_name(id: &str) -> String {
    match id {
        "battery_guardian" => "Battery Thermal Guardian".into(),
        other => other.into(),
    }
}

async fn topology(cli: &Cli) -> Topology {
    let topology = Topology::default();
    {
        let mut t = topology.write().await;
        t.add_component(Component::new(&cli.component, "RoM vehicle HPC").with_tags(vec!["hpc".into()]));
        for app in &cli.apps {
            t.add_app(App::new(app, app_name(app)).with_component_id(&cli.component).with_tags(vec!["dfm".into()]));
        }
    }
    topology
}

async fn shutdown_signal() {
    use tokio::signal::unix::{SignalKind, signal};
    let mut term = signal(SignalKind::terminate()).expect("SIGTERM handler"); // podman / Ankaios stop
    tokio::select! {
        _ = term.recv() => {}
        _ = tokio::signal::ctrl_c() => {}
    }
    tracing::info!("shutting down");
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();
    let cli = Cli::parse();

    let uri: http::Uri = cli.url.parse().with_context(|| format!("invalid --url {:?}", cli.url))?;
    let authority = uri.authority().context("--url must include host:port")?.as_str().to_owned();
    let base_path = uri.path().trim_end_matches('/').to_owned();
    let listener = tokio::net::TcpListener::bind(&authority)
        .await
        .with_context(|| format!("cannot listen on {authority}"))?;

    let dfm: Arc<dyn DfmQueryApi> = Arc::new(faults::IpcDfm::new(Duration::from_millis(cli.dfm_timeout_ms)));
    let mut builder = Server::builder().listener(listener).topology(topology(&cli).await);
    for app in &cli.apps {
        let path = format!("{base_path}/v1/apps/{app}/faults");
        tracing::info!(%path, dfm_path = %app, "serving DFM faults");
        builder = builder.service(&path, faults::router(Arc::clone(&dfm), app.clone()));
    }

    tracing::info!(url = %cli.url, component = %cli.component, apps = ?cli.apps, "OpenSOVD server started");
    builder.base_uri(uri)?.shutdown(shutdown_signal()).build()?.serve().await?;
    Ok(())
}
