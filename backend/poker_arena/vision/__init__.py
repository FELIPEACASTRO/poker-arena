"""Visão — lê uma imagem 2D de mesa de poker e extrai o ESTADO pro Copiloto.

Arquitetura MODULAR (verificada): separa LOCALIZAR (o que precisa generalizar) de
LER (trivialmente preciso). F1 (aqui) = baseline testável offline com gerador
sintético + reconhecedor por template; F2 (notebook Colab) = detector treinado
agnóstico a qualquer tela. Regra de ouro: todo número passa por sanity-check de
regras de poker ANTES de chegar ao Copiloto.
"""

from .onnx_recognize import recognize_table_onnx, vision_model_available
from .recognize import RecognizedState, recognize_table
from .sanity import SanityResult, check_state
from .synth import STYLES, Style, render_table

__all__ = [
    "STYLES",
    "RecognizedState",
    "SanityResult",
    "Style",
    "check_state",
    "recognize_table",
    "recognize_table_onnx",
    "render_table",
    "vision_model_available",
]
