"""Tests for percell3.io._sanitize."""

from percell3.io._sanitize import sanitize_name


class TestSanitizeName:
    def test_already_valid(self):
        assert sanitize_name("DAPI") == "DAPI"

    def test_spaces_to_underscores(self):
        assert sanitize_name("my channel") == "my_channel"

    def test_strips_special_chars(self):
        assert sanitize_name("ch@#$01") == "ch01"

    def test_empty_string_uses_fallback(self):
        assert sanitize_name("") == "unnamed"

    def test_custom_fallback(self):
        assert sanitize_name("", fallback="ch0") == "ch0"

    def test_only_invalid_chars_uses_fallback(self):
        assert sanitize_name("@#$%") == "unnamed"

    def test_leading_dot_stripped(self):
        assert sanitize_name(".hidden") == "hidden"

    def test_leading_dash_stripped(self):
        assert sanitize_name("-flag") == "flag"

    def test_leading_underscore_stripped(self):
        assert sanitize_name("_private") == "private"

    def test_truncates_long_names(self):
        long_name = "A" * 300
        result = sanitize_name(long_name)
        assert len(result) == 255

    def test_whitespace_only_uses_fallback(self):
        assert sanitize_name("   ") == "unnamed"

    def test_dots_and_hyphens_preserved(self):
        assert sanitize_name("region-1.0") == "region-1.0"

    def test_mixed_valid_invalid(self):
        assert sanitize_name("my (region) #1") == "my_region_1"
