import { createClient } from "redis";

export class Encoder {
  encode(scores: number[]): string {
    return JSON.stringify(scores);
  }
}

export class ScoreStore {
  private client;
  private encoder;

  constructor(url: string) {
    this.client = createClient({ url });
    this.encoder = new Encoder();
  }

  async save(key: string, scores: number[]): Promise<number> {
    const body = this.encoder.encode(scores);
    await this.client.set(key, body);
    return scores.length;
  }
}
