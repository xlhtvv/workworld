import {describe, expect, it} from "vitest";
import {copy, isLocale} from "./i18n";

describe("locales", () => {
  it("provides both required platform languages", () => {
    expect(Object.keys(copy).sort()).toEqual(["en", "zh"]);
    expect(copy.en.title).not.toBe(copy.zh.title);
  });

  it("rejects route segments outside the locale contract", () => {
    expect(isLocale("en")).toBe(true);
    expect(isLocale("zh")).toBe(true);
    expect(isLocale("fr")).toBe(false);
  });
});
