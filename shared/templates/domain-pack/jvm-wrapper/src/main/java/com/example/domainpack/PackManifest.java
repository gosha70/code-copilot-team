package com.example.domainpack;

import java.util.List;
import java.util.Map;

public record PackManifest(
        String name,
        String version,
        int schemaVersion,
        String description,
        String contentFormat,
        String contentFile,
        Map<String, String> licenses,
        List<Map<String, String>> sources) {}
