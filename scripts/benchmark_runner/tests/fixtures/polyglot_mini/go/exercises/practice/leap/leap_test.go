package leap

import "testing"

func TestLeap2024(t *testing.T) {
	if !IsLeapYear(2024) {
		t.Fatalf("2024 should be a leap year")
	}
}

func TestLeap1900(t *testing.T) {
	if IsLeapYear(1900) {
		t.Fatalf("1900 should not be a leap year")
	}
}
