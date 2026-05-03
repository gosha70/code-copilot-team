package com.example.domainpack;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import javax.xml.parsers.DocumentBuilderFactory;

import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

/**
 * Loads a domain pack from JAR resources under /domain-pack/.
 * The same logical API exists on the Python side — keep them mirrored.
 */
public final class PackLoader {

    private static final String RESOURCE_ROOT = "domain-pack/";

    private PackLoader() {}

    public static PackManifest manifest() {
        try (InputStream in = open("manifest.yaml")) {
            return parseManifest(readAll(in));
        } catch (IOException e) {
            throw new IllegalStateException("Failed to load manifest", e);
        }
    }

    public static List<PackEntry> entries() {
        PackManifest m = manifest();
        try (InputStream in = open(m.contentFile())) {
            return switch (m.contentFormat()) {
                case "tbx-3.0" -> parseTbx(in);
                default -> throw new IllegalStateException(
                        "Unsupported content_format: " + m.contentFormat());
            };
        } catch (IOException e) {
            throw new IllegalStateException("Failed to load entries", e);
        }
    }

    public static String version() {
        return manifest().version();
    }

    private static InputStream open(String name) {
        InputStream in = PackLoader.class.getClassLoader()
                .getResourceAsStream(RESOURCE_ROOT + name);
        if (in == null) {
            throw new IllegalStateException("Resource not found: " + RESOURCE_ROOT + name);
        }
        return in;
    }

    private static String readAll(InputStream in) throws IOException {
        try (BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) {
            return r.lines().collect(Collectors.joining("\n"));
        }
    }

    // Minimal YAML parser for the manifest's known shape — no third-party dep
    // so the wrapper stays lean. Extend if the manifest grows new shapes.
    static PackManifest parseManifest(String yaml) {
        Map<String, String> top = new LinkedHashMap<>();
        Map<String, String> licenses = new LinkedHashMap<>();
        List<Map<String, String>> sources = new ArrayList<>();

        Pattern topLine = Pattern.compile("^([a-zA-Z_]+):\\s*\"?([^\"\\n]+)\"?\\s*$");
        Pattern nestedLine = Pattern.compile("^\\s+([a-zA-Z_]+):\\s*\"?([^\"\\n]+)\"?\\s*$");

        String currentSection = null;
        Map<String, String> currentSource = null;

        for (String raw : yaml.split("\\n")) {
            if (raw.isBlank() || raw.trim().startsWith("#")) continue;

            if (!raw.startsWith(" ") && !raw.startsWith("\t")) {
                Matcher m = topLine.matcher(raw);
                if (m.matches()) {
                    top.put(m.group(1), m.group(2).trim());
                    currentSection = null;
                    currentSource = null;
                } else if (raw.matches("^[a-zA-Z_]+:\\s*$")) {
                    currentSection = raw.replace(":", "").trim();
                    currentSource = null;
                }
                continue;
            }

            if ("licenses".equals(currentSection)) {
                Matcher m = nestedLine.matcher(raw);
                if (m.matches()) licenses.put(m.group(1), m.group(2).trim());
            } else if ("sources".equals(currentSection)) {
                String trimmed = raw.trim();
                if (trimmed.startsWith("- ")) {
                    currentSource = new LinkedHashMap<>();
                    sources.add(currentSource);
                    String afterDash = trimmed.substring(2);
                    Matcher m = topLine.matcher(afterDash);
                    if (m.matches()) currentSource.put(m.group(1), m.group(2).trim());
                } else if (currentSource != null) {
                    Matcher m = nestedLine.matcher(raw);
                    if (m.matches()) currentSource.put(m.group(1), m.group(2).trim());
                }
            }
        }

        return new PackManifest(
                top.getOrDefault("name", ""),
                top.getOrDefault("version", ""),
                Integer.parseInt(top.getOrDefault("schema_version", "0")),
                top.getOrDefault("description", ""),
                top.getOrDefault("content_format", ""),
                top.getOrDefault("content_file", ""),
                Collections.unmodifiableMap(licenses),
                Collections.unmodifiableList(sources));
    }

    static List<PackEntry> parseTbx(InputStream in) {
        try {
            DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
            dbf.setNamespaceAware(false);
            dbf.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
            Document doc = dbf.newDocumentBuilder().parse(in);

            List<PackEntry> out = new ArrayList<>();
            NodeList termEntries = doc.getElementsByTagName("termEntry");
            for (int i = 0; i < termEntries.getLength(); i++) {
                Element entry = (Element) termEntries.item(i);
                String id = entry.getAttribute("id");
                List<PackEntry.Term> terms = new ArrayList<>();
                NodeList langSets = entry.getElementsByTagName("langSet");
                for (int j = 0; j < langSets.getLength(); j++) {
                    Element langSet = (Element) langSets.item(j);
                    String lang = langSet.getAttribute("xml:lang");
                    NodeList tigs = langSet.getElementsByTagName("tig");
                    for (int k = 0; k < tigs.getLength(); k++) {
                        Element tig = (Element) tigs.item(k);
                        String term = textOf(tig, "term");
                        String pos = noteOf(tig, "partOfSpeech");
                        String def = descripOf(tig, "definition");
                        terms.add(new PackEntry.Term(lang, term, pos, def));
                    }
                }
                out.add(new PackEntry(id, Collections.unmodifiableList(terms)));
            }
            return Collections.unmodifiableList(out);
        } catch (Exception e) {
            throw new IllegalStateException("Failed to parse TBX content", e);
        }
    }

    private static String textOf(Element parent, String tag) {
        NodeList nodes = parent.getElementsByTagName(tag);
        return nodes.getLength() == 0 ? "" : nodes.item(0).getTextContent().trim();
    }

    private static String noteOf(Element parent, String type) {
        NodeList nodes = parent.getElementsByTagName("termNote");
        for (int i = 0; i < nodes.getLength(); i++) {
            Element e = (Element) nodes.item(i);
            if (type.equals(e.getAttribute("type"))) return e.getTextContent().trim();
        }
        return "";
    }

    private static String descripOf(Element parent, String type) {
        NodeList nodes = parent.getElementsByTagName("descrip");
        for (int i = 0; i < nodes.getLength(); i++) {
            Element e = (Element) nodes.item(i);
            if (type.equals(e.getAttribute("type"))) return e.getTextContent().trim();
        }
        return "";
    }
}
