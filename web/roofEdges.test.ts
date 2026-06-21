/**
 * Vitest tests for roofEdges.ts — mirror the validated Python suite exactly.
 * Run: npx vitest run   (or `npm test` once vitest is configured)
 */
import { describe, it, expect } from "vitest";
import {
  hipRoof,
  gableRoof,
  valleyPair,
  lineLengths,
  pitchX12,
} from "./roofEdges";

const TOL = 0.1; // ft

describe("roof edge classification", () => {
  it("hip roof: topology and lengths (40x24, 6/12)", () => {
    const s = lineLengths(hipRoof(40, 24, 6));
    expect(s.ridge.count).toBe(1);
    expect(s.hip.count).toBe(4);
    expect(s.eave.count).toBe(4);
    expect(s.valley).toBeUndefined();
    expect(s.rake).toBeUndefined();
    expect(Math.abs(s.ridge.length - 16)).toBeLessThan(TOL);
    expect(Math.abs(s.hip.length - 72)).toBeLessThan(TOL); // 4 * 18
    expect(Math.abs(s.eave.length - 128)).toBeLessThan(TOL); // 2*(40+24)
  });

  it("gable roof: produces rakes, not hips", () => {
    const s = lineLengths(gableRoof(40, 24, 6));
    expect(s.ridge.count).toBe(1);
    expect(s.eave.count).toBe(2);
    expect(s.rake.count).toBe(4);
    expect(s.hip).toBeUndefined();
    expect(s.valley).toBeUndefined();
    expect(Math.abs(s.ridge.length - 40)).toBeLessThan(TOL);
    expect(Math.abs(s.eave.length - 80)).toBeLessThan(TOL);
    expect(Math.abs(s.rake.length - 4 * Math.sqrt(12 ** 2 + 6 ** 2))).toBeLessThan(TOL);
  });

  it("valley is discriminated from hip", () => {
    const s = lineLengths(valleyPair());
    expect(s.valley).toBeDefined();
    expect(s.hip).toBeUndefined();
    expect(s.valley.count).toBe(1);
    expect(Math.abs(s.valley.length - Math.sqrt(10 ** 2 + 10 ** 2 + 4 ** 2))).toBeLessThan(TOL);
  });

  it("recovers pitch from plane normals (~6/12)", () => {
    for (const f of hipRoof(40, 24, 6)) {
      expect(Math.abs(pitchX12(f) - 6)).toBeLessThan(0.05);
    }
  });
});
