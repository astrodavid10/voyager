// The running Vue app, so the async 3D chunk can install wwtPinia and the
// <WorldWideTelescope> component on it AFTER the engine-free entry chunk has
// painted (sol's pattern: main.ts must not import the engine).
import type { App } from "vue";

let handle: App | null = null;
export function setAppHandle(app: App): void { handle = app; }
export function getAppHandle(): App | null { return handle; }
