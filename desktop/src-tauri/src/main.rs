// Aion Hand desktop app — main entry point.
// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    aion_hand_lib::run()
}
