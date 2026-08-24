//! Манифест сервера, отдаваемый бэкендом панели (app/routes/launcher.py).
//! Схема здесь должна зеркалить JSON оттуда — mods сейчас всегда пустой
//! массив (синхронизация модов — следующий этап), но поле уже в контракте.

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ServerManifest {
    pub name: String,
    pub ip: Option<String>,
    pub mc_version: String,
    pub modloader: String,
    pub modloader_version: Option<String>,
    pub mods: Vec<ModEntry>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ModEntry {
    pub filename: String,
    pub sha1: String,
    pub size: u64,
    pub url: String,
}

#[derive(Debug, Error)]
pub enum ManifestError {
    #[error("сеть: {0}")]
    Network(#[from] reqwest::Error),
    #[error("сервер не найден или ещё не готов для лаунчера (HTTP {0})")]
    NotReady(u16),
}

/// panel_base_url — адрес самой веб-панели MCServerCoreWebUI (не Minecraft
/// IP сервера — это поле берётся уже из самого манифеста).
pub async fn fetch_manifest(
    panel_base_url: &str,
    server_id: u64,
) -> Result<ServerManifest, ManifestError> {
    let url = format!(
        "{}/launcher/servers/{}/manifest",
        panel_base_url.trim_end_matches('/'),
        server_id
    );
    let resp = reqwest::get(&url).await?;
    if !resp.status().is_success() {
        return Err(ManifestError::NotReady(resp.status().as_u16()));
    }
    let manifest = resp.json::<ServerManifest>().await?;
    Ok(manifest)
}
