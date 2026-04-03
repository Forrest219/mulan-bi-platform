/**
 * @vitest-environment jsdom
 */
import { describe, it, expect } from "vitest";

// 测试前端计算健康等级（与后端 HEALTH_CHECKS 保持一致）
function getHealthLevel(score: number): string {
  if (score >= 80) return "excellent";
  if (score >= 60) return "good";
  if (score >= 40) return "warning";
  return "poor";
}

function calcHealthScore(params: {
  hasDescription: boolean;
  hasOwner: boolean;
  hasDatasource: boolean;
  captionRatio: number; // 0.0 - 1.0
  isCertified: boolean;
  nameOk: boolean;
  daysSinceUpdate: number | null; // null = 从未更新
}): number {
  let score = 0;
  if (params.hasDescription) score += 20;
  if (params.hasOwner) score += 15;
  if (params.hasDatasource) score += 15;
  // fields_have_captions: 50%+ 通过，给满分 * ratio
  if (params.captionRatio >= 0.5) score += 20 * Math.min(1, params.captionRatio);
  if (params.isCertified) score += 10;
  if (params.nameOk) score += 10;
  if (params.daysSinceUpdate !== null && params.daysSinceUpdate < 90) score += 10;
  return Math.round(score * 10) / 10;
}

describe("前端健康评分 — 等级划分", () => {
  it(">= 80 → excellent", () => {
    expect(getHealthLevel(80)).toBe("excellent");
    expect(getHealthLevel(100)).toBe("excellent");
  });

  it("60-79 → good", () => {
    expect(getHealthLevel(60)).toBe("good");
    expect(getHealthLevel(79)).toBe("good");
  });

  it("40-59 → warning", () => {
    expect(getHealthLevel(40)).toBe("warning");
    expect(getHealthLevel(59)).toBe("warning");
  });

  it("< 40 → poor", () => {
    expect(getHealthLevel(39)).toBe("poor");
    expect(getHealthLevel(0)).toBe("poor");
  });
});

describe("前端健康评分 — 各因子贡献", () => {
  it("完美资产得 100 分", () => {
    const score = calcHealthScore({
      hasDescription: true,
      hasOwner: true,
      hasDatasource: true,
      captionRatio: 1.0,
      isCertified: true,
      nameOk: true,
      daysSinceUpdate: 1,
    });
    expect(score).toBe(100);
  });

  it("无描述扣 20 分", () => {
    const full = calcHealthScore({
      hasDescription: true,
      hasOwner: true,
      hasDatasource: true,
      captionRatio: 1.0,
      isCertified: true,
      nameOk: true,
      daysSinceUpdate: 1,
    });
    const noDesc = calcHealthScore({
      hasDescription: false,
      hasOwner: true,
      hasDatasource: true,
      captionRatio: 1.0,
      isCertified: true,
      nameOk: true,
      daysSinceUpdate: 1,
    });
    expect(noDesc).toBe(full - 20);
  });

  it("90 天未更新扣 10 分", () => {
    const recent = calcHealthScore({
      hasDescription: true, hasOwner: true, hasDatasource: true,
      captionRatio: 1.0, isCertified: true, nameOk: true,
      daysSinceUpdate: 1,
    });
    const stale = calcHealthScore({
      hasDescription: true, hasOwner: true, hasDatasource: true,
      captionRatio: 1.0, isCertified: true, nameOk: true,
      daysSinceUpdate: 100,
    });
    expect(stale).toBe(recent - 10);
  });

  it("从未更新(daysSinceUpdate=null)扣 10 分", () => {
    const recent = calcHealthScore({
      hasDescription: true, hasOwner: true, hasDatasource: true,
      captionRatio: 1.0, isCertified: true, nameOk: true,
      daysSinceUpdate: 1,
    });
    const never = calcHealthScore({
      hasDescription: true, hasOwner: true, hasDatasource: true,
      captionRatio: 1.0, isCertified: true, nameOk: true,
      daysSinceUpdate: null,
    });
    expect(never).toBe(recent - 10);
  });

  it("字段覆盖率低于 50% 时 fields_have_captions 不通过", () => {
    const pass = calcHealthScore({
      hasDescription: true, hasOwner: true, hasDatasource: true,
      captionRatio: 0.5, isCertified: false, nameOk: false,
      daysSinceUpdate: null,
    });
    const fail = calcHealthScore({
      hasDescription: true, hasOwner: true, hasDatasource: true,
      captionRatio: 0.3, isCertified: false, nameOk: false,
      daysSinceUpdate: null,
    });
    expect(fail).toBeLessThan(pass);
  });
});
