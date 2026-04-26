# CLAUDE.md — MAC Address Changer

## Project Overview

**InfoSec-MacAddressChanger** is a local desktop application that allows users to spoof, randomize, and restore their network interface's MAC address. It targets security researchers, penetration testers, privacy-conscious users, and IT professionals. The application must handle OS-level system calls, administrative privilege escalation, network state management, and provide a polished GUI with real-time feedback.

**Target Platforms:** Linux, macOS, Windows  
**GUI Framework:** Electron (cross-platform) or Qt (native performance); SwiftUI for macOS-only builds  
**Language Stack:** Python (core backend), TypeScript/JavaScript (Electron frontend), C/C++ (low-level NIC interaction where needed)  
**License:** MIT (application code); OUI database governed by IEEE licensing terms

**Development Environment:** All 10 team members develop on **Windows**. All local tooling, scripts, and development workflows must be compatible with Windows 10/11. Use forward slashes or `path.join()` in code (never hardcode Unix-only paths). Shell scripts in `scripts/` must have a `.bat` or PowerShell (`.ps1`) equivalent for Windows developers. WSL2 is acceptable for running Linux-specific tests locally but must not be a required dependency.

---

## Team Roles & Responsibilities

### 1. Core Engineering & Systems (Members 1–3)

#### Member 1 — Kernel / System API Specialist
- Owns all OS-level MAC address manipulation logic.
- **Linux:** Uses `ip link set <iface> address <mac>` via the `iproute2` package; falls back to `ifconfig` on older distros.
- **macOS:** Uses `ifconfig <iface> lladdr <mac>`; interfaces with IOKit/NetworkExtension where `ifconfig` is insufficient.
- **Windows:** Uses the registry path `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Class\{4D36E972-...}` to set `NetworkAddress`; also wraps `netsh` commands as a fallback.
- Implements a `PlatformAdapter` abstraction so upper layers never call OS commands directly—always go through the adapter interface.
- Validates MAC address format (EUI-48, colon/dash-separated, no multicast bit set on the first octet unless intentional).
- Responsible for the `src/core/platform/` directory.

**Key constraints:**
- Never hardcode shell command strings in business logic—use parameterized subprocess calls with argument lists (never `shell=True` in Python).
- All OS command output must be parsed, not `eval`'d.
- The adapter must return structured results (`success: bool`, `error_code`, `message`) never raw stderr strings to the UI.

#### Member 2 — Permission & Security Lead
- Owns privilege escalation, sandboxing, and secure coding practices across the entire codebase.
- **Linux/macOS:** Implements `pkexec`/`sudo` prompts via `PolicyKit` (Linux) and `AuthorizationExecuteWithPrivileges` (macOS); prefers dropping privileges immediately after the single privileged operation.
- **Windows:** Uses UAC manifest (`requireAdministrator`) in the application manifest; the installer sets up a Windows Service or a signed helper binary that runs at elevated level so the main GUI process does not need to run as Administrator continuously.
- Enforces input sanitization on all MAC address inputs before passing to OS commands—regex whitelist `^([0-9A-Fa-f]{2}[:\-]){5}([0-9A-Fa-f]{2})$`.
- Conducts code review on any code that calls subprocess, registry writes, or network interface APIs.
- Responsible for `src/core/security/` and the Windows helper service `src/platform/windows/helper_service/`.

**Security rules for the whole team:**
- No `shell=True` (Python), no `exec()`/`eval()`, no string interpolation into shell commands.
- All IPC between GUI and privileged backend must use a local Unix socket or named pipe with strict permission checks—not HTTP on localhost.
- Log security-relevant events (privilege escalation attempts, failures) to a local audit log, never to a remote endpoint.
- The OUI database must be read-only at runtime; it must not be writable by the unprivileged GUI process.

#### Member 3 — Network State Manager
- Owns the full interface lifecycle: bring-down → change MAC → flush ARP → bring-up → verify.
- Implements a **transaction model**: every operation records the pre-change state so a rollback is always possible even if the process is killed mid-operation (via a small state file written atomically before any destructive step).
- **ARP cache flush:**
  - Linux: `ip neigh flush dev <iface>`
  - macOS: `arp -d -i <iface> -a`
  - Windows: `netsh interface ip delete arpcache`
- Monitors interface state after bring-up using a polling loop (max 10s timeout) to confirm the interface is `UP` and `RUNNING` before reporting success.
- Handles DHCP re-lease after MAC change (optionally triggers `dhclient`/`dhcpcd` on Linux, `ipconfig /renew` on Windows).
- Responsible for `src/core/network/`.

