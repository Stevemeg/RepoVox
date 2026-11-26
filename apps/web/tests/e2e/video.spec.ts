// Real browser-to-video workflow on locally authored synthetic repositories.
//
// Nothing here is mocked or prerecorded: the browser signs in, submits a repository, the
// stack analyses it and generates the videos, and the browser plays and downloads them.
// The repositories come from the development-only synthetic source, so this is not
// evidence about acquiring external repositories.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

// H.264/AAC playback needs a browser with those decoders; bundled Chromium has none.
test.use({ channel: "chrome" });

const MINUTE = 60_000;
const EVIDENCE = "test-results/video";
const sha256 = (body: Buffer) =>
  createHash("sha256").update(body).digest("hex");
const pause = (ms: number) => new Promise((done) => setTimeout(done, ms));

type Video = {
  id: string;
  category: string;
  title: string;
  checksum: string;
  byte_count: number;
};
type Job = {
  id: string;
  project_id: string;
  analysis_job_id: string;
  state: string;
  architecture: string | null;
  repository: string | null;
  commit_sha: string | null;
  error_code: string | null;
  stages: { stage_key: string; state: string; error_code: string | null }[];
  videos: Video[];
};

async function signIn(page: Page, name: RegExp) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
}

async function openProject(page: Page, title: string) {
  await page.getByRole("link", { name: /^Projects/ }).click();
  await page.getByRole("link", { name: new RegExp(title) }).click();
  await expect(
    page.getByRole("heading", { name: "Narrated videos" }),
  ).toBeVisible();
}

async function createProject(page: Page, title: string, repository: string) {
  await page.getByRole("link", { name: /^Projects/ }).click();
  await page.getByRole("button", { name: "New project" }).first().click();
  await page.getByLabel("Project name").fill(title);
  await page.getByLabel("GitHub repository URL").fill(repository);
  await page.getByRole("button", { name: "Create project" }).click();
  await openProject(page, title);
}

async function submit(page: Page): Promise<Job> {
  const button = page.getByRole("button", { name: "Create narrated videos" });
  await expect(button).toBeDisabled();
  await page
    .getByLabel(/I acknowledge this local source processing for video creation/)
    .check();
  const accepted = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/projects\/[a-f0-9-]{36}\/video-jobs$/.test(response.url()),
  );
  await button.click();
  const response = await accepted;
  expect(response.status()).toBe(202);
  const job = (await response.json()) as Job;
  expect(job.state).toBe("awaiting_analysis");
  expect(job.videos).toEqual([]);
  return job;
}

async function fetchJob(request: APIRequestContext, id: string): Promise<Job> {
  const response = await request.get(`/api/v1/video-jobs/${id}`);
  expect(response.status()).toBe(200);
  return (await response.json()) as Job;
}

async function succeeded(page: Page, job: Job): Promise<Job> {
  const card = page.getByRole("article", {
    name: `Video job ${job.id.slice(0, 8)}`,
  });
  // The job heading carries a status badge with the capitalized label ("Succeeded").
  await expect(
    card.getByRole("heading", { name: /^Video job / }),
  ).toContainText(/succeeded|failed|cancelled/i, {
    timeout: 14 * MINUTE,
  });
  const settled = await fetchJob(page.request, job.id);
  expect(settled.state, JSON.stringify(settled.stages)).toBe("succeeded");
  expect(settled.error_code).toBeNull();
  return settled;
}

function record(name: string, value: unknown) {
  mkdirSync(EVIDENCE, { recursive: true });
  writeFileSync(`${EVIDENCE}/${name}.json`, JSON.stringify(value, null, 2));
}

