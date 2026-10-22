"""Execute pinned Rust consent functions with mocked D-Bus and dialog boundaries.

Run with Python on Windows. Requires Rust and its musl target in Ubuntu WSL.
One security-expectation test intentionally fails on the original PR. This is
not a full portal integration test and does not modify either COSMIC checkout.
"""

from __future__ import annotations

import subprocess
import sys
import urllib.request


REVISION = "3fddb5a61c4f4655d331e98ac19d39dceeade8de"
SOURCE_URL = (
    "https://raw.githubusercontent.com/pop-os/xdg-desktop-portal-cosmic/"
    f"{REVISION}/src/input_capture.rs"
)

HARNESS = r'''
#![allow(dead_code)]
use std::sync::{Arc, Mutex};
use std::future::Future;
use std::task::{Context, Poll, Wake, Waker};

macro_rules! quiet_log { ($($arguments:tt)*) => {{ let _ = format_args!($($arguments)*); }}; }
pub(crate) use quiet_log;
mod tracing {
    pub(crate) use crate::quiet_log as debug;
    pub(crate) use crate::quiet_log as warn;
}
macro_rules! fl { ($($arguments:tt)*) => { String::from("mock label") }; }
pub(crate) use fl;

mod subscription { pub struct Event; }
struct Sender<T>(std::marker::PhantomData<T>);
mod zvariant { #[derive(Clone)] pub struct ObjectPath<'scope>(pub &'scope str); }
mod zbus {
    #[derive(Default)]
    pub struct Connection {
        pub grants: std::sync::Mutex<Vec<String>>,
        pub unavailable: bool,
    }
}
struct PermissionStoreProxy<'scope>(&'scope zbus::Connection);
impl<'scope> PermissionStoreProxy<'scope> {
    async fn new(connection: &'scope zbus::Connection) -> Result<Self, &'static str> {
        if connection.unavailable { Err("unavailable") } else { Ok(Self(connection)) }
    }
    async fn get_permission(&self, table: &str, id: &str, app: &str) -> Result<Vec<String>, &'static str> {
        assert_eq!(table, "input-capture");
        assert_eq!(id, "keyboard-and-pointer");
        assert_eq!(app, "org.example.Client");
        Ok(self.0.grants.lock().unwrap().clone())
    }
    async fn set_permission(
        &self, table: &str, create: bool, id: &str, app: &str, permissions: Vec<String>,
    ) -> Result<(), &'static str> {
        assert_eq!(table, "input-capture");
        assert_eq!(id, "keyboard-and-pointer");
        assert_eq!(app, "org.example.Client");
        assert!(create);
        *self.0.grants.lock().unwrap() = permissions;
        Ok(())
    }
}
struct ConsentIdentity { key: Option<String>, label: String }
const PERMISSION_TABLE: &str = "input-capture";
const PERMISSION_ID: &str = "keyboard-and-pointer";
static PROMPTS: Mutex<usize> = Mutex::new(0);
static TEST_LOCK: Mutex<()> = Mutex::new(());

mod access {
    #[derive(Debug, PartialEq, Eq)]
    pub enum ConfirmationResult { Allow, AlwaysAllow, Deny }
    pub struct ConfirmationLabels {
        pub title: String, pub subtitle: String, pub body: String,
        pub grant: String, pub deny: String, pub icon: String, pub always_allow: bool,
    }
    pub async fn show_confirmation(
        _sender: &super::Sender<super::subscription::Event>,
        _handle: super::zvariant::ObjectPath<'_>, _identity: &str,
        _parent: &str, _labels: ConfirmationLabels,
    ) -> ConfirmationResult {
        *super::PROMPTS.lock().unwrap() += 1;
        ConfirmationResult::Deny
    }
}
struct NoopWake;
impl Wake for NoopWake { fn wake(self: Arc<Self>) {} }
fn run_ready<F: Future>(future: F) -> F::Output {
    let waker = Waker::from(Arc::new(NoopWake));
    let mut context = Context::from_waker(&waker);
    match std::pin::pin!(future).as_mut().poll(&mut context) {
        Poll::Ready(result) => result,
        Poll::Pending => panic!("Mocks must complete immediately"),
    }
}

__PRODUCTION_FUNCTIONS__

fn ask(connection: &zbus::Connection) -> access::ConfirmationResult {
    let identity = ConsentIdentity {
        key: Some("org.example.Client".into()), label: "Example Client".into(),
    };
    run_ready(permission_prompt(
        connection, &Sender(std::marker::PhantomData),
        &zvariant::ObjectPath("/request/test"), &identity, "", true,
    ))
}

#[test]
fn no_saved_grant_prompts_and_respects_denial() {
    let _guard = TEST_LOCK.lock().unwrap_or_else(|error| error.into_inner());
    *PROMPTS.lock().unwrap() = 0;
    assert_eq!(ask(&zbus::Connection::default()), access::ConfirmationResult::Deny);
    assert_eq!(*PROMPTS.lock().unwrap(), 1);
}

#[test]
fn unavailable_permission_store_prompts_and_respects_denial() {
    let _guard = TEST_LOCK.lock().unwrap_or_else(|error| error.into_inner());
    *PROMPTS.lock().unwrap() = 0;
    let connection = zbus::Connection { unavailable: true, ..Default::default() };
    assert_eq!(ask(&connection), access::ConfirmationResult::Deny);
    assert_eq!(*PROMPTS.lock().unwrap(), 1);
}

#[test]
fn saved_yes_grant_skips_dialog() {
    let _guard = TEST_LOCK.lock().unwrap_or_else(|error| error.into_inner());
    *PROMPTS.lock().unwrap() = 0;
    let connection = zbus::Connection::default();
    run_ready(remember_always_allowed(&connection, "org.example.Client"));
    assert_eq!(ask(&connection), access::ConfirmationResult::Allow);
    assert_eq!(*PROMPTS.lock().unwrap(), 0);
}

#[test]
fn capability_mismatch_fallback_should_prompt_again() {
    let _guard = TEST_LOCK.lock().unwrap_or_else(|error| error.into_inner());
    *PROMPTS.lock().unwrap() = 0;
    let connection = zbus::Connection::default();
    run_ready(remember_always_allowed(&connection, "org.example.Client"));
    let decision = ask(&connection);
    let prompt_count = *PROMPTS.lock().unwrap();
    assert_eq!(
        prompt_count, 1,
        "Fallback after a capability mismatch skipped consent: decision={decision:?}"
    );
}
'''


