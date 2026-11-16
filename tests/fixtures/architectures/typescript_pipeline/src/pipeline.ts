import { readRecords } from "./ingest";
import * as transform from "./transform";
import { ScoreStore } from "./store";

export async function runPipeline(
  source: string,
  weight: number,
  url: string,
): Promise<number> {
  const rows = readRecords(source);
  const clean = transform.normalise(rows);
  const scores = transform.score(clean, weight);
  const store = new ScoreStore(url);
  return store.save("scores", scores);
}
