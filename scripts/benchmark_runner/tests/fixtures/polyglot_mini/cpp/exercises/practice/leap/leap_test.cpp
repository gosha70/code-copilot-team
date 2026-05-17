#include "leap.h"

int main() {
    return (leap::is_leap_year(2024) && !leap::is_leap_year(1900)) ? 0 : 1;
}
