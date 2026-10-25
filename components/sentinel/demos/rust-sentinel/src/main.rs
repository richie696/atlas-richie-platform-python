mod app;
mod metrics_v2;
mod reporting;
mod rules;
mod source;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    app::run().await
}
