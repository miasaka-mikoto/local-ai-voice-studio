import { afterEach, describe, expect, it, vi } from "vitest";
import { JapaneseLearningApi, apiShadowingToUi, apiTurnToUiTurns, ensureJapaneseSession, type JapaneseTurnResponse, type ShadowingApiResponse } from "./japaneseApi";

const ok = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

describe("JapaneseLearningApi contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("uploads browser WebM/Opus as raw body with encoded query fields", async () => {
    const uploadResponse = {
      id: "recording-1",
      recording_id: "recording-1",
      session_id: "session id/1",
      storage_path: "assets/normalized.wav",
      sha256: "a".repeat(64),
      source_type: "browser_original_upload",
      upload_entry: "api:/api/japanese/recordings",
      original_filename: "我的录音.webm",
      content_type: "audio/webm",
      byte_size: 4,
      created_at: "2026-08-04T00:00:00Z",
      audio_path: "assets/normalized.wav",
    };
    const fetchMock = vi.fn().mockImplementation(() => ok(uploadResponse, 201));
    vi.stubGlobal("fetch", fetchMock);
    const api = new JapaneseLearningApi("http://127.0.0.1:8766/");
    const blob = new Blob(["opus"], { type: "audio/webm;codecs=opus" });

    await expect(api.uploadRecording("session id/1", blob, "我的录音.webm")).resolves.toMatchObject({
      id: "recording-1",
      recording_id: "recording-1",
      source_type: "browser_original_upload",
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8766/api/japanese/recordings?session_id=session+id%2F1&filename=%E6%88%91%E7%9A%84%E5%BD%95%E9%9F%B3.webm");
    expect(init).toMatchObject({ method: "POST", body: blob });
    expect(new Headers(init.headers).get("Content-Type")).toBe("audio/webm;codecs=opus");
  });

  it("constructs conversation, reference and exercise-attempt bodies using recording provenance ids", async () => {
    const turn = { id: "turn-1" };
    const reference = { exercise: { id: "exercise-1" }, synthesis: { audio_url: "/reference" } };
    const shadow = { attempt_id: "attempt-1" };
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => ok(turn, 201))
      .mockImplementationOnce(() => ok(reference, 201))
      .mockImplementationOnce(() => ok(shadow, 201));
    vi.stubGlobal("fetch", fetchMock);
    const api = new JapaneseLearningApi("http://127.0.0.1:8766");

    await api.processTurn("session-1", {
      recordingId: "recording-1",
      transcriptHint: "新宿まで一枚お願いします。",
      expectedText: "新宿まで一枚お願いします。",
    });
    await api.createShadowingReference("session-1", "新宿まで一枚お願いします。");
    await api.submitShadowingAttempt("session-1", "exercise-1", {
      recordingId: "recording-1",
      transcriptHint: "新宿まで一枚お願いします。",
    });

    const turnBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(turnBody).toEqual({
      recording_id: "recording-1",
      transcript_hint: "新宿まで一枚お願いします。",
      expected_text: "新宿まで一枚お願いします。",
      voice_role: "standard_tokyo",
    });
    expect(fetchMock.mock.calls[1][0]).toContain("/shadowing/references");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual({
      expected_text: "新宿まで一枚お願いします。",
      voice_role: "standard_tokyo",
    });
    expect(fetchMock.mock.calls[2][0]).toContain("/shadowing/exercises/exercise-1/attempts");
    const attemptBody = JSON.parse(fetchMock.mock.calls[2][1].body as string);
    expect(attemptBody).toMatchObject({
      recording_id: "recording-1",
      transcript_hint: "新宿まで一枚お願いします。",
    });
    expect(turnBody).not.toHaveProperty("original_audio_path");
    expect(turnBody).not.toHaveProperty("source_kind");
    expect(attemptBody).not.toHaveProperty("original_recording_path");
    expect(attemptBody).not.toHaveProperty("source_kind");
  });

  it("uses recording_id for the direct shadowing endpoint too", async () => {
    const fetchMock = vi.fn().mockImplementation(() => ok({ attempt_id: "attempt-1" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    const api = new JapaneseLearningApi("http://127.0.0.1:8766");

    await api.analyzeShadowing("session-1", {
      referenceAudioPath: "assets/reference.wav",
      recordingId: "recording-1",
      expectedText: "新宿まで一枚お願いします。",
      transcriptHint: "新宿まで一枚お願いします。",
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body).toEqual({
      reference_audio_path: "assets/reference.wav",
      recording_id: "recording-1",
      expected_text: "新宿まで一枚お願いします。",
      transcript_hint: "新宿まで一枚お願いします。",
    });
    expect(body).not.toHaveProperty("original_recording_path");
    expect(body).not.toHaveProperty("source_kind");
  });

  it("maps real API evidence without inventing an overall score or mora metric", () => {
    const response = {
      attempt_id: "a1",
      exercise: {},
      transcript: {},
      feedback: {
        content: { metric: "content", value: 0.92, confidence: 0.8, summary: "内容接近", evidence: { edit_distance: 1 }, limitations: [] },
        rhythm: { metric: "rhythm", value: 0.78, confidence: 0.7, summary: "停顿不同", evidence: { duration_ratio: 1.1, expected_mora_segments_approx: ["し", "ん"], actual_mora_segments_approx: ["しん"] }, limitations: ["近似"] },
        pitch: { metric: "pitch", value: null, confidence: 0.1, summary: "证据不足", evidence: { normalized_time: [0, 1], normalized_reference_f0_semitones: [-1, 1], normalized_recording_f0_semitones: [-0.5, 0.5] }, limitations: ["轻量自相关"] },
        priorities: ["先修节奏"],
        scoring_source_path: "assets/original.wav",
        scoring_source_kind: "original_uncolored",
        reference_audio_path: "assets/reference.wav",
        analyzed_at: "now",
      },
      ab_playback: { recording_id: "recording-1", reference_audio_path: "assets/reference.wav", original_recording_path: "assets/original.wav", reference_audio_url: "/api/japanese/exercises/e1/reference" },
      review_item_ids: [],
    } as unknown as ShadowingApiResponse;
    const mapped = apiShadowingToUi(response);
    expect(mapped).toMatchObject({ source: "api", content: { score: 92 }, rhythm: { score: 78 }, pitch: { score: null }, scoringSourceKind: "original_uncolored", recordingId: "recording-1" });
    expect(mapped.mora).toBeUndefined();
    expect(mapped).not.toHaveProperty("overallScore");
    expect(mapped.referenceF0).toEqual([-1, 1]);
    expect(mapped.learnerF0).toEqual([-0.5, 0.5]);
    expect(mapped.expectedMoraSegmentsApprox).toEqual(["し", "ん"]);
  });

  it("maps persisted conversation turn fields into learner and teacher UI turns", () => {
    const turn = {
      id: "turn-1",
      created_at: "2026-08-04T00:00:00Z",
      transcript: { text: "日本語を勉強します", confidence: 0.82, provider: "mock-asr", fallback_used: true },
      teacher: { reply_text: "いいですね。", demonstration_text: "日本語を勉強します。", feedback: ["助词を补全"], confidence: 0.77 },
      demonstration: { audio_path: "assets/demo.wav", provider: "mock-tts", voice_role: "standard_tokyo", sample_rate: 48000, subtype: "PCM_24", fallback_used: false },
    } as unknown as JapaneseTurnResponse;
    const mapped = apiTurnToUiTurns(turn, "http://127.0.0.1:8766");
    expect(mapped).toHaveLength(2);
    expect(mapped[0]).toMatchObject({ role: "learner", text: "日本語を勉強します", confidence: 0.82 });
    expect(mapped[1]).toMatchObject({ role: "teacher", text: "いいですね。", feedback: "助词を补全" });
    expect(mapped[1].audioUrl).toBe("http://127.0.0.1:8766/api/japanese/turns/turn-1/demonstration");
  });

  it("persists a different conversation session for each curriculum scenario", async () => {
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => ok({ id: "learner-1" }, 201))
      .mockImplementationOnce(() => ok({ id: "session-station" }, 201))
      .mockImplementationOnce(() => ok({ id: "session-cafe" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    const api = new JapaneseLearningApi("http://127.0.0.1:8766");

    const station = await ensureJapaneseSession(api, {
      mode: "conversation",
      coachMode: "fluent",
      scenario: "车站买票",
      scenarioId: "station-ticket",
      metadata: { curriculum_version: "v1", curriculum_level: "N5" },
    });
    const cafe = await ensureJapaneseSession(api, {
      mode: "conversation",
      coachMode: "strict",
      scenario: "咖啡店点单",
      scenarioId: "cafe-order",
      metadata: { curriculum_version: "v1", curriculum_level: "N5" },
    });
    const stationAgain = await ensureJapaneseSession(api, {
      mode: "conversation",
      coachMode: "fluent",
      scenario: "车站买票",
      scenarioId: "station-ticket",
    });

    expect([station, cafe, stationAgain]).toEqual(["session-station", "session-cafe", "session-station"]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const stationBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    const cafeBody = JSON.parse(fetchMock.mock.calls[2][1].body as string);
    expect(stationBody.metadata).toMatchObject({ curriculum_scenario_id: "station-ticket", curriculum_version: "v1", curriculum_level: "N5" });
    expect(cafeBody.metadata).toMatchObject({ curriculum_scenario_id: "cafe-order", curriculum_version: "v1", curriculum_level: "N5" });
  });

  it("requests persisted learning path, progress and manual completion endpoints", async () => {
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => ok({ summary: { total: 38 } }))
      .mockImplementationOnce(() => ok({ metrics: {} }))
      .mockImplementationOnce(() => ok({ id: "session-1", status: "completed" }));
    vi.stubGlobal("fetch", fetchMock);
    const api = new JapaneseLearningApi("http://127.0.0.1:8766");

    await api.learningPath("learner/id");
    await api.progress("learner/id");
    await api.completeSession("session/id");

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://127.0.0.1:8766/api/japanese/learners/learner%2Fid/learning-path",
      "http://127.0.0.1:8766/api/japanese/learners/learner%2Fid/progress",
      "http://127.0.0.1:8766/api/japanese/sessions/session%2Fid/complete",
    ]);
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: "POST" });
  });
});
