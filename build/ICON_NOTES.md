# App Icon Replacement Notes

HigherKey Operator OS currently uses `build/icon.png`, generated from the local placeholder mark.

To replace it with final artwork:

1. Export a 1024 x 1024 PNG.
2. Save it as `build/icon.png`.
3. Keep `build/icon-placeholder.svg` as the editable placeholder source.
4. Run `npm run electron:verify`.
5. Run `npm run dist:dir` and confirm the packaged app displays the new icon.

The icon asset is bundled as a read-only application resource. Runtime outputs must continue to be written to the selected project folder or Electron `userData`, not to the app bundle.