test("supported repository: submit, generate with the browser closed, play, download, isolate", async ({
  page,
  context,
  browser,
}) => {
  test.setTimeout(22 * MINUTE);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const title = `Synthetic supported ${Date.now()}`;
  await signIn(page, /Alex Chen/);
  await createProject(
    page,
    title,
    "https://github.com/synthetic/custom_unnamed",
  );
  const job = await submit(page);

  // Close the page. From here until it is reopened nothing reads the video job, so any
  // progress is the server's own. Only the core analysis job is watched meanwhile.
  await page.close();
  await expect
    .poll(
      async () => {
        const response = await context.request.get(
          `/api/v1/jobs/${job.analysis_job_id}`,
        );
        const core = await response.json();
        return `${core.state}:${core.error_code}`;
      },
      { timeout: 6 * MINUTE, intervals: [2000] },
    )
    .toBe("failed:phase2_pipeline_boundary"); // The accepted Stage 9 analysis boundary.
  await pause(25_000);

  const reopened = await context.newPage();
  await reopened.setViewportSize({ width: 1440, height: 1000 });
  const firstRead = reopened.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().endsWith(`/api/v1/projects/${job.project_id}/video-jobs`),
  );
  await reopened.goto("/projects");
  await openProject(reopened, title);
  const seen = ((await (await firstRead).json()) as Job[]).find(
    (item) => item.id === job.id,
  )!;
  // The first read after reopening already shows work done while no page was open.
  expect(seen.state).not.toBe("awaiting_analysis");
  expect(seen.stages[0]).toMatchObject({
    stage_key: "storyboard",
    state: "succeeded",
  });

  const done = await succeeded(reopened, job);
  expect(done.architecture).toBe("published");
  expect(done.repository).toBe("synthetic/custom_unnamed");
  expect(done.commit_sha).toMatch(/^[a-f0-9]{40}$/);
  expect(done.stages.every((stage) => stage.state === "succeeded")).toBe(true);
  const categories = done.videos.map((video) => video.category);
  expect(categories.filter((c) => c === "walkthrough")).toHaveLength(1);
  expect(categories.filter((c) => c === "architecture").length).toBeGreaterThan(
    0,
  );
  const card = reopened.getByRole("article", {
    name: `Video job ${job.id.slice(0, 8)}`,
  });
  await expect(card.locator("[data-architecture]")).toHaveAttribute(
    "data-architecture",
    "published",
  );
  // The Video Studio plays one video at a time and lists every published video in a
  // playlist, in the job's position order.
  const entries = card.locator("button[data-video-id]");
  await expect(entries).toHaveCount(done.videos.length);
  await expect(entries.first()).toHaveAttribute("aria-pressed", "true");
  await expect(card.locator("video")).toHaveCount(1);

  // Ownership: the owner's listing contains exactly this job with these videos.
  const listing = (await (
    await reopened.request.get(`/api/v1/projects/${job.project_id}/video-jobs`)
  ).json()) as Job[];
  expect(listing.map((item) => item.id)).toEqual([job.id]);
  expect(listing[0].videos.map((v) => v.id)).toEqual(
    done.videos.map((v) => v.id),
  );

  const evidence = [];
  for (const video of done.videos) {
    const base = `/api/v1/video-jobs/${job.id}/videos/${video.id}`;
    const full = await reopened.request.get(base);
    expect(full.status()).toBe(200);
    expect(full.headers()["content-type"]).toBe("video/mp4");
    const body = await full.body();
    expect(body.length).toBe(video.byte_count);
    expect(sha256(body)).toBe(video.checksum);
    expect(body.subarray(4, 8).toString("latin1")).toBe("ftyp");
    const part = await reopened.request.get(base, {
      headers: { range: "bytes=0-1023" },
    });
    expect(part.status()).toBe(206);
    expect(part.headers()["content-range"]).toBe(
      `bytes 0-1023/${video.byte_count}`,
    );
    expect((await part.body()).equals(body.subarray(0, 1024))).toBe(true);
    const captions = await reopened.request.get(`${base}/captions`);
    expect(captions.status()).toBe(200);
    const vtt = await captions.text();
    expect(vtt.startsWith("WEBVTT")).toBe(true);
    expect(vtt).toContain("-->");

    // Put this video on the stage through its playlist entry, as a user would.
    const entry = card.locator(`button[data-video-id="${video.id}"]`);
    await entry.click();
    await expect(entry).toHaveAttribute("aria-pressed", "true");
    await expect(card.locator("video")).toHaveCount(1);
    if (video.category === "walkthrough")
      // The walkthrough's story either loads or is reported as not available; never an error.
      await expect(
        card.locator(
          '.story-explorer [role="tablist"], .story-explorer [data-story="not-available"]',
        ),
      ).toBeVisible({ timeout: 30_000 });

    // Playback in the real browser: decoded frames advance and captions are loaded.
    // Located by the video's own id, since titles need not be unique. An inner locator
    // given to `has` is resolved relative to the outer element, so it starts from the page.
    const player = card.locator("video", {
      has: reopened.locator(`source[src*="/videos/${video.id}"]`),
    });
    await expect(player).toHaveCount(1);
    await player.scrollIntoViewIfNeeded();
    const playback = await player.evaluate(async (element) => {
      const media = element as HTMLVideoElement;
      media.muted = true;
      await media.play();
      await new Promise<void>((resolve, reject) => {
        const limit = setTimeout(() => reject(new Error("no playback")), 30000);
        const check = () => {
          if (media.error) reject(new Error(`media error ${media.error.code}`));
          else if (media.currentTime >= 1) {
            clearTimeout(limit);
            resolve();
          } else requestAnimationFrame(check);
        };
        check();
      });
      media.pause();
      const quality = media.getVideoPlaybackQuality();
      return {
        currentTime: media.currentTime,
        duration: media.duration,
        width: media.videoWidth,
        height: media.videoHeight,
        decodedFrames: quality.totalVideoFrames,
        error: media.error ? media.error.code : null,
        cues: media.textTracks[0]?.cues?.length ?? 0,
        captionMode: media.textTracks[0]?.mode ?? null,
        source: media.currentSrc,
      };
    });
    expect(playback.error).toBeNull();
    expect(playback.currentTime).toBeGreaterThanOrEqual(1);
    expect(playback.duration).toBeGreaterThan(2);
    expect(playback.width).toBeGreaterThan(0);
    expect(playback.decodedFrames).toBeGreaterThan(0);
    expect(playback.cues).toBeGreaterThan(0);
    // Loaded but not drawn: each frame already carries its caption in the lower band.
    expect(playback.captionMode).toBe("hidden");
    expect(playback.source).toContain(base);

    // Download through the page's own link, as a user would.
    const link = card.locator(`a[href$="/videos/${video.id}/download"]`);
    await expect(link).toHaveText("Download MP4");
    const started = reopened.waitForEvent("download");
    await link.click();
    const download = await started;
    const saved = readFileSync(await download.path());
    expect(sha256(saved)).toBe(video.checksum);
    const attachment = await reopened.request.get(`${base}/download`);
    expect(attachment.headers()["content-disposition"]).toContain("attachment");

    evidence.push({
      id: video.id,
      category: video.category,
      title: video.title,
      sha256: video.checksum,
      bytes: video.byte_count,
      downloaded_sha256: sha256(saved),
      caption_bytes: vtt.length,
      playback,
    });
  }
  await reopened.screenshot({
    path: `${EVIDENCE}/supported.png`,
    fullPage: true,
  });

  // Another signed-in user and an anonymous visitor can retrieve none of it.
  const other = await browser.newContext({ baseURL: "http://localhost:3000" });
  const otherPage = await other.newPage();
  await signIn(otherPage, /Sam Rivera/);
  const anonymous = await browser.newContext({
    baseURL: "http://localhost:3000",
  });
  const routes = [`/api/v1/video-jobs/${job.id}`];
  for (const video of done.videos) {
    const base = `/api/v1/video-jobs/${job.id}/videos/${video.id}`;
    routes.push(base, `${base}/captions`, `${base}/download`);
  }
  const denied: Record<string, number[]> = {};
  for (const route of routes) {
    const asOther = await other.request.get(route);
    const asNobody = await anonymous.request.get(route);
    expect(asOther.status(), route).toBe(404);
    expect(asNobody.status(), route).toBe(401);
    expect((await asOther.body()).includes(Buffer.from("ftyp"))).toBe(false);
    denied[route] = [asOther.status(), asNobody.status()];
  }
  expect(
    (
      await other.request.get(`/api/v1/projects/${job.project_id}/video-jobs`)
    ).status(),
  ).toBe(404);
  await other.close();
  await anonymous.close();

  record("supported", {
    source:
      "locally authored synthetic repository (development synthetic source)",
    job: {
      id: job.id,
      repository: done.repository,
      identifier: done.commit_sha,
      architecture: done.architecture,
      stages: done.stages,
    },
    progressed_while_page_closed: seen.stages.map(
      (s) => `${s.stage_key}:${s.state}`,
    ),
    videos: evidence,
    denied,
  });
});

