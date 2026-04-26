# InfoSec-MacAddressChanger

A cross-platform desktop application for spoofing, randomizing, and restoring network interface MAC addresses. Built for security researchers, penetration testers, privacy-conscious users, and IT professionals.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Supported Platforms](#supported-platforms)
- [Architecture](#architecture)
- [Screenshots](#screenshots)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Development Setup](#development-setup)
- [Usage](#usage)
- [Security Model](#security-model)
- [Repository Structure](#repository-structure)
- [Team & Responsibilities](#team--responsibilities)
- [Contributing](#contributing)
- [Ethics & Legal Notice](#ethics--legal-notice)
- [License](#license)

---

## Overview

InfoSec-MacAddressChanger provides a polished graphical interface for changing your network interface's MAC (Media Access Control) address at the OS level. The application handles privilege escalation, network state management, ARP cache flushing, DHCP re-lease, and automatic rollback — all while keeping the unprivileged GUI process isolated from the privileged system helper.

The tool bundles a locally stored IEEE OUI database so vendor information is available entirely offline, and supports vendor-spoofing presets so you can make your device appear as a specific brand (Apple, Samsung, Cisco, etc.).

---

## Features

- **Spoof any MAC address** — manually enter a target MAC or let the app generate one
- **Vendor-aware randomization** — generate a MAC that matches a real registered vendor prefix (OUI)
- **Vendor spoofing presets** — one-click presets to impersonate popular device manufacturers
- **Instant revert** — restore the factory-burned-in permanent MAC at any time
- **Interface selector** — full support for multi-NIC machines (Wi-Fi + Ethernet simultaneously)
- **Live status badge** — `ACTIVE`, `INACTIVE`, `ERROR`, `REVERTING` with real-time polling
- **Change history** — timestamped sidebar log of all previous MAC values
- **Real-time log viewer** — structured log stream with level-based coloring (DEBUG / INFO / WARN / ERROR)
- **Offline OUI database** — vendor lookup for every displayed MAC address, no internet required
- **Transaction model** — atomic state file written before every destructive operation; rollback survives a hard crash and is offered on next launch
- **DHCP re-lease** — automatically triggers DHCP renewal after a successful MAC change
- **Light and dark themes** — design-token-driven UI with full keyboard navigation (WCAG 2.1 AA)

---

## Supported Platforms

| Platform | Versions Tested | Notes |
|---|---|---|
| Linux | Ubuntu 22.04, 24.04 | `iproute2` preferred; `ifconfig` fallback |
| macOS | Ventura (13), Sonoma (14) | `ifconfig lladdr`; IOKit fallback |
| Windows | 10 21H2, 11 23H2 | Registry `NetworkAddress` + `netsh` fallback; UAC helper service |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Electron Renderer Process              │
│  React + TypeScript  │  Zustand state  │  Tailwind CSS  │
│       Components     │     Hooks       │  Design Tokens  │
└────────────────────────────┬────────────────────────────┘
                             │ contextBridge (typed IPC)
┌────────────────────────────▼────────────────────────────┐
│                   Electron Main Process                  │
│            IPC bridge  │  IPC handlers                  │
└────────────────────────────┬────────────────────────────┘
                             │ local named pipe / Unix socket
┌────────────────────────────▼────────────────────────────┐
│               Python Backend (unprivileged)              │
│   PlatformAdapter  │  NetworkStateManager  │  OUILookup  │
└────────────────────────────┬────────────────────────────┘
                             │ single privileged subprocess
┌────────────────────────────▼────────────────────────────┐
│         Privileged Helper (elevated, short-lived)        │
│  Linux: pkexec  │  macOS: AuthorizationExecuteWithPrivs  │
│  Windows: UAC-manifest helper service (signed binary)    │
└─────────────────────────────────────────────────────────┘
```

All OS commands are issued through a `PlatformAdapter` abstraction using parameterized argument lists — never shell strings, never `shell=True`. The GUI process never runs elevated; privilege is held only for the duration of a single MAC change operation and is dropped immediately afterward.

---

## Screenshots

> Screenshots will be added as the UI is finalized. See `tests/screenshots/` for Playwright-captured UI shots generated during the test suite.

---

## Prerequisites

| Dependency | Minimum Version | Notes |
|---|---|---|
| Node.js | 20 LTS | Required for Electron build and frontend dev |
| Python | 3.11 | Required for the backend |
| pip | bundled with Python 3.11 | Used to install Python dependencies |
| npm | bundled with Node.js 20 | Used to install JS dependencies |

**Linux only:**  
- `iproute2` package (`ip` command) — most distributions include this by default  
- `PolicyKit` (`pkexec`) for privilege escalation prompts

**macOS only:**  
- Xcode Command Line Tools (for native module builds)

**Windows only:**  
- The NSIS installer configures the UAC helper service automatically  
- An EV code-signed binary is required to avoid SmartScreen warnings in production releases

---

## Installation

### Pre-built Releases

Download the latest release from the [GitHub Releases](../../releases) page:

| Platform | Artifact |
|---|---|
| Linux (Debian/Ubuntu) | `.deb` package |
| Linux (Fedora/RHEL) | `.rpm` package |
| Linux (universal) | `.AppImage` |
| macOS | `.dmg` (notarized) |
| Windows | NSIS `.exe` installer (code-signed) |

**Linux:**
```bash
sudo dpkg -i InfoSec-MacAddressChanger_*.deb
# or
sudo rpm -i InfoSec-MacAddressChanger_*.rpm
```

**macOS:**  
Open the `.dmg`, drag the app to `/Applications`, and launch it. On first run, macOS will prompt for your password to authorize the MAC change operation.

**Windows:**  
Run the NSIS installer as Administrator. The installer registers the UAC helper service so subsequent uses require only a standard UAC prompt, not full Administrator session.

---

## Development Setup

### 1. Clone the repository

```bash
git clone https://github.com/marcdelro/InfoSec-MacAddressChanger.git
cd InfoSec-MacAddressChanger
```

### 2. Install dependencies

```bash
npm install
pip install -r requirements.txt
```

### 3. Run in development mode (mock adapter — no real MAC changes)

```bash
MAC_ADAPTER=mock npm run dev
```

This starts the Electron app with hot reload and a software-simulated backend so no elevated privileges or real network changes are made.

### 4. Run with real MAC changes (Linux/macOS)

```bash
sudo -E npm run dev
```

### 5. Run tests

```bash
# Python backend unit tests
pytest tests/unit/ -v

# Frontend unit tests
npm test

# Lint
npm run lint
flake8 src/core/

# TypeScript type-check
npm run type-check
```

### 6. Update the OUI database (before a release)

```bash
python scripts/update_oui_db.py
```

This fetches the latest IEEE MA-L registry CSV, validates its checksum, and rebuilds `assets/oui.db`.

---

## Usage

### Basic workflow

1. Launch the application.
2. Select the network interface from the **Interface Selector** dropdown.
3. The **Current MAC** and **Permanent MAC** fields populate automatically.
4. Choose one of:
   - **Randomize** — generate a random unicast MAC
   - **Vendor Preset** — pick a manufacturer from the preset list; a valid OUI prefix for that vendor is selected automatically
   - **Manual entry** — type a MAC into the **Target MAC** field (format: `AA:BB:CC:DD:EE:FF`)
5. Click **Apply**. The app will:
   - Bring the interface down
   - Write the new MAC address
   - Flush the ARP cache
   - Bring the interface back up
   - Trigger a DHCP renewal
   - Poll until the interface is confirmed `UP` and `RUNNING` (timeout: 30 s)
6. The **Status Badge** changes to `ACTIVE` (green) on success.
7. To undo, click **Revert** — the permanent MAC is restored using the same procedure.

### Crash recovery

If the application is killed mid-operation, a state file is preserved at:

- **Linux/macOS:** `~/.macchanger/state/`
- **Windows:** `%APPDATA%\MACChanger\state\`

On next launch, the app detects the incomplete transaction and offers to roll back to the pre-change state.

### MAC address format

Accepted input formats:

```
AA:BB:CC:DD:EE:FF   (colon-separated)
AA-BB-CC-DD-EE-FF   (dash-separated)
```

The first octet's least-significant bit (multicast bit) must be `0`. Input is validated against the regex `^([0-9A-Fa-f]{2}[:\-]){5}([0-9A-Fa-f]{2})$` before any OS command is issued.

---

## Security Model

| Principle | Implementation |
|---|---|
| Least privilege | GUI process is unprivileged; only the helper binary runs elevated, only for the duration of one operation |
| No remote callbacks | No telemetry, no auto-update pings, no analytics. Update checks are manual and opt-in |
| No `shell=True` | All subprocess calls use argument lists; no string interpolation into OS commands |
| Signed binaries | All release builds are code-signed to minimize AV false positives |
| Read-only OUI DB | `assets/oui.db` is opened in read-only mode at runtime; the GUI process cannot write it |
| Local audit log | Privilege escalation attempts and failures are logged locally, never to a remote endpoint |
| IPC isolation | GUI ↔ backend communication uses a local named pipe or Unix socket with strict permission checks — not HTTP on localhost |
| Reproducible builds | The CI pipeline produces byte-for-byte reproducible binaries; published SHA-256 hashes can be independently verified |

To report a security vulnerability, see [SECURITY.md](SECURITY.md). Do **not** open a public GitHub issue for vulnerability reports.

---

## Repository Structure

```
InfoSec-MacAddressChanger/
├── .github/
│   └── workflows/
│       ├── build.yml          # CI on every push / PR
│       ├── release.yml        # Triggered on version tags (v*.*.*)
│       └── oui-update.yml     # Monthly OUI database refresh
├── assets/
│   ├── oui.db                 # Read-only IEEE OUI SQLite database
│   ├── vendor_presets.json    # Curated vendor spoofing presets
│   └── icons/                 # Per-platform app icons
├── docs/
│   ├── architecture.md
│   ├── contributing.md
│   ├── ethics-and-legal.md    # Required reading — legal & ethical guidance
│   ├── installation.md
│   ├── nic-driver-quirks.md   # Known NIC/driver issues and workarounds
│   └── user-guide.md
├── scripts/
│   ├── build/                 # Build helper scripts (.bat / .ps1 variants included)
│   └── update_oui_db.py       # OUI database update script
├── src/
│   ├── core/                  # Python backend
│   │   ├── network/           # Interface lifecycle & transaction model
│   │   ├── oui/               # OUI lookup & vendor presets
│   │   ├── platform/          # OS-level PlatformAdapter (Linux / macOS / Windows)
│   │   └── security/          # Privilege escalation & input validation
│   ├── frontend/              # Electron + React + TypeScript
│   │   ├── components/        # UI components (MacDisplay, MacInput, StatusBadge, …)
│   │   ├── design/            # Design tokens & themes (tokens.json)
│   │   ├── hooks/             # Custom React hooks
│   │   ├── ipc/               # Typed IPC bridge (bridge.ts)
│   │   └── state/             # Zustand global store
│   └── platform/
│       └── windows/
│           └── helper_service/ # Windows UAC-elevated helper service
├── tests/
│   ├── frontend/              # Jest tests
│   ├── integration/           # Real-NIC integration tests (require test VM or CI runner)
│   ├── reports/               # JUnit XML output (gitignored)
│   ├── screenshots/           # Playwright UI screenshots
│   └── unit/                  # pytest unit tests
├── CHANGELOG.md
├── CLAUDE.md
├── README.md
├── SECURITY.md
├── electron-builder.config.js
├── package.json
└── requirements.txt
```

---

## Team & Responsibilities

| Role | Owns |
|---|---|
| Kernel / System API | `src/core/platform/` — OS-level MAC manipulation, `PlatformAdapter` |
| Permission & Security | `src/core/security/`, Windows helper service — privilege escalation, input validation |
| Network State Manager | `src/core/network/` — interface lifecycle, transaction model, ARP flush, DHCP |
| UI Designer | `src/frontend/design/` — wireframes, design system, tokens, light/dark themes |
| Frontend Developer | `src/frontend/components/`, `src/frontend/ipc/` — React components, IPC bridge |
| Data Visualization / State | `src/frontend/state/`, `src/frontend/hooks/` — Zustand store, live monitor, log stream |
| OUI Database Manager | `assets/oui.db`, `src/core/oui/`, `scripts/update_oui_db.py` |
| DevOps & Build Engineer | `package.json`, `electron-builder.config.js`, `.github/workflows/`, `scripts/build/` |
| QA / Manual Tester | `tests/` — unit, integration, regression, edge-case matrix |
| Technical Writer | `docs/` — user guide, architecture, ethics doc, driver quirks, CHANGELOG |

---

## Contributing

Please read [docs/contributing.md](docs/contributing.md) for full contribution guidelines. Key points:

- All PRs touching `src/core/` require review from the **Kernel/System API** owner and the **Permission & Security** lead before merge.
- All PRs touching `src/core/network/` must re-run the full revert regression test suite.
- Commit messages must follow `commitlint` format:

  ```
  <type>(<scope>): <subject>

  Types:  feat | fix | docs | style | refactor | test | chore | security
  Scopes: core | frontend | build | oui | docs | security | network
  ```

- Every feature must ship with a `CHANGELOG.md` entry and at least one test covering the happy path and the failure/revert path.
- No `shell=True` in Python. No unsanitized string interpolation into any OS command. Ever.

---

## Ethics & Legal Notice

MAC address spoofing has legitimate uses (privacy protection, penetration testing on authorized networks, network research, device emulation in lab environments) **and** illegitimate ones (bypassing network access controls on networks you do not own, fraud, evading law enforcement).

**This tool is intended exclusively for authorized, lawful use.**

Before using this application, read [docs/ethics-and-legal.md](docs/ethics-and-legal.md). It covers the legal landscape across multiple jurisdictions and outlines acceptable and prohibited use cases.

By using this software you accept responsibility for ensuring your use complies with all applicable laws and the terms of any network you connect to.

---

## License

This project is released under the [MIT License](LICENSE).

The bundled OUI database (`assets/oui.db`) is derived from the IEEE MA-L public registry and is governed by IEEE's own licensing terms for that data.