def production_functions(source: str) -> str:
    """Extract the three complete functions from this fixed source revision."""
    start = source.index("async fn always_allowed(")
    end = source.index("#[allow(unused_variables)]", start)
    functions = source[start:end]
    if "async fn remember_always_allowed(" not in functions or "async fn permission_prompt(" not in functions:
        raise ValueError("Pinned source no longer matches the expected function boundaries")
    return functions


def wsl_output(*arguments: str) -> str:
    """Read a small result from Ubuntu without invoking a shell."""
    return subprocess.check_output(
        ["wsl", "-d", "Ubuntu", "--exec", *arguments], text=True,
    ).strip()


def main() -> int:
    """Compile the real consent functions and run the four focused Rust tests."""
    temporary = None
    try:
        with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:
            source = response.read().decode("utf-8")
        harness = HARNESS.replace("__PRODUCTION_FUNCTIONS__", production_functions(source))
        home = wsl_output("printenv", "HOME")
        temporary = wsl_output("mktemp", "-d", "/tmp/cosmic-consent-test.XXXXXXXX")
        binary = temporary + "/consent-tests"
        print(f"Portal revision: {REVISION}", flush=True)
        print("Actual Rust consent functions; mocked permission store and denial dialog.", flush=True)
        print("The capability-scoping expectation should fail on the original PR.", flush=True)
        compiled = subprocess.run(
            [
                "wsl", "-d", "Ubuntu", "--exec", home + "/.cargo/bin/rustc",
                "--edition=2024", "--target=x86_64-unknown-linux-musl",
                "-C", f"linker={home}/.cargo/lib/rustlib/x86_64-unknown-linux-gnu/bin/rust-lld",
                "--test", "-", "-o", binary,
            ],
            input=harness.encode("utf-8"), check=False,
        )
        if compiled.returncode:
            return 2
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--exec", binary, "--test-threads=1", "--nocapture"],
            check=False,
        )
        return result.returncode
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Test setup failed: {error}", file=sys.stderr)
        return 2
    finally:
        if temporary:
            subprocess.run(["wsl", "-d", "Ubuntu", "--exec", "rm", "-rf", temporary], check=False)


if __name__ == "__main__":
    raise SystemExit(main())