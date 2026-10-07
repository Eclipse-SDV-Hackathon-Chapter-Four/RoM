export function createCellSource(options?: { simUrl?: string; adapterUrl?: string; fetchFn?: typeof fetch }): {
  get(): Promise<{ mode: "hw" | "sim" | "both" | "none"; hwAvailable: boolean; simulatorCells: number[]; adapterEnabled: boolean | null }>;
  set(mode: unknown): ReturnType<ReturnType<typeof createCellSource>["get"]>;
};
export default function cellSourcePlugin(options?: { simUrl?: string; adapterUrl?: string }): import("vite").Plugin;