**Critical constraints:**
- The bring-down/bring-up cycle must never exceed 30 seconds total; if it does, auto-rollback and surface a timeout error to the UI.
- State files stored in `~/.macchanger/state/` (Linux/macOS) or `%APPDATA%\MACChanger\state\` (Windows).
- The rollback must work even if the application is restarted (read state file on startup and offer recovery).

---

### 2. Frontend & User Experience (Members 4–6)

#### Member 4 — UI Designer
- Owns all wireframes, mockups, and the visual design system (colors, typography, spacing tokens).
- The main window must display three clearly labeled fields at all times:
  - **Current MAC** — live value read from the OS
  - **Permanent MAC** — the factory-burned-in address (read from driver or registry; shown in muted style)
  - **Target MAC** — the address the user wants to spoof (editable input or randomized)
- Designs must accommodate:
  - A **vendor lookup label** next to each MAC field (e.g., "Apple, Inc." derived from OUI DB)
  - A **spoofing status badge** — `ACTIVE` (green), `INACTIVE` (gray), `ERROR` (red), `REVERTING` (amber)
  - An **interface selector** dropdown for multi-NIC machines
  - A **history panel** (collapsible sidebar) listing previous MAC values with timestamps
- Design tokens live in `src/frontend/design/tokens.json`; the frontend developer must consume them—do not hardcode hex colors or font sizes in component files.
- Provides both light and dark theme variants.

#### Member 5 — Frontend Developer
- Translates designs into working UI components using **Electron + React + TypeScript**.
- Component structure under `src/frontend/components/`:
  - `MacDisplay/` — read-only display for Current and Permanent MAC
  - `MacInput/` — validated input for Target MAC with format masking
  - `InterfaceSelector/` — dropdown populated by IPC call to backend
  - `StatusBadge/` — reactive badge component consuming app state
  - `ControlPanel/` — primary action buttons (Randomize, Apply, Revert)
  - `HistoryPanel/` — scrollable log of past changes
  - `LogViewer/` — real-time scrolling log output
- All IPC to the privileged backend goes through a typed IPC bridge (`src/frontend/ipc/bridge.ts`)—never call `ipcRenderer` directly in components.
- The app must remain responsive during backend operations; all backend calls are async with loading states.
- Supports keyboard navigation and screen readers (WCAG 2.1 AA minimum).

**Frontend rules:**
- No inline styles. All styles via CSS modules or Tailwind utility classes with design tokens.
- Do not store sensitive data (e.g., original MAC) in `localStorage` or Electron's `webContents`—use the backend's secure state file.
- The `window.electronAPI` surface exposed via `contextBridge` is the only way the renderer communicates with main process.

#### Member 6 — Data Visualization / State Specialist
- Owns all real-time feedback components and application state management.
- Implements the global state store using **Zustand** (lightweight, no Redux boilerplate).
- State shape:
  ```typescript
  interface AppState {
    interfaces: NetworkInterface[];
    selectedInterface: string | null;
    currentMac: string | null;
    permanentMac: string | null;
    targetMac: string | null;
    spoofStatus: 'inactive' | 'active' | 'error' | 'reverting';
    isLoading: boolean;
    logs: LogEntry[];
    history: HistoryEntry[];
  }
  ```
- Implements a **live connection monitor** that polls interface state every 5 seconds while spoofing is active and updates `spoofStatus` accordingly.
- Implements the **log stream**: backend emits structured JSON log lines over IPC; this member parses and renders them in the `LogViewer` with level-based coloring (DEBUG gray, INFO blue, WARN amber, ERROR red).
- Responsible for `src/frontend/state/` and `src/frontend/hooks/`.

---

### 3. Support & Infrastructure (Members 7–8)

#### Member 7 — OUI Database Manager
- Owns the locally bundled OUI (Organizationally Unique Identifier) database.
- **Source:** IEEE MA-L (MAC Address Large) public registry, downloaded from `https://regauth.standards.ieee.org/standards-ra-web/pub/view.html#registries`.
- **Storage format:** SQLite database (`assets/oui.db`) with schema:
  ```sql
  CREATE TABLE oui (
    prefix TEXT PRIMARY KEY,  -- e.g., "A4:C3:F0"
    vendor  TEXT NOT NULL,
    country TEXT
  );
  ```
- Provides a Python script `scripts/update_oui_db.py` that fetches the latest IEEE CSV and rebuilds `oui.db`; this script is run manually before each release and as part of the CI pipeline monthly.
- Exposes a `OUILookup` class (`src/core/oui/lookup.py`) with method `lookup(mac: str) -> Optional[VendorInfo]`.
- Implements **vendor spoofing presets**: a curated list of popular vendors (Apple, Samsung, Intel, Cisco, etc.) with randomly selectable OUI prefixes from their registered range, so users can make their device appear to be a specific brand.
- Vendor preset file: `assets/vendor_presets.json`.

