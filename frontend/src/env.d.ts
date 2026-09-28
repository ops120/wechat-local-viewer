/// <reference types="vite/client" />

// Vite resolves these at build time; TypeScript needs the declarations so the
// `typecheck` script can validate the rest of the source tree.
declare module '*.vue' {
  import type { DefineComponent } from 'vue'

  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}
