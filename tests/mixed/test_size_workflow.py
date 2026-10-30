# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
E2E tests for size formatting workflow.

Tests realistic use cases for size_str and size_to_bytes in application contexts.
"""

import pytest

from appinfra.size import size_str, size_to_bytes


@pytest.mark.e2e
class TestSizeFormattingWorkflow:
    """E2E tests for size formatting in real use cases."""

    def test_file_size_logging(self):
        """Test formatting file sizes for log output."""
        # Simulate logging various file sizes
        test_files = [
            (0, "0B"),
            (256, "256B"),
            (1024, "1KB"),
            (1024 * 100, "100KB"),
            (1024 * 1024, "1MB"),
            (1024 * 1024 * 50, "50MB"),
            (1024 * 1024 * 1024, "1GB"),
            (1024 * 1024 * 1024 * 2.5, "2.5GB"),
        ]

        for size_bytes, expected in test_files:
            formatted = size_str(size_bytes)
            assert formatted == expected, f"Failed for {size_bytes}: got {formatted}"

    def test_transfer_stats_display(self):
        """Test displaying transfer statistics."""
        # Simulate a file transfer progress display
        total_size = 1024 * 1024 * 100  # 100MB
        transferred = 1024 * 1024 * 45  # 45MB

        total_str = size_str(total_size)
        transferred_str = size_str(transferred)

        assert total_str == "100MB"
        assert transferred_str == "45MB"

        # Format a progress message
        progress_msg = f"Downloaded {transferred_str} of {total_str}"
        assert progress_msg == "Downloaded 45MB of 100MB"

    def test_parse_user_input_size(self):
        """Test parsing size strings from user input."""
        # User might input sizes in various formats
        user_inputs = [
            ("100MB", 1024 * 1024 * 100),
            ("1GB", 1024 * 1024 * 1024),
            ("512KB", 1024 * 512),
            ("1.5GB", int(1024 * 1024 * 1024 * 1.5)),
        ]

        for input_str, expected_bytes in user_inputs:
            parsed = size_to_bytes(input_str)
            assert parsed == expected_bytes, f"Failed for {input_str}"

    def test_config_size_limits(self):
        """Test parsing size limits from configuration."""
        # Config might specify limits like "max_file_size: 10MB"
        config_values = {
            "max_upload_size": "50MB",
            "buffer_size": "64KB",
            "cache_size": "1GB",
        }

        expected = {
            "max_upload_size": 1024 * 1024 * 50,
            "buffer_size": 1024 * 64,
            "cache_size": 1024 * 1024 * 1024,
        }

        for key, value in config_values.items():
            parsed = size_to_bytes(value)
            assert parsed == expected[key], f"Failed for {key}: {value}"

    def test_round_trip_consistency(self):
        """Test that format -> parse -> format is consistent."""
        test_sizes = [
            1024,  # 1KB
            1024 * 1024,  # 1MB
            1024 * 1024 * 1024,  # 1GB
            1536,  # 1.5KB
            1024 * 1024 * 1536 // 1024,  # 1.5MB
        ]

        for original in test_sizes:
            formatted = size_str(original)
            parsed = size_to_bytes(formatted)
            reformatted = size_str(parsed)
            assert formatted == reformatted, f"Inconsistent for {original}"

    def test_precise_mode_for_detailed_stats(self):
        """Test precise mode for detailed size reporting."""
        # For detailed reports, might want fixed precision
        sizes = [
            (1024, "1.000KB"),
            (1536, "1.500KB"),
            (2000, "1.953KB"),  # 2000/1024 ≈ 1.953
        ]

        for size_bytes, expected in sizes:
            formatted = size_str(size_bytes, precise=True)
            assert formatted == expected

    def test_si_units_for_network_stats(self):
        """Test SI units (1000-based) for network statistics."""
        # Network speeds often use SI units (1 Mbps = 1,000,000 bits)
        # Storage/transfer might also use SI

        sizes = [
            (1000, "1KB"),
            (1000000, "1MB"),
            (1000000000, "1GB"),
        ]

        for size_bytes, expected in sizes:
            formatted = size_str(size_bytes, binary=False)
            assert formatted == expected

    def test_api_response_size_tracking(self):
        """Test tracking API response sizes in logs."""
        # Simulate logging API response sizes
        responses = [
            {"endpoint": "/api/users", "size": 2048},
            {"endpoint": "/api/data", "size": 1024 * 1024 * 5},
            {"endpoint": "/api/health", "size": 128},
        ]

        log_entries = []
        for resp in responses:
            size_formatted = size_str(resp["size"])
            log_entries.append(f"{resp['endpoint']}: {size_formatted}")

        assert log_entries == [
            "/api/users: 2KB",
            "/api/data: 5MB",
            "/api/health: 128B",
        ]
