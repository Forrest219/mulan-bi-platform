# Data Agent Intent Recognition — Spec 36 §15
from .strategy import IntentStrategy, IntentResult
from .registry import IntentRecognizer, get_intent_registry

__all__ = [
    "IntentStrategy",
    "IntentResult",
    "IntentRecognizer",
    "get_intent_registry",
]