declare module "node:fs" {
  export function rmSync(path: string, options?: { force?: boolean }): void;
}

declare module "node:path" {
  export function resolve(...pathSegments: string[]): string;
}
