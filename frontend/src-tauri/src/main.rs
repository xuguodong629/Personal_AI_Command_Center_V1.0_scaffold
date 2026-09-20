// 个人 AI 指挥中心 · Tauri 2 桌面壳
//
// 职责：
//   1. 打开原生窗口加载界面（开发模式 127.0.0.1:5173 / 打包后 frontend/dist）
//   2. 自动拉起本地 Python 后端（uvicorn :8787），窗口关闭时一并结束
//   3. 若后端已在运行（端口可连），则不重复启动
//
// 不依赖 Dify；Python 环境使用 backend/.venv（不存在时回退系统 python）。

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent};

struct BackendProcess(Mutex<Option<Child>>);

const BACKEND_ADDR: &str = "127.0.0.1:8787";

/// 后端是否已在监听（避免重复启动 / 误杀用户自己开的实例）
fn backend_running() -> bool {
    match BACKEND_ADDR.parse::<SocketAddr>() {
        Ok(addr) => TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok(),
        Err(_) => false,
    }
}

/// 定位项目根目录（含 backend/ 的那一层）
/// 开发：CARGO_MANIFEST_DIR = <root>/frontend/src-tauri → 上两级 = <root>
/// 打包：可执行文件所在目录（发行时需把 backend/ 放在同级）
fn project_root() -> Option<PathBuf> {
    #[cfg(debug_assertions)]
    {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent() // frontend
            .and_then(|p| p.parent()) // 项目根
            .map(|p| p.to_path_buf())
    }
    #[cfg(not(debug_assertions))]
    {
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|d| d.to_path_buf()))
    }
}

fn start_backend() -> Option<Child> {
    if backend_running() {
        println!("[backend] 8787 已在运行，复用现有实例");
        return None;
    }
    let root = project_root()?;
    let backend_dir = root.join("backend");
    let venv_python = backend_dir.join(".venv").join("Scripts").join("python.exe");

    // 依次尝试：项目虚拟环境 → Windows py 启动器 → 系统 python
    let candidates: Vec<(PathBuf, Vec<String>)> = vec![
        (venv_python.clone(), vec![]),
        (PathBuf::from("py"), vec!["-3.10".to_string()]),
        (PathBuf::from("python"), vec![]),
    ];

    let mut last_err = String::from("无可用解释器");
    for (program, extra) in candidates {
        let mut args = extra;
        args.extend(
            ["-m", "uvicorn", "app.main:app", "--port", "8787"]
                .iter()
                .map(|s| s.to_string()),
        );

        let mut cmd = Command::new(&program);
        cmd.args(&args).current_dir(&backend_dir);

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        match cmd.spawn() {
            Ok(child) => {
                println!("[backend] 已启动：{:?}（pid {}）", program, child.id());
                return Some(child);
            }
            Err(e) => last_err = format!("{program:?} → {e}"),
        }
    }

    eprintln!(
        "[backend] 启动失败：{last_err}\n  后端目录：{backend_dir:?}\n  期望虚拟环境：{venv_python:?}\n  请在项目根执行 启动.bat，或手动创建 backend/.venv"
    );
    None
}

fn main() {
    let child = start_backend();

    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(child)))
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Tauri 应用初始化失败")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}
