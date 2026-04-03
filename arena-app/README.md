# Arena App

A local desktop shell for the scoring arena.

## Planned stack

- Tauri v2
- React + Vite + TypeScript
- Python evaluator engine reused from the main repo

## Status

The core UI and backend bridge are implemented. The application supports dataset browsing, model targeting configuration, and run execution.

## Development and Compilation

### Prerequisites

1.  **Rust Toolchain**: Install from [rustup.rs](https://rustup.rs/).
2.  **Node.js**: LTS version recommended.
3.  **Tauri Prerequisites**: Follow the [official guide](https://tauri.app/v1/guides/getting-started/prerequisites) for your OS (Windows: C++ Build Tools).

### Setup

```bash
cd arena-app
npm install
```

### Run in Development

```bash
npm run tauri dev
```

### Build for Production

```bash
npm run tauri build
```
