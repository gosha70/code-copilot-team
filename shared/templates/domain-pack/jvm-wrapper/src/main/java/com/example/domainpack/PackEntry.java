package com.example.domainpack;

import java.util.List;

public record PackEntry(String id, List<Term> terms) {

    public record Term(String language, String text, String partOfSpeech, String definition) {}
}