test("unsupported architecture: the walkthrough is published and no architecture video is invented", async ({
  page,
}) => {
  test.setTimeout(18 * MINUTE);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const title = `Synthetic unsupported ${Date.now()}`;
  await signIn(page, /Sam Rivera/);
  await createProject(
    page,
    title,
    "https://github.com/synthetic/tech_mention_only",
  );
  const job = await submit(page);
  const done = await succeeded(page, job);
  expect(done.architecture).toBe("unsupported");
  expect(done.videos.map((video) => video.category)).toEqual(["walkthrough"]);
  expect(done.stages.at(-1)).toMatchObject({
    stage_key: "architecture",
    state: "succeeded",
    error_code: null,
  });
  const card = page.getByRole("article", {
    name: `Video job ${job.id.slice(0, 8)}`,
  });
  await expect(card.locator("[data-architecture]")).toHaveAttribute(
    "data-architecture",
    "unsupported",
  );
  await expect(card.getByText(/evidence was not sufficient/)).toBeVisible();
  await expect(card.getByText(/explainers were generated/)).toHaveCount(0);
  await expect(card.locator("video")).toHaveCount(1);
  // The player label, not the outcome note ("No architecture explainer: ...").
  await expect(card.getByText(/^Architecture explainer/)).toHaveCount(0);
  const walkthrough = done.videos[0];
  const body = await (
    await page.request.get(
      `/api/v1/video-jobs/${job.id}/videos/${walkthrough.id}`,
    )
  ).body();
  expect(sha256(body)).toBe(walkthrough.checksum);
  await page.screenshot({
    path: `${EVIDENCE}/unsupported.png`,
    fullPage: true,
  });
  record("unsupported", {
    source:
      "locally authored synthetic repository (development synthetic source)",
    job: {
      id: job.id,
      repository: done.repository,
      identifier: done.commit_sha,
      architecture: done.architecture,
      stages: done.stages,
    },
    videos: done.videos.map((video) => ({
      id: video.id,
      category: video.category,
      sha256: video.checksum,
      bytes: video.byte_count,
    })),
  });
});
