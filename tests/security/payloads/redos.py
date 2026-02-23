"""ReDoS (Regular Expression Denial of Service) attack patterns."""

# Nested Quantifier Patterns
# These patterns cause exponential backtracking in regex engines
NESTED_QUANTIFIERS = [
    r"(.+)+",
    r"(.*)*",
    r"(a+)+",
    r"(a*)*",
    r"(x+x+)+y",
    r"([a-z]+)*",
    r"(a+)+b",
    r"(a*)+b",
]

# Alternation Explosion Patterns
# These patterns cause catastrophic backtracking via alternations
ALTERNATION_EXPLOSION = [
    r"(a|a|a|a|a|a|a|a)*",
    r"(x|x)*",
    r"(1|1|1|1|1|1|1|1|1|1)*",
    r"(a|a|a)*b",
    r"(foo|foo|foo|foo)*bar",
    r"(a|a)+",  # Moved from NESTED_QUANTIFIERS - this is alternation, not nested quantifier
]

# Known Evil Patterns
# Well-documented ReDoS patterns that cause hangs
KNOWN_EVIL_PATTERNS = [
    r"^(a+)+$",  # Classic ReDoS - exponential with input "aaaa...b"
    r"(a|a)*",  # Degenerate alternation
    r"(a*)*b",  # Exponential backtracking
    r"(a+)+",  # Nested quantifiers
    r"([a-zA-Z]+)*",  # Greedy quantifier with nested group
    r"(a|ab)*",  # Alternation with overlap
    r"(.*)*",  # Wildcard nested quantifier
]


# Long Pattern Payloads
# These patterns exceed reasonable length limits
def generate_long_pattern(length: int) -> str:
    """Generate a regex pattern of specified length."""
    return "a" * length


# Evil Input Strings
# Strings designed to maximize backtracking on vulnerable patterns
REDOS_EVIL_INPUTS = {
    r"^(a+)+$": "a" * 30
    + "b",  # 30 a's followed by b - causes exponential backtracking
    r"(a*)*b": "a" * 30 + "c",  # No 'b' at end causes full backtracking
    # NOTE: (a+)+ without anchors doesn't cause backtracking - the unanchored pattern
    # simply matches all the a's and succeeds. Backtracking only occurs when the
    # pattern is forced to fail (e.g., with $ anchor that can't match after 'x').
    # r"(a+)+": "a" * 30 + "x",
    # NOTE: (a|a)* is theoretically vulnerable to ReDoS, but Python's regex engine
    # optimizes it (recognizes a|a is redundant), so it matches instantly instead
    # of causing catastrophic backtracking. Not useful for timeout testing.
    # r"(a|a)*": "a" * 30,
}