**OUI database rules:**
- The database file must never be modified at runtime; it is read-only.
- Ship with a database that is no older than 90 days at release time.
- The update script must validate the IEEE CSV checksum before overwriting the database.

#### Member 8 — DevOps & Build Engineer
- Owns the build pipeline, packaging, code signing, and release process.
- **Build targets:**
  - Linux: `.deb` (Debian/Ubuntu) and `.rpm` (Fedora/RHEL) via `electron-builder`; also an AppImage for universal Linux.
  - macOS: `.dmg` with a notarized `.app` bundle; requires Apple Developer ID certificate.
  - Windows: NSIS installer (`.exe`) with EV code signing certificate to minimize SmartScreen warnings.
- **CI/CD:** GitHub Actions workflows in `.github/workflows/`:
  - `build.yml` — triggered on every push to `main` and all PRs; runs lint, type-check, unit tests, and builds all targets.
  - `release.yml` — triggered on version tags (`v*.*.*`); builds, signs, and uploads artifacts to GitHub Releases.
  - `oui-update.yml` — runs monthly; executes `scripts/update_oui_db.py` and opens a PR if the database changed.
- **Antivirus false positive mitigation:**
  - All binaries must be code-signed (unsigned binaries are nearly universally flagged).
  - Avoid packing/obfuscating the Python backend (packed executables trigger heuristic AV detections).
  - Submit hashes to major AV vendors' false-positive portals after each release (VirusTotal, Windows Defender, Malwarebytes).
- Responsible for `package.json`, `electron-builder.config.js`, `.github/workflows/`, and `scripts/build/`.

---

### 4. Quality Assurance & Documentation (Members 9–10)

#### Member 9 — QA / Manual Tester
- Owns the test matrix and all automated + manual testing.
- **Unit tests:** `pytest` for Python backend (`tests/unit/`); `Jest` for TypeScript frontend (`tests/frontend/`). Coverage target: 80% minimum for `src/core/`.
- **Integration tests:** Test scripts in `tests/integration/` that exercise the full backend stack against a real (or virtual) network interface. These tests require a test VM or CI runner with a real NIC.
- **Test matrix** (must be verified before every release):

  | OS | Version | Interface Type | Expected Result |
  |---|---|---|---|
  | Ubuntu | 22.04, 24.04 | Wi-Fi (Intel AX200) | Pass |
  | Ubuntu | 22.04 | Ethernet (Realtek 8111) | Pass |
  | macOS | Ventura, Sonoma | Wi-Fi (Apple Broadcom) | Pass |
  | macOS | Sonoma | Ethernet (USB adapter) | Pass |
  | Windows | 10 21H2 | Wi-Fi (Intel) | Pass |
  | Windows | 11 23H2 | Wi-Fi + Ethernet | Pass |

- **Regression tests** specifically for the "revert to original" path — this must be verified after every change to `src/core/network/`.
- **Edge cases to always test:**
  - Interface is already down when the app opens.
  - User kills the app mid-operation; relaunch must offer rollback.
  - Spoofing attempt with a multicast MAC (must be rejected).
  - Two simultaneous spoof operations on the same interface (must be serialized, not race).
  - Applying a MAC that is already the current MAC (should be a no-op with a clear message).
- Files the test suite produces: `tests/reports/` (JUnit XML for CI); `tests/screenshots/` (Playwright screenshots for UI tests).

#### Member 10 — Technical Writer & Researcher
- Owns all user-facing and developer-facing documentation.
- **Required documents** (all under `docs/`):
  - `docs/installation.md` — step-by-step install guide per OS, including prerequisites (admin rights, driver requirements).
  - `docs/user-guide.md` — full feature walkthrough with annotated screenshots.
  - `docs/ethics-and-legal.md` — mandatory reading; covers legal jurisdictions where MAC spoofing may be regulated, acceptable use cases (privacy, testing), and prohibited use cases (bypassing network access controls on unauthorized networks, fraud).
  - `docs/nic-driver-quirks.md` — a living document tracking NIC/driver combinations with known issues (e.g., some Realtek drivers on Windows ignore the registry `NetworkAddress` value and require a specific NDIS property).
  - `docs/architecture.md` — high-level system architecture diagram and component descriptions.
  - `docs/contributing.md` — coding standards, branch naming, PR process, commit message format.
