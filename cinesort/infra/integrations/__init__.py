"""Integrations infra : adapters autour de modeles/binaires tiers (V4.2+).

Convention : un module par integration externe (ONNX vision models,
modeles audio, etc.). Chaque module expose une API minimale (load,
infer) avec lazy loading et erreurs explicites si binaire/modele absent.
"""
