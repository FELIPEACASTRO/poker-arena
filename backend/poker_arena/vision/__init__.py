"""Extrai um estado candidato de uma imagem 2D para o Copiloto.

F1 é um baseline calibrado em imagens sintéticas; F2 é um detector YOLO cujo contrato
ONNX é validado no carregamento. Nenhum deles é considerado universal. O VLM também é
não calibrado e recebe confiança zero até existir verificação independente por campo.
Todo estado passa por um gate fail-closed antes de poder alimentar uma decisão.
"""

from .onnx_recognize import recognize_table_onnx, vision_model_available
from .recognize import RecognizedState, recognize_table
from .sanity import SanityResult, check_state
from .synth import STYLES, Style, render_table
from .vlm_reader import (
    VlmConfigurationError,
    VlmPrivacyError,
    VlmRequestContext,
    VlmUnavailable,
    configured_redaction_policy,
    read_table_vlm,
    redact_configured_regions,
    vlm_available,
)

__all__ = [
    "STYLES",
    "RecognizedState",
    "SanityResult",
    "Style",
    "VlmConfigurationError",
    "VlmPrivacyError",
    "VlmRequestContext",
    "VlmUnavailable",
    "check_state",
    "configured_redaction_policy",
    "read_table_vlm",
    "redact_configured_regions",
    "recognize_table",
    "recognize_table_onnx",
    "render_table",
    "vision_model_available",
    "vlm_available",
]
