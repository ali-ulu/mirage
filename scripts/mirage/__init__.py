"""MIRAGE — Synthetic Data Engine (deception-only, no payload injection)."""
from .synthesizer import MirageSynthesizer, SynthesisResult
from .honeytoken import HoneytokenRecord, HoneytokenRegistry
from .supabase_registry import (
    SupabaseHoneytokenRegistry,
    SupabaseNotConfiguredError,
    SupabaseOperationError,
)

__all__ = [
    "MirageSynthesizer",
    "SynthesisResult",
    "HoneytokenRecord",
    "HoneytokenRegistry",
    "SupabaseHoneytokenRegistry",
    "SupabaseNotConfiguredError",
    "SupabaseOperationError",
]
