import { isLeapYear } from "./leap.js";

test("2024 is leap", () => {
  expect(isLeapYear(2024)).toBe(true);
});

test("1900 is not leap", () => {
  expect(isLeapYear(1900)).toBe(false);
});