- **Commit message format** (enforced via `commitlint`):
  ```
  <type>(<scope>): <subject>

  Types: feat, fix, docs, style, refactor, test, chore, security
  Scopes: core, frontend, build, oui, docs, security, network
  ```
- Maintains a `CHANGELOG.md` following Keep a Changelog format.
- Researches driver-specific MAC change mechanisms for NICs flagged in QA testing and documents workarounds in `docs/nic-driver-quirks.md`.

---

## Repository Structure

```
InfoSec-MacAddressChanger/
├── .github/
│   └── workflows/
│       ├── build.yml
│       ├── release.yml
│       └── oui-update.yml
├── assets/
│   ├── oui.db                    # Read-only OUI SQLite database
│   ├── vendor_presets.json       # Curated vendor spoofing presets
│   └── icons/                    # App icons per platform
├── docs/
│   ├── architecture.md
│   ├── contributing.md
│   ├── ethics-and-legal.md
│   ├── installation.md
│   ├── nic-driver-quirks.md
│   └── user-guide.md
├── scripts/
│   ├── build/                    # Build helper scripts
│   └── update_oui_db.py          # OUI database update script
├── src/
│   ├── core/                     # Python backend
│   │   ├── network/              # Member 3: interface lifecycle
│   │   ├── oui/                  # Member 7: OUI lookup
│   │   ├── platform/             # Member 1: OS adapters
│   │   └── security/             # Member 2: privilege & validation
│   ├── frontend/                 # Electron + React + TypeScript
│   │   ├── components/           # Member 5: UI components
│   │   ├── design/               # Member 4: tokens, themes
│   │   ├── hooks/                # Member 6: custom React hooks
│   │   ├── ipc/                  # Member 5: IPC bridge
│   │   └── state/                # Member 6: Zustand store
│   └── platform/
│       └── windows/
│           └── helper_service/   # Member 2: Windows elevated helper
├── tests/
│   ├── frontend/                 # Jest tests
│   ├── integration/              # Real-NIC integration tests
│   ├── reports/                  # CI test output (gitignored)
│   ├── screenshots/              # Playwright UI screenshots
│   └── unit/                     # pytest unit tests
├── CHANGELOG.md
├── CLAUDE.md
├── README.md
├── electron-builder.config.js
├── package.json
└── requirements.txt
```

---

## Development Setup

### Prerequisites
- Node.js >= 20 LTS
- Python >= 3.11
- `pip install -r requirements.txt`
- `npm install`

### Running in Development
```bash
# Start the Electron app in dev mode (hot reload)
npm run dev

# Run Python backend tests
pytest tests/unit/ -v

# Run frontend tests
npm test

# Run linter
npm run lint && flake8 src/core/

# Type-check TypeScript
npm run type-check
```

### Running with Elevated Privileges (dev)
On Linux/macOS, the backend needs `sudo` for actual MAC changes. During development, use the mock adapter:
```bash
MAC_ADAPTER=mock npm run dev
```
To test with real changes:
```bash
sudo -E npm run dev
```

---

## Critical Rules for All Contributors

1. **Never use `shell=True`** (Python) or unsanitized string interpolation in any subprocess call. All OS commands use argument lists.
2. **Never log MAC addresses to remote services.** All logs are local-only.
3. **All PRs touching `src/core/` require review from both Member 1 and Member 2** before merge.
4. **All PRs touching `src/core/network/` must re-run the full revert regression test** before merge—network breakage is the highest severity bug.
5. **The OUI database (`assets/oui.db`) is never modified at runtime.** Any code that opens it must use read-only mode.
6. **Commit messages must follow the `commitlint` format** defined above. CI will reject non-conforming commits.
7. **No feature ships without a corresponding entry in `CHANGELOG.md`** and at minimum one test covering the happy path and the failure/revert path.
8. **The "Ethics & Legal" document (`docs/ethics-and-legal.md`) must be linked from the application's About screen.** Users must be able to reach it in one click.

---

## Security Posture

This tool performs privileged OS operations and will attract scrutiny from both security researchers and antivirus engines. The team must treat the following as non-negotiable:

- **Principle of least privilege:** The GUI process runs unprivileged. Only the minimal helper binary or the single privileged subprocess runs elevated, and only for the duration of the MAC change operation.
- **No network callbacks:** The application never phones home, checks for updates automatically, or sends telemetry. Update checks are opt-in and manual only.
- **Reproducible builds:** The build pipeline must produce byte-for-byte reproducible binaries so that published hashes can be independently verified.
- **Responsible disclosure:** A `SECURITY.md` file in the repo root provides a GPG-encrypted contact channel for vulnerability reports. Do not accept vulnerability reports via public GitHub issues.
