use leap::is_leap_year;

#[test]
fn year_divisible_by_400_is_leap() {
    assert!(is_leap_year(2000));
}

#[test]
fn year_not_divisible_by_4_is_not_leap() {
    assert!(!is_leap_year(2023));
}
