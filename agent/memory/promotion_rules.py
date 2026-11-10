def should_promote_style_edit(edit_count: int, consistent_pattern: bool) -> bool:
    # TODO: Define and document a conservative rule for promoting repeated user edits.
    # Raw tool output must never be written directly to long-term memory.
    return edit_count >= 3 and consistent_pattern
