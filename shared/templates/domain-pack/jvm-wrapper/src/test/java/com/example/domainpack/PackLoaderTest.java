package com.example.domainpack;

import java.util.List;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PackLoaderTest {

    @Test
    void manifestHasRequiredFields() {
        PackManifest m = PackLoader.manifest();
        assertNotNull(m.name());
        assertFalse(m.name().isBlank());
        assertNotNull(m.version());
        assertFalse(m.version().isBlank());
        assertEquals(1, m.schemaVersion());
        assertEquals("tbx-3.0", m.contentFormat());
        assertTrue(m.licenses().containsKey("data"));
        assertTrue(m.licenses().containsKey("code"));
    }

    @Test
    void entriesLoadFromSampleContent() {
        List<PackEntry> entries = PackLoader.entries();
        assertFalse(entries.isEmpty(), "expected at least one term entry");
        PackEntry first = entries.get(0);
        assertNotNull(first.id());
        assertFalse(first.terms().isEmpty());
    }

    @Test
    void versionMatchesManifest() {
        assertEquals(PackLoader.manifest().version(), PackLoader.version());
    }
}
