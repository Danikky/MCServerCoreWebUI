// M1, шаг 2: скелет — приложение умеет только запросить манифест сервера у
// панели и показать его во фронте. Скачивание/установка/запуск Minecraft —
// следующие шаги плана (mojang.rs/install.rs/auth.rs/launch.rs).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;
mod manifest;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![commands::get_manifest])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
