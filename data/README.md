# Data Directory

Large data are not tracked in Git.

- `registry/`: small versioned company and source registries may be tracked.
- `raw/`: immutable downloaded files.
- `snapshots/`: archived official web captures.
- `normalized/`: parsed text and passages.
- `interim/`: candidates and unresolved records.
- `processed/`: validated released tables.
- `manifests/`: source and run provenance.

Use `.gitkeep` only for directory structure.
