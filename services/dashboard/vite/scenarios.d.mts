export const SCENARIOS: Readonly<Record<string, string>>;
export const CONTAINER_PREFIX: string;
export const CAMPAIGN_LABEL: string;
export function isCampaignContainer(name: unknown): boolean;
export function campaignCommand(id: string, container: string): { command: string; args: string[] };
export function defaultRuntimeRepo(): string;
export function listScenarios(runtimeRepo: string): { id: string; label: string }[];
export function createScenarioRunner(options?: Record<string, unknown>): {
  stop(): Promise<{ code: number; body: Record<string, unknown> }>;
  adopt(): Promise<void>;
  run(id: unknown): Promise<{ code: number; body: Record<string, unknown> }>;
  status(): Record<string, unknown>;
  list(): { id: string; label: string }[];
};
export default function scenariosPlugin(options?: Record<string, unknown>): import("vite").Plugin;
