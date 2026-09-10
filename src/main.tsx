import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { studioAudio } from "./audio/engine";
import "./style.css";

/**
 * A handle on the audio engine, for verification and for debugging by ear.
 *
 * `tests/browser/sidechain.spec.ts` uses it to render a project offline and
 * measure the result, which is the only way to prove that what the mixer says
 * is happening is what the speakers actually do.
 */
declare global {
  interface Window {
    rdx: { audio: typeof studioAudio };
  }
}
window.rdx = { audio: studioAudio };

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
