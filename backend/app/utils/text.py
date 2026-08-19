"""Text conventions shared between extraction and chunking."""

# Pages are joined with a blank line to form a PDF document's text. The chunker
# uses the same separator to turn a chunk's character offset back into a page
# number, so the adapter and the chunker have to agree on it — hence one
# definition rather than two.
PAGE_SEPARATOR = "\n\n"
