import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class LeapTest {
    private final Leap leap = new Leap();

    @Test
    public void year2024IsLeap() {
        assertTrue(leap.isLeapYear(2024));
    }

    @Test
    public void year1900IsNotLeap() {
        assertFalse(leap.isLeapYear(1900));
    }
}
