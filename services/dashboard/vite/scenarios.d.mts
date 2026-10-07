export const SCENARIOS: Readonly<Record<string, string>>;
export function campaignCommand(id: string): { command: string; args: string[] };
export function defaultRuntimeRepo(): string;
export function listScenarios(runtimeRepo: string): { id: string; label: string }[];
export function createScenarioRunner(options?: Record<string, unknown>): {
  run(id: unknown): Promise<{ code: number; body: Record<string, unknown> }>;
  status(): Record<string, unknown>;
  list(): { id: string; label: string }[];
};
export default function scenariosPlugin(options?: Record<string, unknown>): import("vite").Plugin;
