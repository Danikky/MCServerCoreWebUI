//! #[tauri::command]-обвязка — то, что реально вызывает фронт (src/main.js)
//! через invoke(). Сама логика — в соседних модулях (manifest.rs и т.д.),
//! команды здесь только адаптируют Result<_, ManifestError> в Result<_, String>
//! (Tauri умеет прокидывать в JS только String/сериализуемую ошибку).

use crate::manifest::{self, ServerManifest};

#[tauri::command]
pub async fn get_manifest(panel_url: String, server_id: u64) -> Result<ServerManifest, String> {
    manifest::fetch_manifest(&panel_url, server_id)
        .await
        .map_err(|e| e.to_string())
}
