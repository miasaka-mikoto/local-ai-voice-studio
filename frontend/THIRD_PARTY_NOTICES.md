# Frontend third-party notices

This file records the direct runtime dependencies added for the optional local
VRM avatar. It is part of the source deliverable; `npm install` obtains the
same versions recorded in `package-lock.json`.

## Three.js

- Package: `three` `0.180.0`
- License: MIT
- Copyright: three.js authors
- Used for: lazy WebGL renderer, camera, lights, scene graph and GLTF loader
  integration.

## @pixiv/three-vrm

- Package: `@pixiv/three-vrm` `3.4.2`
- License: MIT
- Copyright: pixiv Inc.
- Used for: VRM 0.x/1.0 parsing, humanoid expressions, look-at and spring-bone
  updates.
- Its MIT-compatible runtime dependencies are locked transitively in
  `package-lock.json` (including `@pixiv/three-vrm-core`, MToon/material and
  springbone packages).

## Type declarations

- Package: `@types/three` `0.180.0`
- License: MIT
- Used only at build time; it is not shipped as a browser runtime.

No VRM model, texture, voice, or remote asset is bundled by this project. The
viewer accepts a user-selected `.vrm` file only after an explicit authorization
acknowledgement. It creates a browser `ObjectURL` for the current session,
requires a self-contained GLB 2.0 payload (external `uri` references are
rejected), never uploads the bytes, and revokes the URL and disposes the renderer/model on
replacement or unmount. A model's own license metadata is shown but is not a
license grant; users remain responsible for use, performance, commercial and
redistribution rights.
