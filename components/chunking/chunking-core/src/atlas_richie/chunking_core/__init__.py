"""Framework-neutral document chunking: rules, strategies, diagnostics.

Zero runtime dependencies. Tokenizer and semantic-boundary implementations are
injected through the `TokenCounter` / `SemanticBoundaryAdvisor` SPIs.
"""

import importlib.metadata

from .model import (
    DEFAULT_SEPARATORS,
    Chunk,
    ChunkingDiagnostics,
    ChunkingResult,
    ChunkingRule,
    ChunkingSignal,
    Strategy,
)
from .service import (
    ChunkingService,
    DefaultChunkingService,
    SemanticBoundaryException,
    SemanticChunkingOptions,
    SemanticChunkingService,
    SemanticFailureMode,
    approximate_token_counter,
)
from .spi import SemanticBoundaryAdvisor, TokenCounter
from .streaming import StreamingChunker
from .strategies import (
    ChunkLimitExceededError,
    ChunkingStrategy,
    ChunkingStrategyFactory,
    FixedChunkingStrategy,
    HtmlChunkingStrategy,
    MarkdownChunkingStrategy,
    PageChunkingStrategy,
    ParagraphChunkingStrategy,
    RecursiveChunkingStrategy,
    SemanticChunkingStrategy,
    SentenceChunkingStrategy,
    TokenChunkingStrategy,
)

__version__ = importlib.metadata.version("atlas-richie-chunking-core")

__all__ = [
    "DEFAULT_SEPARATORS",
    "Chunk",
    "ChunkLimitExceededError",
    "ChunkingDiagnostics",
    "ChunkingResult",
    "ChunkingRule",
    "ChunkingService",
    "ChunkingSignal",
    "ChunkingStrategy",
    "ChunkingStrategyFactory",
    "DefaultChunkingService",
    "FixedChunkingStrategy",
    "HtmlChunkingStrategy",
    "MarkdownChunkingStrategy",
    "PageChunkingStrategy",
    "ParagraphChunkingStrategy",
    "RecursiveChunkingStrategy",
    "SemanticBoundaryAdvisor",
    "SemanticBoundaryException",
    "SemanticChunkingOptions",
    "SemanticChunkingService",
    "SemanticChunkingStrategy",
    "SemanticFailureMode",
    "SentenceChunkingStrategy",
    "Strategy",
    "StreamingChunker",
    "TokenChunkingStrategy",
    "TokenCounter",
    "approximate_token_counter",
    "__version__",
]
