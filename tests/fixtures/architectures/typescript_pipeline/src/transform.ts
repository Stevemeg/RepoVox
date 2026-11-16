export const normalise = (rows: string[]): string[] => rows.map((row) => row.trim());

export function score(rows: string[], weight: number): number[] {
  return rows.map((row) => row.length * weight);
}
