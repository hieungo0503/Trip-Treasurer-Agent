"""Tests cho app/domain/fuzzy_match.py"""

import pytest
from app.domain.fuzzy_match import (
    normalize_vn,
    levenshtein_distance,
    match_member_name,
    match_all_ambiguous,
    capitalize_vn,
)


class TestNormalizeVn:
    def test_basic_diacritics(self):
        assert normalize_vn("Hà") == "ha"
        assert normalize_vn("Đức") == "duc"
        assert normalize_vn("Minh") == "minh"

    def test_lowercase(self):
        assert normalize_vn("LONG") == "long"
        assert normalize_vn("Ha") == "ha"

    def test_strip_whitespace(self):
        assert normalize_vn("  Hà  ") == "ha"

    def test_complex_names(self):
        assert normalize_vn("Nguyễn") == "nguyen"
        assert normalize_vn("Trần") == "tran"
        assert normalize_vn("Phương") == "phuong"

    def test_special_chars_stripped(self):
        # Ký tự đặc biệt bị bỏ
        assert normalize_vn("Hà-Gầy") == "ha gay"

    def test_two_words(self):
        assert normalize_vn("Hà Béo") == "ha beo"


class TestLevenshteinDistance:
    def test_same(self):
        assert levenshtein_distance("ha", "ha") == 0

    def test_empty(self):
        assert levenshtein_distance("", "ha") == 2
        assert levenshtein_distance("ha", "") == 2

    def test_one_edit(self):
        assert levenshtein_distance("ha", "hb") == 1
        assert levenshtein_distance("long", "lnog") == 2

    def test_insert(self):
        assert levenshtein_distance("ha", "hao") == 1

    def test_delete(self):
        assert levenshtein_distance("long", "lon") == 1

    def test_completely_different(self):
        dist = levenshtein_distance("abc", "xyz")
        assert dist == 3


class TestMatchMemberName:
    CANDIDATES = ["Hà", "Long", "Minh", "Đức"]

    def test_exact_match(self):
        result = match_member_name("Hà", self.CANDIDATES)
        assert result.matched_name == "Hà"
        assert result.confidence == 1.0
        assert result.method == "exact"

    def test_exact_case_insensitive(self):
        result = match_member_name("hà", self.CANDIDATES)
        assert result.matched_name == "Hà"
        assert result.confidence == 1.0

    def test_normalized_match_no_diacritic(self):
        result = match_member_name("Ha", self.CANDIDATES)
        assert result.matched_name == "Hà"
        assert result.confidence == 0.8
        assert result.method == "normalized"

    def test_normalized_match_wrong_tone(self):
        # "Hã" bỏ dấu → "ha" = "Hà" bỏ dấu → match
        result = match_member_name("Hã", self.CANDIDATES)
        assert result.matched_name == "Hà"
        assert result.confidence == 0.8

    def test_levenshtein_match(self):
        # "Lnog" → normalize → "lnog", dist từ "long" = 2
        result = match_member_name("Lnog", self.CANDIDATES)
        assert result.matched_name == "Long"
        assert result.method == "levenshtein"

    def test_no_match(self):
        result = match_member_name("xyz", self.CANDIDATES)
        assert result.matched_name is None
        assert result.confidence == 0.0
        assert result.method == "none"

    def test_empty_candidates(self):
        result = match_member_name("Hà", [])
        assert result.matched_name is None

    def test_duc_special_char(self):
        result = match_member_name("Duc", self.CANDIDATES)
        assert result.matched_name == "Đức"

    def test_duc_exact(self):
        result = match_member_name("Đức", self.CANDIDATES)
        assert result.matched_name == "Đức"
        assert result.confidence == 1.0


class TestMatchAllAmbiguous:
    def test_unique_match(self):
        results = match_all_ambiguous("Ha", ["Hà", "Long", "Minh"])
        assert len(results) == 1
        assert results[0][0] == "Hà"

    def test_two_matches_same_confidence(self):
        # Nếu có 2 "Hà" trong DB (bình thường không xảy ra nhưng test logic)
        results = match_all_ambiguous("Ha", ["Hà", "Há", "Long"])
        # Cả Hà và Há đều normalize về "ha"
        assert len(results) == 2

    def test_no_match(self):
        results = match_all_ambiguous("xyz", ["Hà", "Long"])
        assert results == []


class TestCapitalizeVn:
    def test_simple(self):
        assert capitalize_vn("đức") == "Đức"

    def test_two_words(self):
        assert capitalize_vn("hà gầy") == "Hà Gầy"

    def test_already_capitalized(self):
        assert capitalize_vn("Hà") == "Hà"

    def test_uppercase(self):
        assert capitalize_vn("LONG") == "Long"

    def test_strip(self):
        assert capitalize_vn("  minh  ") == "Minh"
