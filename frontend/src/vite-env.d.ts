/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DATA_MODE?: "auto" | "api" | "mock";
  readonly VITE_ENABLE_MOCK?: string;
  readonly VITE_INCLUDE_LOCAL_FAN_DEMO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
